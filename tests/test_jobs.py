from __future__ import annotations

import pytest

from app.claude_cli import ClaudeError
from app.jobs import STATUS_DONE, STATUS_ERROR, JobBusy, JobStore


def test_inline_job_runs_and_records_result():
    store = JobStore(inline=True)
    job = store.submit("grade", lambda j: (j.set_progress("ai"), 42)[1])
    assert job.status == STATUS_DONE
    assert job.result == 42
    assert job.progress == {"stage": "ai"}
    assert job.to_dict()["label"] == "採点"
    assert store.get(job.id) is job


def test_job_error_keeps_detail():
    store = JobStore(inline=True)

    def fail(_job):
        raise ClaudeError("短い説明", detail="生の出力")

    job = store.submit("explain", fail)
    assert job.status == STATUS_ERROR
    assert job.error == "短い説明"
    assert job.error_detail == "生の出力"


def test_only_one_running_job():
    store = JobStore()
    import threading

    gate = threading.Event()
    job = store.submit("content", lambda _j: gate.wait(5))
    with pytest.raises(JobBusy):
        store.submit("grade", lambda _j: None)
    gate.set()
    for _ in range(100):
        if job.status == STATUS_DONE:
            break
        import time

        time.sleep(0.01)
    assert job.status == STATUS_DONE
    assert store.active() == []
