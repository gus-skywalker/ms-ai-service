# ai-service

This service centralizes AI/ML features for the Budget project: prediction, anomaly detection, auto-categorization, cashflow insights and savings recommendations.

This README documents the main features, architecture, internal flows (sync & feature-store), worker/training integration (Redis + RQ), how to run locally and how the Java backend should integrate.

---

## Quick overview

- Language: Python 3.x (project uses 3.9 in CI/dev)
- Framework: FastAPI
- Queue/worker: Redis + RQ (queue `ai-training`) — worker entrypoint: `worker/worker.py`
- Feature store: local filesystem under `storage/user_data/{userId}` (parquet/json)
- Models: persisted under `models/{feature}/{version}/{userId}` (joblib)
- Tests: PyTest (fakeredis used for queue tests)

---

## Core concepts

1. Feature Store
   - `storage/user_data/{userId}/` holds preprocessed artifacts (raw_transactions.parquet, monthly_series.parquet, categories_stats.json, anomaly_stats.json, training_status.json, metadata.json)
   - Helpers: `app/core/feature_store.py` — `path_for_user`, `save_user_data`, `UserFinancialDataProvider`.

2. Sync Endpoint (internal)
   - POST `/internal/ai/sync-user-data`
   - Auth: `X-Service-Token: <SECRET>` (or Bearer header) — validated by `app.core.auth.verify_service_token`
   - Payload: supports `rawTransactions` (full list) and `monthlyAggregates` (lighter aggregation). `mode` can be `full` or `incremental`.
   - Behavior: validates, writes feature store files, updates metadata, checks eligibility and enqueues training job (RQ) if eligible.

3. Training queue
   - Redis URL: `REDIS_URL` (env)
   - Queue name: `ai-training`
   - Helper: `app/core/training_queue.py` — `enqueue_training_job`, `get_job_status`, `persist_training_status`, `acquire_lock`/`release_lock`.
   - Per-user lock: prevents concurrent training for the same user (Redis key `training:lock:{userId}`).

4. Trainers & Models
   - Trainer entrypoint: `app/core/trainers.py` (functions: `run_all_trainers`, `train_prediction`, `train_autocat`, `compute_anomaly_stats`)
   - Models saved via `app/core/models_registry.py` into `models/{feature}/{version}/{userId}/model.joblib`
   - On train start/finish/failure the system persists `storage/user_data/{userId}/training_status.json` so other services (Java) can read model readiness without Redis dependency.

5. Worker
   - `worker/worker.py` starts an RQ worker — on macOS uses `SimpleWorker` to avoid `fork()`+ObjectiveC issues.
   - Run the worker in a separate process/container.

6. Metrics
   - Prometheus metrics available at `/metrics` provided by `prometheus_client` (job count, durations, failures).

---

## Public API (FastAPI)

- POST `/api/v1/ai/monthly-expenses-prediction` — Uses `prediction` service.
- POST `/api/v1/ai/anomaly-detection` — Uses `anomaly` service.
- POST `/api/v1/ai/auto-categorize` — Uses `autocat` service.
- POST `/api/v1/ai/savings-recommendations` — Uses `savings` service.
- POST `/api/v1/ai/cashflow-insights` — Uses `cashflow` service.

All public endpoints use JWT auth to get `user_id` (via `app.core.auth.get_current_user_id`) and expect request bodies defined in `app/features/*/types.py`.

---

## Internal API (for backend integration)

- POST `/internal/ai/sync-user-data` (X-Service-Token or internal Bearer token)
  - Used by `budget-api` to push raw or aggregated user data.
  - Example payload:
  ```json
  {
    "userId": "123",
    "mode": "full",              
    "rawTransactions": [{"transactionId": "t1", "date": "2025-11-01", "amount": -35.5, "type": "EXPENSE", "categoryId": 10, "description": "Uber"}],
    "monthlyAggregates": {"income": {"2025-01": 5000.0}, "expenses": {"2025-01": 4200.0}},
    "syncType": "full",
    "source": "budget-api",
    "timestamp": "2025-12-02T15:00:00Z"
  }
  ```
  - Response (accepted): `{ status: "accepted", userId: "123", lastSync: "...", queued: true|false, jobId: null|"..." }`

- GET `/internal/ai/user/{userId}/training-status` (X-Service-Token required) — returns last job id and RQ job status.

---

## Feature store layout (local)

```
storage/
  user_data/
    {userId}/
      raw_transactions.parquet
      monthly_series.parquet
      categories_stats.json
      anomaly_stats.json
      training_status.json
      metadata.json
models/
  prediction/
    v1/
      {userId}/model.joblib
  autocat/
    v1/
      {userId}/model.joblib
```

Notes:
- `training_status.json` is the canonical file for other services (like `budget-api`) to check model readiness if filesystem is shared.

---

## Java integration (how `budget-api` should sync)

Two practical options:

A) HTTP sync (fast to implement)
- `budget-api` posts incremental or full payloads to `/internal/ai/sync-user-data` with `X-Service-Token`.
- For events (create/update/delete transaction) use incremental sync with a small rawTransactions array and `syncType: "incremental"`.
- For bulk import or initial sync use `mode: "full"` and `syncType: "full"`.
- After POST, `budget-api` can poll `/internal/ai/user/{userId}/training-status` or read `storage/user_data/{userId}/training_status.json` (if shared filesystem) for progress.

B) Message broker (recommended at scale)
- Produce messages to a queue (Kafka) and have ai-service consume and apply syncs to the feature store.
- This decouples systems and handles spikes better.

Important: Do not rely solely on immediate training completion — training is performed asynchronously (RQ worker). Use `training_status.json` or training-status endpoint for readiness.

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
export REDIS_URL=redis://localhost:6379/0
export AI_SERVICE_TOKEN=testtoken
uvicorn app.main:app --reload
```

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
- `TRAINING_MIN_MONTHS`, `TRAINING_MIN_TRANSACTIONS`, `TRAINING_MIN_DESCRIPTION_RATIO` — configurable thresholds for eligibility.
- `TRAINING_FORCE_ENQUEUE` — dev-only flag to bypass eligibility (do NOT enable in prod).
- `AI_MODEL_DIR` — optional override for model paths used in some tests.

---

## Observability & logs

- Structured logs use `logger.info(..., extra={"user_id":..., ...})` throughout the code base.
- Metrics are available at `/metrics` for Prometheus scraping.
- Training status is persisted to `storage/user_data/{userId}/training_status.json` for simple integration which Java can read.

---

## Testing

- Unit tests: `pytest` in repository root. Tests use `fakeredis` to simulate Redis for queue tests.
- Tests cover services (prediction, autocat, anomaly, cashflow, savings), sync endpoint, trainers and provider utilities.

---

## Next improvements (short roadmap)

- Replace local feature store with object store (S3) or a central DB for multi-instance deployments.
- Implement Redlock or ownership checks for locks to make distributed locks robust.
- Add a Java-side client library (AiSyncService) that encapsulates request formatting and error handling.
- Add an admin endpoint to re-enqueue training for users / batch re-training.
- Add a retraining scheduler (nightly batches) and a monitoring dashboard (RQ dashboard / Prometheus+Grafana).

---

## Where to start when contributing

1. Read `app/core/sync.py` and `app/core/feature_store.py` to understand ingestion.
2. Look at `app/core/trainers.py` and `app/core/models_registry.py` for training and persistence.
3. Run tests and start the worker locally to iterate quickly.
4. When adding new features, follow existing service patterns and types in `app/features/*`.

---