from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from pydantic import BaseModel
from typing import List, Optional
import httpx
from functools import lru_cache

app = FastAPI(title="Budget AI Service", version="0.1.0")


# ---- Shared models ----

class AiTransaction(BaseModel):
    transactionId: Optional[str]
    userId: Optional[str]
    type: str  # "INCOME" or "EXPENSE"
    date: str  # ISO date
    amount: float
    currency: str
    categoryId: Optional[int] = None
    categoryCode: Optional[str] = None
    description: Optional[str] = None
    paymentMethodId: Optional[int] = None


# ---- Auth / user extraction ----

JWKS_URL = "http://localhost:9000/oauth2/jwks"
JWT_ALGORITHM = "RS256"  # ajuste se o auth-server usar outro algoritmo
JWT_AUDIENCE = None       # defina se precisar validar "aud"

auth_scheme = HTTPBearer(auto_error=True)


@lru_cache(maxsize=1)
def get_jwks():
    response = httpx.get(JWKS_URL, timeout=5.0)
    response.raise_for_status()
    return response.json()


def decode_token_with_jwks(token: str) -> dict:
    jwks = get_jwks()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    keys = jwks.get("keys", [])
    key = next((k for k in keys if k.get("kid") == kid), None)
    if not key:
        raise JWTError("Public key not found for kid")

    options = {}
    if JWT_AUDIENCE is None:
        options["verify_aud"] = False

    payload = jwt.decode(
        token,
        key,
        algorithms=[JWT_ALGORITHM],
        audience=JWT_AUDIENCE,
        options=options,
    )
    return payload


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(auth_scheme),
) -> str:
    token = credentials.credentials
    try:
        payload = decode_token_with_jwks(token)
        user_id: Optional[str] = payload.get("sub") or payload.get("user_id")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token sem user id",
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        )


# ---- 1) Monthly expenses prediction ----

class PredictionItem(BaseModel):
    month: str
    categoryId: Optional[int] = None
    predictedAmount: float
    confidence: float
    historicalAverage: Optional[float] = None
    trend: Optional[str] = None
    minExpected: Optional[float] = None
    maxExpected: Optional[float] = None


class PredictionRequest(BaseModel):
    # userId removed – always comes from token
    categoryId: Optional[int]
    forecastMonths: int = 3
    historicalTransactions: List[AiTransaction]


class PredictionResponse(BaseModel):
    predictions: List[PredictionItem]
    totalPredicted: float
    modelAccuracy: Optional[float] = None


@app.post("/api/v1/ai/monthly-expenses-prediction", response_model=PredictionResponse)
async def monthly_expenses_prediction(
    req: PredictionRequest,
    user_id: str = Depends(get_current_user_id),
) -> PredictionResponse:
    # Baseline simples: usa média dos últimos valores conhecidos
    expenses = [t.amount for t in req.historicalTransactions if t.type == "EXPENSE" and (t.userId is None or t.userId == user_id)]

    if not req.historicalTransactions or not expenses:
        predictions: List[PredictionItem] = []
        for i in range(req.forecastMonths):
            predictions.append(
                PredictionItem(
                    month=f"future-{i+1}",
                    categoryId=req.categoryId,
                    predictedAmount=0.0,
                    confidence=0.2,
                )
            )
        return PredictionResponse(predictions=predictions, totalPredicted=0.0, modelAccuracy=None)

    avg = sum(expenses) / len(expenses)

    predictions = []
    for i in range(req.forecastMonths):
        predictions.append(
            PredictionItem(
                month=f"future-{i+1}",
                categoryId=req.categoryId,
                predictedAmount=round(avg, 2),
                confidence=0.5,
                historicalAverage=round(avg, 2),
                trend="stable",
                minExpected=round(0.8 * avg, 2),
                maxExpected=round(1.2 * avg, 2),
            )
        )

    total = sum(p.predictedAmount for p in predictions)
    return PredictionResponse(predictions=predictions, totalPredicted=round(total, 2), modelAccuracy=None)


# ---- 2) Anomaly detection ----

class ExpectedRange(BaseModel):
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


class AnomalyItem(BaseModel):
    expense: AnomalyExpense
    expectedRange: ExpectedRange
    deviation: float
    severity: str
    suggestion: Optional[str]


class AnomalySummary(BaseModel):
    totalTransactionsAnalyzed: int
    anomaliesCount: int
    totalAnomalousAmount: float
    highestAnomalyScore: float
    summaryText: Optional[str]


class AnomalyDetectionRequest(BaseModel):
    # userId removed – always comes from token
    transactions: List[AiTransaction]
    sensitivity: Optional[float] = 1.5


class AnomalyDetectionResponse(BaseModel):
    anomalies: List[AnomalyItem]
    summary: AnomalySummary


@app.post("/api/v1/ai/anomaly-detection", response_model=AnomalyDetectionResponse)
async def anomaly_detection(
    req: AnomalyDetectionRequest,
    user_id: str = Depends(get_current_user_id),
) -> AnomalyDetectionResponse:
    user_transactions = [t for t in req.transactions if t.type == "EXPENSE" and (t.userId is None or t.userId == user_id)]
    amounts = [t.amount for t in user_transactions]
    n = len(amounts)
    if n == 0:
        summary = AnomalySummary(
            totalTransactionsAnalyzed=0,
            anomaliesCount=0,
            totalAnomalousAmount=0.0,
            highestAnomalyScore=0.0,
            summaryText="Sem dados suficientes para detectar anomalias.",
        )
        return AnomalyDetectionResponse(anomalies=[], summary=summary)

    avg = sum(amounts) / n
    var = sum((x - avg) ** 2 for x in amounts) / n
    std = var ** 0.5 if var > 0 else 1.0
    threshold = req.sensitivity or 1.5

    anomalies: List[AnomalyItem] = []
    total_anomalous = 0.0
    highest_score = 0.0

    for t in user_transactions:
        z = (t.amount - avg) / std
        if z > threshold:
            severity = "high" if z > 2 * threshold else "medium"
            exp = AnomalyExpense(
                id=t.transactionId,
                date=t.date,
                amount=t.amount,
                description=t.description,
                categoryId=t.categoryId,
                categoryCode=t.categoryCode,
                categoryName=None,
            )
            expected = ExpectedRange(min=avg - std, max=avg + std, average=avg)
            suggestion = (
                f"Valor {t.amount:.2f} está {z:.1f} desvios acima da média. "
                f"Considere revisar esta despesa."
            )
            anomalies.append(
                AnomalyItem(
                    expense=exp,
                    expectedRange=expected,
                    deviation=round(z, 2),
                    severity=severity,
                    suggestion=suggestion,
                )
            )
            total_anomalous += t.amount
            highest_score = max(highest_score, abs(z))

    summary = AnomalySummary(
        totalTransactionsAnalyzed=n,
        anomaliesCount=len(anomalies),
        totalAnomalousAmount=round(total_anomalous, 2),
        highestAnomalyScore=round(highest_score, 2),
        summaryText=None,
    )
    return AnomalyDetectionResponse(anomalies=anomalies, summary=summary)


# ---- 3) Auto-categorization ----

class AutoCategorizationRequestItem(BaseModel):
    expenseId: Optional[str]
    description: Optional[str]
    amount: float
    paymentMethodId: Optional[int]


class AutoCategorizationRequest(BaseModel):
    # userId removed – always comes from token
    expenses: List[AutoCategorizationRequestItem]


class CategorySuggestion(BaseModel):
    id: int
    code: str
    name: str
    confidence: float


class CategorizationSuggestionItem(BaseModel):
    expenseId: Optional[str]
    suggestedCategory: CategorySuggestion
    alternativeCategories: List[CategorySuggestion]
    reasoning: Optional[str]


class AutoCategorizationResponse(BaseModel):
    suggestions: List[CategorizationSuggestionItem]


@app.post("/api/v1/ai/auto-categorize", response_model=AutoCategorizationResponse)
async def auto_categorize(
    req: AutoCategorizationRequest,
    user_id: str = Depends(get_current_user_id),
) -> AutoCategorizationResponse:
    suggestions: List[CategorizationSuggestionItem] = []
    for item in req.expenses:
        desc = (item.description or "").lower()
        if "uber" in desc or "99" in desc:
            code, name, conf = "transportation", "Transporte", 0.8
        elif "ifood" in desc or "rappi" in desc:
            code, name, conf = "dining_out", "Alimentação Fora", 0.85
        elif "mercado" in desc or "supermercado" in desc:
            code, name, conf = "groceries", "Compras", 0.9
        else:
            code, name, conf = "miscellaneous", "Outros", 0.4

        suggested = CategorySuggestion(id=0, code=code, name=name, confidence=conf)
        alt = CategorySuggestion(id=0, code="miscellaneous", name="Outros", confidence=1.0 - conf)
        suggestions.append(
            CategorizationSuggestionItem(
                expenseId=item.expenseId,
                suggestedCategory=suggested,
                alternativeCategories=[alt],
                reasoning=f"Heurística baseada na descrição: '{item.description}'" if item.description else None,
            )
        )

    return AutoCategorizationResponse(suggestions=suggestions)


# ---- 4) Savings recommendations ----

class SavingsRecommendationRequest(BaseModel):
    # userId removed – always comes from token
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


@app.post("/api/v1/ai/savings-recommendations", response_model=SavingsRecommendationResponse)
async def savings_recommendations(
    req: SavingsRecommendationRequest,
    user_id: str = Depends(get_current_user_id),
) -> SavingsRecommendationResponse:
    goal = req.savingsGoalAmount or 200.0
    action = SavingsAction(
        id="reduce_dining_out",
        description="Reduzir gastos com alimentação fora em 20%",
        estimatedMonthlyImpact=goal,
        categoryId=None,
        difficultyLevel="medium",
        confidence=0.8,
    )
    plan = SavingsPlan(
        recommendedMonthlySavings=goal,
        projectedBalanceByTargetDate=goal * 6,
        probabilityOfSuccess=0.75,
        actions=[action],
    )
    return SavingsRecommendationResponse(
        plan=plan,
        summaryText="Plano de economia gerado com base nas suas metas.",
    )


# ---- 5) Cashflow insights ----

class CashflowInsightsRequest(BaseModel):
    # userId removed – always comes from token
    months: int = 6


class CashflowAlert(BaseModel):
    severity: str
    message: str
    suggestions: List[str]


class CashflowForecastItem(BaseModel):
    month: str
    predictedIncome: float
    predictedExpenses: float
    projectedBalance: float
    status: str
    alert: Optional[CashflowAlert]


class CashflowInsightsResponse(BaseModel):
    currentBalance: float
    forecast: List[CashflowForecastItem]
    averageMonthlyBalance: float
    insights: List[str]


@app.post("/api/v1/ai/cashflow-insights", response_model=CashflowInsightsResponse)
async def cashflow_insights(
    req: CashflowInsightsRequest,
    user_id: str = Depends(get_current_user_id),
) -> CashflowInsightsResponse:
    months = req.months or 6
    forecast: List[CashflowForecastItem] = []
    balance = 0.0
    for i in range(1, months + 1):
        income = 5000.0
        expenses = 4000.0 + 100 * (i - 1)
        net = income - expenses
        balance += net
        status = "surplus" if net >= 0 else "deficit"
        alert = None
        if status == "deficit":
            alert = CashflowAlert(
                severity="warning",
                message="Possível déficit no mês projetado.",
                suggestions=[
                    "Reduza despesas variáveis",
                    "Considere adiar gastos não essenciais",
                ],
            )
        forecast.append(
            CashflowForecastItem(
                month=f"future-{i}",
                predictedIncome=income,
                predictedExpenses=expenses,
                projectedBalance=balance,
                status=status,
                alert=alert,
            )
        )

    avg_balance = balance / months if months > 0 else 0.0
    insights = ["Seu fluxo de caixa projetado está estável nos próximos meses."]
    if any(item.status == "deficit" for item in forecast):
        insights = [
            "Há meses projetados com déficit. Considere reduzir despesas ou aumentar receitas."
        ]

    return CashflowInsightsResponse(
        currentBalance=0.0,
        forecast=forecast,
        averageMonthlyBalance=avg_balance,
        insights=insights,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
