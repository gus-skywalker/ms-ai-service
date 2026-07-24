from __future__ import annotations

from fastapi import FastAPI, Depends, Header, HTTPException, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.auth import get_current_user_id, verify_service_token
from app.core.health import internal_health
from app.core.sync import handle_sync_request
from app.core.training_queue import get_job_status, get_last_job_for_user
from app.features.prediction.service import predict_monthly_expenses
from app.features.prediction.types import (
    MonthlyExpensesPredictionRequest,
    MonthlyExpensesPredictionResponse,
)
from app.features.anomaly.service import detect_anomalies
from app.features.anomaly.types import (
    AnomalyDetectionRequest,
    AnomalyDetectionResponse,
)
from app.features.autocat.service import auto_categorize_expenses
from app.features.autocat.types import (
    AutoCategorizeRequest,
    AutoCategorizeResponse,
)
from app.features.cashflow.service import get_cashflow_insights
from app.features.cashflow.types import (
    CashflowInsightsRequest,
    CashflowInsightsResponse,
)
from app.features.savings.service import generate_savings_recommendations
from app.features.savings.types import (
    SavingsRecommendationRequest,
    SavingsRecommendationResponse,
)

app = FastAPI(title="Budget AI Service", version="0.1.0")


def _require_internal_workspace_id(workspace_id: str | None) -> str:
    if workspace_id is None or not workspace_id.strip():
        raise HTTPException(status_code=400, detail="workspaceId is required")
    return workspace_id.strip()


def _resolve_legacy_workspace_id(workspace_id: str | None, legacy_user_id: str | None) -> str:
    resolved_workspace_id = workspace_id.strip() if workspace_id and workspace_id.strip() else None
    resolved_legacy_id = legacy_user_id.strip() if legacy_user_id and legacy_user_id.strip() else None
    if resolved_workspace_id and resolved_legacy_id and resolved_workspace_id != resolved_legacy_id:
        raise HTTPException(status_code=400, detail="workspaceId and legacy userId must match")
    return _require_internal_workspace_id(resolved_workspace_id or resolved_legacy_id)


# ---- 1) Monthly expenses prediction ----

@app.post("/api/v1/ai/monthly-expenses-prediction", response_model=MonthlyExpensesPredictionResponse)
async def monthly_expenses_prediction(
    req: MonthlyExpensesPredictionRequest,
    user_id: str = Depends(get_current_user_id),
) -> MonthlyExpensesPredictionResponse:
    return predict_monthly_expenses(user_id=user_id, request=req)


@app.post("/internal/ai/monthly-expenses-prediction", response_model=MonthlyExpensesPredictionResponse)
async def internal_monthly_expenses_prediction(
    req: MonthlyExpensesPredictionRequest,
    x_service_token: str = Header(None),
) -> MonthlyExpensesPredictionResponse:
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _require_internal_workspace_id(req.workspaceId)
    return predict_monthly_expenses(user_id=workspace_id, request=req)


# ---- 2) Anomaly detection ----

@app.post("/api/v1/ai/anomaly-detection", response_model=AnomalyDetectionResponse)
async def anomaly_detection(
    req: AnomalyDetectionRequest,
    user_id: str = Depends(get_current_user_id),
) -> AnomalyDetectionResponse:
    return detect_anomalies(user_id=user_id, request=req)


@app.post("/internal/ai/anomaly-detection", response_model=AnomalyDetectionResponse)
async def internal_anomaly_detection(
    req: AnomalyDetectionRequest,
    x_service_token: str = Header(None),
) -> AnomalyDetectionResponse:
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _require_internal_workspace_id(req.workspaceId)
    return detect_anomalies(user_id=workspace_id, request=req)


# ---- 3) Auto-categorization ----

@app.post("/api/v1/ai/auto-categorize", response_model=AutoCategorizeResponse)
async def auto_categorize(
    req: AutoCategorizeRequest,
    user_id: str = Depends(get_current_user_id),
) -> AutoCategorizeResponse:
    return auto_categorize_expenses(user_id=user_id, request=req)


@app.post("/internal/ai/auto-categorize", response_model=AutoCategorizeResponse)
async def internal_auto_categorize(
    req: AutoCategorizeRequest,
    x_service_token: str = Header(None),
) -> AutoCategorizeResponse:
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _resolve_legacy_workspace_id(req.workspaceId, req.userId)
    return auto_categorize_expenses(user_id=workspace_id, request=req)


# ---- 4) Savings recommendations ----

@app.post("/api/v1/ai/savings-recommendations", response_model=SavingsRecommendationResponse)
async def savings_recommendations(
    req: SavingsRecommendationRequest,
    user_id: str = Depends(get_current_user_id),
) -> SavingsRecommendationResponse:
    return generate_savings_recommendations(user_id=user_id, request=req)


@app.post("/internal/ai/savings-recommendations", response_model=SavingsRecommendationResponse)
async def internal_savings_recommendations(
    req: SavingsRecommendationRequest,
    x_service_token: str = Header(None),
) -> SavingsRecommendationResponse:
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _require_internal_workspace_id(req.workspaceId)
    return generate_savings_recommendations(user_id=workspace_id, request=req)


# ---- 5) Cashflow insights ----

@app.post("/api/v1/ai/cashflow-insights", response_model=CashflowInsightsResponse)
async def cashflow_insights(
    req: CashflowInsightsRequest,
    user_id: str = Depends(get_current_user_id),
) -> CashflowInsightsResponse:
    return get_cashflow_insights(user_id=user_id, request=req)


@app.post("/internal/ai/cashflow-insights", response_model=CashflowInsightsResponse)
async def internal_cashflow_insights(
    req: CashflowInsightsRequest,
    x_service_token: str = Header(None),
) -> CashflowInsightsResponse:
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _require_internal_workspace_id(req.workspaceId)
    return get_cashflow_insights(user_id=workspace_id, request=req)


@app.post("/internal/ai/sync-user-data")
async def sync_user_data(request: Request, x_service_token: str = Header(None)):
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload = await request.json()
    result = handle_sync_request(payload)
    return result


@app.get("/internal/ai/user/{user_id}/training-status")
async def training_status(user_id: str, x_service_token: str = Header(None)):
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    last_job_id = get_last_job_for_user(user_id)
    status = get_job_status(last_job_id) if last_job_id else None
    return {"userId": user_id, "jobId": last_job_id, "status": status}


@app.get("/internal/ai/workspace/{workspace_id}/training-status")
async def workspace_training_status(workspace_id: str, x_service_token: str = Header(None)):
    if not verify_service_token(x_service_token):
        raise HTTPException(status_code=401, detail="Unauthorized")
    workspace_id = _require_internal_workspace_id(workspace_id)
    last_job_id = get_last_job_for_user(workspace_id)
    status = get_job_status(last_job_id) if last_job_id else None
    return {"workspaceId": workspace_id, "jobId": last_job_id, "status": status}


@app.get("/internal/ai/health")
async def internal_health_endpoint():
    return internal_health()


@app.get('/metrics')
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

# How To Use
# uvicorn app.main:app --reload
