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

