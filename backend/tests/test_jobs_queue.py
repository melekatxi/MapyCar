import fakeredis

from app.jobs.queue import JobQueue


def test_job_lifecycle_queued_running_succeeded() -> None:
    client = fakeredis.FakeStrictRedis()
    queue = JobQueue(client)
    calls = []

    job = queue.enqueue(queue="imports", payload={"batch_id": "abc"})
    assert queue.get_status(job.id) == "queued"

    result = queue.run_once(queue="imports", handler=lambda payload: calls.append(payload))

    assert result is not None
    assert result.status == "succeeded"
    assert queue.get_status(job.id) == "succeeded"
    assert calls == [{"batch_id": "abc"}]


def test_zoning_queue_is_registered() -> None:
    client = fakeredis.FakeStrictRedis()
    queue = JobQueue(client)
    job = queue.enqueue(queue="zoning", payload={"proposal_id": "abc"})
    assert queue.get_status(job.id) == "queued"


def test_planning_queue_is_registered() -> None:
    client = fakeredis.FakeStrictRedis()
    queue = JobQueue(client)
    job = queue.enqueue(queue="planning", payload={"plan_id": "abc"})
    assert queue.get_status(job.id) == "queued"


def test_optimization_queue_is_registered() -> None:
    client = fakeredis.FakeStrictRedis()
    queue = JobQueue(client)
    job = queue.enqueue(queue="optimization", payload={"route_id": "abc"})
    assert queue.get_status(job.id) == "queued"


def test_job_retries_with_backoff_before_failing() -> None:
    client = fakeredis.FakeStrictRedis()
    queue = JobQueue(client, max_attempts=2, base_backoff_seconds=0.0)

    def always_fails(_payload: dict) -> None:
        raise RuntimeError("boom")

    job = queue.enqueue(queue="geocoding", payload={})

    first = queue.run_once(queue="geocoding", handler=always_fails)
    assert first.status == "queued"  # reintento 1/2

    second = queue.run_once(queue="geocoding", handler=always_fails)
    assert second.status == "failed"
    assert queue.get_status(job.id) == "failed"
