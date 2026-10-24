"""AI の呼び出しをまとめて回す。

- 1 つ終わるごとに保存する（save）。途中で止まっても、再実行すれば済んだところを飛ばして続きから進む
- 利用枠の上限・ログイン切れ・モデルの設定違いは、何度呼んでも失敗するので、残りを取り消して StopRun を投げる
- そのほかの失敗（タイムアウト、出力が機械の確認を通らない）は 1 回だけやり直し、それでもだめなら失敗として数えて次へ進む
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from app.claude_cli import STOPPING_KINDS, ClaudeError

log = logging.getLogger("langlang.build")

T = TypeVar("T")
ATTEMPTS = 2


class StopRun(Exception):
    """続けても失敗するので止めた。時間をおくか設定を直してから再実行すれば、続きから進む。"""


class BadOutput(Exception):
    """AI の出力が機械の確認を通らない（聞いたキーが足りない など）。やり直す。"""


@dataclass
class Outcome:
    done: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)  # (どれか, なぜか)

    def summary(self) -> str:
        text = f"{self.done} 件済み"
        if self.failed:
            text += f"、{len(self.failed)} 件失敗（再実行するとやり直します）"
        return text


def run(
    step: str,
    tasks: list[T],
    work: Callable[[T], Any],
    save: Callable[[T, Any], None],
    *,
    label: Callable[[T], str],
    parallel: int = 1,
) -> Outcome:
    """tasks を最大 parallel 個ずつ並列に work し、終わった順に save する（save はこのスレッドで順に呼ぶ）。"""
    outcome = Outcome()
    if not tasks:
        return outcome
    stop = threading.Event()
    stopped: list[str] = []
    started = time.monotonic()
    log.info("[%s] %d 件を始めます（並列 %d）", step, len(tasks), parallel)

    def attempt(task: T) -> Any:
        last: Exception | None = None
        for i in range(ATTEMPTS):
            if stop.is_set():
                raise StopRun(stopped[0] if stopped else "止めました")
            try:
                return work(task)
            except ClaudeError as exc:
                if exc.kind in STOPPING_KINDS:
                    stop.set()
                    stopped.append(str(exc))
                    raise StopRun(str(exc)) from exc
                last = exc
            except BadOutput as exc:
                last = exc
            log.warning("[%s] %s: %s（%s）", step, label(task), last, "やり直します" if i + 1 < ATTEMPTS else "あきらめます")
        assert last is not None
        raise last

    with ThreadPoolExecutor(max_workers=max(1, parallel), thread_name_prefix=f"build-{step}") as pool:
        pending: dict[Future, T] = {pool.submit(attempt, task): task for task in tasks}
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                task = pending.pop(future)
                if future.cancelled():
                    continue
                try:
                    result = future.result()
                except StopRun:
                    for other in pending:
                        other.cancel()
                    continue
                except Exception as exc:  # noqa: BLE001 - 1 件の失敗で全体を止めない
                    outcome.failed.append((label(task), str(exc) or exc.__class__.__name__))
                    log.error("[%s] %s: 失敗: %s", step, label(task), exc)
                    continue
                save(task, result)
                outcome.done += 1
                log.info(
                    "[%s] %s 済み（%d/%d、%.0f 秒経過）",
                    step, label(task), outcome.done + len(outcome.failed), len(tasks), time.monotonic() - started,
                )
    if stopped:
        raise StopRun(stopped[0])
    return outcome
