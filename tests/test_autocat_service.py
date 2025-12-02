import os
from pathlib import Path
import re

import pytest

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


def test_fallback_on_corrupted_model(monkeypatch, tmp_path):
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
    import shutil
    from app.features.autocat import service as autocat_service
    from app.core.models_registry import get_model_registry, ModelKey

    model_dir = Path(os.getenv("AI_MODEL_DIR")) / "autocat" / "autocat_v1" / user_id
    if model_dir.exists():
        shutil.rmtree(model_dir)

    registry = get_model_registry()
    key = ModelKey(feature="autocat", version="autocat_v1", user_id=user_id)
    registry.delete_model(key)
    autocat_service._CORRUPT_FLAG.clear()

    monkeypatch.setattr(
        "app.features.autocat.service.get_user_labeled_history",
        lambda _: []
    )

    response_corrupt = auto_categorize_expenses(user_id, request)
    assert all(s.suggestedCategory.id == 14 for s in response_corrupt.suggestions), \
        f"Expected all category 14, got: {[s.suggestedCategory.id for s in response_corrupt.suggestions]}"
    assert all(s.reasoning == "model-error" for s in response_corrupt.suggestions)


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
    expected_count = len(small_history) + len(request.expenses)
    match = re.search(r"(\d+) transações", first_response.suggestions[0].reasoning)
    assert match and int(match.group(1)) == expected_count

    # Treina com histórico maior (acumulado)
    larger_history = _make_history(80, [3, 4], user_id=user_id)
    _train_with_history(monkeypatch, larger_history, extra_expenses=request_expenses, history_accum=larger_history)
    second_response = auto_categorize_expenses(user_id, request)
    expected_count2 = len(larger_history) + len(request.expenses)
    match2 = re.search(r"(\d+) transações", second_response.suggestions[0].reasoning)
    assert match2 and int(match2.group(1)) == expected_count2
