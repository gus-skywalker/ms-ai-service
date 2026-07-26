from pathlib import Path

import pandas as pd
import pytest

from app.core.config import get_settings
from app.core.feature_store import path_for_user
from app.features.autocat.bundle_store import get_autocat_bundle_store
from app.features.autocat.policy import ALLOWED_LABEL_SOURCES, evaluate_eligibility, load_training_dataset
from app.features.autocat.service import auto_categorize_expenses
from app.features.autocat.training import train_autocat
from app.features.autocat.types import AutoCategorizeRequest, AutoCategorizeRequestItem


@pytest.fixture(autouse=True)
def isolated_autocat(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.feature_store.STORAGE_PATH", str(tmp_path / "workspace_data"))
    monkeypatch.setenv("AI_MODEL_DIR", str(tmp_path / "models"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _write_learning_data(workspace_id: str, count: int = 24, sources=None, blank_descriptions: int = 0):
    sources = sources or ["USER"] * count
    transactions, labels = [], []
    for index in range(count):
        category = 1 if index % 2 == 0 else 2
        description = "" if index < blank_descriptions else (
            f"mercado supermercado alimento compra {index}" if category == 1
            else f"uber taxi transporte corrida {index}"
        )
        transactions.append({
            "workspaceId": workspace_id, "transactionId": f"tx-{index}", "entryId": f"entry-{index}",
            "date": "2026-07-01", "type": "EXPENSE", "amount": 10 + index,
            "categoryId": 99, "description": description,
        })
        source = sources[index]
        labels.append({
            "labelId": f"label-{index}", "transactionId": f"tx-{index}", "entryId": f"entry-{index}",
            "categoryId": category, "labelSource": source,
            "trust": ALLOWED_LABEL_SOURCES.get(source, 1.0), "labeledAt": f"2026-07-{(index % 24) + 1:02d}T10:00:00Z",
        })
    tx_path = Path(path_for_user(workspace_id, "raw_transactions.parquet"))
    tx_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(transactions).to_parquet(tx_path)
    pd.DataFrame(labels).to_parquet(path_for_user(workspace_id, "trusted_labels.parquet"))


def _request(description="mercado supermercado compra", allowed=None):
    return AutoCategorizeRequest(
        allowedCategoryIds=allowed,
        expenses=[AutoCategorizeRequestItem(expenseId="expense-1", description=description, amount=25, paymentMethodId=1)],
    )


def test_raw_transaction_category_is_not_a_training_label():
    _write_learning_data("raw-only")
    Path(path_for_user("raw-only", "trusted_labels.parquet")).unlink()
    assert load_training_dataset("raw-only").empty
    assert evaluate_eligibility("raw-only").blockingReasons[0] == "INSUFFICIENT_LABELS"


@pytest.mark.parametrize("source", ["AI", "HISTORY", "DOMAIN_ALIAS"])
def test_derived_sources_are_excluded(source):
    _write_learning_data("untrusted", sources=[source] * 24)
    assert load_training_dataset("untrusted").empty


@pytest.mark.parametrize("source", list(ALLOWED_LABEL_SOURCES))
def test_canonical_sources_are_accepted(source):
    _write_learning_data(source, sources=[source] * 24)
    assert len(load_training_dataset(source)) == 24


def test_label_category_wins_over_raw_category():
    _write_learning_data("label-wins")
    assert set(load_training_dataset("label-wins")["categoryId"]) == {1, 2}


def test_latest_conflicting_label_wins():
    _write_learning_data("conflict")
    path = path_for_user("conflict", "trusted_labels.parquet")
    labels = pd.read_parquet(path)
    labels = pd.concat([labels, pd.DataFrame([{
        "labelId": "latest", "transactionId": "tx-0", "entryId": "entry-0", "categoryId": 7,
        "labelSource": "USER", "trust": 1.0, "labeledAt": "2026-08-01T00:00:00Z",
    }])], ignore_index=True)
    labels.to_parquet(path)
    dataset = load_training_dataset("conflict")
    assert dataset.loc[dataset["entryId"] == "entry-0", "categoryId"].item() == 7
    assert len(dataset) == 24


def test_eligibility_reports_structured_blockers():
    _write_learning_data("small", count=8)
    diagnostic = evaluate_eligibility("small")
    assert diagnostic.eligible is False
    assert "INSUFFICIENT_LABELS" in diagnostic.blockingReasons
    assert diagnostic.classDistribution == {"1": 4, "2": 4}


def test_description_coverage_is_feature_specific():
    _write_learning_data("blank", blank_descriptions=12)
    diagnostic = evaluate_eligibility("blank")
    assert "INSUFFICIENT_DESCRIPTION_COVERAGE" in diagnostic.blockingReasons


def test_canonical_training_activates_complete_bundle():
    _write_learning_data("trained")
    result = train_autocat("trained")
    bundle = get_autocat_bundle_store().load_active("trained")
    assert result["status"] == "READY"
    assert result["activated"] is True
    assert bundle["scope"] == "WORKSPACE"
    assert bundle["workspaceId"] == "trained"
    assert bundle["labelPolicyVersion"] == "autocat-label-policy-v1"
    assert bundle["metrics"]["macroF1"] >= 0.35


def test_same_dataset_does_not_retrain():
    _write_learning_data("unchanged")
    first = train_autocat("unchanged")
    second = train_autocat("unchanged")
    assert second["status"] == "UNCHANGED_DATASET"
    assert second["modelVersion"] == first["modelVersion"]


def test_inference_never_trains_implicitly():
    _write_learning_data("eligible-no-model")
    response = auto_categorize_expenses("eligible-no-model", _request(allowed=[1, 2]))
    assert response.status == "MODEL_NOT_READY"
    assert response.suggestions[0].suggestedCategory is None
    assert get_autocat_bundle_store().active_metadata("eligible-no-model") is None


def test_personalized_inference_is_safe_inside_active_domain():
    _write_learning_data("infer")
    train_autocat("infer")
    response = auto_categorize_expenses("infer", _request(allowed=[1, 2]))
    suggestion = response.suggestions[0]
    assert response.status == "READY"
    assert suggestion.suggestedCategory.id == 1
    assert suggestion.safeToApply is True
    assert suggestion.modelScope == "WORKSPACE"
    assert suggestion.modelVersion == response.modelVersion


def test_prediction_outside_allowed_domain_abstains():
    _write_learning_data("domain")
    train_autocat("domain")
    suggestion = auto_categorize_expenses("domain", _request(allowed=[9])).suggestions[0]
    assert suggestion.status == "OUTSIDE_ALLOWED_DOMAIN"
    assert suggestion.safeToApply is False
    assert suggestion.suggestedCategory is None


def test_missing_domain_abstains():
    _write_learning_data("missing-domain")
    train_autocat("missing-domain")
    suggestion = auto_categorize_expenses("missing-domain", _request()).suggestions[0]
    assert suggestion.safeToApply is False


def test_low_confidence_abstains(monkeypatch):
    _write_learning_data("low-confidence")
    train_autocat("low-confidence")
    monkeypatch.setenv("AUTOCAT_SAFE_CONFIDENCE", "1.01")
    get_settings.cache_clear()
    suggestion = auto_categorize_expenses("low-confidence", _request(allowed=[1, 2])).suggestions[0]
    assert suggestion.status == "NO_SAFE_SUGGESTION"
    assert suggestion.safeToApply is False


def test_empty_description_has_semantic_status():
    _write_learning_data("empty")
    train_autocat("empty")
    suggestion = auto_categorize_expenses("empty", _request(description=None, allowed=[1, 2])).suggestions[0]
    assert suggestion.status == "INVALID_INPUT"
    assert suggestion.suggestedCategory is None


def test_workspace_model_isolation():
    _write_learning_data("workspace-a")
    train_autocat("workspace-a")
    response = auto_categorize_expenses("workspace-b", _request(allowed=[1, 2]))
    assert response.status == "INSUFFICIENT_LABELED_HISTORY"
    assert response.modelVersion is None


def test_legacy_artifact_is_never_loaded():
    workspace = "legacy"
    legacy = Path(get_settings().AI_MODEL_DIR) / "autocat" / "autocat_v1" / workspace
    legacy.mkdir(parents=True)
    (legacy / "model.joblib").write_bytes(b"legacy")
    response = auto_categorize_expenses(workspace, _request(allowed=[1, 2]))
    assert response.status == "MODEL_REJECTED"
    assert response.reason == "legacy-model-incompatible"
