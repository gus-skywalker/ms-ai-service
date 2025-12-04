from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_training_status_requires_token():
    response = client.get("/internal/ai/user/u1/training-status")
    assert response.status_code == 401


def test_training_status_returns_job(monkeypatch):
    monkeypatch.setenv("AI_SERVICE_TOKEN", "token")
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_last_job_for_user", lambda uid: "job-1")
    monkeypatch.setattr(main_module, "get_job_status", lambda job_id: {"status": "finished"})

    response = client.get(
        "/internal/ai/user/u1/training-status",
        headers={"X-Service-Token": "token"},
    )
    assert response.status_code == 200
    assert response.json()["jobId"] == "job-1"
    assert response.json()["status"]["status"] == "finished"
