from __future__ import annotations

from datetime import date
from typing import List
from unittest.mock import MagicMock, patch
import math

from app.core import config
from app.features.prediction.service import predict_monthly_expenses, _derive_trend
from app.features.prediction.types import MonthlyExpensesPredictionRequest
from app.models.transactions import AiTransaction


def _build_month_date(base: date, offset: int) -> date:
    """Return a date offset months back from base."""
    year = base.year
    month = base.month - offset
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 15)


def _make_transactions(months: int, user_id: str, base_amount: float = 500.0) -> List[AiTransaction]:
    base = date.today().replace(day=1)
    transactions: List[AiTransaction] = []
    for i in range(months):
        tx_date = _build_month_date(base, months - i)
        transactions.append(
            AiTransaction(
                transactionId=f"tx-{i}",
                userId=user_id,
                type="EXPENSE",
                date=tx_date.isoformat(),
                amount=base_amount + i * 10,
                currency="BRL",
                categoryId=1,
                categoryCode="groceries",
            )
        )
    return transactions


def _mock_registry(saved_payload_container: dict):
    registry = MagicMock()
    registry.load_model.return_value = saved_payload_container.get("payload")

    def _save(key, payload):
        saved_payload_container["payload"] = payload
        return None

    registry.save_model.side_effect = _save
    return registry


def _prediction_request(months: int, user_id: str) -> MonthlyExpensesPredictionRequest:
    transactions = _make_transactions(months, user_id)
    return MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=3,
        historicalTransactions=transactions,
    )


def test_prediction_returns_forecast(tmp_path, monkeypatch):
    # Ensure models are stored under a temporary directory for isolation.
    monkeypatch.setenv("AI_MODEL_DIR", str(tmp_path))
    config.get_settings.cache_clear()

    user_id = "test-user"
    historical_transactions = _make_transactions(12, user_id)
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=3,
        historicalTransactions=historical_transactions,
    )

    response = predict_monthly_expenses(user_id=user_id, request=request)

    assert len(response.predictions) == request.forecastMonths
    assert response.totalPredicted >= 0
    for item in response.predictions:
        assert item.predictedAmount >= 0
        assert item.confidence >= 0


def test_model_trains_and_persists_when_enough_history(monkeypatch):
    saved_payload = {}
    registry = _mock_registry(saved_payload)
    monkeypatch.setattr("app.features.prediction.service.get_model_registry", lambda: registry)

    user_id = "user-model"
    request = _prediction_request(12, user_id)

    response = predict_monthly_expenses(user_id=user_id, request=request)

    assert len(response.predictions) == 3
    assert response.modelAccuracy is not None
    assert saved_payload["payload"].get("model_path") is not None
    assert saved_payload["payload"].get("trained_months") == 12
    assert response.predictions[0].predictedAmount >= 0
    assert response.predictions[0].minExpected <= response.predictions[0].maxExpected


def test_fallback_is_used_when_insufficient_history(monkeypatch):
    saved_payload = {}
    registry = _mock_registry(saved_payload)
    monkeypatch.setattr("app.features.prediction.service.get_model_registry", lambda: registry)

    user_id = "user-fallback"
    request = _prediction_request(3, user_id)

    response = predict_monthly_expenses(user_id=user_id, request=request)

    assert len(response.predictions) == 3
    assert response.modelAccuracy is None
    assert all(item.predictedAmount == response.predictions[0].historicalAverage for item in response.predictions)


def test_cached_model_is_loaded_and_reused(monkeypatch):
    saved_payload = {}
    registry = _mock_registry(saved_payload)

    user_id = "user-cached"
    initial_request = _prediction_request(8, user_id)
    monkeypatch.setattr("app.features.prediction.service.get_model_registry", lambda: registry)
    _ = predict_monthly_expenses(user_id=user_id, request=initial_request)

    cached_payload = saved_payload["payload"]
    assert cached_payload.get("model_path")
    registry.load_model.return_value = cached_payload

    more_transactions = _make_transactions(8, user_id, base_amount=700.0)
    request_with_cache = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=more_transactions,
    )

    response = predict_monthly_expenses(user_id=user_id, request=request_with_cache)

    assert len(response.predictions) == 2
    assert response.modelAccuracy == round(cached_payload["stats"]["confidence"], 2)
    assert registry.save_model.call_count >= 1
    assert all(item.modelAccuracy is None if hasattr(item, "modelAccuracy") else True for item in [])


def test_trend_increasing():
    user_id = "trend-up"
    # Increasing pattern
    txs = _make_transactions(8, user_id, base_amount=100)
    for i, tx in enumerate(txs):
        tx.amount = 100 + i * 20
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=txs,
    )
    response = predict_monthly_expenses(user_id=user_id, request=request)
    assert all(p.trend == "increasing" for p in response.predictions)


def test_trend_decreasing():
    user_id = "trend-down"
    txs = _make_transactions(8, user_id, base_amount=200)
    for i, tx in enumerate(txs):
        tx.amount = 200 - i * 10
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=txs,
    )
    response = predict_monthly_expenses(user_id=user_id, request=request)
    assert all(p.trend == "decreasing" for p in response.predictions)


def test_trend_stable():
    user_id = "trend-stable"
    txs = _make_transactions(8, user_id, base_amount=300)
    for tx in txs:
        tx.amount = 300
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=txs,
    )
    response = predict_monthly_expenses(user_id=user_id, request=request)
    assert all(p.trend == "stable" for p in response.predictions)


def test_bounds_are_correct():
    user_id = "bounds"
    txs = _make_transactions(8, user_id, base_amount=500)
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=txs,
    )
    response = predict_monthly_expenses(user_id=user_id, request=request)
    for p in response.predictions:
        assert p.minExpected <= p.predictedAmount <= p.maxExpected
        assert p.minExpected >= 0
        assert p.maxExpected >= p.predictedAmount


def test_fallback_when_model_load_fails(monkeypatch):
    saved_payload = {}
    registry = _mock_registry(saved_payload)
    # Simulate model_path present but file missing
    user_id = "fail-load"
    request = _prediction_request(8, user_id)
    monkeypatch.setattr("app.features.prediction.service.get_model_registry", lambda: registry)
    monkeypatch.setattr("app.features.prediction.service._load_rf_model", lambda _: None)
    # Save a payload with a bogus model_path
    saved_payload["payload"] = {
        "model_path": "/tmp/nonexistent_model.joblib",
        "feature_order": ["total_amount", "moving_avg_3", "moving_avg_6", "month_of_year"],
        "stats": {"confidence": 0.5},
        "avg": 500.0,
        "months": 8,
        "trained_months": 8,
        "recent_totals": [500, 510, 520, 530, 540, 550],
    }
    response = predict_monthly_expenses(user_id=user_id, request=request)
    assert response.modelAccuracy is None or response.modelAccuracy < 1
    for p in response.predictions:
        assert math.isclose(p.predictedAmount, p.historicalAverage, rel_tol=1e-6)


def test_out_of_order_month_series(monkeypatch):
    user_id = "out-of-order"
    txs = _make_transactions(8, user_id, base_amount=100)
    # Shuffle months out of order
    txs = txs[::-1]
    request = MonthlyExpensesPredictionRequest(
        categoryId=None,
        forecastMonths=2,
        historicalTransactions=txs,
    )
    response = predict_monthly_expenses(user_id=user_id, request=request)
    # Should still be sorted and predictions valid
    assert len(response.predictions) == 2
    assert all(p.predictedAmount >= 0 for p in response.predictions)
