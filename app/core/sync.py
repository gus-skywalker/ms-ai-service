from __future__ import annotations

from datetime import datetime, timezone
from fastapi import HTTPException
from app.core.feature_store import get_metadata, save_semantic_records, save_user_data, update_metadata
from app.core.training_queue import enqueue_autocat_training_job
from app.features.autocat.policy import evaluate_eligibility, validate_label_source

def handle_sync_request(payload: dict):
    workspace_id = _resolve_workspace_id(payload)
    schema_version = payload.get("schemaVersion", 1)
    if schema_version != 1:
        raise HTTPException(status_code=400, detail="Unsupported schemaVersion")
    mode = str(payload.get("mode", "FULL")).strip().lower()
    if mode not in {"full", "incremental"}:
        raise HTTPException(status_code=400, detail="mode must be FULL or INCREMENTAL")
    sync_type = str(payload.get("syncType", mode)).strip().lower()
    sync_id = _optional_string(payload.get("syncId"))
    timestamp = payload.get("timestamp", datetime.now(timezone.utc).isoformat())
    if sync_id and sync_id in (get_metadata(workspace_id).get("processed_sync_ids") or []):
        return {
            "status": "duplicate",
            "workspaceId": workspace_id,
            "userId": workspace_id,
            "syncId": sync_id,
            "lastSync": timestamp,
            "queued": False,
            "jobId": None,
            "alreadyRunning": False,
        }
    # Process rawTransactions or monthlyAggregates
    raw_transactions = payload.get("transactions")
    if raw_transactions is None:
        raw_transactions = payload.get("rawTransactions")
    monthly_aggregates = payload.get("monthlyAggregates")
    labels = payload.get("labels") or []
    feedback = payload.get("feedback") or []
    _validate_trusted_labels(labels)
    # Save feature store files
    save_user_data(workspace_id, raw_transactions, monthly_aggregates, mode, sync_type)
    save_semantic_records(workspace_id, labels, feedback)
    update_metadata(workspace_id, timestamp, sync_id)
    job_id = None
    queued = False
    already_running = False
    eligibility = evaluate_eligibility(workspace_id)
    enqueue_reason = "NOT_ELIGIBLE"
    if eligibility.eligible and eligibility.datasetFingerprint:
        job_id, already_running, enqueue_reason = enqueue_autocat_training_job(
            workspace_id, eligibility.datasetFingerprint,
        )
        queued = job_id is not None
    return {
        "status": "accepted",
        "workspaceId": workspace_id,
        "userId": workspace_id,
        "syncId": sync_id,
        "lastSync": timestamp,
        "queued": queued,
        "jobId": job_id,
        "alreadyRunning": already_running,
        "trainingDecision": enqueue_reason,
        "autocatEligibility": eligibility.to_dict(),
    }


def _resolve_workspace_id(payload: dict) -> str:
    workspace_id = _optional_string(payload.get("workspaceId"))
    legacy_user_id = _optional_string(payload.get("userId"))
    if workspace_id and legacy_user_id and workspace_id != legacy_user_id:
        raise HTTPException(status_code=400, detail="workspaceId and legacy userId must match")
    resolved = workspace_id or legacy_user_id
    if not resolved:
        raise HTTPException(status_code=400, detail="Missing workspaceId")
    return resolved


def _optional_string(value) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _validate_trusted_labels(labels):
    for label in labels:
        if not isinstance(label, dict):
            raise HTTPException(status_code=400, detail="Each label must be an object")
        try:
            validate_label_source(label.get("labelSource"))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
