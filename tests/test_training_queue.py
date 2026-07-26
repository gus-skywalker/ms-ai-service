import fakeredis
from rq import Queue

from app.core import training_queue


def test_enqueue_training_job(monkeypatch):
    fake_conn = fakeredis.FakeRedis()
    queue = Queue(training_queue.QUEUE_NAME, connection=fake_conn)

    monkeypatch.setattr(training_queue, "_connection", fake_conn)
    monkeypatch.setattr(training_queue, "queue", queue)

    job_id = training_queue.enqueue_training_job("user-1")

    assert job_id is not None
    assert fake_conn.get(training_queue._LAST_JOB_KEY.format(user_id="user-1"))


def _canonical_queue(monkeypatch):
    fake_conn = fakeredis.FakeRedis()
    monkeypatch.setattr(training_queue, "_connection", fake_conn)
    monkeypatch.setattr(training_queue, "queue", Queue(training_queue.QUEUE_NAME, connection=fake_conn))
    monkeypatch.setattr(training_queue, "persist_training_status", lambda *_args: None)
    return fake_conn


def test_autocat_queue_deduplicates_same_fingerprint(monkeypatch):
    _canonical_queue(monkeypatch)
    first = training_queue.enqueue_autocat_training_job("workspace-1", "fingerprint-1")
    second = training_queue.enqueue_autocat_training_job("workspace-1", "fingerprint-1")
    assert first[2] == "QUEUED"
    assert second == (None, False, "UNCHANGED_DATASET")


def test_autocat_queue_enforces_cooldown_for_changed_data(monkeypatch):
    _canonical_queue(monkeypatch)
    training_queue.enqueue_autocat_training_job("workspace-2", "fingerprint-1")
    second = training_queue.enqueue_autocat_training_job("workspace-2", "fingerprint-2")
    assert second == (None, False, "COOLDOWN")


def test_autocat_queue_reports_lock_contention(monkeypatch):
    connection = _canonical_queue(monkeypatch)
    connection.set(training_queue._AUTOCAT_LOCK_KEY.format(workspace_id="workspace-3"), "running")
    result = training_queue.enqueue_autocat_training_job("workspace-3", "fingerprint-1")
    assert result == (None, True, "ALREADY_RUNNING")
