"""苦手な単語（docs/plan.md 4.6）と、矢印ゲームの反応時間の基準（4.4）。どちらも学習の記録からその場で数える。

苦手とするのは、次のどれかに当てはまる単語:
- いずれかの面の FSRS の難しさが 7 以上（1〜10）
- 直近 10 回の解答の不正解率が 40% 以上。5 回以上答えてから見る（初めての単語を 1 回間違えただけで苦手にしないため）
- 2 回以上取り違えた相手がいる
- 矢印ゲームで正解したときの反応時間が、3 回続けて、その面の中央値の 2 倍以上

解答は FSRS を動かしたもの（その日のその面の最初の 1 回）だけを数える。最後尾に回ったあとの正解は、
正解を見た直後なので数えない。
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from app.records import CardRow

ARROW_FACES = ("meaning", "listen", "reverse")
DIFFICULTY = 7.0
RECENT = 10
RECENT_MIN = 5
MISS_RATE = 0.4
CONFUSION_TIMES = 2
SLOW_FACTOR = 2.0
SLOW_STREAK = 3
# 自分の中央値を基準にするのに要る、その面の正解の数
MEDIAN_MIN = 30
FAST_FACTOR = 0.7
HARD_FACTOR = 1.5

REASONS = {"difficulty": "難しさが高い", "misses": "間違いが多い", "confusion": "取り違えが多い", "slow": "反応が遅い"}

# 文の誤りを単語のどの面に返すか（docs/plan.md 4.5）。助詞・活用など文法の誤りは単語には返さない
SPELL_TAGS = {"綴り", "받침"}
MEANING_TAGS = {"語彙の選択", "訳抜け"}


@dataclass
class Analysis:
    weak: dict[str, list[str]] = field(default_factory=dict)  # 単語 → 苦手の理由（REASONS のキー）
    partners: dict[str, dict[str, int]] = field(default_factory=dict)  # 単語 → {取り違えた相手: 回数}
    medians: dict[str, float] = field(default_factory=dict)  # 面 → 正解時の反応時間の中央値（十分にたまった面だけ）

    def partners_of(self, word_id: str) -> list[str]:
        """取り違えた相手（多い順）。"""
        picked = self.partners.get(word_id, {})
        return sorted(picked, key=lambda p: -picked[p])

    def timing(self) -> dict[str, dict[str, float]]:
        """面ごとの速い・遅いの基準（秒）。中央値がまだない面は入れない（画面は設定の値を使う）。"""
        return {f: {"fast": round(m * FAST_FACTOR, 2), "slow": round(m * HARD_FACTOR, 2), "median": round(m, 2)} for f, m in self.medians.items()}


def analyze(cards: dict[tuple[str, str], CardRow], reviews: list[dict[str, Any]], confusions: dict[str, dict[str, int]]) -> Analysis:
    """cards は単語のカード、reviews は FSRS を動かした単語の解答（古い順）、confusions は取り違えの回数。"""
    times: dict[str, list[float]] = {}
    for r in reviews:
        if r["face"] in ARROW_FACES and r["correct"] and r["elapsed_sec"] is not None:
            times.setdefault(r["face"], []).append(r["elapsed_sec"])
    medians = {face: statistics.median(ts) for face, ts in times.items() if len(ts) >= MEDIAN_MIN}

    weak: dict[str, list[str]] = {}

    def mark(word_id: str, reason: str) -> None:
        reasons = weak.setdefault(word_id, [])
        if reason not in reasons:
            reasons.append(reason)

    for (word_id, _), card in cards.items():
        if card.card.difficulty is not None and card.card.difficulty >= DIFFICULTY:
            mark(word_id, "difficulty")

    by_word: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        by_word.setdefault(r["item_id"], []).append(r)
    for word_id, rs in by_word.items():
        recent = rs[-RECENT:]
        if len(recent) >= RECENT_MIN and sum(not r["correct"] for r in recent) / len(recent) >= MISS_RATE:
            mark(word_id, "misses")
        timed = [r for r in rs if r["correct"] and r["face"] in medians and r["elapsed_sec"] is not None][-SLOW_STREAK:]
        if len(timed) == SLOW_STREAK and all(r["elapsed_sec"] >= SLOW_FACTOR * medians[r["face"]] for r in timed):
            mark(word_id, "slow")

    for word_id, picked in confusions.items():
        if picked and max(picked.values()) >= CONFUSION_TIMES:
            mark(word_id, "confusion")
    return Analysis(weak, confusions, medians)


def face_for_issue(issue: dict[str, Any]) -> str | None:
    """文の誤りを返す単語の面。綴り・받침の誤りは綴りの面、意味の取り違えは意味の面。ほかは返さない。"""
    if issue.get("tag") in SPELL_TAGS:
        return "spell"
    if issue.get("tag") in MEANING_TAGS or issue.get("axis") == "meaning":
        return "meaning"
    return None
