import os
import logging
import platform
import threading
import time
from redis import Redis
import rq
from rq import Worker
from rq.worker import SimpleWorker

from app.core.training_queue import set_worker_heartbeat

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = "ai-training"


def _start_heartbeat_loop(stop_event: threading.Event):
    while not stop_event.is_set():
        set_worker_heartbeat()
        stop_event.wait(5)


def main():
    logger.info("starting ai-training worker", extra={"queue": QUEUE_NAME})
    # Diagnostic info to help debug import/venv issues
    try:
        logger.info(f"rq module: {rq.__file__}, version: {getattr(rq, '__version__', 'unknown')}" )
    except Exception:
        logger.info("rq module diagnostic unavailable")

    conn = Redis.from_url(REDIS_URL)
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(target=_start_heartbeat_loop, args=(stop_event,), daemon=True)
    heartbeat_thread.start()
    try:
        use_simple = platform.system() == "Darwin"
        if use_simple:
            logger.info("Using SimpleWorker to avoid fork issues on macOS", extra={"platform": platform.system()})
            worker = SimpleWorker([QUEUE_NAME], connection=conn)
        else:
            worker = Worker([QUEUE_NAME], connection=conn)
        worker.work()
    except Exception as exc:
        logger.exception("worker failed", exc_info=exc)
    finally:
        stop_event.set()
        heartbeat_thread.join()


if __name__ == "__main__":
    main()
