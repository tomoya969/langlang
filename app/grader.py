"""採点。機械で確かめられるものを先に確かめ、決まらない答えはすべて AI に判定させる（docs/plan.md 5.4）。

機械で決めるのは「正解」と「正解（注意つき）」だけ。機械では打ち間違いと意味が変わる誤り（있어요 と 없어요）を
見分けられないので、不正解は AI だけが決める。

韓→日訳の答えは学習者の言葉（日本語）なので、言語パックの正規化ではなく normalize_ja で比べる。
訳は言い回しの幅が広く、機械で決まるのは模範訳か許容訳との一致だけ。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from app import prompts
from app.langs.base import LanguagePack

VERDICT_CORRECT = "correct"
VERDICT_NOTES = "correct_with_notes"
VERDICT_INCORRECT = "incorrect"

# 判定と FSRS の評価の対応（docs/plan.md 5.1）
RATING_OF_VERDICT = {VERDICT_CORRECT: "good", VERDICT_NOTES: "hard", VERDICT_INCORRECT: "again"}

AskFn = Callable[[str, dict], dict[str, Any]]


@dataclass(frozen=True)
class Task:
    """採点する問題。type は練習の種類、item_id は単語か文の id。context は AI に見せる問題の中身（prompts.build_grade_prompt）。"""

    type: str
    item_id: str
    expected: str
    variants: tuple[str, ...] = ()
    context: dict[str, Any] = field(default_factory=dict)
    word_ids: tuple[str, ...] = ()
    native: bool = False  # 答えが学習者の言葉（日本語）か。韓→日訳

    def normalize(self, pack: LanguagePack, text: str) -> str:
        return normalize_ja(text) if self.native else pack.normalize(text)


@dataclass
class Judgement:
    verdict: str
    source: str  # "exact" / "variant" / "spacing" / "pronunciation" / "synonym"（機械）、"ai" / "cache"（AI）
    issues: list[dict[str, Any]] = field(default_factory=list)
    corrected: str | None = None
    comment_ja: str = ""
    diff: list[dict[str, Any]] | None = None  # 直した答えとの文字単位の差分
    # 綴りの面で、読み上げた語とは違う正しい語を書いた（正解と表示するが、読み上げた語の綴りの記録には使わない）
    other_word: bool = False

    @property
    def rating(self) -> str:
        return RATING_OF_VERDICT[self.verdict]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "rating": self.rating,
            "source": self.source,
            "issues": self.issues,
            "corrected": self.corrected,
            "comment_ja": self.comment_ja,
            "diff": self.diff,
            "other_word": self.other_word,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], source: str) -> Judgement:
        return cls(
            verdict=data["verdict"],
            source=source,
            issues=list(data.get("issues") or []),
            corrected=data.get("corrected"),
            comment_ja=data.get("comment_ja") or "",
            diff=data.get("diff"),
            other_word=bool(data.get("other_word")),
        )


def normalize_ja(text: str) -> str:
    """日本語の訳の正規化。全角と半角をそろえ、空白と記号（句読点・かっこ・？！など）を除く。"""
    return re.sub(r"[\s、。，．,.!?「」『』()（）・…]", "", unicodedata.normalize("NFKC", text))


def judge_task(pack: LanguagePack, task: Task, answer: str) -> Judgement | None:
    """機械で決まる判定。決まらなければ None。"""
    if task.native:
        norm = normalize_ja(answer)
        candidates = [normalize_ja(task.expected)] + [normalize_ja(v) for v in task.variants]
        if norm in candidates:
            return Judgement(VERDICT_CORRECT, "exact" if norm == candidates[0] else "variant", corrected=task.expected)
        return None
    return judge_machine(pack, answer, task.expected, task.variants)


def judge_machine(pack: LanguagePack, answer: str, expected: str, variants: tuple[str, ...] | list[str] = ()) -> Judgement | None:
    """模範解答か許容例に一致すれば正解。空白の位置だけ、または綴りだけが違って発音が同じなら正解（注意つき）。
    決まらなければ None（AI に判定させる）。"""
    norm = pack.normalize(answer)
    candidates = [pack.normalize(expected)] + [pack.normalize(v) for v in variants]
    if norm in candidates:
        return Judgement(VERDICT_CORRECT, "exact" if norm == candidates[0] else "variant", corrected=expected)
    squeezed = norm.replace(" ", "")
    for c in candidates:
        if squeezed == c.replace(" ", ""):
            return Judgement(
                VERDICT_NOTES,
                "spacing",
                issues=[{"axis": "orthography", "tag": pack.spacing_tag or "spacing", "span": answer.strip(), "note": "分かち書きの位置が違います", "suggestion": c}],
                corrected=expected,
                comment_ja="意味も綴りも合っています。分かち書きだけ見直しましょう。",
            )
    if pack.pronounce is not None:
        sound = pack.pronounce(norm)
        for c in candidates:
            if sound == pack.pronounce(c):
                return Judgement(
                    VERDICT_NOTES,
                    "pronunciation",
                    issues=[{"axis": "orthography", "tag": pack.spelling_tag or "spelling", "span": answer.strip(), "note": "発音は同じですが、綴りが違います", "suggestion": c}],
                    corrected=c,
                    comment_ja="聞こえる音は合っています。綴りを見直しましょう。",
                    diff=char_diff(norm, c),
                )
    return None


def judge_ai(pack: LanguagePack, task: Task, answer: str, ask: AskFn) -> Judgement:
    """機械で決まらなかった答えを AI に判定させる。"""
    prompt = prompts.build_grade_prompt(task.type, task.context, answer.strip())
    raw = ask(prompt, prompts.grade_schema(task.type))
    verdict = raw["verdict"]
    issues = [_clean_issue(i, task.word_ids) for i in raw.get("issues") or []]
    # 直すところを挙げたのに「正解」と返すことがある。注意があるなら注意つきにそろえる
    if verdict == VERDICT_CORRECT and issues:
        verdict = VERDICT_NOTES
    corrected = (raw.get("corrected") or "").strip() or None
    norm = task.normalize(pack, answer)
    if corrected is not None and task.normalize(pack, corrected) == task.normalize(pack, task.expected):
        corrected = task.expected
    diff = None
    if verdict != VERDICT_CORRECT and corrected is not None and task.normalize(pack, corrected) != norm:
        # 差分は見せるための文字の並びなので、記号を除かない形で比べる
        diff = char_diff(pack.normalize(answer), pack.normalize(corrected))
    other_word = bool(raw.get("other_word")) and verdict != VERDICT_INCORRECT
    return Judgement(verdict, "ai", issues=issues, corrected=corrected, comment_ja=(raw.get("comment_ja") or "").strip(), diff=diff, other_word=other_word)


def _clean_issue(issue: dict[str, Any], word_ids: tuple[str, ...]) -> dict[str, Any]:
    word_id = issue.get("word_id")
    return {
        "axis": issue["axis"],
        "tag": issue["tag"],
        "span": issue.get("span", ""),
        "note": issue.get("note", ""),
        "suggestion": issue.get("suggestion") or None,
        "word_id": word_id if word_id in word_ids else None,
    }


def char_diff(answer: str, expected: str) -> list[dict[str, Any]]:
    """文字単位の差分（LCS）。画面で「どこが違うか」を示す。字母への分解は画面側（言語パック）が行う。"""
    a, b = list(answer), list(expected)
    n, m = len(a), len(b)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            table[i][j] = table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
    out: list[dict[str, Any]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            _push(out, "same", a[i])
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            _push(out, "extra", a[i])
            i += 1
        else:
            _push(out, "missing", b[j])
            j += 1
    for ch in a[i:]:
        _push(out, "extra", ch)
    for ch in b[j:]:
        _push(out, "missing", ch)
    return out


def _push(out: list[dict[str, Any]], kind: str, ch: str) -> None:
    if out and out[-1]["kind"] == kind:
        out[-1]["text"] += ch
    else:
        out.append({"kind": kind, "text": ch})
