from datetime import datetime, timezone
from fastapi import HTTPException
from app.core.feature_store import save_user_data, update_metadata
from app.core.models_registry import run_async_training

def handle_sync_request(payload: dict):
    user_id = payload.get("userId")
    mode = payload.get("mode", "full")
    sync_type = payload.get("syncType", "full")
    timestamp = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing userId")
    # Process rawTransactions or monthlyAggregates
    raw_transactions = payload.get("rawTransactions")
    monthly_aggregates = payload.get("monthlyAggregates")
    # Save feature store files
    save_user_data(user_id, raw_transactions, monthly_aggregates, mode, sync_type)
    update_metadata(user_id, timestamp)
    # Dispara treinamento assíncrono
    run_async_training(user_id)
    return {
        "status": "accepted",
        "userId": user_id,
        "lastSync": timestamp,
        "trained": False
    }
