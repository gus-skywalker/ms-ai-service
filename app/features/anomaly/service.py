from __future__ import annotations

from typing import List
import logging

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
    logger.info(
        "anomaly detection request",
        extra={
            "user_id": user_id,
            "transactions": len(request.transactions),
            "sensitivity": request.sensitivity,
        },
    )
    transactions = filter_user_transactions(request.transactions, user_id)
    expenses = filter_by_type(transactions, "EXPENSE")

    if not expenses:
        summary = AnomalyDetectionSummary(
            totalTransactionsAnalyzed=0,
            anomaliesCount=0,
            totalAnomalousAmount=0.0,
            highestAnomalyScore=0.0,
            summaryText="No expenses to analyze.",
        )
        return AnomalyDetectionResponse(anomalies=[], summary=summary)

    # Aggregate by month
    amounts = []
    for tx in expenses:
        amounts.append(tx.amount)

    avg = safe_mean(amounts)
    std = population_std(amounts)

    sensitivity = request.sensitivity or 2.0
    threshold = sensitivity

    anomalies: List[AnomalyDetectionItem] = []
    highest_score = 0.0
    total_anomalous_amount = 0.0

    for tx in expenses:
        score = 0.0
        if std > 0:
            score = abs((tx.amount - avg) / std)
        if score >= threshold:
            highest_score = max(highest_score, score)
            total_anomalous_amount += tx.amount

            expense = AnomalyExpense(
                id=tx.transactionId,
                date=tx.date,
                amount=tx.amount,
                description=tx.description,
                categoryId=tx.categoryId,
                categoryCode=tx.categoryCode,
                categoryName=None,
            )

            expected_range = AnomalyExpectedRange(
                min=round(avg * 0.5, 2),
                max=round(avg * 1.5, 2),
                average=round(avg, 2),
            )

            severity = "medium"
            if score >= threshold * 1.5:
                severity = "high"

            item = AnomalyDetectionItem(
                expense=expense,
                expectedRange=expected_range,
                deviation=round(score, 2),
                severity=severity,
                suggestion=None,
            )
            anomalies.append(item)

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
