"""AI が判定した答えの保存。同じ問題に同じ答えが来たら、保存した判定を返して AI を呼ばない（docs/plan.md 5.4）。

学習の記録（SQLite）を入れるまでは、言語ごとに records/graded/<言語>.json に置く。

    {"<練習の種類>\\t<単語か文の id>\\t<正規化した答え>": {"expected": ..., "style": ..., "judgement": {...}}}

文の id は教材を作り直しても変わらないので、模範解答が変わっていたら保存した判定は使わない。
採点のプロンプトの版（GRADE_STYLE）が変わったときも使わない。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.grader import Judgement, Task
from app.prompts import GRADE_STYLE

log = logging.getLogger("langlang.graded")


class GradedStore:
    def __init__(self, root: Path):
        self._root = root
        self._lock = threading.Lock()

    def path(self, language: str) -> Path:
        return self._root / "records" / "graded" / f"{language}.json"

    def get(self, language: str, task: Task, normalized_answer: str) -> Judgement | None:
        with self._lock:
            entry = self._read(language).get(_key(task, normalized_answer))
        if not isinstance(entry, dict) or entry.get("expected") != task.expected or entry.get("style") != GRADE_STYLE:
            return None
        try:
            return Judgement.from_dict(entry["judgement"], source="cache")
        except (KeyError, TypeError):
            return None

    def put(self, language: str, task: Task, normalized_answer: str, judgement: Judgement) -> None:
        data = judgement.to_dict()
        del data["rating"], data["source"]
        with self._lock:
            entries = self._read(language)
            entries[_key(task, normalized_answer)] = {
                "expected": task.expected,
                "style": GRADE_STYLE,
                "graded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "judgement": data,
            }
            p = self.path(language)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(p)

    def _read(self, language: str) -> dict[str, Any]:
        p = self.path(language)
        if not p.exists():
            return {}
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("保存した判定が読めないので、ないものとして扱います: %s", p)
            return {}
        return raw if isinstance(raw, dict) else {}


def _key(task: Task, normalized_answer: str) -> str:
    return f"{task.type}\t{task.item_id}\t{normalized_answer}"
