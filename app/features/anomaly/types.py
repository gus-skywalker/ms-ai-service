from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel

from app.models.transactions import AiTransaction


class AnomalyExpectedRange(BaseModel):
    min: float
    max: float
    average: float


class AnomalyExpense(BaseModel):
    id: Optional[str]
    date: Optional[str]
    amount: float
    description: Optional[str]
    categoryId: Optional[int]
    categoryCode: Optional[str]
    categoryName: Optional[str]


class AnomalyDetectionItem(BaseModel):
    expense: AnomalyExpense
    expectedRange: AnomalyExpectedRange
    deviation: float
    severity: str
    suggestion: Optional[str]


class AnomalyDetectionSummary(BaseModel):
    totalTransactionsAnalyzed: int
    anomaliesCount: int
    totalAnomalousAmount: float
    highestAnomalyScore: float
    summaryText: Optional[str]


class AnomalyDetectionRequest(BaseModel):
    workspaceId: Optional[str] = None
    actorUserId: Optional[str] = None
    requestId: Optional[str] = None
    transactions: List[AiTransaction]
    sensitivity: Optional[float] = 1.5


class AnomalyDetectionResponse(BaseModel):
    anomalies: List[AnomalyDetectionItem]
    summary: AnomalyDetectionSummary
