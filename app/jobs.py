"""時間のかかる処理（AI 採点、解説、教材づくり）をバックグラウンドのスレッドで実行し、状態を問い合わせられるようにする（suburi から移植）。

ローカルの 1 人用なので、同時に動くジョブは種類（採点・解説・教材づくり）ごとに 1 つだけ。同じ種類のジョブの実行中に
次の要求が来たら JobBusy を投げる。種類が違えば並べて動かす（採点を待つ間に解説を押せるように）。
ジョブはメモリ上にだけ持つ（サーバーを再起動すると消える。結果は保存先に書かれているので困らない）。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

log = logging.getLogger("langlang.jobs")

MAX_KEPT = 50
KIND_LABELS = {"grade": "採点", "explain": "解説", "content": "教材づくり"}

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class JobBusy(Exception):
    """別のジョブが実行中。"""


@dataclass
class Job:
    id: str
    kind: str
    created_at: str
    status: str = STATUS_RUNNING
    finished_at: str | None = None
    result: Any = None
    error: str | None = None  # 画面に出す短い文
    error_detail: str | None = None  # 生の出力など（画面では折りたたむ）
    progress: dict[str, Any] | None = None
    _started: float = field(default_factory=time.monotonic, repr=False, compare=False)
    _finished: float | None = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def duration_sec(self) -> float:
        end = self._finished if self._finished is not None else time.monotonic()
        return round(end - self._started, 1)

    def set_progress(self, stage: str, **extra: Any) -> None:
        self.progress = {"stage": stage, **extra}
        log.info("%s %s: 段階 %s（%.1f 秒経過）", self.label, self.id, stage, self.duration_sec)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "duration_sec": self.duration_sec,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "error_detail": self.error_detail,
        }


JobFn = Callable[[Job], Any]


class JobStore:
    def __init__(self, inline: bool = False):
        """inline=True のときはスレッドを使わず submit の中で実行し終える（テスト用）。"""
        self._inline = inline
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, fn: JobFn) -> Job:
        with self._lock:
            self._ensure_idle_locked(kind)
            job = Job(id=uuid.uuid4().hex[:12], kind=kind, created_at=now_iso())
            self._jobs[job.id] = job
            self._prune_locked()
        log.info("%s %s: 開始", job.label, job.id)
        if self._inline:
            self._run(job, fn)
        else:
            threading.Thread(target=self._run, args=(job, fn), name=f"langlang-job-{job.id}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active(self) -> list[Job]:
        return [job for job in self._jobs.values() if job.status == STATUS_RUNNING]

    def _ensure_idle_locked(self, kind: str) -> None:
        running = [job for job in self._jobs.values() if job.status == STATUS_RUNNING and job.kind == kind]
        if running:
            raise JobBusy(f"処理中です（{running[0].label}）。終わるまで待ってください")

    def _prune_locked(self) -> None:
        finished = [job for job in self._jobs.values() if job.status != STATUS_RUNNING]
        excess = len(self._jobs) - MAX_KEPT
        for job in finished[:excess] if excess > 0 else []:
            del self._jobs[job.id]

    @staticmethod
    def _run(job: Job, fn: JobFn) -> None:
        try:
            job.result = fn(job)
            job.status = STATUS_DONE
            log.info("%s %s: 完了（%.1f 秒）", job.label, job.id, time.monotonic() - job._started)
        except Exception as exc:  # noqa: BLE001 - ジョブの失敗は状態として返す
            job.error = str(exc) or exc.__class__.__name__
            job.error_detail = getattr(exc, "detail", None)
            job.status = STATUS_ERROR
            log.error("%s %s: 失敗（%.1f 秒）: %s", job.label, job.id, time.monotonic() - job._started, job.error)
        finally:
            job._finished = time.monotonic()
            job.finished_at = now_iso()
