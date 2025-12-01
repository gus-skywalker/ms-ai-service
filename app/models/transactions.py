from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AiTransaction(BaseModel):
    transactionId: Optional[str]
    userId: Optional[str]
    type: str
    date: str
    amount: float
    currency: str
    categoryId: Optional[int] = None
    categoryCode: Optional[str] = None
    description: Optional[str] = None
    paymentMethodId: Optional[int] = None

