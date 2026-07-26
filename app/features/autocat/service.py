from __future__ import annotations

import logging
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.core.metrics import AUTOCAT_INFERENCE_RESULTS
from app.features.autocat.bundle_store import IncompatibleBundleError, get_autocat_bundle_store
from app.features.autocat.policy import evaluate_eligibility
from app.features.autocat.training import _clean_text
from app.features.autocat.types import (
    AutoCategorizeRequest,
    AutoCategorizeResponse,
    AutoCategorizeSuggestion,
    CategorySuggestion,
)


logger = logging.getLogger(__name__)
MAX_ALTERNATIVES = 3


def auto_categorize_expenses(user_id: str, request: AutoCategorizeRequest) -> AutoCategorizeResponse:
    """Run inference only against the active, workspace-scoped canonical bundle.

    Training is intentionally absent from this request path. A missing, legacy or
    incompatible artifact is represented as a semantic state, never as a fabricated
    default category.
    """
    workspace_id = str(user_id)
    store = get_autocat_bundle_store()
    try:
        bundle = store.load_active(workspace_id)
    except (FileNotFoundError, IncompatibleBundleError, OSError, ValueError, TypeError):
        logger.exception("autocat active bundle is unavailable or incompatible", extra={"workspace_id": workspace_id})
        return _unavailable_response(request, "MODEL_REJECTED", "active-model-incompatible")

    if bundle is None:
        eligibility = evaluate_eligibility(workspace_id)
        status = "MODEL_NOT_READY" if eligibility.eligible else "INSUFFICIENT_LABELED_HISTORY"
        reason = "model-not-trained" if eligibility.eligible else "insufficient-labeled-history"
        if store.legacy_artifact_present(workspace_id):
            status, reason = "MODEL_REJECTED", "legacy-model-incompatible"
        return _unavailable_response(request, status, reason, eligibility.to_dict())

    try:
        suggestions = [_predict_item(bundle, item, request.allowedCategoryIds) for item in request.expenses]
    except Exception:
        logger.exception("autocat inference failed", extra={"workspace_id": workspace_id, "model_version": bundle.get("modelVersion")})
        return _unavailable_response(request, "MODEL_REJECTED", "model-inference-error")
    response_status = "READY" if any(item.safeToApply for item in suggestions) else "NO_SAFE_SUGGESTION"
    AUTOCAT_INFERENCE_RESULTS.labels(response_status).inc()
    return AutoCategorizeResponse(
        status=response_status,
        reason=None if response_status == "READY" else "no-safe-suggestion",
        modelVersion=bundle["modelVersion"],
        modelScope=bundle["scope"],
        suggestions=suggestions,
    )


def _predict_item(bundle: dict[str, Any], item, allowed_category_ids: list[int] | None) -> AutoCategorizeSuggestion:
    description = str(item.description or "").strip()
    common = {
        "expenseId": item.expenseId,
        "strategy": "PERSONALIZED_MODEL",
        "strategyVersion": bundle["algorithmVersion"],
        "modelVersion": bundle["modelVersion"],
        "modelScope": bundle["scope"],
        "source": "AI",
    }
    if not description:
        return AutoCategorizeSuggestion(
            **common,
            suggestedCategory=None,
            alternativeCategories=[],
            confidence=0.0,
            safeToApply=False,
            status="INVALID_INPUT",
            reasoning="empty-description",
            explanation="A descrição é obrigatória para categorizar com segurança.",
        )

    matrix = bundle["vectorizer"].transform([_clean_text(description)])
    probabilities = bundle["classifier"].predict_proba(matrix)[0]
    order = np.argsort(probabilities)[::-1]
    candidates: list[CategorySuggestion] = []
    allowed = {int(value) for value in allowed_category_ids} if allowed_category_ids else None
    for encoded_index in order:
        category_id = int(bundle["labelEncoder"].inverse_transform([int(encoded_index)])[0])
        confidence = float(probabilities[int(encoded_index)])
        candidates.append(_category(category_id, confidence))

    model_best = candidates[0]
    valid_candidates = [candidate for candidate in candidates if allowed and candidate.id in allowed]
    if not valid_candidates:
        return AutoCategorizeSuggestion(
            **common,
            suggestedCategory=None,
            alternativeCategories=[],
            confidence=0.0,
            safeToApply=False,
            status="OUTSIDE_ALLOWED_DOMAIN",
            reasoning="category-outside-active-workspace-domain",
            explanation="Nenhuma classe do modelo pertence à taxonomia ativa do workspace.",
        )
    best = valid_candidates[0]
    in_domain = model_best.id in allowed
    confident = best.confidence >= get_settings().AUTOCAT_SAFE_CONFIDENCE
    safe = in_domain and confident
    if not in_domain:
        status, reasoning = "OUTSIDE_ALLOWED_DOMAIN", "category-outside-active-workspace-domain"
    elif not confident:
        status, reasoning = "NO_SAFE_SUGGESTION", "confidence-below-safe-threshold"
    else:
        status, reasoning = "READY", "personalized-workspace-model"
    return AutoCategorizeSuggestion(
        **common,
        suggestedCategory=best,
        alternativeCategories=valid_candidates[1:MAX_ALTERNATIVES + 1],
        confidence=best.confidence,
        safeToApply=safe,
        status=status,
        reasoning=reasoning,
        explanation=(
            f"Modelo personalizado do workspace; confiança {best.confidence:.3f}."
            if safe else f"Sugestão não aplicável automaticamente: {reasoning}."
        ),
    )


def _category(category_id: int, confidence: float) -> CategorySuggestion:
    # The budget-api enriches id-only results from the active workspace taxonomy.
    return CategorySuggestion(
        id=category_id,
        code="",
        name="",
        confidence=round(confidence, 6),
    )


def _unavailable_response(
    request: AutoCategorizeRequest,
    status: str,
    reason: str,
    eligibility: dict[str, Any] | None = None,
) -> AutoCategorizeResponse:
    AUTOCAT_INFERENCE_RESULTS.labels(status).inc()
    suggestions = [
        AutoCategorizeSuggestion(
            expenseId=item.expenseId,
            suggestedCategory=None,
            alternativeCategories=[],
            confidence=0.0,
            strategy="NONE",
            strategyVersion=None,
            modelVersion=None,
            modelScope=None,
            source="NONE",
            explanation="Nenhum modelo personalizado compatível está ativo para este workspace.",
            safeToApply=False,
            status=status,
            reasoning=reason,
        )
        for item in request.expenses
    ]
    return AutoCategorizeResponse(
        status=status,
        reason=reason,
        modelVersion=None,
        modelScope=None,
        eligibility=eligibility,
        suggestions=suggestions,
    )
