from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator

import fcntl
import joblib

from app.core.config import get_settings


BUNDLE_SCHEMA_VERSION = 1
ALGORITHM_VERSION = "autocat-tfidf-logreg-v2"
MODEL_FAMILY_VERSION = "autocat_v2"


class IncompatibleBundleError(ValueError):
    pass


class AutocatBundleStore:
    def workspace_root(self, workspace_id: str) -> Path:
        return Path(get_settings().AI_MODEL_DIR) / "autocat" / MODEL_FAMILY_VERSION / str(workspace_id)

    def versions_root(self, workspace_id: str) -> Path:
        return self.workspace_root(workspace_id) / "versions"

    @contextmanager
    def training_lock(self, workspace_id: str) -> Iterator[None]:
        root = self.workspace_root(workspace_id)
        root.mkdir(parents=True, exist_ok=True)
        with (root / ".training.lock").open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def persist_candidate(self, workspace_id: str, bundle: dict[str, Any]) -> str:
        validate_bundle(bundle, expected_workspace_id=workspace_id)
        version = str(bundle["modelVersion"])
        versions = self.versions_root(workspace_id)
        versions.mkdir(parents=True, exist_ok=True)
        final_dir = versions / version
        if final_dir.exists():
            existing = self.load_version(workspace_id, version)
            validate_bundle(existing, expected_workspace_id=workspace_id)
            return version

        temp_dir = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=versions))
        try:
            joblib.dump(bundle, temp_dir / "bundle.joblib")
            (temp_dir / "manifest.json").write_text(
                json.dumps(public_metadata(bundle), sort_keys=True, indent=2, default=str),
                encoding="utf-8",
            )
            reloaded = joblib.load(temp_dir / "bundle.joblib")
            validate_bundle(reloaded, expected_workspace_id=workspace_id)
            os.replace(temp_dir, final_dir)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        return version

    def activate(self, workspace_id: str, model_version: str) -> dict[str, Any]:
        bundle = self.load_version(workspace_id, model_version)
        validate_bundle(bundle, expected_workspace_id=workspace_id)
        root = self.workspace_root(workspace_id)
        pointer = root / "active.json"
        root.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".active-", suffix=".json", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "modelVersion": model_version,
                        "datasetFingerprint": bundle["datasetFingerprint"],
                        "activatedAt": datetime.now(timezone.utc).isoformat(),
                    },
                    handle,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, pointer)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        return bundle

    def active_metadata(self, workspace_id: str) -> dict[str, Any] | None:
        pointer = self.workspace_root(workspace_id) / "active.json"
        if not pointer.exists():
            return None
        try:
            metadata = json.loads(pointer.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as error:
            raise IncompatibleBundleError("invalid active model pointer") from error
        if not isinstance(metadata, dict) or not metadata.get("modelVersion"):
            raise IncompatibleBundleError("active model pointer missing modelVersion")
        return metadata

    def load_active(self, workspace_id: str) -> dict[str, Any] | None:
        metadata = self.active_metadata(workspace_id)
        if not metadata or not metadata.get("modelVersion"):
            return None
        bundle = self.load_version(workspace_id, metadata["modelVersion"])
        validate_bundle(bundle, expected_workspace_id=workspace_id)
        return bundle

    def load_version(self, workspace_id: str, model_version: str) -> dict[str, Any]:
        path = self.versions_root(workspace_id) / str(model_version) / "bundle.joblib"
        if not path.exists():
            raise FileNotFoundError(f"Autocat model version not found: {model_version}")
        return joblib.load(path)

    def list_versions(self, workspace_id: str) -> list[dict[str, Any]]:
        active = self.active_metadata(workspace_id) or {}
        versions = self.versions_root(workspace_id)
        result: list[dict[str, Any]] = []
        if versions.exists():
            for manifest in sorted(versions.glob("*/manifest.json"), reverse=True):
                try:
                    item = json.loads(manifest.read_text(encoding="utf-8"))
                    item["active"] = item.get("modelVersion") == active.get("modelVersion")
                    result.append(item)
                except (OSError, ValueError, TypeError):
                    continue
        return result

    def legacy_artifact_present(self, workspace_id: str) -> bool:
        root = Path(get_settings().AI_MODEL_DIR) / "autocat" / "autocat_v1" / str(workspace_id)
        return (root / "model.joblib").exists()


def validate_bundle(bundle: Any, expected_workspace_id: str | None = None) -> None:
    if not isinstance(bundle, dict):
        raise IncompatibleBundleError("bundle must be an object")
    required = {
        "bundleSchemaVersion", "algorithmVersion", "scope", "workspaceId", "modelVersion",
        "vectorizer", "classifier", "labelEncoder", "classes", "metrics", "trainingExamples",
        "classDistribution", "labelPolicyVersion", "datasetFingerprint", "trainedAt",
        "trainingPeriod", "compatibility",
    }
    missing = sorted(required - set(bundle))
    if missing:
        raise IncompatibleBundleError(f"bundle missing fields: {','.join(missing)}")
    if bundle["bundleSchemaVersion"] != BUNDLE_SCHEMA_VERSION:
        raise IncompatibleBundleError("unsupported bundleSchemaVersion")
    if bundle["algorithmVersion"] != ALGORITHM_VERSION:
        raise IncompatibleBundleError("unsupported algorithmVersion")
    if bundle["scope"] != "WORKSPACE":
        raise IncompatibleBundleError("unsupported model scope")
    if expected_workspace_id is not None and str(bundle["workspaceId"]) != str(expected_workspace_id):
        raise IncompatibleBundleError("bundle workspace mismatch")
    if not hasattr(bundle["vectorizer"], "transform"):
        raise IncompatibleBundleError("invalid vectorizer")
    if not hasattr(bundle["classifier"], "predict") or not hasattr(bundle["classifier"], "predict_proba"):
        raise IncompatibleBundleError("invalid classifier")
    if not hasattr(bundle["labelEncoder"], "inverse_transform"):
        raise IncompatibleBundleError("invalid label encoder")
    if not bundle["classes"]:
        raise IncompatibleBundleError("bundle classes are empty")
    compatibility = bundle.get("compatibility") or {}
    if compatibility.get("inferenceContract") != "autocat-inference-v2":
        raise IncompatibleBundleError("incompatible inference contract")
    if compatibility.get("featureSchema") != "description-tfidf-v2":
        raise IncompatibleBundleError("incompatible feature schema")
    import sklearn

    trained_sklearn = str(compatibility.get("sklearn") or "")
    if trained_sklearn.split(".")[:2] != sklearn.__version__.split(".")[:2]:
        raise IncompatibleBundleError("incompatible sklearn runtime")


def public_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "bundleSchemaVersion": bundle["bundleSchemaVersion"],
        "algorithmVersion": bundle["algorithmVersion"],
        "scope": bundle["scope"],
        "workspaceId": bundle["workspaceId"],
        "modelVersion": bundle["modelVersion"],
        "classes": bundle["classes"],
        "metrics": bundle["metrics"],
        "trainingExamples": bundle["trainingExamples"],
        "classDistribution": bundle["classDistribution"],
        "labelPolicyVersion": bundle["labelPolicyVersion"],
        "datasetFingerprint": bundle["datasetFingerprint"],
        "trainedAt": bundle["trainedAt"],
        "trainingPeriod": bundle["trainingPeriod"],
        "compatibility": bundle["compatibility"],
    }


_store = AutocatBundleStore()


def get_autocat_bundle_store() -> AutocatBundleStore:
    return _store
