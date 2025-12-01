from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class SavingsRecommendationRequest(BaseModel):
    savingsGoalAmount: Optional[float]
    targetDate: Optional[str]


class SavingsAction(BaseModel):
    id: str
    description: str
    estimatedMonthlyImpact: float
    categoryId: Optional[int]
    difficultyLevel: str
    confidence: float


class SavingsPlan(BaseModel):
    recommendedMonthlySavings: float
    projectedBalanceByTargetDate: float
    probabilityOfSuccess: float
    actions: List[SavingsAction]


class SavingsRecommendationResponse(BaseModel):
    plan: SavingsPlan
    summaryText: Optional[str]

