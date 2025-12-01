from __future__ import annotations

from app.features.savings.types import (
    SavingsRecommendationRequest,
    SavingsRecommendationResponse,
    SavingsPlan,
    SavingsAction,
)


SAVINGS_VERSION = "savings_v1"


def generate_savings_recommendations(
    user_id: str,
    request: SavingsRecommendationRequest,
) -> SavingsRecommendationResponse:
    goal = request.savingsGoalAmount or 200.0

    actions = [
        SavingsAction(
            id="dining_out_reduce",
            description="Reduzir gastos com alimentação fora em 20%",
            estimatedMonthlyImpact=round(goal * 0.5, 2),
            categoryId=None,
            difficultyLevel="medium",
            confidence=0.8,
        ),
        SavingsAction(
            id="subscriptions_review",
            description="Revisar assinaturas e cancelar serviços pouco usados",
            estimatedMonthlyImpact=round(goal * 0.3, 2),
            categoryId=None,
            difficultyLevel="low",
            confidence=0.75,
        ),
        SavingsAction(
            id="transport_optimization",
            description="Otimizar transporte usando alternativas mais baratas",
            estimatedMonthlyImpact=round(goal * 0.2, 2),
            categoryId=None,
            difficultyLevel="medium",
            confidence=0.7,
        ),
    ]

    plan = SavingsPlan(
        recommendedMonthlySavings=round(goal, 2),
        projectedBalanceByTargetDate=0.0,
        probabilityOfSuccess=0.75,
        actions=actions,
    )

    summary = (
        f"Para atingir sua meta de economia de R$ {goal:.2f}, "
        "considere aplicar as ações sugeridas acima."
    )

    return SavingsRecommendationResponse(plan=plan, summaryText=summary)
