"""AI が判定した答えの保存。同じ問題に同じ答えが来たら、保存した判定を返して AI を呼ばない（docs/plan.md 5.4）。

学習の記録（records/langlang.db の graded_answers）に、練習の種類・単語か文の id・正規化した答えごとに置く。
文の id は教材を作り直しても変わらないので、模範解答が変わっていたら保存した判定は使わない。
採点のプロンプトの版（GRADE_STYLE）が変わったときも使わない。
"""

from __future__ import annotations

from app.grader import Judgement, Task
from app.prompts import GRADE_STYLE
from app.records import Records


class GradedStore:
    def __init__(self, records: Records):
        self._records = records

    def get(self, language: str, task: Task, normalized_answer: str) -> Judgement | None:
        entry = self._records.graded(language, task.type, task.item_id, normalized_answer)
        if entry is None or entry["expected"] != task.expected or entry["style"] != GRADE_STYLE:
            return None
        try:
            return Judgement.from_dict(entry["judgement"], source="cache")
        except (KeyError, TypeError):
            return None

    def put(self, language: str, task: Task, normalized_answer: str, judgement: Judgement) -> None:
        data = judgement.to_dict()
        del data["rating"], data["source"]
        self._records.save_graded(language, task.type, task.item_id, normalized_answer, expected=task.expected, style=GRADE_STYLE, judgement=data)
