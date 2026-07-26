from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.core.feature_store import path_for_user


KNOWN_FEEDBACK_TYPES = {"SUGGESTION_ACCEPTED", "SUGGESTION_REJECTED", "CATEGORY_CORRECTED"}


def feedback_metrics(workspace_id: str) -> dict[str, Any]:
    path = Path(path_for_user(workspace_id, "feedback_events.parquet"))
    if not path.exists():
        return _empty_metrics(workspace_id)
    frame = pd.read_parquet(path)
    if frame.empty:
        return _empty_metrics(workspace_id)
    frame = frame.copy()
    if "workspaceId" in frame.columns:
        frame = frame[frame["workspaceId"].fillna(workspace_id).astype(str) == str(workspace_id)]
    type_column = next((column for column in ("feedbackType", "eventType", "type") if column in frame.columns), None)
    if type_column not in frame.columns:
        return _empty_metrics(workspace_id)
    frame["feedbackType"] = frame[type_column].fillna("").astype(str).str.upper()
    frame = frame[frame["feedbackType"].isin(KNOWN_FEEDBACK_TYPES)]
    counts = {kind: int((frame["feedbackType"] == kind).sum()) for kind in sorted(KNOWN_FEEDBACK_TYPES)}
    total = int(len(frame))
    result = {
        "workspaceId": workspace_id,
        "totalFeedback": total,
        "counts": counts,
        "rates": {kind: round(value / total, 6) if total else 0.0 for kind, value in counts.items()},
        "byStrategyVersion": _group_counts(frame, "strategyVersion"),
        "byModelVersion": _group_counts(frame, "modelVersion"),
        "byConfidenceBucket": _confidence_buckets(frame),
    }
    return result


def _group_counts(frame: pd.DataFrame, column: str) -> dict[str, dict[str, int]]:
    if column not in frame.columns or frame.empty:
        return {}
    grouped = frame.assign(_key=frame[column].fillna("UNKNOWN").astype(str)).groupby(["_key", "feedbackType"]).size()
    result: dict[str, dict[str, int]] = {}
    for (key, feedback_type), count in grouped.items():
        result.setdefault(str(key), {})[str(feedback_type)] = int(count)
    return result


def _confidence_buckets(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    if "confidence" not in frame.columns or frame.empty:
        return {}
    confidence = pd.to_numeric(frame["confidence"], errors="coerce")
    buckets = pd.cut(confidence, bins=[-0.001, 0.5, 0.7, 0.85, 1.0], labels=["0-0.50", "0.50-0.70", "0.70-0.85", "0.85-1.00"])
    return _group_counts(frame.assign(confidenceBucket=buckets.astype(str)), "confidenceBucket")


def _empty_metrics(workspace_id: str) -> dict[str, Any]:
    return {
        "workspaceId": workspace_id,
        "totalFeedback": 0,
        "counts": {kind: 0 for kind in sorted(KNOWN_FEEDBACK_TYPES)},
        "rates": {kind: 0.0 for kind in sorted(KNOWN_FEEDBACK_TYPES)},
        "byStrategyVersion": {},
        "byModelVersion": {},
        "byConfidenceBucket": {},
    }
