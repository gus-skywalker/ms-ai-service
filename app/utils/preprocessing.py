from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List

from app.models.transactions import AiTransaction
from app.utils.dates import parse_iso_date, month_key


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
