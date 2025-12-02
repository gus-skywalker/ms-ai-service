import os
import json
import pandas as pd
from typing import List, Optional

STORAGE_PATH = "storage/user_data"

def path_for_user(user_id: str, filename: str) -> str:
    return os.path.join(STORAGE_PATH, str(user_id), filename)

def save_user_data(user_id, raw_transactions, monthly_aggregates, mode, sync_type):
    user_dir = os.path.join(STORAGE_PATH, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    if raw_transactions:
        df = pd.DataFrame(raw_transactions)
        df.to_parquet(path_for_user(user_id, "raw_transactions.parquet"))
    if monthly_aggregates:
        df = pd.DataFrame([monthly_aggregates])
        df.to_parquet(path_for_user(user_id, "monthly_series.parquet"))

def update_metadata(user_id, timestamp):
    meta_path = path_for_user(user_id, "metadata.json")
    meta = {"last_sync": timestamp}
    with open(meta_path, "w") as f:
        json.dump(meta, f)

class UserFinancialDataProvider:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.user_dir = os.path.join(STORAGE_PATH, str(user_id))
    def get_user_transactions(self, months: Optional[int] = None):
        path = path_for_user(self.user_id, "raw_transactions.parquet")
        if not os.path.exists(path):
            return []
        df = pd.read_parquet(path)
        if months:
            # Filter by last N months
            df["date"] = pd.to_datetime(df["date"])
            cutoff = pd.Timestamp.now() - pd.DateOffset(months=months)
            df = df[df["date"] >= cutoff]
        return df.to_dict("records")
    def get_monthly_totals(self, months: Optional[int] = None):
        path = path_for_user(self.user_id, "monthly_series.parquet")
        if not os.path.exists(path):
            return {}
        df = pd.read_parquet(path)
        if months:
            # Filter by last N months
            df = df.tail(months)
        return df.to_dict("records")
    def get_current_balance(self):
        monthly = self.get_monthly_totals(months=1)
        if monthly:
            m = monthly[0]
            # income/expenses são dicts: pegar o maior valor (mês mais recente)
            income = max(m.get("income", {}).values()) if m.get("income") else 0
            expenses = max(m.get("expenses", {}).values()) if m.get("expenses") else 0
            return income - expenses
        return 0
    def get_category_stats(self):
        path = path_for_user(self.user_id, "categories_stats.json")
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            return json.load(f)
