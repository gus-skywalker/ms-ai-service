from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class CategorySuggestion(BaseModel):
    id: int
    code: str
    name: str
    confidence: float


class AutoCategorizeSuggestion(BaseModel):
    expenseId: Optional[str]
    suggestedCategory: CategorySuggestion
    alternativeCategories: List[CategorySuggestion]
    reasoning: Optional[str]


class AutoCategorizeRequestItem(BaseModel):
    expenseId: Optional[str]
    description: Optional[str]
    amount: float
    paymentMethodId: Optional[int]
    categoryId: Optional[int] = None


class AutoCategorizeRequest(BaseModel):
    userId: Optional[str] = None
    expenses: List[AutoCategorizeRequestItem]


class AutoCategorizeResponse(BaseModel):
    suggestions: List[AutoCategorizeSuggestion]
