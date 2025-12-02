from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Tuple

from app.models.transactions import AiTransaction
from app.utils.dates import parse_iso_date, month_key
from app.utils.stats import safe_mean


def filter_user_transactions(
    transactions: Iterable[AiTransaction], user_id: str | None
) -> List[AiTransaction]:
    if user_id is None:
        return list(transactions)
    return [t for t in transactions if t.userId is None or t.userId == user_id]


def filter_by_type(
    transactions: Iterable[AiTransaction], type_value: str
) -> List[AiTransaction]:
    type_upper = type_value.upper()
    return [t for t in transactions if t.type.upper() == type_upper]


def group_transactions_by_month_amount(
    transactions: Iterable[AiTransaction],
) -> Dict[str, float]:
    grouped: Dict[str, float] = defaultdict(float)
    for tx in transactions:
        d = parse_iso_date(tx.date)
        key = month_key(d)
        grouped[key] += tx.amount
    return dict(grouped)


def month_of_year_from_key(key: str) -> int:
    try:
        _, month_str = key.split("-")
        return int(month_str)
    except ValueError:
        dt = datetime.strptime(f"{key}-01", "%Y-%m-%d")
        return dt.month


def moving_average_for_series(
    month_series: Sequence[Tuple[str, float]],
    idx: int,
    window: int,
) -> float:
    start = max(0, idx - window + 1)
    values = [amount for _, amount in month_series[start : idx + 1]]
    return safe_mean(values)


def moving_average_from_history(history: Sequence[float], window: int) -> float:
    if not history:
        return 0.0
    return safe_mean(history[-window:])


def build_month_feature_vector(
    month_series: Sequence[Tuple[str, float]],
    idx: int,
) -> List[float]:
    total_amount = month_series[idx][1]
    mov3 = moving_average_for_series(month_series, idx, 3)
    mov6 = moving_average_for_series(month_series, idx, 6)
    month_of_year = month_of_year_from_key(month_series[idx][0])
    return [total_amount, mov3, mov6, float(month_of_year)]


def build_future_feature_vector(
    history_amounts: Sequence[float],
    month_key_value: str,
) -> List[float]:
    base_amount = history_amounts[-1] if history_amounts else 0.0
    mov3 = moving_average_from_history(history_amounts, 3)
    mov6 = moving_average_from_history(history_amounts, 6)
    month_of_year = month_of_year_from_key(month_key_value)
    return [base_amount, mov3, mov6, float(month_of_year)]
