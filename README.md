# ai-service

This service centralizes AI/ML features for the Budget project: prediction, anomaly detection, auto-categorization, cashflow insights and savings recommendations.

This README documents the main features, architecture, internal flows (sync & feature-store), worker/training integration (Redis + RQ), how to run locally and how the Java backend should integrate.

---

## Quick overview

- Language: Python 3.x (project uses 3.9 in CI/dev)
- Framework: FastAPI
- Queue/worker: Redis + RQ (queue `ai-training`) — worker entrypoint: `worker/worker.py`
- Feature store: local filesystem under the legacy physical path `storage/user_data/{workspaceId}` (parquet/json)
- Autocat models: immutable bundles under `models/autocat/autocat_v2/{workspaceId}/versions/{modelVersion}` with an atomic `active.json` pointer
- Tests: PyTest (fakeredis used for queue tests)

---

## Core concepts

1. Feature Store
   - `storage/user_data/{workspaceId}/` holds derived artifacts. The directory name is retained for artifact compatibility; the partition key is a workspace, not a user.
   - Helpers: `app/core/feature_store.py` — `path_for_user`, `save_user_data`, `UserFinancialDataProvider`.

2. Sync Endpoint (internal)
   - POST `/internal/ai/sync-user-data`
   - Auth: `X-Service-Token: <SECRET>` — validated by `app.core.auth.verify_service_token`
   - Payload: contract v1 uses `workspaceId`, separate `transactions`/`labels`/`feedback`, deterministic `syncId`, and `FULL` or `INCREMENTAL`. Legacy `userId`/`rawTransactions` remain accepted only for migration.
   - Behavior: validates, writes feature store files, updates metadata, evaluates autocat-specific eligibility and enqueues the canonical trainer only when the supervised fingerprint changed and cooldown permits.

3. Training queue
   - Redis URL: `REDIS_URL` (env)
   - Queue name: `ai-training`
   - Helper: `app/core/training_queue.py` — `enqueue_autocat_training_job`, status helpers and legacy multi-feature queue compatibility.
   - Per-workspace/per-feature lock, dataset fingerprint and cooldown prevent duplicate or concurrent autocat training.

4. Trainers & Models
   - Canonical autocat trainer: `app/features/autocat/training.py`. Legacy functions in `trainers.py` and `models_registry.py` only delegate to it.
   - It reads `trusted_labels.parquet`, joins canonical transaction descriptions, evaluates cross-validated accuracy/macro-F1/per-category metrics, persists a complete candidate bundle and only then atomically activates it.
   - `USER` and `USER_CONFIRMED_SUGGESTION` have trust 1.00, `BANK_MAPPING` 0.95 and `RULE` 0.90. `AI`, `HISTORY` and `DOMAIN_ALIAS` are never training labels without explicit confirmation.
   - Inference never trains, never loads a global model and never fabricates a default category.
   - On train start/finish/failure the system persists `storage/user_data/{workspaceId}/training_status.json`.

5. Worker
   - `worker/worker.py` starts an RQ worker — on macOS uses `SimpleWorker` to avoid `fork()`+ObjectiveC issues.
   - Run the worker in a separate process/container.

6. Metrics
   - Prometheus metrics available at `/metrics` include job counts/durations/failures plus autocat training and inference outcomes.

---

## Public API (FastAPI)

- POST `/api/v1/ai/monthly-expenses-prediction` — Uses `prediction` service.
- POST `/api/v1/ai/anomaly-detection` — Uses `anomaly` service.
- POST `/api/v1/ai/auto-categorize` — Uses `autocat` service.
- POST `/api/v1/ai/savings-recommendations` — Uses `savings` service.
- POST `/api/v1/ai/cashflow-insights` — Uses `cashflow` service.

All public endpoints use JWT auth to get `user_id` (via `app.core.auth.get_current_user_id`) and expect request bodies defined in `app/features/*/types.py`.
They are compatibility endpoints and are not used by the official CoBudget frontend/backend flow.

---

## Internal API (for backend integration)

All endpoints below require `X-Service-Token`. Inference requests require
`workspaceId`; `actorUserId` and `requestId` are correlation/audit context and
never select a feature partition.

- POST `/internal/ai/monthly-expenses-prediction`
- POST `/internal/ai/anomaly-detection`
- POST `/internal/ai/auto-categorize`
- POST `/internal/ai/savings-recommendations`
- POST `/internal/ai/cashflow-insights`

Autocat inference accepts `allowedCategoryIds`. A personalized result is only
safe when its model belongs to the requested workspace, its confidence meets
`AUTOCAT_SAFE_CONFIDENCE`, and its category belongs to that active domain. The
response includes `status`, `strategy`, `modelVersion`, `modelScope`,
`explanation` and `safeToApply`. Missing or incompatible models return semantic
states such as `INSUFFICIENT_LABELED_HISTORY`, `MODEL_NOT_READY`,
`MODEL_REJECTED` or `NO_SAFE_SUGGESTION`.

- POST `/internal/ai/sync-user-data` (X-Service-Token or internal Bearer token)
  - Used by `budget-api` to push raw or aggregated workspace data.
  - Example payload:
  ```json
  {
    "schemaVersion": 1,
    "workspaceId": "workspace-123",
    "actorUserId": "user-123",
    "requestId": "request-123",
    "syncId": "sync-123",
    "mode": "FULL",
    "reason": "BACKFILL",
    "transactions": [{"transactionId": "t1", "entryId": "e1", "date": "2025-11-01", "amount": 35.5, "type": "EXPENSE", "categoryId": 10, "description": "Uber"}],
    "labels": [{"labelId": "t1:e1", "transactionId": "t1", "entryId": "e1", "categoryId": 10, "labelSource": "USER", "trust": 1.0}],
    "feedback": [{"feedbackId": "f1", "eventType": "SUGGESTION_ACCEPTED", "transactionId": "t1"}],
    "monthlyAggregates": {"income": {"2025-01": 5000.0}, "expenses": {"2025-01": 4200.0}},
    "syncType": "full",
    "source": "budget-api",
    "timestamp": "2025-12-02T15:00:00Z"
  }
  ```
  - Response: `{ status: "accepted"|"duplicate", workspaceId: "workspace-123", syncId: "sync-123", lastSync: "...", queued: true|false, jobId: null|"..." }`

- GET `/internal/ai/workspace/{workspaceId}/training-status` — canonical training status endpoint.
- GET `/internal/ai/user/{userId}/training-status` — legacy compatibility alias.
- GET `/internal/ai/workspace/{workspaceId}/autocat/eligibility`
- POST `/internal/ai/workspace/{workspaceId}/autocat/train`
- GET `/internal/ai/workspace/{workspaceId}/autocat/models`
- GET `/internal/ai/workspace/{workspaceId}/autocat/models/active`
- POST `/internal/ai/workspace/{workspaceId}/autocat/models/{modelVersion}/activate`
- GET `/internal/ai/workspace/{workspaceId}/autocat/feedback-metrics`

- GET `/internal/ai/health`
  - Purpose: verify Redis and worker heartbeat
  - Response: `{ "redis": "ok", "worker": "ok" }`

---

## Feature store layout (local)

```
storage/
  user_data/
    {workspaceId}/
      raw_transactions.parquet
      trusted_labels.parquet
      feedback_events.parquet
      monthly_series.parquet
      categories_stats.json
      anomaly_stats.json
      training_status.json
      metadata.json
models/
  prediction/
    v1/
      {workspaceId}/model.joblib
  autocat/
    autocat_v2/
      {workspaceId}/
        active.json
        versions/
          {modelVersion}/
            bundle.joblib
            manifest.json
```

Notes:
- `training_status.json` is the canonical file for other services (like `budget-api`) to check model readiness if filesystem is shared.

---

## Java integration (how `budget-api` syncs)

`budget-api` is the only supported producer. It writes a transactional outbox
alongside the financial mutation and posts committed rows to
`/internal/ai/sync-user-data`. Retry always keeps the same `syncId`; both
`accepted` and `duplicate` mean success. Backfill and Open Finance use bounded
incremental upsert pages so a later page never replaces an earlier one.

Canonical transactions feed features. Trusted labels are persisted separately
and accept only `USER`, `RULE`, `BANK_MAPPING`, or
`USER_CONFIRMED_SUGGESTION`; a raw `AI` label receives HTTP 400. Feedback is
deduplicated by `feedbackId`. The currently connected feedback types are
`SUGGESTION_ACCEPTED`, `SUGGESTION_REJECTED`, and `CATEGORY_CORRECTED`.

Cold start is owned by `budget-api`: `BANK_MAPPING`, workspace history/rules and curated `DOMAIN_ALIAS` run before remote inference. The Python service does not use raw global data as a fallback. Training is asynchronous; use the eligibility/model/status endpoints for readiness.

---

## API docs (sync + status)
- `POST /internal/ai/sync-user-data`
  - Header: `X-Service-Token: <token>`
  - Body: the v1 workspace envelope shown above (`transactions` plus optional `monthlyAggregates`)
  - Response: `{
      "status": "accepted",
      "workspaceId": "workspace-123",
      "syncId": "sync-123",
      "lastSync": "...",
      "queued": true|false,
      "jobId": "..."|null,
      "alreadyRunning": true|false
    }`
  - `trainingDecision` explains `QUEUED`, `NOT_ELIGIBLE`, `UNCHANGED_DATASET`, `COOLDOWN`, `ALREADY_RUNNING` or `QUEUE_UNAVAILABLE`; retry policy should follow that state instead of a fixed loop.
- `GET /internal/ai/workspace/{workspaceId}/training-status`
  - Header: `X-Service-Token`
  - Response: `{
      "workspaceId": "workspace-123",
      "jobId": "job-123",
      "status": { ... RQ job structure ... }
    }`
  - Use this to poll for readiness and to detect failure states before resubmitting sync.

## Railway deployment

Example `railway.json` config:

```json
{
  "build": {
    "env": {
      "AI_SERVICE_TOKEN": "your_token",
      "REDIS_URL": "redis://default:password@redis-12345.c250.us-east-1-4.ec2.cloud.redislabs.com:12345"
    }
  }
}
```

- Services:
  - api: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`
  - worker: `python -m worker.worker`
  - redis: official redis image
- Shared env vars:
  - `AI_SERVICE_TOKEN`
  - `REDIS_URL`
  - Optional autocat thresholds: `AUTOCAT_MIN_*`, `AUTOCAT_MAX_*`, `AUTOCAT_SAFE_CONFIDENCE`, `AUTOCAT_TRAINING_COOLDOWN_SECONDS`
- Worker must run in Railway `worker` service with same env.
- Add `Procfile` or Railway service settings accordingly.

---

## Running locally (dev)

Prerequisites
- Python 3.9+, pip, Docker (for Redis) or a Redis instance

Quickstart (macOS/Linux):

1. Create & activate venv
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Start Redis (for queue)
```bash
docker run --rm -p 6379:6379 redis:7
```

3. Start API
```bash
cp .env.example .env
export REDIS_URL=redis://localhost:6379/0
export AI_SERVICE_TOKEN=testtoken
uvicorn app.main:app --reload
```

For CoBudget local development, keep `AI_SERVICE_TOKEN` equal to the `budget-api`
`AI_SERVICE_TOKEN` value. The default local pair is `testtoken` on both sides.
The public AI endpoints validate JWTs against `AUTH_SERVER_URL`, which defaults
to the local auth service at `http://localhost:9000`.

4. Start worker (in another terminal)
```bash
source .venv/bin/activate
export REDIS_URL=redis://localhost:6379/0
python -m worker.worker
```

5. Run tests
```bash
pytest -q
```

Notes for macOS: worker defaults to `SimpleWorker` to avoid Objective-C fork issues.

---

## Environment variables

- `AI_SERVICE_TOKEN` — internal service token used by `budget-api` to call internal endpoints.
- `REDIS_URL` — Redis connection used for RQ queue.
- `AUTH_SERVER_URL` — auth service base URL used to validate public endpoint JWTs.
- `JWT_JWKS_PATH` — JWKS path appended to `AUTH_SERVER_URL`; defaults to `/oauth2/jwks`.
- `AUTH_JWKS_TIMEOUT_SECONDS` — timeout for JWKS fetches; defaults to `3.0`.
- `AUTH_JWKS_CACHE_TTL_SECONDS` — fresh JWKS cache lifetime; defaults to `300`.
- `AUTH_JWKS_STALE_SECONDS` — max time to keep using cached JWKS when auth is temporarily unavailable; defaults to `3600`.
- `TRAINING_MIN_MONTHS`, `TRAINING_MIN_TRANSACTIONS`, `TRAINING_MIN_DESCRIPTION_RATIO` — configurable thresholds for eligibility.
- `TRAINING_FORCE_ENQUEUE` — dev-only flag to bypass eligibility (do NOT enable in prod).
- `AI_MODEL_DIR` — optional override for model paths used in some tests.

---

## Observability & logs

- Structured logs use `logger.info(..., extra={"user_id":..., ...})` throughout the code base.
- Metrics are available at `/metrics` for Prometheus scraping.
- Training status is persisted to `storage/user_data/{workspaceId}/training_status.json`.

---

## Testing

- Unit tests: `pytest` in repository root. Tests use `fakeredis` to simulate Redis for queue tests.
- Tests cover services (prediction, autocat, anomaly, cashflow, savings), sync endpoint, trainers and provider utilities.

---

## Next improvements (short roadmap)

- Replace local feature store with object store (S3) or a central DB for multi-instance deployments.
- Implement Redlock or ownership checks for locks to make distributed locks robust.
- Move feature artifacts to shared/object storage before horizontally scaling API instances.
- Add an admin endpoint to re-enqueue training for users / batch re-training.
- Add a retraining scheduler (nightly batches) and a monitoring dashboard (RQ dashboard / Prometheus+Grafana).

---

## Where to start when contributing

1. Read `app/core/sync.py` and `app/core/feature_store.py` to understand ingestion.
2. Look at `app/core/trainers.py` and `app/core/models_registry.py` for training and persistence.
3. Run tests and start the worker locally to iterate quickly.
4. When adding new features, follow existing service patterns and types in `app/features/*`.

---
