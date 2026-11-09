"""苦手な単語（docs/plan.md 4.6）と、矢印ゲームの反応時間の基準（4.4）。どちらも学習の記録からその場で数える。

苦手は「今つまずいている語」に絞る（苦手枠で期限の前にも出すので、多すぎると復習が苦手で埋まるため）。
次のどれかに当てはまる単語を苦手とする:
- 矢印ゲームの面（意味・聞き取り・逆引き）の FSRS の難しさが 7 以上（1〜10）で、その面の直近の解答が不正解。
  難しさは正解を重ねてもなかなか下がらないので、直近の解答で今もつまずいているかを見る。綴りの面は、打ち間違いでも
  難しさが上がるので見ない
- 直近 10 回の解答の不正解率が 40% 以上。5 回以上答えてから見る（初めての単語を 1 回間違えただけで苦手にしないため）
- 同じ相手と、直近 CONFUSION_DAYS 日のうち 2 日以上取り違えた（取り違えは 1 日 1 組 1 回まで数える。同じ日に
  続けて選び直したものまで数えると、1 回のつまずきで苦手になるため）
- 矢印ゲームで正解したときの反応時間が、3 回続けて、その面の中央値の 2 倍以上

しきい値は、40 日の模擬（新出 15 語・7 文、15% 不正解）で、苦手が導入した語の 1 割前後になるように決めた（docs/design.md）。
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
CONFUSION_DAYS = 13
# 単語帳の「苦手を練習」で出す単語の数（理由の多い順）
PRACTICE_WORDS = 30
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
# 意味の誤りを返す面は、その練習で何を思い出したかで決める。韓国語を見て意味を答える練習は意味の面、
# 意味から韓国語を出す練習は逆引きの面、聞いて書く練習は聞き取りの面
MEANING_FACE_OF_PRACTICE = {
    "sentence_ko_to_ja": "meaning",
    "sentence_ja_to_ko": "reverse",
    "sentence_compose": "reverse",
    "sentence_cloze": "reverse",
    "sentence_dictation": "listen",
}


@dataclass
class Analysis:
    weak: dict[str, list[str]] = field(default_factory=dict)  # 単語 → 苦手の理由（REASONS のキー）
    partners: dict[str, dict[str, int]] = field(default_factory=dict)  # 単語 → {取り違えた相手: 取り違えた日数}
    medians: dict[str, float] = field(default_factory=dict)  # 面 → 正解時の反応時間の中央値（十分にたまった面だけ）

    def partners_of(self, word_id: str) -> list[str]:
        """取り違えた相手（多い順）。"""
        picked = self.partners.get(word_id, {})
        return sorted(picked, key=lambda p: -picked[p])

    def timing(self) -> dict[str, dict[str, float]]:
        """面ごとの速い・遅いの基準（秒）。中央値がまだない面は入れない（画面は設定の値を使う）。"""
        return {f: {"fast": round(m * FAST_FACTOR, 2), "slow": round(m * HARD_FACTOR, 2), "median": round(m, 2)} for f, m in self.medians.items()}


def analyze(
    cards: dict[tuple[str, str], CardRow],
    reviews: list[dict[str, Any]],
    confusions: dict[str, dict[str, int]],
    recent_confusions: dict[str, dict[str, int]] | None = None,
) -> Analysis:
    """cards は単語のカード、reviews は FSRS を動かした単語の解答（古い順）。confusions はこれまでに取り違えた日数、
    recent_confusions は直近 CONFUSION_DAYS 日に取り違えた日数（どちらも {正解の語: {選んだ語: 日数}}）。"""
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

    last_correct: dict[tuple[str, str], bool] = {}
    by_word: dict[str, list[dict[str, Any]]] = {}
    for r in reviews:
        by_word.setdefault(r["item_id"], []).append(r)
        last_correct[(r["item_id"], r["face"])] = r["correct"]
    for (word_id, face), card in cards.items():
        if face in ARROW_FACES and card.card.difficulty is not None and card.card.difficulty >= DIFFICULTY and not last_correct.get((word_id, face), True):
            mark(word_id, "difficulty")

    for word_id, rs in by_word.items():
        recent = rs[-RECENT:]
        if len(recent) >= RECENT_MIN and sum(not r["correct"] for r in recent) / len(recent) >= MISS_RATE:
            mark(word_id, "misses")
        timed = [r for r in rs if r["correct"] and r["face"] in medians and r["elapsed_sec"] is not None][-SLOW_STREAK:]
        if len(timed) == SLOW_STREAK and all(r["elapsed_sec"] >= SLOW_FACTOR * medians[r["face"]] for r in timed):
            mark(word_id, "slow")

    for word_id, picked in (recent_confusions or {}).items():
        if picked and max(picked.values()) >= CONFUSION_TIMES:
            mark(word_id, "confusion")
    return Analysis(weak, confusions, medians)


def face_for_issue(issue: dict[str, Any], practice: str) -> str | None:
    """文の誤りを返す単語の面。綴り・받침の誤りは綴りの面、意味の誤りは練習で決まる面（MEANING_FACE_OF_PRACTICE）。
    ほかは返さない。"""
    if issue.get("tag") in SPELL_TAGS:
        return "spell"
    if issue.get("tag") in MEANING_TAGS or issue.get("axis") == "meaning":
        return MEANING_FACE_OF_PRACTICE.get(practice)
    return None
