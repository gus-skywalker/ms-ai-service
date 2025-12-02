import os
import pandas as pd
from app.core.feature_store import UserFinancialDataProvider, save_user_data

def setup_user_data(user_id):
    raw = [
        {"transactionId": "t1", "date": "2025-11-01", "amount": -35.5, "type": "EXPENSE", "categoryId": 10, "description": "Uber"},
        {"transactionId": "t2", "date": "2025-12-01", "amount": 5000.0, "type": "INCOME", "categoryId": None, "description": "Salário"}
    ]
    monthly = {
        "income": {"2025-11": 5000.0, "2025-12": 5100.0},
        "expenses": {"2025-11": 4200.0, "2025-12": 4300.0},
        "categories": {"food": 800.0, "transport": 300.0}
    }
    save_user_data(user_id, raw, monthly, "full", "full")

def test_get_user_transactions():
    user_id = "testuser"
    setup_user_data(user_id)
    provider = UserFinancialDataProvider(user_id)
    txs = provider.get_user_transactions()
    assert len(txs) == 2
    txs_last_month = provider.get_user_transactions(months=1)
    assert isinstance(txs_last_month, list)

def test_get_monthly_totals_returns_expected():
    user_id = "testuser"
    setup_user_data(user_id)
    provider = UserFinancialDataProvider(user_id)
    totals = provider.get_monthly_totals()
    assert isinstance(totals, list)
    assert len(totals) == 1 or len(totals) == 2

def test_get_current_balance():
    user_id = "testuser"
    setup_user_data(user_id)
    provider = UserFinancialDataProvider(user_id)
    balance = provider.get_current_balance()
    assert isinstance(balance, (int, float))

