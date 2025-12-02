from __future__ import annotations

from typing import List, Optional
import logging
import numpy as np

from app.features.anomaly.types import (
    AnomalyDetectionRequest,
    AnomalyDetectionResponse,
    AnomalyDetectionItem,
    AnomalyDetectionSummary,
    AnomalyExpectedRange,
    AnomalyExpense,
)
from app.utils.preprocessing import filter_user_transactions, filter_by_type
from app.utils.stats import safe_mean, population_std


logger = logging.getLogger(__name__)

ANOMALY_VERSION = "anomaly_v1"


def detect_anomalies(
    user_id: str,
    request: AnomalyDetectionRequest,
) -> AnomalyDetectionResponse:
    """
    Detects anomalies in a list of AiTransaction using MAD (Median Absolute Deviation).
    Fallbacks to z-score if MAD=0. Supports per-user and optional categoryId filtering.
    """
    logger.info(
        "anomaly detection request",
        extra={
            "user_id": user_id,
            "transactions": len(request.transactions),
        },
    )
    transactions = filter_user_transactions(request.transactions, user_id)
    expenses = filter_by_type(transactions, "EXPENSE")
    category_id: Optional[int] = getattr(request, "categoryId", None)
    if category_id is not None:
        expenses = [tx for tx in expenses if tx.categoryId == category_id]

    if not expenses:
        summary = AnomalyDetectionSummary(
            totalTransactionsAnalyzed=0,
            anomaliesCount=0,
            totalAnomalousAmount=0.0,
            highestAnomalyScore=0.0,
            summaryText="No expenses to analyze.",
        )
        return AnomalyDetectionResponse(anomalies=[], summary=summary)

    amounts = np.array([tx.amount for tx in expenses], dtype=float)
    median = float(np.median(amounts))
    abs_devs = np.abs(amounts - median)
    mad = float(np.median(abs_devs))
    threshold = 3.0 * mad if mad > 0 else 3.0  # fallback threshold for z-score

    # Fallback to z-score if MAD=0
    use_zscore = mad == 0.0
    mean = float(np.mean(amounts))
    std = float(np.std(amounts, ddof=0))

    anomalies: List[AnomalyDetectionItem] = []
    highest_score = 0.0
    total_anomalous_amount = 0.0

    for tx in expenses:
        if use_zscore and std > 0:
            deviation_score = abs((tx.amount - mean) / std)
            is_anomaly = deviation_score > 3.0
        else:
            deviation_score = abs(tx.amount - median)
            is_anomaly = deviation_score > threshold
        if is_anomaly:
            highest_score = max(highest_score, deviation_score)
            total_anomalous_amount += tx.amount
            # Set severity based on deviation_score
            if deviation_score > (threshold * 2 if not use_zscore else 6.0):
                severity = "high"
            elif deviation_score > (threshold * 1.2 if not use_zscore else 4.0):
                severity = "medium"
            else:
                severity = "low"
            anomalies.append(
                AnomalyDetectionItem(
                    expense=AnomalyExpense(
                        id=tx.transactionId,
                        date=tx.date,
                        amount=tx.amount,
                        description=getattr(tx, "description", None),
                        categoryId=tx.categoryId,
                        categoryCode=getattr(tx, "categoryCode", None),
                        categoryName=None,
                    ),
                    expectedRange=AnomalyExpectedRange(
                        min=round(median - threshold, 2),
                        max=round(median + threshold, 2),
                        average=round(median, 2),
                    ),
                    deviation=round(deviation_score, 2),
                    severity=severity,
                    suggestion=None,
                )
            )

    summary_text = (
        "No anomalies detected."
        if not anomalies
        else f"Detected {len(anomalies)} anomalous expenses."
    )
    summary = AnomalyDetectionSummary(
        totalTransactionsAnalyzed=len(expenses),
        anomaliesCount=len(anomalies),
        totalAnomalousAmount=round(total_anomalous_amount, 2),
        highestAnomalyScore=round(highest_score, 2),
        summaryText=summary_text,
    )
    logger.info(
        "anomaly response",
        extra={
            "user_id": user_id,
            "anomalies": len(anomalies),
            "highest_score": round(highest_score, 2),
        },
    )
    return AnomalyDetectionResponse(anomalies=anomalies, summary=summary)
