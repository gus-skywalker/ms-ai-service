from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.core.feature_store import path_for_user


LABEL_POLICY_VERSION = "autocat-label-policy-v1"
ALLOWED_LABEL_SOURCES = {
    "USER": 1.00,
    "USER_CONFIRMED_SUGGESTION": 1.00,
    "BANK_MAPPING": 0.95,
    "RULE": 0.90,
}


@dataclass(frozen=True)
class EligibilityDiagnostic:
    eligible: bool
    eligibleLabels: int
    distinctCategories: int
    requiredLabels: int
    requiredCategories: int
    requiredExamplesPerCategory: int
    classDistribution: dict[str, int]
    maxCategoryConcentration: float
    descriptionCoverage: float
    averageTrust: float
    datasetFingerprint: str | None
    blockingReasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_label_source(source: Any) -> str:
    normalized = str(source or "").strip().upper()
    if normalized not in ALLOWED_LABEL_SOURCES:
        raise ValueError(f"Untrusted labelSource: {normalized or 'missing'}")
    return normalized


def load_training_dataset(workspace_id: str) -> pd.DataFrame:
    labels_path = Path(path_for_user(workspace_id, "trusted_labels.parquet"))
    transactions_path = Path(path_for_user(workspace_id, "raw_transactions.parquet"))
    if not labels_path.exists() or not transactions_path.exists():
        return _empty_dataset()

    labels = pd.read_parquet(labels_path)
    transactions = pd.read_parquet(transactions_path)
    if labels.empty or transactions.empty:
        return _empty_dataset()

    labels = _normalize_labels(labels)
    if labels.empty:
        return _empty_dataset()

    transactions = transactions.copy()
    transactions["workspaceId"] = transactions.get("workspaceId", workspace_id)
    transactions = transactions[transactions["workspaceId"].fillna(workspace_id).astype(str) == str(workspace_id)]
    if transactions.empty:
        return _empty_dataset()

    by_entry = labels[labels["entryId"].notna()].merge(
        transactions,
        how="inner",
        on="entryId",
        suffixes=("_label", "_transaction"),
    )

    without_entry = labels[labels["entryId"].isna()]
    if not without_entry.empty and "transactionId" in transactions.columns:
        counts = transactions.groupby("transactionId").size()
        unambiguous_ids = counts[counts == 1].index
        by_transaction = without_entry[without_entry["transactionId"].isin(unambiguous_ids)].merge(
            transactions,
            how="inner",
            on="transactionId",
            suffixes=("_label", "_transaction"),
        )
    else:
        by_transaction = pd.DataFrame()

    joined = pd.concat([by_entry, by_transaction], ignore_index=True)
    if joined.empty:
        return _empty_dataset()

    result = pd.DataFrame(
        {
            "labelId": joined["labelId"],
            "transactionId": _coalesce(joined, "transactionId_label", "transactionId"),
            "entryId": _coalesce(joined, "entryId", "entryId_transaction"),
            "description": _series(joined, "description", "").fillna("").astype(str),
            "amount": pd.to_numeric(_series(joined, "amount", 0.0), errors="coerce").fillna(0.0),
            # When canonical facts also expose categoryId pandas suffixes both
            # columns; otherwise the unsuffixed value still comes from labels.
            "categoryId": pd.to_numeric(
                joined["categoryId_label"] if "categoryId_label" in joined.columns else joined["categoryId"],
                errors="coerce",
            ),
            "labelSource": joined["labelSource"],
            "trust": joined["trust"],
            "labeledAt": joined["labeledAt"],
        }
    )
    result = result[result["categoryId"].notna()].copy()
    result["categoryId"] = result["categoryId"].astype(int)
    return result.sort_values(["labeledAt", "labelId"]).reset_index(drop=True)


def evaluate_eligibility(workspace_id: str, dataset: pd.DataFrame | None = None) -> EligibilityDiagnostic:
    settings = get_settings()
    dataset = load_training_dataset(workspace_id) if dataset is None else dataset.copy()
    count = len(dataset)
    distribution = {
        str(int(category)): int(total)
        for category, total in dataset.get("categoryId", pd.Series(dtype=int)).value_counts().sort_index().items()
    }
    distinct = len(distribution)
    max_concentration = (max(distribution.values()) / count) if count else 0.0
    descriptions = dataset.get("description", pd.Series(dtype=str)).fillna("").astype(str).str.strip()
    description_coverage = float((descriptions != "").mean()) if count else 0.0
    average_trust = float(dataset.get("trust", pd.Series(dtype=float)).mean()) if count else 0.0
    reasons: list[str] = []
    if count < settings.AUTOCAT_MIN_LABELS:
        reasons.append("INSUFFICIENT_LABELS")
    if distinct < settings.AUTOCAT_MIN_CATEGORIES:
        reasons.append("INSUFFICIENT_CATEGORIES")
    if distribution and min(distribution.values()) < settings.AUTOCAT_MIN_EXAMPLES_PER_CATEGORY:
        reasons.append("INSUFFICIENT_EXAMPLES_PER_CATEGORY")
    if max_concentration > settings.AUTOCAT_MAX_CATEGORY_CONCENTRATION:
        reasons.append("CATEGORY_CONCENTRATION_TOO_HIGH")
    if description_coverage < settings.AUTOCAT_MIN_DESCRIPTION_COVERAGE:
        reasons.append("INSUFFICIENT_DESCRIPTION_COVERAGE")
    if count and average_trust < settings.AUTOCAT_MIN_AVERAGE_TRUST:
        reasons.append("INSUFFICIENT_LABEL_TRUST")
    fingerprint = dataset_fingerprint(dataset) if count else None
    return EligibilityDiagnostic(
        eligible=not reasons,
        eligibleLabels=count,
        distinctCategories=distinct,
        requiredLabels=settings.AUTOCAT_MIN_LABELS,
        requiredCategories=settings.AUTOCAT_MIN_CATEGORIES,
        requiredExamplesPerCategory=settings.AUTOCAT_MIN_EXAMPLES_PER_CATEGORY,
        classDistribution=distribution,
        maxCategoryConcentration=round(max_concentration, 6),
        descriptionCoverage=round(description_coverage, 6),
        averageTrust=round(average_trust, 6),
        datasetFingerprint=fingerprint,
        blockingReasons=reasons,
    )


def dataset_fingerprint(dataset: pd.DataFrame) -> str:
    records = dataset[["labelId", "transactionId", "entryId", "categoryId", "labelSource", "trust", "labeledAt"]].copy()
    records = records.fillna("").astype(str).sort_values(["labelId", "labeledAt"]).to_dict("records")
    return sha256(json.dumps(records, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _normalize_labels(labels: pd.DataFrame) -> pd.DataFrame:
    required = {"labelId", "transactionId", "categoryId", "labelSource"}
    if not required.issubset(labels.columns):
        return pd.DataFrame()
    normalized = labels.copy()
    normalized["labelSource"] = normalized["labelSource"].fillna("").astype(str).str.upper()
    normalized = normalized[normalized["labelSource"].isin(ALLOWED_LABEL_SOURCES)]
    declared_trust = pd.to_numeric(_series(normalized, "trust", None), errors="coerce")
    policy_trust = normalized["labelSource"].map(ALLOWED_LABEL_SOURCES).astype(float)
    normalized["trust"] = declared_trust.fillna(policy_trust).clip(upper=policy_trust)
    normalized = normalized[normalized["trust"] >= get_settings().AUTOCAT_MIN_LABEL_TRUST]
    normalized["labeledAt"] = pd.to_datetime(_series(normalized, "labeledAt", None), errors="coerce", utc=True)
    normalized["labeledAt"] = normalized["labeledAt"].fillna(pd.Timestamp(0, tz="UTC"))
    if "entryId" not in normalized.columns:
        normalized["entryId"] = None
    normalized["dedupeKey"] = normalized["entryId"].fillna(normalized["transactionId"])
    normalized = normalized.sort_values(["labeledAt", "trust", "labelId"]).drop_duplicates("dedupeKey", keep="last")
    return normalized


def _coalesce(frame: pd.DataFrame, first: str, second: str) -> pd.Series:
    if first in frame.columns and second in frame.columns:
        return frame[first].combine_first(frame[second])
    if first in frame.columns:
        return frame[first]
    if second in frame.columns:
        return frame[second]
    return pd.Series([None] * len(frame))


def _series(frame: pd.DataFrame, column: str, default: Any) -> pd.Series:
    if column in frame.columns:
        return frame[column]
    return pd.Series([default] * len(frame), index=frame.index)


def _empty_dataset() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "labelId", "transactionId", "entryId", "description", "amount", "categoryId",
        "labelSource", "trust", "labeledAt",
    ])
