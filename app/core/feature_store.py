import os
import json
import pandas as pd
from typing import List, Optional

STORAGE_PATH = "storage/user_data"

def path_for_user(user_id: str, filename: str) -> str:
    return os.path.join(STORAGE_PATH, str(user_id), filename)

def _ensure_parent(path: str):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

def save_user_data(user_id, raw_transactions, monthly_aggregates, mode, sync_type):
    user_dir = os.path.join(STORAGE_PATH, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    # Carrega transações existentes se incremental
    existing_path = path_for_user(user_id, "raw_transactions.parquet")
    existing_df = None
    if mode == "incremental" and os.path.exists(existing_path):
        existing_df = pd.read_parquet(existing_path)
    # Processa transações
    if raw_transactions:
        df = pd.DataFrame(raw_transactions)
        # Remove transações deletadas
        if "deleted" in df.columns:
            deleted_ids = df[df["deleted"] == True]["transactionId"].tolist()
            if existing_df is not None:
                existing_df = existing_df[~existing_df["transactionId"].isin(deleted_ids)]
            df = df[df["deleted"] != True]
        # Mescla incremental
        if mode == "incremental" and existing_df is not None:
            # Remove duplicadas pelo transactionId
            df = pd.concat([existing_df, df]).drop_duplicates(subset=["transactionId"], keep="last")
        raw_path = path_for_user(user_id, "raw_transactions.parquet")
        _ensure_parent(raw_path)
        df.to_parquet(raw_path)
    elif mode == "incremental" and existing_df is not None:
        existing_path = path_for_user(user_id, "raw_transactions.parquet")
        _ensure_parent(existing_path)
        existing_df.to_parquet(existing_path)
    if monthly_aggregates:
        df = pd.DataFrame([monthly_aggregates])
        monthly_path = path_for_user(user_id, "monthly_series.parquet")
        _ensure_parent(monthly_path)
        df.to_parquet(monthly_path)

def update_metadata(user_id, timestamp):
    meta_path = path_for_user(user_id, "metadata.json")
    meta = {"last_sync": timestamp}
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
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
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)
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
