import pytest
from app.features.cashflow.types import CashflowInsightsRequest
from app.features.cashflow.service import get_cashflow_insights


def test_surplus_no_alerts():
    req = CashflowInsightsRequest(months=1)
    resp = get_cashflow_insights("user1", req)
    # For a short period, should be all surplus
    assert all(item.alert is None for item in resp.forecast)
    assert all(item.status == "surplus" for item in resp.forecast)


def test_deficit_alerts():
    req = CashflowInsightsRequest(months=12)
    resp = get_cashflow_insights("user1", req)
    deficit_months = [item for item in resp.forecast if item.status == "deficit"]
    for item in resp.forecast:
        if item.status == "surplus":
            assert item.alert is None
        if item.status == "deficit":
            assert item.alert is not None
            assert getattr(item.alert, "severity", None) == "warning"
    for item in deficit_months:
        assert item.alert is not None
        assert getattr(item.alert, "severity", None) == "warning"


def test_invalid_months():
    with pytest.raises(ValueError):
        get_cashflow_insights("user1", CashflowInsightsRequest(months=-1))
    with pytest.raises(ValueError):
        get_cashflow_insights("user1", CashflowInsightsRequest(months=25))
    with pytest.raises(ValueError):
        get_cashflow_insights("user1", CashflowInsightsRequest(months=0))


def test_success():
    req = CashflowInsightsRequest(months=6)
    resp = get_cashflow_insights("user1", req)
    assert all(item.status in ("surplus", "deficit") for item in resp.forecast)
    assert isinstance(resp.insights, list)
    assert isinstance(resp.averageMonthlyBalance, float)
    assert len(resp.forecast) == 6
    assert resp.currentBalance == 3500.0
