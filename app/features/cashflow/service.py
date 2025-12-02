from __future__ import annotations

from datetime import date, timedelta
from typing import List
import logging
import random

from app.features.cashflow.types import (
    CashflowInsightsRequest,
    CashflowInsightsResponse,
    CashflowForecastItem,
    CashflowAlert,
)
from app.utils.dates import future_month_keys
from app.core.feature_store import UserFinancialDataProvider

CASHFLOW_VERSION = "cashflow_v1"
logger = logging.getLogger(__name__)


def get_cashflow_insights(
    user_id: str,
    request: CashflowInsightsRequest,
) -> CashflowInsightsResponse:
    # Defensive validation
    months = request.months if request.months is not None else 6
    if not isinstance(months, int) or months < 1 or months > 24:
        logger.info(
            "cashflow insight invalid months",
            extra={"user_id": user_id, "months": months},
        )
        raise ValueError("months must be an integer between 1 and 24")
    provider = UserFinancialDataProvider(user_id)
    monthly_totals = provider.get_monthly_totals(months=months)
    if monthly_totals and isinstance(monthly_totals, list) and monthly_totals[0].get("income"):
        # Reconstrói baseline a partir do feature store
        base_income = max(monthly_totals[0].get("income", {}).values()) if monthly_totals[0].get("income") else 5000.0
        base_expenses = max(monthly_totals[0].get("expenses", {}).values()) if monthly_totals[0].get("expenses") else 4200.0
        current_balance = provider.get_current_balance() or 3500.0
    else:
        base_income = 5000.0
        base_expenses = 4200.0
        current_balance = 3500.0
    start = date.today().replace(day=1)
    future_keys = future_month_keys(start, months)
    balance = current_balance
    forecast_items: List[CashflowForecastItem] = []
    deficits = 0
    balances = []
    for i, key in enumerate(future_keys):
        predicted_income = base_income * (1.01 ** i) + random.uniform(-50, 50)
        predicted_expenses = base_expenses * (1.01 ** i) + random.uniform(-50, 50)
        balance = balance + predicted_income - predicted_expenses
        balances.append(balance)
        status = "surplus" if balance >= 0 else "deficit"
        alert = None
        if status == "deficit":
            deficits += 1
            alert = CashflowAlert(
                severity="warning",
                message="Possível déficit projetado. Considere reduzir despesas ou aumentar receitas.",
                suggestions=[
                    "Reveja gastos discricionários",
                    "Avalie oportunidades de renda extra"
                ],
            )
        forecast_items.append(
            CashflowForecastItem(
                month=key,
                predictedIncome=round(predicted_income, 2),
                predictedExpenses=round(predicted_expenses, 2),
                projectedBalance=round(balance, 2),
                status=status,
                alert=alert,
            )
        )
    average_balance = sum(balances) / len(balances) if balances else 0.0
    insights = []
    if deficits == 0:
        insights.append("Fluxo de caixa estável: Nenhum déficit previsto nos próximos meses.")
    if deficits > 2:
        insights.append("Risco financeiro relevante: múltiplos déficits previstos.")
    if average_balance < 0:
        insights.append("Atenção: saldo médio projetado negativo.")
    if not insights:
        insights.append("Acompanhe seu fluxo de caixa para evitar surpresas.")
    logger.info(
        "cashflow insight response",
        extra={
            "user_id": user_id,
            "months": months,
            "deficits": deficits,
        },
    )
    return CashflowInsightsResponse(
        currentBalance=current_balance,
        forecast=forecast_items,
        averageMonthlyBalance=round(average_balance, 2),
        insights=insights,
    )
