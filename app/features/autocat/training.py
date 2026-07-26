from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
import unicodedata
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

from app.core.config import get_settings
from app.core.metrics import AUTOCAT_TRAINING_RESULTS
from app.features.autocat.bundle_store import (
    ALGORITHM_VERSION,
    BUNDLE_SCHEMA_VERSION,
    get_autocat_bundle_store,
    validate_bundle,
)
from app.features.autocat.policy import LABEL_POLICY_VERSION, evaluate_eligibility, load_training_dataset


logger = logging.getLogger(__name__)
PORTUGUESE_STOPWORDS = [
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e",
    "em", "na", "nas", "no", "nos", "o", "os", "para", "por", "um", "uma",
]


class CandidateRejectedError(RuntimeError):
    pass


def train_autocat(workspace_id: str) -> dict[str, Any]:
    store = get_autocat_bundle_store()
    with store.training_lock(workspace_id):
        dataset = load_training_dataset(workspace_id)
        eligibility = evaluate_eligibility(workspace_id, dataset)
        if not eligibility.eligible:
            AUTOCAT_TRAINING_RESULTS.labels("INSUFFICIENT_LABELED_HISTORY").inc()
            return {"status": "INSUFFICIENT_LABELED_HISTORY", "eligibility": eligibility.to_dict(), "activated": False}

        active_metadata = store.active_metadata(workspace_id)
        if active_metadata and active_metadata.get("datasetFingerprint") == eligibility.datasetFingerprint:
            AUTOCAT_TRAINING_RESULTS.labels("UNCHANGED_DATASET").inc()
            return {
                "status": "UNCHANGED_DATASET",
                "modelVersion": active_metadata.get("modelVersion"),
                "datasetFingerprint": eligibility.datasetFingerprint,
                "eligibility": eligibility.to_dict(),
                "activated": False,
            }

        previous_version = active_metadata.get("modelVersion") if active_metadata else None
        try:
            bundle = build_candidate_bundle(workspace_id, dataset, eligibility.to_dict())
            validate_bundle(bundle, expected_workspace_id=workspace_id)
            # A candidate is immutable and inspectable before the active pointer changes.
            store.persist_candidate(workspace_id, bundle)
            publication_reasons = publication_blocking_reasons(bundle, store.load_active(workspace_id) if active_metadata else None)
            if publication_reasons:
                AUTOCAT_TRAINING_RESULTS.labels("MODEL_REJECTED").inc()
                logger.warning(
                    "autocat candidate rejected",
                    extra={"workspace_id": workspace_id, "model_version": bundle["modelVersion"], "reasons": publication_reasons},
                )
                return {
                    "status": "MODEL_REJECTED",
                    "modelVersion": bundle["modelVersion"],
                    "previousModelVersion": previous_version,
                    "metrics": bundle["metrics"],
                    "blockingReasons": publication_reasons,
                    "eligibility": eligibility.to_dict(),
                    "activated": False,
                }
            store.activate(workspace_id, bundle["modelVersion"])
            AUTOCAT_TRAINING_RESULTS.labels("READY").inc()
            logger.info(
                "autocat model activated",
                extra={
                    "workspace_id": workspace_id,
                    "model_version": bundle["modelVersion"],
                    "dataset_fingerprint": bundle["datasetFingerprint"],
                    "previous_model_version": previous_version,
                },
            )
            return {
                "status": "READY",
                "modelVersion": bundle["modelVersion"],
                "previousModelVersion": previous_version,
                "datasetFingerprint": bundle["datasetFingerprint"],
                "metrics": bundle["metrics"],
                "eligibility": eligibility.to_dict(),
                "activated": True,
            }
        except Exception:
            AUTOCAT_TRAINING_RESULTS.labels("FAILED").inc()
            logger.exception(
                "autocat canonical training failed; active version preserved",
                extra={"workspace_id": workspace_id, "previous_model_version": previous_version},
            )
            raise


def run_autocat_training_job(workspace_id: str) -> dict[str, Any]:
    """RQ entrypoint. Every asynchronous autocat trigger terminates here."""
    from rq import get_current_job
    from app.core import training_queue

    job = get_current_job()
    job_id = job.id if job else training_queue.get_last_job_for_user(workspace_id)
    training_queue.persist_training_status(workspace_id, {
        "feature": "autocat", "jobId": job_id, "status": "running",
    })
    try:
        result = train_autocat(workspace_id)
        training_queue.persist_training_status(workspace_id, {
            "feature": "autocat", "jobId": job_id, "status": "finished", "result": result,
        })
        return result
    except Exception as error:
        training_queue.persist_training_status(workspace_id, {
            "feature": "autocat", "jobId": job_id, "status": "failed", "error": str(error),
        })
        raise
    finally:
        training_queue.release_autocat_lock(workspace_id)


def build_candidate_bundle(workspace_id: str, dataset, eligibility: dict[str, Any]) -> dict[str, Any]:
    texts = [_clean_text(value) for value in dataset["description"].tolist()]
    categories = dataset["categoryId"].astype(int).tolist()
    label_encoder = LabelEncoder()
    encoded = label_encoder.fit_transform(categories)
    metrics = _evaluate_candidate(texts, encoded, label_encoder)

    vectorizer = TfidfVectorizer(
        stop_words=PORTUGUESE_STOPWORDS,
        max_features=2000,
        min_df=1,
        ngram_range=(1, 2),
    )
    matrix = vectorizer.fit_transform(texts)
    classifier = LogisticRegression(max_iter=800, class_weight="balanced", solver="liblinear")
    classifier.fit(matrix, encoded)

    now = datetime.now(timezone.utc)
    fingerprint = eligibility["datasetFingerprint"]
    model_version = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{fingerprint[:12]}"
    labeled_times = dataset["labeledAt"]
    return {
        "bundleSchemaVersion": BUNDLE_SCHEMA_VERSION,
        "algorithmVersion": ALGORITHM_VERSION,
        "scope": "WORKSPACE",
        "workspaceId": str(workspace_id),
        "modelVersion": model_version,
        "vectorizer": vectorizer,
        "classifier": classifier,
        "labelEncoder": label_encoder,
        "classes": [int(value) for value in label_encoder.classes_.tolist()],
        "metrics": metrics,
        "trainingExamples": int(len(dataset)),
        "classDistribution": eligibility["classDistribution"],
        "labelPolicyVersion": LABEL_POLICY_VERSION,
        "datasetFingerprint": fingerprint,
        "trainedAt": now.isoformat(),
        "trainingPeriod": {
            "from": labeled_times.min().isoformat() if len(labeled_times) else None,
            "to": labeled_times.max().isoformat() if len(labeled_times) else None,
        },
        "compatibility": {
            "inferenceContract": "autocat-inference-v2",
            "featureSchema": "description-tfidf-v2",
            "sklearn": _sklearn_version(),
        },
    }


def publication_blocking_reasons(candidate: dict[str, Any], active: dict[str, Any] | None) -> list[str]:
    settings = get_settings()
    metrics = candidate["metrics"]
    reasons: list[str] = []
    if metrics["accuracy"] < settings.AUTOCAT_MIN_ACCURACY:
        reasons.append("ACCURACY_BELOW_THRESHOLD")
    if metrics["macroF1"] < settings.AUTOCAT_MIN_MACRO_F1:
        reasons.append("MACRO_F1_BELOW_THRESHOLD")
    if metrics["accuracy"] < metrics["majorityBaselineAccuracy"] + settings.AUTOCAT_MIN_BASELINE_LIFT:
        reasons.append("BELOW_MAJORITY_BASELINE")
    if active:
        active_f1 = float((active.get("metrics") or {}).get("macroF1", 0.0))
        if metrics["macroF1"] + settings.AUTOCAT_MAX_MACRO_F1_REGRESSION < active_f1:
            reasons.append("REGRESSION_VERSUS_ACTIVE_MODEL")
    return reasons


def _evaluate_candidate(texts: list[str], encoded: np.ndarray, label_encoder: LabelEncoder) -> dict[str, Any]:
    class_counts = np.bincount(encoded)
    folds = min(5, int(class_counts.min()))
    pipeline = Pipeline([
        ("vectorizer", TfidfVectorizer(stop_words=PORTUGUESE_STOPWORDS, max_features=2000, min_df=1, ngram_range=(1, 2))),
        ("classifier", LogisticRegression(max_iter=800, class_weight="balanced", solver="liblinear")),
    ])
    predictions = cross_val_predict(
        pipeline,
        texts,
        encoded,
        cv=StratifiedKFold(n_splits=folds, shuffle=True, random_state=42),
        method="predict",
    )
    precision, recall, f1, support = precision_recall_fscore_support(encoded, predictions, zero_division=0)
    labels = [int(value) for value in label_encoder.classes_.tolist()]
    per_category = {
        str(category): {
            "precision": round(float(precision[index]), 6),
            "recall": round(float(recall[index]), 6),
            "f1": round(float(f1[index]), 6),
            "support": int(support[index]),
        }
        for index, category in enumerate(labels)
    }
    majority_baseline = float(class_counts.max() / len(encoded))
    return {
        "evaluation": f"stratified-{folds}-fold-cross-validation",
        "accuracy": round(float(accuracy_score(encoded, predictions)), 6),
        "macroF1": round(float(f1_score(encoded, predictions, average="macro", zero_division=0)), 6),
        "majorityBaselineAccuracy": round(majority_baseline, 6),
        "coverage": 1.0,
        "perCategory": per_category,
        "confusionMatrix": confusion_matrix(encoded, predictions).astype(int).tolist(),
    }


def _clean_text(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"\d+", " <num> ", normalized.lower())
    normalized = re.sub(r"[^a-z\s<>]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or "<empty>"


def _sklearn_version() -> str:
    import sklearn

    return sklearn.__version__
