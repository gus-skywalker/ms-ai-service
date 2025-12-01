from __future__ import annotations

from typing import List

from app.features.prediction.types import (
    MonthlyExpensesPredictionRequest,
    MonthlyExpensesPredictionResponse,
    MonthlyExpensePredictionItem,
)
from app.utils.preprocessing import (
    filter_user_transactions,
    filter_by_type,
    group_transactions_by_month_amount,
)
from app.utils.dates import future_month_keys
from app.utils.stats import safe_mean
from datetime import date


PREDICTION_VERSION = "prediction_v1"


def predict_monthly_expenses(
    user_id: str,
    request: MonthlyExpensesPredictionRequest,
) -> MonthlyExpensesPredictionResponse:
    historical = filter_user_transactions(request.historicalTransactions, user_id)
    expenses = filter_by_type(historical, "EXPENSE")

    by_month = group_transactions_by_month_amount(expenses)
    if not by_month:
        return MonthlyExpensesPredictionResponse(predictions=[], totalPredicted=0.0)

    # Simple baseline: average of historical months
    amounts = list(by_month.values())
    avg = safe_mean(amounts)

    months_ahead = request.forecastMonths or 3
    start = date.today().replace(day=1)
    future_keys = future_month_keys(start, months_ahead)

    predictions: List[MonthlyExpensePredictionItem] = []
    for key in future_keys:
        item = MonthlyExpensePredictionItem(
            month=key,
            categoryId=request.categoryId,
            predictedAmount=round(avg, 2),
            confidence=0.7,
            historicalAverage=round(avg, 2),
            trend="stable",
            minExpected=round(avg * 0.8, 2),
            maxExpected=round(avg * 1.2, 2),
        )
        predictions.append(item)

    total = round(sum(p.predictedAmount for p in predictions), 2)

    return MonthlyExpensesPredictionResponse(
        predictions=predictions,
        totalPredicted=total,
        modelAccuracy=0.7,
    )
