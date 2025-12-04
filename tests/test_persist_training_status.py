import json
from pathlib import Path
from app.core import training_queue


def test_persist_training_status(tmp_path, monkeypatch):
    user_id = "u-test"
    # monkeypatch path_for_user to use tmp_path
    def fake_path_for_user(u, filename):
        return str(tmp_path / u / filename)

    import app.core.feature_store as fs
    monkeypatch.setattr(fs, "path_for_user", fake_path_for_user)

    status = {"jobId": "job-1", "status": "queued"}
    training_queue.persist_training_status(user_id, status)
    p = Path(tmp_path / user_id / "training_status.json")
    assert p.exists()
    data = json.loads(p.read_text())
    assert data["jobId"] == "job-1"
    assert data["status"] == "queued"
