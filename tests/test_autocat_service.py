import os
from pathlib import Path
import re

import pandas as pd
import pytest

from app.core.feature_store import path_for_user
from app.features.autocat.service import auto_categorize_expenses
from app.features.autocat.types import AutoCategorizeRequest, AutoCategorizeRequestItem
from app.models.transactions import AiTransaction


def _make_history(count, categories, user_id="user1"):
    history = []
    for i in range(count):
        cat = categories[i % len(categories)]
        history.append(
            AiTransaction(
                transactionId=f"hist-{i}",
                userId=user_id,
                type="EXPENSE",
                date="2025-01-01",
                amount=100 + i,
                currency="BRL",
                categoryId=cat,
                description=f"Descricao categoria {cat} item {i}",
            )
        )
    return history


def _request_items(descriptions):
    return [
        AutoCategorizeRequestItem(
            expenseId=f"req-{i}",
            description=desc,
            amount=50 + i,
            paymentMethodId=1,
        )
        for i, desc in enumerate(descriptions)
    ]


@pytest.fixture(autouse=True)
def _patch_model_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_MODEL_DIR", str(tmp_path / "models"))
    from app.core.config import get_settings

    get_settings.cache_clear()


def _train_with_history(monkeypatch, history, extra_expenses=None, history_accum=None):
    monkeypatch.setattr(
        "app.features.autocat.service.get_user_labeled_history",
        lambda _: history_accum if history_accum is not None else history,
    )
    # dispara treinamento automático com o mesmo user_id do histórico e expenses extras
    uid = history[0].userId if history else "dummy-user-trigger"
    expenses = extra_expenses if extra_expenses is not None else []
    auto_categorize_expenses(uid, AutoCategorizeRequest(expenses=expenses))


def _clean_user_model_dir(user_id):
    model_dir = Path(os.getenv("AI_MODEL_DIR")) / "autocat" / "autocat_v1" / user_id
    if model_dir.exists():
        for f in model_dir.glob("*"):
            f.unlink()
        model_dir.rmdir()


def test_training_and_prediction(monkeypatch):
    user_id = "user-train"
    _clean_user_model_dir(user_id)
    history = _make_history(40, [1, 2], user_id=user_id)
    _train_with_history(monkeypatch, history)
    request = AutoCategorizeRequest(expenses=_request_items(["Supermercado Extra", "McDonalds"]))
    response = auto_categorize_expenses(user_id, request)
    assert all(s.suggestedCategory.id in {1, 2} for s in response.suggestions)
    assert all(s.suggestedCategory.id != 14 for s in response.suggestions)


def test_small_labeled_history_does_not_train_below_threshold(monkeypatch):
    user_id = "user-small-history"
    _clean_user_model_dir(user_id)
    history = [
        AiTransaction(transactionId="hist-1", userId=user_id, type="EXPENSE", date="2025-11-01", amount=120, currency="BRL", categoryId=1, description="Mercado Extra compra"),
        AiTransaction(transactionId="hist-2", userId=user_id, type="EXPENSE", date="2025-11-02", amount=98, currency="BRL", categoryId=1, description="Supermercado Pao de Acucar"),
        AiTransaction(transactionId="hist-3", userId=user_id, type="EXPENSE", date="2025-11-03", amount=210, currency="BRL", categoryId=1, description="Atacadao alimentos"),
        AiTransaction(transactionId="hist-4", userId=user_id, type="EXPENSE", date="2025-11-04", amount=32, currency="BRL", categoryId=2, description="Uber viagem centro"),
        AiTransaction(transactionId="hist-5", userId=user_id, type="EXPENSE", date="2025-11-05", amount=28, currency="BRL", categoryId=2, description="99 Taxi corrida"),
        AiTransaction(transactionId="hist-6", userId=user_id, type="EXPENSE", date="2025-11-06", amount=8, currency="BRL", categoryId=2, description="Metro bilhete unico"),
        AiTransaction(transactionId="hist-7", userId=user_id, type="EXPENSE", date="2025-11-07", amount=39.9, currency="BRL", categoryId=3, description="Netflix assinatura"),
        AiTransaction(transactionId="hist-8", userId=user_id, type="EXPENSE", date="2025-11-08", amount=21.9, currency="BRL", categoryId=3, description="Spotify mensalidade"),
        AiTransaction(transactionId="hist-9", userId=user_id, type="EXPENSE", date="2025-11-09", amount=14.9, currency="BRL", categoryId=3, description="Amazon Prime assinatura"),
        AiTransaction(transactionId="hist-10", userId=user_id, type="EXPENSE", date="2025-11-10", amount=46, currency="BRL", categoryId=4, description="Drogaria Sao Paulo"),
        AiTransaction(transactionId="hist-11", userId=user_id, type="EXPENSE", date="2025-11-11", amount=62, currency="BRL", categoryId=4, description="Droga Raia remedios"),
        AiTransaction(transactionId="hist-12", userId=user_id, type="EXPENSE", date="2025-11-12", amount=54, currency="BRL", categoryId=5, description="Restaurante almoco"),
        AiTransaction(transactionId="hist-13", userId=user_id, type="EXPENSE", date="2025-11-13", amount=71, currency="BRL", categoryId=5, description="Ifood jantar"),
    ]
    monkeypatch.setattr("app.features.autocat.service.get_user_labeled_history", lambda _: history)

    request = AutoCategorizeRequest(expenses=[
        AutoCategorizeRequestItem(expenseId="req-market", description="Supermercado Extra", amount=87, paymentMethodId=1),
        AutoCategorizeRequestItem(expenseId="req-uber", description="Uber aeroporto", amount=45, paymentMethodId=1),
    ])
    response = auto_categorize_expenses(user_id, request)

    assert all(s.suggestedCategory.id == 14 for s in response.suggestions)
    assert all(s.reasoning == "insufficient-history" for s in response.suggestions)


def test_seed_sized_history_trains_and_boosts_with_similarity(monkeypatch):
    user_id = "user-seed-history"
    _clean_user_model_dir(user_id)
    examples = [
        ("Mercado Extra compra da semana", 1, 142.35),
        ("Supermercado Pao de Acucar", 1, 87.42),
        ("Atacadao alimentos", 1, 213.90),
        ("Carrefour mercado", 1, 96.10),
        ("Hortifruti frutas e verduras", 1, 54.75),
        ("Uber viagem centro", 2, 31.20),
        ("99 Taxi corrida", 2, 27.80),
        ("Metro bilhete unico", 2, 8.80),
        ("Uber aeroporto", 2, 44.50),
        ("Estacionamento shopping", 2, 19.90),
        ("Netflix assinatura mensal", 3, 39.90),
        ("Spotify mensalidade", 3, 21.90),
        ("Amazon Prime assinatura", 3, 14.90),
        ("Netflix streaming", 3, 39.90),
        ("iCloud armazenamento", 3, 29.90),
        ("Drogaria Sao Paulo remedios", 4, 46.20),
        ("Droga Raia farmacia", 4, 62.40),
        ("Consulta laboratorio exame", 4, 118.00),
        ("Pague Menos farmacia", 4, 35.70),
        ("Drogasil medicamentos", 4, 74.80),
        ("Restaurante almoco", 5, 54.00),
        ("Ifood jantar", 5, 71.30),
        ("Padaria cafe da manha", 5, 18.50),
        ("Outback jantar", 5, 83.10),
        ("Lanchonete lanche", 5, 42.90),
    ]
    history = [
        AiTransaction(
            transactionId=f"hist-{idx}",
            userId=user_id,
            type="EXPENSE",
            date="2025-11-01",
            amount=amount,
            currency="BRL",
            categoryId=category_id,
            description=description,
        )
        for idx, (description, category_id, amount) in enumerate(examples)
    ]
    monkeypatch.setattr("app.features.autocat.service.get_user_labeled_history", lambda _: history)

    request = AutoCategorizeRequest(expenses=[
        AutoCategorizeRequestItem(expenseId="req-market", description="Supermercado Extra", amount=87, paymentMethodId=1),
        AutoCategorizeRequestItem(expenseId="req-uber", description="Uber aeroporto", amount=45, paymentMethodId=1),
    ])
    response = auto_categorize_expenses(user_id, request)

    assert response.suggestions[0].suggestedCategory.id == 1
    assert response.suggestions[1].suggestedCategory.id == 2
    assert all(s.suggestedCategory.confidence > 0.5 for s in response.suggestions)
    assert all("historical-similarity" in s.reasoning for s in response.suggestions)


def test_parquet_timestamp_history_is_normalized(monkeypatch):
    user_id = "user-parquet-history"
    records = [
        {
            "transactionId": f"hist-{idx}",
            "userId": user_id,
            "type": "EXPENSE",
            "date": pd.Timestamp("2026-07-15"),
            "amount": 50 + idx,
            "currency": "BRL",
            "categoryId": 1 if idx < 11 else 2,
            "description": f"Descricao categoria {1 if idx < 11 else 2} item {idx}",
        }
        for idx in range(22)
    ]
    path = Path(path_for_user(user_id, "raw_transactions.parquet"))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(records).to_parquet(path)

    request = AutoCategorizeRequest(
        expenses=[
            AutoCategorizeRequestItem(
                expenseId="req-timestamp",
                description="Descricao categoria 1 nova",
                amount=80,
                paymentMethodId=1,
            )
        ]
    )
    response = auto_categorize_expenses(user_id, request)

    assert response.suggestions[0].reasoning != "model-error"


def test_alternative_categories(monkeypatch):
    user_id = "user-alt"
    _clean_user_model_dir(user_id)
    history = _make_history(60, [1, 2, 3], user_id=user_id)
    _train_with_history(monkeypatch, history)
    request = AutoCategorizeRequest(expenses=_request_items(["Supermercado Extra" for _ in range(3)]))
    response = auto_categorize_expenses(user_id, request)
    assert response.suggestions
    for suggestion in response.suggestions:
        assert suggestion.alternativeCategories
        assert 0 < len(suggestion.alternativeCategories) <= 3
        confidences = [alt.confidence for alt in suggestion.alternativeCategories]
        assert confidences == sorted(confidences, reverse=True)


def test_fallback_when_model_removed_and_history_unavailable(monkeypatch, tmp_path):
    user_id = "user-corrupt"
    _clean_user_model_dir(user_id)
    # Use at least two classes in history and request
    history = _make_history(40, [5, 6], user_id=user_id)
    request_expenses = [
        AutoCategorizeRequestItem(expenseId="req-0", description="Descricao categoria 5 item 0", amount=50, paymentMethodId=1),
        AutoCategorizeRequestItem(expenseId="req-1", description="Descricao categoria 6 item 1", amount=51, paymentMethodId=1),
    ]
    _train_with_history(monkeypatch, history, extra_expenses=request_expenses)
    request = AutoCategorizeRequest(expenses=request_expenses)
    response = auto_categorize_expenses(user_id, request)
    for s in response.suggestions:
        assert s.suggestedCategory.id in {5, 6}

    # Simular modelo corrompido: deletar modelo e histórico
    from app.features.autocat import service as autocat_service
    from app.core.models_registry import get_model_registry, ModelKey


    registry = get_model_registry()
    key = ModelKey(feature="autocat", version="autocat_v1", user_id=user_id)
    registry.delete_model(key)
    autocat_service._CORRUPT_FLAG.clear()

    monkeypatch.setattr(
        "app.features.autocat.service.get_user_labeled_history",
        lambda _: []
    )

    response_without_history = auto_categorize_expenses(user_id, request)
    assert all(s.suggestedCategory.id == 14 for s in response_without_history.suggestions), \
        f"Expected all category 14, got: {[s.suggestedCategory.id for s in response_without_history.suggestions]}"
    assert all(s.reasoning == "insufficient-history" for s in response_without_history.suggestions)


def test_empty_descriptions(monkeypatch):
    user_id = "user-empty"
    _clean_user_model_dir(user_id)
    history = _make_history(40, [9, 10], user_id=user_id)
    _train_with_history(monkeypatch, history)
    request = AutoCategorizeRequest(
        expenses=[AutoCategorizeRequestItem(expenseId="req-empty", description=None, amount=80.0, paymentMethodId=1)]
    )
    response = auto_categorize_expenses(user_id, request)
    assert response.suggestions[0].suggestedCategory.id == 14
    assert response.suggestions[0].reasoning == "empty-description"


def test_unbalanced_labels(monkeypatch):
    user_id = "user-unbal"
    _clean_user_model_dir(user_id)
    history = _make_history(50, [1, 1, 1, 2], user_id=user_id)
    _train_with_history(monkeypatch, history)
    request = AutoCategorizeRequest(
        expenses=[AutoCategorizeRequestItem(expenseId="req-0", description="Descricao categoria 2 item 1", amount=50, paymentMethodId=1)]
    )
    response = auto_categorize_expenses(user_id, request)
    assert response.suggestions[0].suggestedCategory.id in {1, 2}


def test_retraining_when_history_grows(monkeypatch):
    user_id = "user-retrain"
    _clean_user_model_dir(user_id)
    # Use at least duas classes em history e request
    small_history = _make_history(40, [3, 4], user_id=user_id)
    request_expenses = [
        AutoCategorizeRequestItem(expenseId="req-0", description="Descricao categoria 3 item 0", amount=50, paymentMethodId=1),
        AutoCategorizeRequestItem(expenseId="req-1", description="Descricao categoria 4 item 1", amount=51, paymentMethodId=1),
    ]
    # Treina com histórico inicial
    _train_with_history(monkeypatch, small_history, extra_expenses=request_expenses, history_accum=small_history)
    request = AutoCategorizeRequest(expenses=request_expenses)
    first_response = auto_categorize_expenses(user_id, request)
    expected_count = len(small_history)
    match = re.search(r"(\d+) transações", first_response.suggestions[0].reasoning)
    assert match and int(match.group(1)) == expected_count

    # Treina com histórico maior (acumulado)
    larger_history = _make_history(80, [3, 4], user_id=user_id)
    _train_with_history(monkeypatch, larger_history, extra_expenses=request_expenses, history_accum=larger_history)
    second_response = auto_categorize_expenses(user_id, request)
    expected_count2 = len(larger_history)
    match2 = re.search(r"(\d+) transações", second_response.suggestions[0].reasoning)
    assert match2 and int(match2.group(1)) == expected_count2
