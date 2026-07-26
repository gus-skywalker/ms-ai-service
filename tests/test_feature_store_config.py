from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from app.core.config import Settings


def test_feature_store_uses_local_default(monkeypatch):
    monkeypatch.delenv("AI_FEATURE_STORE_DIR", raising=False)
    monkeypatch.delenv("AI_MODEL_DIR", raising=False)
    settings = Settings(_env_file=None)

    assert settings.AI_FEATURE_STORE_DIR == "storage/user_data"
    assert settings.AI_MODEL_DIR == "./models"


def test_feature_store_resolves_configured_absolute_path(tmp_path):
    configured_path = tmp_path / "workspace-data"
    environment = os.environ.copy()
    environment["AI_FEATURE_STORE_DIR"] = str(configured_path)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.feature_store import STORAGE_PATH; print(STORAGE_PATH)",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == str(configured_path)


def test_railway_manifest_and_supervisor_are_release_safe():
    import json

    repository_root = Path(__file__).parents[1]
    manifest = json.loads((repository_root / "railway.json").read_text(encoding="utf-8"))
    script = repository_root / "scripts" / "start-railway.sh"

    assert set(manifest) == {"$schema", "build", "deploy"}
    assert manifest["build"] == {"builder": "RAILPACK"}
    assert manifest["deploy"] == {
        "startCommand": "bash scripts/start-railway.sh",
        "healthcheckPath": "/internal/ai/health",
        "healthcheckTimeout": 120,
        "restartPolicyType": "ON_FAILURE",
        "restartPolicyMaxRetries": 10,
    }
    assert os.access(script, os.X_OK)
    subprocess.run(["bash", "-n", script], check=True)
    script_contents = script.read_text(encoding="utf-8")
    assert "python -m app.serve &" in script_contents
    assert "uvicorn app.main:app" not in script_contents
