import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.feature_store import UserFinancialDataProvider
from app.core.feature_store import path_for_user
import pandas as pd

os.environ["AI_SERVICE_TOKEN"] = "testtoken"
client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_feature_store(tmp_path, monkeypatch):
    monkeypatch.setattr("app.core.feature_store.STORAGE_PATH", str(tmp_path / "workspace_data"))
    monkeypatch.setattr("app.core.sync.is_eligible_for_training", lambda _workspace_id: False)

def test_invalid_token_rejected():
    resp = client.post("/internal/ai/sync-user-data", json={"userId": "u1"}, headers={"X-Service-Token": "wrong"})
    assert resp.status_code == 401

def test_full_sync_creates_files():
    payload = {
        "schemaVersion": 1,
        "workspaceId": "workspace-1",
        "actorUserId": "actor-1",
        "requestId": "request-1",
        "syncId": "sync-1",
        "mode": "FULL",
        "transactions": [
            {"transactionId": "t1", "date": "2025-11-01", "amount": -35.5, "type": "EXPENSE", "categoryId": 10, "description": "Uber"}
        ],
        "monthlyAggregates": {
            "income": {"2025-11": 5000.0},
            "expenses": {"2025-11": 4200.0},
            "categories": {"food": 800.0, "transport": 300.0}
        },
        "syncType": "full",
        "source": "budget-api",
        "timestamp": "2025-12-02T15:00:00Z"
    }
    resp = client.post("/internal/ai/sync-user-data", json=payload, headers={"X-Service-Token": "testtoken"})
    assert resp.status_code == 200 or resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    assert resp.json()["workspaceId"] == "workspace-1"

def test_incremental_sync_merges():
    payload1 = {
        "userId": "u2",
        "mode": "full",
        "rawTransactions": [
            {"transactionId": "t1", "date": "2025-11-01", "amount": -35.5, "type": "EXPENSE", "categoryId": 10, "description": "Uber"}
        ],
        "monthlyAggregates": {
            "income": {"2025-11": 5000.0},
            "expenses": {"2025-11": 4200.0},
            "categories": {"food": 800.0, "transport": 300.0}
        },
        "syncType": "full",
        "source": "budget-api",
        "timestamp": "2025-12-02T15:00:00Z"
    }
    payload2 = {
        "userId": "u2",
        "mode": "incremental",
        "rawTransactions": [
            {"transactionId": "t2", "date": "2025-12-01", "amount": -20.0, "type": "EXPENSE", "categoryId": 11, "description": "Padaria"}
        ],
        "monthlyAggregates": {
            "income": {"2025-12": 5100.0},
            "expenses": {"2025-12": 4300.0},
            "categories": {"food": 850.0, "transport": 320.0}
        },
        "syncType": "incremental",
        "source": "budget-api",
        "timestamp": "2025-12-02T16:00:00Z"
    }
    resp1 = client.post("/internal/ai/sync-user-data", json=payload1, headers={"X-Service-Token": "testtoken"})
    resp2 = client.post("/internal/ai/sync-user-data", json=payload2, headers={"X-Service-Token": "testtoken"})
    assert resp1.status_code == 200 or resp1.status_code == 202
    assert resp2.status_code == 200 or resp2.status_code == 202
    assert resp2.json()["status"] == "accepted"


def test_sync_rejects_conflicting_legacy_identity():
    response = client.post(
        "/internal/ai/sync-user-data",
        json={"workspaceId": "workspace-1", "userId": "user-1"},
        headers={"X-Service-Token": "testtoken"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "workspaceId and legacy userId must match"


def test_sync_id_is_idempotent():
    payload = {
        "schemaVersion": 1,
        "workspaceId": "workspace-idempotent",
        "syncId": "same-sync",
        "mode": "INCREMENTAL",
        "transactions": [
            {"transactionId": "t1", "date": "2025-11-01", "amount": 35.5, "type": "EXPENSE", "description": "Uber"}
        ],
    }

    first = client.post("/internal/ai/sync-user-data", json=payload, headers={"X-Service-Token": "testtoken"})
    second = client.post("/internal/ai/sync-user-data", json=payload, headers={"X-Service-Token": "testtoken"})

    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"


def test_internal_prediction_reads_only_explicit_workspace_feature_store():
    for workspace_id, amount in (("workspace-a", 100.0), ("workspace-b", 900.0)):
        sync = client.post(
            "/internal/ai/sync-user-data",
            json={
                "schemaVersion": 1,
                "workspaceId": workspace_id,
                "syncId": f"sync-{workspace_id}",
                "mode": "FULL",
                "transactions": [],
                "monthlyAggregates": {
                    "income": {"2026-06": 1000.0},
                    "expenses": {"2026-06": amount},
                    "categories": {},
                },
            },
            headers={"X-Service-Token": "testtoken"},
        )
        assert sync.status_code == 200

    response = client.post(
        "/internal/ai/monthly-expenses-prediction",
        json={
            "workspaceId": "workspace-a",
            "actorUserId": "actor-from-another-workspace",
            "requestId": "request-isolation",
            "categoryId": None,
            "forecastMonths": 1,
            "historicalTransactions": [],
        },
        headers={"X-Service-Token": "testtoken"},
    )

    assert response.status_code == 200
    assert response.json()["predictions"][0]["predictedAmount"] == 100.0


def test_internal_prediction_requires_workspace_id():
    response = client.post(
        "/internal/ai/monthly-expenses-prediction",
        json={"categoryId": None, "forecastMonths": 1, "historicalTransactions": []},
        headers={"X-Service-Token": "testtoken"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "workspaceId is required"


def test_incremental_update_preserves_all_entries_of_same_transaction():
    workspace_id = "workspace-multi-entry"
    headers = {"X-Service-Token": "testtoken"}
    base = {
        "schemaVersion": 1,
        "workspaceId": workspace_id,
        "mode": "INCREMENTAL",
    }
    first = client.post(
        "/internal/ai/sync-user-data",
        json={
            **base,
            "syncId": "multi-1",
            "transactions": [
                {"transactionId": "tx-1", "entryId": "entry-1", "date": "2026-07-01", "amount": 100, "type": "EXPENSE", "description": "Split"},
                {"transactionId": "tx-1", "entryId": "entry-2", "date": "2026-07-01", "amount": 40, "type": "EXPENSE", "description": "Split"},
            ],
        },
        headers=headers,
    )
    second = client.post(
        "/internal/ai/sync-user-data",
        json={
            **base,
            "syncId": "multi-2",
            "transactions": [
                {"transactionId": "tx-1", "entryId": "entry-1", "date": "2026-07-01", "amount": 110, "type": "EXPENSE", "description": "Split updated"},
                {"transactionId": "tx-1", "entryId": "entry-2", "date": "2026-07-01", "amount": 45, "type": "EXPENSE", "description": "Split updated"},
            ],
        },
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    stored = UserFinancialDataProvider(workspace_id).get_user_transactions()
    assert len(stored) == 2
    assert sorted(item["amount"] for item in stored) == [45, 110]


def test_labels_and_feedback_are_stored_separately_and_idempotently():
    payload = {
        "schemaVersion": 1,
        "workspaceId": "workspace-learning",
        "syncId": "learning-1",
        "mode": "INCREMENTAL",
        "transactions": [{"transactionId": "t1", "entryId": "e1", "date": "2026-07-01", "amount": 10, "type": "EXPENSE"}],
        "labels": [{"labelId": "l1", "transactionId": "t1", "entryId": "e1", "categoryId": 7, "labelSource": "USER", "trust": 1.0}],
        "feedback": [{"feedbackId": "f1", "eventType": "SUGGESTION_ACCEPTED", "transactionId": "t1"}],
    }
    response = client.post("/internal/ai/sync-user-data", json=payload, headers={"X-Service-Token": "testtoken"})

    assert response.status_code == 200
    labels = pd.read_parquet(path_for_user("workspace-learning", "trusted_labels.parquet"))
    feedback = pd.read_parquet(path_for_user("workspace-learning", "feedback_events.parquet"))
    assert labels.to_dict("records")[0]["labelSource"] == "USER"
    assert feedback.to_dict("records")[0]["eventType"] == "SUGGESTION_ACCEPTED"


def test_ai_generated_category_is_rejected_as_trusted_label():
    response = client.post(
        "/internal/ai/sync-user-data",
        json={
            "schemaVersion": 1,
            "workspaceId": "workspace-untrusted",
            "syncId": "untrusted-1",
            "mode": "INCREMENTAL",
            "transactions": [],
            "labels": [{"labelId": "l-ai", "transactionId": "t1", "categoryId": 9, "labelSource": "AI"}],
        },
        headers={"X-Service-Token": "testtoken"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Untrusted labelSource: AI"
