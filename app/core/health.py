from fastapi import HTTPException
from app.core.training_queue import ping_redis, worker_heartbeat_ok


def internal_health():
    redis_ok = ping_redis()
    worker_ok = worker_heartbeat_ok()
    if not redis_ok:
        raise HTTPException(status_code=503, detail="Redis unreachable")
    if not worker_ok:
        raise HTTPException(status_code=503, detail="Worker heartbeat missing")
    return {"redis": "ok", "worker": "ok"}

