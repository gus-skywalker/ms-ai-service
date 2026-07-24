from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from app.models.transactions import AiTransaction


class MonthlyExpensePredictionItem(BaseModel):
    month: str
    categoryId: Optional[int]
    predictedAmount: float
    confidence: float
    historicalAverage: Optional[float]
    trend: Optional[str]
    minExpected: Optional[float]
    maxExpected: Optional[float]


class MonthlyExpensesPredictionRequest(BaseModel):
    workspaceId: Optional[str] = None
    actorUserId: Optional[str] = None
    requestId: Optional[str] = None
    categoryId: Optional[int]
    forecastMonths: int = 3
    historicalTransactions: List[AiTransaction]


class MonthlyExpensesPredictionResponse(BaseModel):
    predictions: List[MonthlyExpensePredictionItem]
    totalPredicted: float
    modelAccuracy: Optional[float]
