from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class CashflowAlert(BaseModel):
    severity: str
    message: str
    suggestions: List[str]


class CashflowForecastItem(BaseModel):
    month: str
    predictedIncome: float
    predictedExpenses: float
    projectedBalance: float
    status: str
    alert: Optional[CashflowAlert]


class CashflowInsightsRequest(BaseModel):
    months: int = 6


class CashflowInsightsResponse(BaseModel):
    currentBalance: float
    forecast: List[CashflowForecastItem]
    averageMonthlyBalance: float
    insights: List[str]

