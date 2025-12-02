from __future__ import annotations

from typing import List
import logging

from app.features.autocat.types import (
    AutoCategorizeRequest,
    AutoCategorizeResponse,
    AutoCategorizeSuggestion,
    CategorySuggestion,
)


logger = logging.getLogger(__name__)

AUTOCAT_VERSION = "autocat_v1"


_KEYWORDS = {
    "uber": (1, "transportation", "Transporte"),
    "99": (1, "transportation", "Transporte"),
    "ifood": (7, "dining_out", "Alimentação Fora"),
    "rappi": (7, "dining_out", "Alimentação Fora"),
    "supermerc": (1, "groceries", "Compras"),
}


def _suggest_category_from_description(description: str) -> CategorySuggestion | None:
    desc_lower = description.lower()
    for keyword, (cid, code, name) in _KEYWORDS.items():
        if keyword in desc_lower:
            return CategorySuggestion(
                id=cid,
                code=code,
                name=name,
                confidence=0.8,
            )
    return None


def auto_categorize_expenses(
    user_id: str,
    request: AutoCategorizeRequest,
) -> AutoCategorizeResponse:
    logger.info(
        "auto-categorization request",
        extra={
            "user_id": user_id,
            "expense_count": len(request.expenses),
        },
    )
    suggestions: List[AutoCategorizeSuggestion] = []

    for exp in request.expenses:
        desc = exp.description or ""

        primary = _suggest_category_from_description(desc) or CategorySuggestion(
            id=14,
            code="miscellaneous",
            name="Outros",
            confidence=0.5,
        )

        alternatives: List[CategorySuggestion] = []
        if primary.code != "miscellaneous":
            alternatives.append(
                CategorySuggestion(
                    id=14,
                    code="miscellaneous",
                    name="Outros",
                    confidence=0.1,
                )
            )

        suggestion = AutoCategorizeSuggestion(
            expenseId=exp.expenseId,
            suggestedCategory=primary,
            alternativeCategories=alternatives,
            reasoning="Sugestão baseada em palavras-chave na descrição.",
        )
        suggestions.append(suggestion)

    logger.info(
        "auto-categorization response",
        extra={
            "user_id": user_id,
            "suggestion_count": len(suggestions),
        },
    )
    return AutoCategorizeResponse(suggestions=suggestions)
