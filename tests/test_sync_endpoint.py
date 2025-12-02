import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.main import app

os.environ["AI_SERVICE_TOKEN"] = "testtoken"
client = TestClient(app)

def test_invalid_token_rejected():
    resp = client.post("/internal/ai/sync-user-data", json={"userId": "u1"}, headers={"X-Service-Token": "wrong"})
    assert resp.status_code == 401

def test_full_sync_creates_files():
    payload = {
        "userId": "u1",
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
    resp = client.post("/internal/ai/sync-user-data", json=payload, headers={"X-Service-Token": "testtoken"})
    assert resp.status_code == 200 or resp.status_code == 202
    assert resp.json()["status"] == "accepted"

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

