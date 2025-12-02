from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, TypedDict
import logging
import uuid

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from app.core.config import get_settings
from app.core.models_registry import ModelKey, get_model_registry
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
    build_month_feature_vector,
    build_future_feature_vector,
)
from app.utils.stats import safe_mean

logger = logging.getLogger(__name__)

PREDICTION_VERSION = "prediction_v1"
MIN_MONTHS_FOR_MODEL = 6
DEFAULT_FORECAST_MONTHS = 3
FEATURE_ORDER = [
    "total_amount",
    "moving_avg_3",
    "moving_avg_6",
    "month_of_year",
]


class PredictionModelStats(TypedDict, total=False):
    residual_std: float
    mean_y: float
    confidence: float


class PredictionModelPayload(TypedDict, total=False):
    model_path: str
    feature_order: List[str]
    stats: PredictionModelStats
    avg: float
    months: int
    trained_months: int
    recent_totals: List[float]


class _Trend:
    STABLE = "stable"
    INCREASING = "increasing"
    DECREASING = "decreasing"


def predict_monthly_expenses(
    user_id: str,
    request: MonthlyExpensesPredictionRequest,
) -> MonthlyExpensesPredictionResponse:
    logger.info(
        "prediction request started",
        extra={
            "user_id": user_id,
            "forecast_months": request.forecastMonths,
            "category_id": request.categoryId,
            "historical_count": len(request.historicalTransactions),
        },
    )

    historical = filter_user_transactions(request.historicalTransactions, user_id)
    expenses = filter_by_type(historical, "EXPENSE")

    registry = get_model_registry()
    model_key = ModelKey(feature="prediction", version=PREDICTION_VERSION, user_id=user_id)
    cached_payload: PredictionModelPayload = registry.load_model(model_key) or {}

    by_month = group_transactions_by_month_amount(expenses)
    month_series = _sorted_month_series(by_month, user_id=user_id)
    month_count = len(month_series)

    if not month_series:
        logger.warning(
            "no valid historical months found; falling back to cached data",
            extra={
                "user_id": user_id,
                "raw_months": len(by_month),
            },
        )
        if not cached_payload.get("avg") and not cached_payload.get("model_path"):
            return MonthlyExpensesPredictionResponse(
                predictions=[],
                totalPredicted=0.0,
                modelAccuracy=None,
            )

    historical_avg = safe_mean(amount for _, amount in month_series) if month_series else cached_payload.get("avg")

    payload = cached_payload
    model: Optional[RandomForestRegressor] = None
    force_baseline = False

    if month_count >= MIN_MONTHS_FOR_MODEL:
        if payload.get("model_path"):
            model = _load_rf_model(payload.get("model_path"))
            if model is not None:
                logger.info(
                    "loaded cached prediction model",
                    extra={
                        "user_id": user_id,
                        "trained_months": payload.get("trained_months"),
                    },
                )
            else:
                logger.warning(
                    "cached model missing on disk; forcing fallback",
                    extra={"user_id": user_id},
                )
                payload.clear()
                avg = safe_mean(amount for _, amount in month_series)
                payload["avg"] = avg
                payload["months"] = month_count
                payload["trained_months"] = 0
                model = None
                force_baseline = True
        needs_training = (
            not force_baseline
            and (
                payload.get("model_path") is None
                or payload.get("trained_months", 0) < month_count
                or model is None
            )
        )
        if needs_training:
            logger.info(
                "training prediction model",
                extra={
                    "user_id": user_id,
                    "month_count": month_count,
                },
            )
            payload = _train_prediction_model(registry, model_key, month_series, user_id=user_id)
            model = _load_rf_model(payload.get("model_path"))
    elif not payload.get("model_path") and historical_avg is not None:
        payload = {
            "avg": historical_avg,
            "months": month_count,
            "trained_months": 0,
        }
        model = None
    else:
        model = None

    if historical_avg is None:
        historical_avg = payload.get("avg")

    if historical_avg is None:
        logger.warning(
            "historical average unavailable; returning empty prediction",
            extra={"user_id": user_id},
        )
        return MonthlyExpensesPredictionResponse(
            predictions=[],
            totalPredicted=0.0,
            modelAccuracy=None,
        )

    months_ahead = request.forecastMonths or DEFAULT_FORECAST_MONTHS
    start = date.today().replace(day=1)
    future_keys = future_month_keys(start, months_ahead)

    predictions, confidence = _build_predictions(
        payload=payload,
        model=model,
        future_keys=future_keys,
        category_id=request.categoryId,
        historical_avg=historical_avg,
        month_series=month_series,
        user_id=user_id,
    )

    total = round(sum(item.predictedAmount for item in predictions), 2)
    model_accuracy = confidence if model is not None else None

    logger.info(
        "prediction response",
        extra={
            "user_id": user_id,
            "prediction_count": len(predictions),
            "total": total,
            "model_accuracy": model_accuracy,
        },
    )

    return MonthlyExpensesPredictionResponse(
        predictions=predictions,
        totalPredicted=total,
        modelAccuracy=round(model_accuracy, 2) if model_accuracy is not None else None,
    )


def _train_prediction_model(
    registry,
    key: ModelKey,
    month_series: Sequence[Tuple[str, float]],
    user_id: str,
) -> PredictionModelPayload:
    features, targets = _build_training_data(month_series)
    logger.debug(
        "training data built",
        extra={
            "user_id": user_id,
            "feature_rows": len(features),
            "target_rows": len(targets),
        },
    )
    if len(features) == 0 or len(targets) == 0:
        avg = safe_mean(amount for _, amount in month_series)
        payload: PredictionModelPayload = {
            "avg": avg,
            "months": len(month_series),
            "trained_months": len(month_series),
        }
        registry.save_model(key, payload)
        return payload

    model = RandomForestRegressor(n_estimators=200, random_state=42)
    model.fit(features, targets)

    predictions = model.predict(features)
    residuals = targets - predictions
    residual_std = float(np.std(residuals)) if len(residuals) else 0.0
    mean_y = float(np.mean(targets)) if len(targets) else 0.0
    raw_confidence = 1.0 - (residual_std / max(mean_y, 1.0))
    confidence = _clamp(raw_confidence, 0.3, 0.95)
    logger.info(
        "model trained",
        extra={
            "user_id": user_id,
            "residual_std": residual_std,
            "mean_y": mean_y,
            "confidence": confidence,
        },
    )

    model_path = _save_rf_model(model, key)

    payload = PredictionModelPayload(
        model_path=str(model_path),
        feature_order=list(FEATURE_ORDER),
        stats=PredictionModelStats(
            residual_std=residual_std,
            mean_y=mean_y,
            confidence=confidence,
        ),
        avg=safe_mean(amount for _, amount in month_series),
        months=len(month_series),
        trained_months=len(month_series),
        recent_totals=[amount for _, amount in month_series][-6:],
    )
    registry.save_model(key, payload)
    return payload


def _build_training_data(
    month_series: Sequence[Tuple[str, float]]
) -> Tuple[np.ndarray, np.ndarray]:
    feature_rows: List[List[float]] = []
    targets: List[float] = []

    for idx in range(len(month_series) - 1):
        vector = build_month_feature_vector(month_series, idx)
        logger.debug("feature_vector", extra={"index": idx, "vector": vector})
        feature_rows.append(vector)
        targets.append(month_series[idx + 1][1])

    return np.array(feature_rows, dtype=float), np.array(targets, dtype=float)


def _build_predictions(
    payload: PredictionModelPayload,
    model: Optional[RandomForestRegressor],
    future_keys: List[str],
    category_id: Optional[int],
    historical_avg: float,
    month_series: Sequence[Tuple[str, float]],
    user_id: str,
) -> Tuple[List[MonthlyExpensePredictionItem], float]:
    stats = payload.get("stats", {})
    if model and future_keys:
        return _predict_with_model(
            payload=payload,
            model=model,
            future_keys=future_keys,
            category_id=category_id,
            historical_avg=historical_avg,
            stats=stats,
            month_series=month_series,
            user_id=user_id,
        )
    return _predict_baseline(
        payload=payload,
        future_keys=future_keys,
        category_id=category_id,
        historical_avg=historical_avg,
        month_series=month_series,
        user_id=user_id,
    )


def _predict_with_model(
    payload: PredictionModelPayload,
    model: RandomForestRegressor,
    future_keys: List[str],
    category_id: Optional[int],
    historical_avg: float,
    stats: PredictionModelStats,
    month_series: Sequence[Tuple[str, float]],
    user_id: str,
) -> Tuple[List[MonthlyExpensePredictionItem], float]:
    history_amounts = [amount for _, amount in month_series]
    if not history_amounts:
        fallback_seed = payload.get("recent_totals") or [historical_avg]
        history_amounts = list(fallback_seed)

    confidence = float(stats.get("confidence", 0.5))
    residual_std = float(stats.get("residual_std", 0.0))

    predictions: List[MonthlyExpensePredictionItem] = []
    trend = _derive_trend(history_amounts, user_id=user_id)
    for month_key_value in future_keys:
        features = build_future_feature_vector(history_amounts, month_key_value)
        logger.debug(
            "forecast_features",
            extra={"user_id": user_id, "month": month_key_value, "features": features},
        )
        predicted = float(model.predict([features])[0])
        predicted = max(predicted, 0.0)
        history_amounts.append(predicted)

        min_possible = max(0.0, predicted - residual_std)
        max_possible = max(predicted + residual_std, min_possible)
        trend = _derive_trend(history_amounts, user_id=user_id)

        predictions.append(
            MonthlyExpensePredictionItem(
                month=month_key_value,
                categoryId=category_id,
                predictedAmount=round(predicted, 2),
                confidence=confidence,
                historicalAverage=round(historical_avg, 2),
                trend=trend,
                minExpected=round(min_possible, 2),
                maxExpected=round(max_possible, 2),
            )
        )

    return predictions, confidence


def _predict_baseline(
    payload: PredictionModelPayload,
    future_keys: List[str],
    category_id: Optional[int],
    historical_avg: float,
    month_series: Sequence[Tuple[str, float]],
    user_id: str,
) -> Tuple[List[MonthlyExpensePredictionItem], float]:
    confidence = float(payload.get("stats", {}).get("confidence", 0.5))
    predictions: List[MonthlyExpensePredictionItem] = []
    history_amounts = [amount for _, amount in month_series] or [historical_avg]
    trend = _derive_trend(history_amounts, user_id=user_id)

    for month_key_value in future_keys:
        logger.debug(
            "baseline_forecast",
            extra={
                "user_id": user_id,
                "month": month_key_value,
                "historical_avg": historical_avg,
            },
        )
        min_expected = max(0.0, historical_avg * 0.8)
        max_expected = round(historical_avg * 1.2, 2)
        predictions.append(
            MonthlyExpensePredictionItem(
                month=month_key_value,
                categoryId=category_id,
                predictedAmount=round(historical_avg, 2),
                confidence=confidence,
                historicalAverage=round(historical_avg, 2),
                trend=trend,
                minExpected=round(min_expected, 2),
                maxExpected=max_expected,
            )
        )

    return predictions, confidence


def _derive_trend(history_amounts: Sequence[float], user_id: Optional[str] = None) -> str:
    if len(history_amounts) < 4:
        return _Trend.STABLE
    recent = safe_mean(history_amounts[-3:])
    previous_slice = history_amounts[-6:-3] if len(history_amounts) >= 6 else history_amounts[:-3]
    if not previous_slice:
        return _Trend.STABLE
    previous = safe_mean(previous_slice)
    delta = recent - previous
    threshold = max(abs(previous) * 0.05, 5.0)
    if delta > threshold:
        result = _Trend.INCREASING
    elif delta < -threshold:
        result = _Trend.DECREASING
    else:
        result = _Trend.STABLE
    logger.debug(
        "trend_calculation",
        extra={
            "user_id": user_id,
            "recent_avg": recent,
            "previous_avg": previous,
            "delta": delta,
            "trend": result,
        },
    )
    return result


def _sorted_month_series(by_month: Dict[str, float], user_id: str) -> List[Tuple[str, float]]:
    cleaned: List[Tuple[str, float]] = []
    invalid_keys: List[str] = []
    for key, total in by_month.items():
        try:
            datetime.strptime(key + "-01", "%Y-%m-%d")
            cleaned.append((key, total))
        except ValueError:
            invalid_keys.append(key)

    if invalid_keys:
        logger.warning(
            "dropping malformed month keys",
            extra={
                "user_id": user_id,
                "invalid_keys": invalid_keys,
            },
        )

    cleaned.sort(key=lambda item: item[0])
    if cleaned:
        logger.debug(
            "validated_month_series",
            extra={
                "user_id": user_id,
                "first_month": cleaned[0][0],
                "last_month": cleaned[-1][0],
                "count": len(cleaned),
            },
        )
    return cleaned


def _month_of_year_from_key(key: str) -> int:
    try:
        _, month_str = key.split("-")
        return int(month_str)
    except ValueError:
        dt = datetime.strptime(key + "-01", "%Y-%m-%d")
        return dt.month


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _save_rf_model(model: RandomForestRegressor, key: ModelKey) -> Path:
    settings = get_settings()
    model_dir = Path(settings.AI_MODEL_DIR) / key.feature / key.version / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    filename = f"rf_{key.user_id or 'global'}_{uuid.uuid4().hex}.joblib"
    path = model_dir / filename
    joblib.dump(model, path)
    return path


def _load_rf_model(model_path: Optional[str]) -> Optional[RandomForestRegressor]:
    if not model_path:
        return None
    path = Path(model_path)
    if not path.exists():
        return None
    return joblib.load(path)
