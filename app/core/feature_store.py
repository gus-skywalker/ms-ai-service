import os
import json
import pandas as pd
from typing import List, Optional

from app.core.config import get_settings

STORAGE_PATH = get_settings().AI_FEATURE_STORE_DIR

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
    if raw_transactions is not None and (raw_transactions or mode == "full"):
        df = pd.DataFrame(raw_transactions)
        if df.empty and not len(df.columns):
            df = pd.DataFrame(columns=[
                "transactionId",
                "entryId",
                "userId",
                "workspaceId",
                "type",
                "date",
                "amount",
                "currency",
                "categoryId",
                "description",
            ])
        # Remove transações deletadas
        if "deleted" in df.columns:
            deleted_ids = df[df["deleted"] == True]["transactionId"].tolist()
            if existing_df is not None:
                existing_df = existing_df[~existing_df["transactionId"].isin(deleted_ids)]
            df = df[df["deleted"] != True]
        # Mescla incremental
        if mode == "incremental" and existing_df is not None:
            # Replace all derived ledger entries for each canonical transaction.
            # This preserves multi-entry transactions across retries and updates.
            if "transactionId" in df.columns and "transactionId" in existing_df.columns:
                incoming_transaction_ids = df["transactionId"].dropna().tolist()
                existing_df = existing_df[~existing_df["transactionId"].isin(incoming_transaction_ids)]
            df = pd.concat([existing_df, df])
            deduplication_key = "entryId" if "entryId" in df.columns else "transactionId"
            if deduplication_key in df.columns:
                df = df.drop_duplicates(subset=[deduplication_key], keep="last")
        raw_path = path_for_user(user_id, "raw_transactions.parquet")
        _ensure_parent(raw_path)
        df.to_parquet(raw_path)
    elif mode == "incremental" and existing_df is not None:
        existing_path = path_for_user(user_id, "raw_transactions.parquet")
        _ensure_parent(existing_path)
        existing_df.to_parquet(existing_path)
    if monthly_aggregates:
        normalized_aggregates = {
            key: (None if isinstance(value, dict) and not value else value)
            for key, value in monthly_aggregates.items()
        }
        df = pd.DataFrame([normalized_aggregates])
        monthly_path = path_for_user(user_id, "monthly_series.parquet")
        _ensure_parent(monthly_path)
        df.to_parquet(monthly_path)


def save_semantic_records(user_id, labels, feedback):
    """Persist supervised labels and product feedback separately from canonical facts."""
    _upsert_records(user_id, "trusted_labels.parquet", labels, "labelId")
    _upsert_records(user_id, "feedback_events.parquet", feedback, "feedbackId")


def _upsert_records(user_id, filename, records, key):
    if records is None or not records:
        return
    path = path_for_user(user_id, filename)
    incoming = pd.DataFrame(records)
    if incoming.empty:
        return
    deleted_keys = []
    if "deleted" in incoming.columns and key in incoming.columns:
        deleted_keys = incoming[incoming["deleted"] == True][key].dropna().tolist()
        incoming = incoming[incoming["deleted"] != True]
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        if deleted_keys and key in existing.columns:
            existing = existing[~existing[key].isin(deleted_keys)]
        combined = pd.concat([existing, incoming], ignore_index=True)
    else:
        combined = incoming
    if key in combined.columns:
        combined = combined.drop_duplicates(subset=[key], keep="last")
    _ensure_parent(path)
    combined.to_parquet(path)

def get_metadata(user_id):
    meta_path = path_for_user(user_id, "metadata.json")
    if not os.path.exists(meta_path):
        return {}
    try:
        with open(meta_path) as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return {}


def update_metadata(user_id, timestamp, sync_id=None):
    meta_path = path_for_user(user_id, "metadata.json")
    meta = get_metadata(user_id)
    meta["last_sync"] = timestamp
    if sync_id:
        processed_sync_ids = list(meta.get("processed_sync_ids") or [])
        if sync_id not in processed_sync_ids:
            processed_sync_ids.append(sync_id)
        meta["processed_sync_ids"] = processed_sync_ids[-1000:]
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
