import os
import json
import joblib
from typing import Optional

class ModelKey:
    def __init__(self, feature: str, version: str, user_id: Optional[str] = None):
        self.feature = feature
        self.version = version
        self.user_id = user_id

    def path(self):
        from app.core.config import get_settings

        parts = [get_settings().AI_MODEL_DIR, self.feature, self.version]
        if self.user_id:
            parts.append(str(self.user_id))
        return os.path.join(*parts)

class ModelRegistry:
    def save_model(self, key: ModelKey, payload):
        path = key.path()
        os.makedirs(path, exist_ok=True)
        file_path = os.path.join(path, "model.joblib")
        joblib.dump(payload, file_path)
        meta_path = os.path.join(path, "meta.json")
        with open(meta_path, "w") as f:
            json.dump({"feature": key.feature, "version": key.version, "user_id": key.user_id}, f)

    def load_model(self, key: ModelKey):
        path = key.path()
        file_path = os.path.join(path, "model.joblib")
        if not os.path.exists(file_path):
            return None
        return joblib.load(file_path)

    def get_model_path(self, key: ModelKey):
        return os.path.join(key.path(), "model.joblib")

    def delete_model(self, key: ModelKey):
        path = key.path()
        if os.path.isdir(path):
            import shutil
            shutil.rmtree(path)

_registry = ModelRegistry()

def get_model_registry():
    return _registry

def get_model_path(feature, version, user_id=None):
    key = ModelKey(feature, version, user_id)
    return _registry.get_model_path(key)

def save_model(feature, version, model_obj, user_id=None):
    key = ModelKey(feature, version, user_id)
    _registry.save_model(key, model_obj)

def load_model(feature, version, user_id=None, fallback=True):
    key = ModelKey(feature, version, user_id)
    model = _registry.load_model(key)
    if model is None and fallback:
        return _registry.load_model(ModelKey(feature, version, None))
    return model

# --- Trainer skeletons ---
import pandas as pd
import threading

def train_prediction(user_id):
    # Load monthly_series.parquet
    from app.core.feature_store import path_for_user
    path = path_for_user(user_id, "monthly_series.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    # Simple baseline: mean of expenses
    expenses = df.iloc[0].get("expenses", {})
    avg = sum(expenses.values()) / len(expenses) if expenses else 0.0
    save_model("prediction", "v1", {"avg": avg}, user_id)
    return avg

def train_autocat(user_id):
    from app.features.autocat.training import train_autocat as canonical_train_autocat

    return canonical_train_autocat(user_id)

def compute_anomaly_stats(user_id):
    # Placeholder: compute median/MAD per category
    from app.core.feature_store import path_for_user
    path = path_for_user(user_id, "raw_transactions.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    stats = {}
    for cat in df["categoryId"].dropna().unique():
        # Garante que a chave do dict será str
        cat_key = str(cat)
        amounts = df[df["categoryId"] == cat]["amount"].values
        median = float(pd.Series(amounts).median())
        mad = float((abs(pd.Series(amounts) - median)).median())
        stats[cat_key] = {"median": median, "mad": mad}
    # Save as JSON
    out_path = path_for_user(user_id, "anomaly_stats.json")
    with open(out_path, "w") as f:
        json.dump(stats, f)
    return stats

def run_async_training(user_id):
    threading.Thread(target=train_prediction, args=(user_id,), daemon=True).start()
    threading.Thread(target=train_autocat, args=(user_id,), daemon=True).start()
    threading.Thread(target=compute_anomaly_stats, args=(user_id,), daemon=True).start()
