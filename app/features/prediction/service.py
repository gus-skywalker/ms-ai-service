from __future__ import annotations
from datetime import date
from typing import List, Optional

from app.core.models_registry import get_model_registry, ModelKey
from app.features.prediction.types import (
    MonthlyExpensesPredictionRequest,
    MonthlyExpensesPredictionResponse,
    MonthlyExpensePredictionItem,
)
from app.utils.dates import future_month_keys
from app.utils.preprocessing import (
    filter_user_transactions,
    filter_by_type,
    group_transactions_by_month_amount,
)
from app.utils.stats import safe_mean


PREDICTION_VERSION = "prediction_v1"


def predict_monthly_expenses(
    user_id: str,
    request: MonthlyExpensesPredictionRequest,
) -> MonthlyExpensesPredictionResponse:
    historical = filter_user_transactions(request.historicalTransactions, user_id)
    expenses = filter_by_type(historical, "EXPENSE")

    registry = get_model_registry()
    model_key = ModelKey(feature="prediction", version=PREDICTION_VERSION, user_id=user_id)
    cached_baseline = registry.load_model(model_key) or {}

    by_month = group_transactions_by_month_amount(expenses)
    avg: Optional[float] = None

    if by_month:
        # Simple baseline: average of historical months
        amounts = list(by_month.values())
        avg = safe_mean(amounts)
        registry.save_model(model_key, {"avg": avg, "months": len(amounts)})
    else:
        avg = cached_baseline.get("avg")

    if avg is None:
        return MonthlyExpensesPredictionResponse(predictions=[], totalPredicted=0.0)

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

    model_accuracy = cached_baseline.get("accuracy", 0.7) if cached_baseline else 0.7

    return MonthlyExpensesPredictionResponse(
        predictions=predictions,
        totalPredicted=total,
        modelAccuracy=model_accuracy,
    )
