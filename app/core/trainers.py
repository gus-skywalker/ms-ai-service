import logging
import os
import time
import json
from typing import Dict
import sys

import pandas as pd

from app.core.feature_store import path_for_user, UserFinancialDataProvider
from app.core.models_registry import save_model
from app.core import training_queue
from app.core.metrics import TRAINING_JOB_DURATION, TRAINER_DURATION, TRAINING_JOB_FAILURES

logger = logging.getLogger(__name__)

MIN_MONTHS = int(os.getenv("TRAINING_MIN_MONTHS", 6))
MIN_TRANSACTIONS = int(os.getenv("TRAINING_MIN_TRANSACTIONS", 100))
MIN_DESCRIPTION_RATIO = float(os.getenv("TRAINING_MIN_DESCRIPTION_RATIO", 0.5))


def _load_monthly_series(user_id: str) -> pd.DataFrame:
    path = path_for_user(user_id, "monthly_series.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_parquet(path)


def _load_transactions(user_id: str) -> pd.DataFrame:
    path = path_for_user(user_id, "raw_transactions.parquet")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_parquet(path)


def is_eligible_for_training(user_id: str) -> bool:
    """Return True if user has enough data to produce a reasonable model.

    Rules (configurable via env):
      - at least MIN_MONTHS entries in monthly series
      - at least MIN_TRANSACTIONS transactions
      - at least MIN_DESCRIPTION_RATIO fraction of transactions with description
      - (optional) require current balance available

    Set TRAINING_FORCE_ENQUEUE=1 to bypass checks (dev/test only).
    """
    # If running under pytest, ignore force enqueue env to keep tests deterministic
    running_pytest = "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules
    force = False
    if not running_pytest:
        force = os.getenv("TRAINING_FORCE_ENQUEUE", "0") in ("1", "true", "True")
    if force:
        logger.info("training eligibility override enabled (force)", extra={"user_id": user_id})
        return True

    monthly = _load_monthly_series(user_id)
    months_count = len(monthly)
    tx = _load_transactions(user_id)
    tx_count = len(tx)
    described_count = 0
    if tx_count:
        described_count = tx[tx["description"].fillna("") != ""].shape[0]
        described_ratio = described_count / tx_count
    else:
        described_ratio = 0.0

    # Current balance check via provider (optional)
    try:
        provider = UserFinancialDataProvider(user_id)
        current_balance = provider.get_current_balance()
    except Exception:
        current_balance = None

    logger.info(
        "training eligibility check",
        extra={
            "user_id": user_id,
            "months_count": months_count,
            "tx_count": tx_count,
            "described_count": described_count,
            "described_ratio": described_ratio,
            "current_balance": current_balance,
        },
    )

    if months_count < MIN_MONTHS:
        logger.info("not eligible: not enough months", extra={"user_id": user_id, "months_count": months_count})
        return False
    if tx_count < MIN_TRANSACTIONS:
        logger.info("not eligible: not enough transactions", extra={"user_id": user_id, "tx_count": tx_count})
        return False
    if described_ratio < MIN_DESCRIPTION_RATIO:
        logger.info("not eligible: not enough described transactions", extra={"user_id": user_id, "described_ratio": described_ratio})
        return False
    if current_balance is None:
        logger.info("not eligible: missing current balance", extra={"user_id": user_id})
        return False

    return True


def train_prediction(user_id: str) -> Dict:
    start = time.time()
    df = _load_monthly_series(user_id)
    if df.empty:
        raise ValueError("monthly series missing")
    latest = df.iloc[-1]
    expenses = latest.get("expenses", {})
    avg_expense = sum(expenses.values()) / len(expenses) if expenses else 0.0
    save_model("prediction", "v1", {"avg_expense": avg_expense}, user_id)
    duration = time.time() - start
    logger.info("train_prediction completed", extra={"user_id": user_id, "duration_s": duration})
    return {"avg_expense": avg_expense, "duration_s": duration}


def train_autocat(user_id: str) -> Dict:
    from app.features.autocat.training import train_autocat as canonical_train_autocat

    return canonical_train_autocat(user_id)


def compute_anomaly_stats(user_id: str) -> Dict:
    start = time.time()
    df = _load_transactions(user_id)
    if df.empty or "categoryId" not in df.columns:
        raise ValueError("category data missing")
    stats = {}
    for category in df["categoryId"].dropna().unique():
        cat_df = df[df["categoryId"] == category]
        amounts = cat_df["amount"].astype(float)
        median = float(amounts.median())
        mad = float((amounts - median).abs().median())
        stats[str(category)] = {"median": median, "mad": mad}
    out_path = path_for_user(user_id, "anomaly_stats.json")
    with open(out_path, "w") as fh:
        json.dump(stats, fh)
    duration = time.time() - start
    logger.info("compute_anomaly_stats completed", extra={"user_id": user_id, "duration_s": duration, "categories": len(stats)})
    return {"categories": len(stats), "duration_s": duration}


def run_all_trainers(user_id: str, job_id: str = None) -> Dict:
    # Ensure we don't run concurrently: check lock exists
    try:
        conn = training_queue._connection
        lock_key = f"training:lock:{user_id}"
        # If lock not present, someone may have removed it; still proceed but log
        if not conn.get(lock_key):
            logger.warning("no lock present at run start (possible race), proceeding", extra={"user_id": user_id, "job_id": job_id})
    except Exception:
        logger.exception("failed to check lock", extra={"user_id": user_id})

    # Persist start
    try:
        job_info = {"jobId": job_id, "status": "running", "started_at": time.time()}
        if job_id is None:
            # attempt to find last job id
            job_id = training_queue.get_last_job_for_user(user_id)
            job_info["jobId"] = job_id
        training_queue.persist_training_status(user_id, job_info)
    except Exception:
        logger.exception("failed to persist job start status", extra={"user_id": user_id})

    logger.info("training started", extra={"user_id": user_id, "job_id": job_id})
    results = {}
    overall_start = time.time()
    with TRAINING_JOB_DURATION.time():
        try:
            for name, func in {
                "prediction": train_prediction,
                "autocat": train_autocat,
                "anomaly": compute_anomaly_stats,
            }.items():
                t0 = time.time()
                with TRAINER_DURATION.labels(name).time():
                    try:
                        res = func(user_id)
                        results[name] = {"status": "ok", "metrics": res}
                    except Exception as exc:
                        duration = time.time() - t0
                        logger.exception("trainer failed", extra={"user_id": user_id, "trainer": name, "duration_s": duration, "job_id": job_id})
                        results[name] = {"status": "failed", "error": str(exc)}
                        TRAINING_JOB_FAILURES.inc()
                        # persist failure
                        try:
                            training_queue.persist_training_status(user_id, {"jobId": job_id, "status": "failed", "trainer": name, "error": str(exc)})
                        except Exception:
                            logger.exception("failed to persist failure status", extra={"user_id": user_id})
                        raise
                    finally:
                        duration = time.time() - t0
                        logger.info("trainer finished", extra={"user_id": user_id, "trainer": name, "duration_s": duration, "job_id": job_id})

            overall_duration = time.time() - overall_start
            logger.info("training finished", extra={"user_id": user_id, "job_id": job_id, "duration_s": overall_duration})
            # persist success
            try:
                training_queue.persist_training_status(user_id, {"jobId": job_id, "status": "finished", "result": results, "duration_s": overall_duration})
            except Exception:
                logger.exception("failed to persist success status", extra={"user_id": user_id})
            return results
        finally:
            # Always release lock
            try:
                training_queue.release_lock(user_id)
            except Exception:
                logger.exception("failed to release lock at end", extra={"user_id": user_id})
