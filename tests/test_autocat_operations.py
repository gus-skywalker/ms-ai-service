from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.feature_store import path_for_user
from app.features.autocat.bundle_store import IncompatibleBundleError, get_autocat_bundle_store, validate_bundle
from app.features.autocat.feedback_metrics import feedback_metrics
from app.features.autocat.policy import evaluate_eligibility
from app.features.autocat.service import auto_categorize_expenses
from app.features.autocat.training import train_autocat
from app.features.autocat.types import AutoCategorizeRequest, AutoCategorizeRequestItem
from app.main import app


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.feature_store.STORAGE_PATH", str(tmp_path / "workspace_data"))
    monkeypatch.setenv("AI_MODEL_DIR", str(tmp_path / "models"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _data(workspace: str):
    root = Path(path_for_user(workspace, "raw_transactions.parquet"))
    root.parent.mkdir(parents=True, exist_ok=True)
    transactions, labels = [], []
    for index in range(24):
        category = 1 if index % 2 == 0 else 2
        transactions.append({
            "workspaceId": workspace, "transactionId": f"t{index}", "entryId": f"e{index}",
            "description": ("mercado comida " if category == 1 else "uber transporte ") + str(index),
            "amount": index + 1,
        })
        labels.append({
            "labelId": f"l{index}", "transactionId": f"t{index}", "entryId": f"e{index}",
            "categoryId": category, "labelSource": "USER", "trust": 1.0,
            "labeledAt": f"2026-07-{index + 1:02d}T00:00:00Z",
        })
    pd.DataFrame(transactions).to_parquet(root)
    pd.DataFrame(labels).to_parquet(path_for_user(workspace, "trusted_labels.parquet"))


def _request():
    return AutoCategorizeRequest(
        allowedCategoryIds=[1, 2],
        expenses=[AutoCategorizeRequestItem(expenseId="x", description="mercado comida", amount=10, paymentMethodId=1)],
    )


def test_bundle_validation_rejects_incomplete_artifact():
    with pytest.raises(IncompatibleBundleError, match="missing fields"):
        validate_bundle({"modelVersion": "bad"})


def test_failed_candidate_build_preserves_previous_active(monkeypatch):
    _data("preserve")
    first = train_autocat("preserve")
    labels_path = path_for_user("preserve", "trusted_labels.parquet")
    labels = pd.read_parquet(labels_path)
    labels.loc[0, "categoryId"] = 2
    labels.to_parquet(labels_path)
    monkeypatch.setattr("app.features.autocat.training.build_candidate_bundle", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        train_autocat("preserve")
    assert get_autocat_bundle_store().active_metadata("preserve")["modelVersion"] == first["modelVersion"]


def test_rejected_candidate_is_persisted_but_not_activated(monkeypatch):
    _data("rejected")
    first = train_autocat("rejected")
    labels_path = path_for_user("rejected", "trusted_labels.parquet")
    labels = pd.read_parquet(labels_path)
    labels.loc[0, "categoryId"] = 2
    labels.to_parquet(labels_path)
    monkeypatch.setattr("app.features.autocat.training.publication_blocking_reasons", lambda *_args: ["TEST_REJECTION"])
    rejected = train_autocat("rejected")
    versions = get_autocat_bundle_store().list_versions("rejected")
    assert rejected["status"] == "MODEL_REJECTED"
    assert len(versions) == 2
    assert get_autocat_bundle_store().active_metadata("rejected")["modelVersion"] == first["modelVersion"]


def test_previous_version_can_be_reactivated():
    _data("rollback")
    first = train_autocat("rollback")
    labels_path = path_for_user("rollback", "trusted_labels.parquet")
    labels = pd.read_parquet(labels_path)
    labels.loc[0, "categoryId"] = 2
    labels.to_parquet(labels_path)
    second = train_autocat("rollback")
    assert second["modelVersion"] != first["modelVersion"]
    get_autocat_bundle_store().activate("rollback", first["modelVersion"])
    assert get_autocat_bundle_store().active_metadata("rollback")["modelVersion"] == first["modelVersion"]


def test_corrupt_active_pointer_returns_semantic_rejection():
    _data("corrupt")
    train_autocat("corrupt")
    pointer = get_autocat_bundle_store().workspace_root("corrupt") / "active.json"
    pointer.write_text("not-json", encoding="utf-8")
    response = auto_categorize_expenses("corrupt", _request())
    assert response.status == "MODEL_REJECTED"
    assert response.suggestions[0].safeToApply is False


def test_unexpected_classifier_error_returns_semantic_rejection(monkeypatch):
    _data("broken-inference")
    train_autocat("broken-inference")
    bundle = get_autocat_bundle_store().load_active("broken-inference")

    class BrokenClassifier:
        def predict_proba(self, _matrix):
            raise RuntimeError("unexpected classifier failure")

    bundle["classifier"] = BrokenClassifier()
    monkeypatch.setattr(get_autocat_bundle_store(), "load_active", lambda _workspace: bundle)
    response = auto_categorize_expenses("broken-inference", _request())
    assert response.status == "MODEL_REJECTED"
    assert response.reason == "model-inference-error"


def test_fingerprint_changes_when_supervised_semantics_change():
    _data("fingerprint")
    before = evaluate_eligibility("fingerprint").datasetFingerprint
    path = path_for_user("fingerprint", "trusted_labels.parquet")
    labels = pd.read_parquet(path)
    labels.loc[0, "categoryId"] = 2
    labels.to_parquet(path)
    assert evaluate_eligibility("fingerprint").datasetFingerprint != before


def test_feedback_metrics_are_partitioned_and_aggregated():
    workspace = "feedback"
    path = Path(path_for_user(workspace, "feedback_events.parquet"))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([
        {"workspaceId": workspace, "eventType": "SUGGESTION_ACCEPTED", "strategyVersion": "v1", "modelVersion": "m1", "confidence": 0.9},
        {"workspaceId": workspace, "eventType": "CATEGORY_CORRECTED", "strategyVersion": "v1", "modelVersion": "m1", "confidence": 0.6},
        {"workspaceId": "other", "eventType": "SUGGESTION_REJECTED", "strategyVersion": "v2", "modelVersion": "m2", "confidence": 0.2},
    ]).to_parquet(path)
    result = feedback_metrics(workspace)
    assert result["totalFeedback"] == 2
    assert result["counts"]["SUGGESTION_ACCEPTED"] == 1
    assert result["counts"]["SUGGESTION_REJECTED"] == 0
    assert result["byModelVersion"]["m1"]["CATEGORY_CORRECTED"] == 1


def test_internal_operations_require_service_token():
    response = TestClient(app).get("/internal/ai/workspace/w/autocat/eligibility", headers={"X-Service-Token": "wrong"})
    assert response.status_code == 401


def test_internal_model_inventory_reports_active_version():
    _data("inventory")
    trained = train_autocat("inventory")
    response = TestClient(app).get(
        "/internal/ai/workspace/inventory/autocat/models",
        headers={"X-Service-Token": "testtoken"},
    )
    assert response.status_code == 200
    assert response.json()["models"][0]["modelVersion"] == trained["modelVersion"]
    assert response.json()["models"][0]["active"] is True
