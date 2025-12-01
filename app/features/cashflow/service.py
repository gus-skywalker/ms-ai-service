from __future__ import annotations

from datetime import date
from typing import List

from app.features.cashflow.types import (
    CashflowInsightsRequest,
    CashflowInsightsResponse,
    CashflowForecastItem,
    CashflowAlert,
)
from app.utils.dates import future_month_keys


CASHFLOW_VERSION = "cashflow_v1"


def get_cashflow_insights(
    user_id: str,
    request: CashflowInsightsRequest,
) -> CashflowInsightsResponse:
    months = request.months or 6
    start = date.today().replace(day=1)
    future_keys = future_month_keys(start, months)

    # Placeholder baseline: assume constant income and expenses
    base_income = 5000.0
    base_expenses = 4200.0
    current_balance = 3500.0

    forecast_items: List[CashflowForecastItem] = []
    balance = current_balance

    for key in future_keys:
        predicted_income = base_income
        predicted_expenses = base_expenses
        balance = balance + predicted_income - predicted_expenses
        status = "surplus" if balance >= 0 else "deficit"

        alert: CashflowAlert | None = None
        if status == "deficit":
            alert = CashflowAlert(
                severity="warning",
                message="Possível déficit projetado. Considere reduzir despesas ou aumentar receitas.",
                suggestions=[
                    "Reduzir gastos em categorias não essenciais",
                    "Adiar compras de alto valor",
                ],
            )

        item = CashflowForecastItem(
            month=key,
            predictedIncome=predicted_income,
            predictedExpenses=predicted_expenses,
            projectedBalance=round(balance, 2),
            status=status,  # type: ignore[arg-type]
            alert=alert,
        )
        forecast_items.append(item)

    avg_balance = sum(item.projectedBalance for item in forecast_items) / len(
        forecast_items
    )

    insights = [
        "Fluxo de caixa projetado com base em médias simples de renda e despesa.",
    ]

    return CashflowInsightsResponse(
        currentBalance=round(current_balance, 2),
        forecast=forecast_items,
        averageMonthlyBalance=round(avg_balance, 2),
        insights=insights,
    )
