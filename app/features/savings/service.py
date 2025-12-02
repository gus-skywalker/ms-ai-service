from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
import logging
import math

from app.features.savings.types import (
    SavingsRecommendationRequest,
    SavingsRecommendationResponse,
    SavingsPlan,
    SavingsAction,
)

SAVINGS_VERSION = "savings_v1"
logger = logging.getLogger(__name__)


def generate_savings_recommendations(
    user_id: str,
    request: SavingsRecommendationRequest,
) -> SavingsRecommendationResponse:
    logger.info(
        "savings recommendation request",
        extra={
            "user_id": user_id,
            "goal": request.savingsGoalAmount,
            "target_date": request.targetDate,
        },
    )

    goal = request.savingsGoalAmount or 200.0
    target_date = request.targetDate
    today = date.today()
    meses_restantes = 6
    recommended_monthly_savings = goal / meses_restantes
    projected_balance = goal
    probability_of_success = 0.7
    summary = ""

    # Calcular meses_restantes
    if target_date:
        try:
            target = datetime.strptime(target_date, "%Y-%m-%d").date()
            delta = (target.year - today.year) * 12 + (target.month - today.month)
            meses_restantes = max(1, delta)
        except Exception:
            meses_restantes = 6
    recommended_monthly_savings = goal / meses_restantes if meses_restantes > 0 else goal
    projected_balance = goal

    # Gerar ações dinâmicas
    actions: List[SavingsAction] = []
    if recommended_monthly_savings < 100:
        actions = [
            SavingsAction(
                id="coffee_cut",
                description="Reduzir gastos com cafés e pequenos luxos",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.5, 2),
                categoryId=None,
                difficultyLevel="low",
                confidence=0.7,
            ),
            SavingsAction(
                id="subscriptions_review",
                description="Revisar assinaturas e cancelar serviços pouco usados",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.5, 2),
                categoryId=None,
                difficultyLevel="low",
                confidence=0.75,
            ),
        ]
    elif recommended_monthly_savings < 300:
        actions = [
            SavingsAction(
                id="dining_out_reduce",
                description="Reduzir gastos com alimentação fora em 20%",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.5, 2),
                categoryId=None,
                difficultyLevel="medium",
                confidence=0.8,
            ),
            SavingsAction(
                id="transport_optimization",
                description="Otimizar transporte usando alternativas mais baratas",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.3, 2),
                categoryId=None,
                difficultyLevel="medium",
                confidence=0.7,
            ),
            SavingsAction(
                id="subscriptions_review",
                description="Revisar assinaturas e cancelar serviços pouco usados",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.2, 2),
                categoryId=None,
                difficultyLevel="low",
                confidence=0.75,
            ),
        ]
    else:
        actions = [
            SavingsAction(
                id="major_expense_cut",
                description="Rever grandes despesas mensais e renegociar contratos",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.5, 2),
                categoryId=None,
                difficultyLevel="high",
                confidence=0.6,
            ),
            SavingsAction(
                id="side_income",
                description="Buscar renda extra com freelances ou vendas",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.3, 2),
                categoryId=None,
                difficultyLevel="high",
                confidence=0.65,
            ),
            SavingsAction(
                id="lifestyle_review",
                description="Reavaliar padrão de vida e cortar supérfluos",
                estimatedMonthlyImpact=round(recommended_monthly_savings * 0.2, 2),
                categoryId=None,
                difficultyLevel="medium",
                confidence=0.7,
            ),
        ]

    # Heurística de probabilidade de sucesso
    if recommended_monthly_savings < 100:
        probability_of_success = 0.9
    elif recommended_monthly_savings < 300:
        probability_of_success = 0.75
    else:
        probability_of_success = 0.6
    probability_of_success = min(1.0, max(0.0, probability_of_success))

    plan = SavingsPlan(
        recommendedMonthlySavings=round(recommended_monthly_savings, 2),
        projectedBalanceByTargetDate=round(projected_balance, 2),
        probabilityOfSuccess=probability_of_success,
        actions=actions,
    )

    summary = (
        f"Para atingir sua meta de economia de R$ {goal:.2f} até {target_date or 'o prazo definido'}, "
        f"você precisará economizar cerca de R$ {plan.recommendedMonthlySavings:.2f} por mês. "
        "Considere as ações sugeridas para aumentar suas chances de sucesso."
    )

    logger.info(
        "savings recommendation response",
        extra={
            "user_id": user_id,
            "goal": goal,
            "targetDate": target_date,
            "recommendedMonthlySavings": plan.recommendedMonthlySavings,
        },
    )

    return SavingsRecommendationResponse(plan=plan, summaryText=summary)
