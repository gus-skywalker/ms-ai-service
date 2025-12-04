import fakeredis
from app.core import training_queue


def test_locking_acquire_release(monkeypatch):
    fake = fakeredis.FakeRedis()
    monkeypatch.setattr(training_queue, '_connection', fake)

    # Acquire should succeed first time
    got = training_queue.acquire_lock('u1')
    assert got is True
    # Second acquire should fail
    got2 = training_queue.acquire_lock('u1')
    assert got2 is False
    # Release and acquire again
    training_queue.release_lock('u1')
    got3 = training_queue.acquire_lock('u1')
    assert got3 is True
    training_queue.release_lock('u1')

