from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel


class CategorySuggestion(BaseModel):
    id: int
    code: str
    name: str
    confidence: float


class AutoCategorizeSuggestion(BaseModel):
    expenseId: Optional[str]
    suggestedCategory: Optional[CategorySuggestion]
    alternativeCategories: List[CategorySuggestion]
    reasoning: Optional[str]
    confidence: float = 0.0
    strategy: str = "NONE"
    strategyVersion: Optional[str] = None
    modelVersion: Optional[str] = None
    modelScope: Optional[str] = None
    source: str = "NONE"
    explanation: Optional[str] = None
    safeToApply: bool = False
    status: str = "NO_SAFE_SUGGESTION"


class AutoCategorizeRequestItem(BaseModel):
    expenseId: Optional[str]
    description: Optional[str]
    amount: float
    paymentMethodId: Optional[int]
    categoryId: Optional[int] = None


class AutoCategorizeRequest(BaseModel):
    workspaceId: Optional[str] = None
    actorUserId: Optional[str] = None
    requestId: Optional[str] = None
    userId: Optional[str] = None
    allowedCategoryIds: Optional[List[int]] = None
    expenses: List[AutoCategorizeRequestItem]


class AutoCategorizeResponse(BaseModel):
    status: str = "READY"
    reason: Optional[str] = None
    modelVersion: Optional[str] = None
    modelScope: Optional[str] = None
    eligibility: Optional[dict[str, Any]] = None
    suggestions: List[AutoCategorizeSuggestion]
