import os
import logging
from typing import Optional, Tuple
from redis import Redis
from rq import Queue
from rq.job import Job, Retry
from datetime import datetime, timezone
import json

import app.core.feature_store as feature_store
from app.core.metrics import TRAINING_JOBS_TOTAL

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "ai-training"
_LAST_JOB_KEY = "training:last_job:{user_id}"
_LOCK_KEY = "training:lock:{user_id}"
_HEARTBEAT_KEY = "training:worker:heartbeat"

# Initialize connection lazily to allow env changes in tests
def _get_connection():
    return Redis.from_url(REDIS_URL)

_connection = _get_connection()
queue = Queue(QUEUE_NAME, connection=_connection)
_DEFAULT_RETRY = Retry(max=2, interval=[5, 15])


def persist_training_status(user_id: str, status: dict):
    """Persist a small JSON status file under storage/user_data/{userId}/training_status.json."""
    try:
        path = feature_store.path_for_user(user_id, "training_status.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # add timestamp if not present
        if "updated_at" not in status:
            status["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(path, "w") as fh:
            json.dump(status, fh)
        logger.info("persisted training status", extra={"user_id": user_id, "path": path, "status": status.get("status")})
    except Exception:
        logger.exception("failed to persist training status", extra={"user_id": user_id})


def acquire_lock(user_id: str, ttl: int = 3600) -> bool:
    """Try to acquire a lock for a user. Returns True if lock was acquired."""
    key = _LOCK_KEY.format(user_id=user_id)
    try:
        res = _connection.set(key, "1", nx=True, ex=ttl)
        return bool(res)
    except Exception:
        logger.exception("failed to acquire lock", extra={"user_id": user_id})
        return False


def release_lock(user_id: str):
    key = _LOCK_KEY.format(user_id=user_id)
    try:
        _connection.delete(key)
    except Exception:
        logger.exception("failed to release lock", extra={"user_id": user_id})


def enqueue_training_job(user_id: str) -> Tuple[Optional[str], bool]:
    try:
        acquired = acquire_lock(user_id)
        if not acquired:
            logger.info("training already queued/running for user", extra={"user_id": user_id})
            return None, True
        # increment metric
        TRAINING_JOBS_TOTAL.inc()
        job = queue.enqueue(
            "app.core.trainers.run_all_trainers",
            user_id,
            job_timeout=600,
            retry=_DEFAULT_RETRY,
        )
        _connection.set(_LAST_JOB_KEY.format(user_id=user_id), job.id)
        logger.info(
            "training job enqueued",
            extra={"user_id": user_id, "job_id": job.id},
        )
        # persist initial queued status
        persist_training_status(user_id, {"jobId": job.id, "status": "queued", "enqueued_at": datetime.now(timezone.utc).isoformat()})
        return job.id, False
    except Exception:
        logger.exception("failed to enqueue training job", extra={"user_id": user_id})
        try:
            pong = _connection.ping()
            logger.error("Redis ping response: %s", pong, extra={"user_id": user_id})
        except Exception:
            logger.exception("Redis connectivity check failed", extra={"user_id": user_id})
        # ensure we release lock if error
        try:
            release_lock(user_id)
        except Exception:
            pass
        return None, False


def ping_redis() -> bool:
    try:
        return _connection.ping()
    except Exception:
        logger.exception("redis ping failed")
        return False


def worker_heartbeat_ok() -> bool:
    try:
        return _connection.exists(_HEARTBEAT_KEY) == 1
    except Exception:
        logger.exception("worker heartbeat check failed")
        return False


def set_worker_heartbeat():
    try:
        _connection.set(_HEARTBEAT_KEY, "1", ex=10)
    except Exception:
        logger.exception("failed to update worker heartbeat")


def get_job_status(job_id: str) -> Optional[dict]:
    try:
        job = Job.fetch(job_id, connection=_connection)
    except Exception:
        return None
    return {
        "id": job.id,
        "status": job.get_status(refresh=True),
        "enqueued_at": job.enqueued_at.isoformat() if job.enqueued_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "result": job.result,
        "exc_info": job.exc_info,
    }


def get_last_job_for_user(user_id: str) -> Optional[str]:
    job_id = _connection.get(_LAST_JOB_KEY.format(user_id=user_id))
    return job_id.decode() if job_id else None
