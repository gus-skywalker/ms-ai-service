from prometheus_client import Counter, Histogram

TRAINING_JOBS_TOTAL = Counter("ai_training_jobs_total", "Total number of training jobs enqueued")
TRAINING_JOB_DURATION = Histogram("ai_training_job_duration_seconds", "Training job duration seconds")
TRAINER_DURATION = Histogram("ai_trainer_duration_seconds", "Duration per trainer", ['trainer'])
TRAINING_JOB_FAILURES = Counter("ai_training_jobs_failed_total", "Total number of failed training jobs")
AUTOCAT_TRAINING_RESULTS = Counter(
    "ai_autocat_training_results_total", "Canonical autocat training outcomes", ["status"],
)
AUTOCAT_INFERENCE_RESULTS = Counter(
    "ai_autocat_inference_results_total", "Autocat inference outcomes", ["status"],
)
