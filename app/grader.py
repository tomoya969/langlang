"""採点。機械で確かめられるものを先に確かめ、決まらないときだけ AI に判定させる（docs/plan.md 5.4）。

このモジュールの機械採点は、答えを正規化して模範解答・許容例と比べるところまで。
AI 採点（翻訳・作文）と判定の保存は M5 で足す。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.langs.base import LanguagePack

VERDICT_CORRECT = "correct"
VERDICT_NOTES = "correct_with_notes"
VERDICT_INCORRECT = "incorrect"

# 判定と FSRS の評価の対応（docs/plan.md 5.1）
RATING_OF_VERDICT = {VERDICT_CORRECT: "good", VERDICT_NOTES: "hard", VERDICT_INCORRECT: "again"}


@dataclass
class Judgement:
    verdict: str
    source: str  # "exact" / "variant" / "spacing" / "diff"（機械）、"cache" / "ai"（AI）
    issues: list[dict[str, Any]] = field(default_factory=list)
    corrected: str | None = None
    comment_ja: str = ""
    diff: list[dict[str, Any]] | None = None  # 字母単位の差分（機械採点で不正解のとき）

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
        }


def judge_exact(pack: LanguagePack, answer: str, expected: str, variants: list[str] | None = None) -> Judgement | None:
    """模範解答か許容例に一致すれば正解、空白の位置だけが違えば正解（注意つき）。決まらなければ None。"""
    norm = pack.normalize(answer)
    candidates = [pack.normalize(expected)] + [pack.normalize(v) for v in (variants or [])]
    if norm in candidates:
        return Judgement(VERDICT_CORRECT, "exact" if norm == candidates[0] else "variant", corrected=expected)
    squeezed = norm.replace(" ", "")
    for c in candidates:
        if squeezed == c.replace(" ", ""):
            tag = pack.spacing_tag or "spacing"
            return Judgement(
                VERDICT_NOTES,
                "spacing",
                issues=[{"axis": "orthography", "tag": tag, "span": answer.strip(), "note": "分かち書きの位置が違います", "suggestion": c}],
                corrected=expected,
                comment_ja="意味も綴りも合っています。分かち書きだけ見直しましょう。",
            )
    return None


def judge_machine(pack: LanguagePack, answer: str, expected: str, variants: list[str] | None = None) -> Judgement:
    """機械採点だけの練習（穴埋め・書き取り・綴り）。一致しなければ不正解にして、字母単位の差分を返す。"""
    result = judge_exact(pack, answer, expected, variants)
    if result is not None:
        return result
    return Judgement(
        VERDICT_INCORRECT,
        "diff",
        corrected=expected,
        diff=char_diff(pack.normalize(answer), pack.normalize(expected)),
    )


def judge_ai_placeholder(pack: LanguagePack, answer: str, expected: str) -> Judgement:
    """AI 採点の代わりの仮の判定。画面の「不正解 → 自分で直す → 答えを見る」の流れを作るためのもので、M5 で AI 採点に置き換える。

    模範解答と最初に食い違った語を issues[].span にして返す（意味の判断はしない）。
    """
    norm = pack.normalize(answer)
    got, want = norm.split(" "), pack.normalize(expected).split(" ")
    span = next((g for g, w in zip(got, want) if g != w), got[-1] if got else "")
    return Judgement(
        VERDICT_INCORRECT,
        "placeholder",
        issues=[{"axis": "meaning", "tag": "その他", "span": span, "note": "模範解答と違います（AI 採点はまだ作っていないので、仮の判定です）", "suggestion": None, "word_id": None}],
        corrected=expected,
        comment_ja="仮の判定です。模範解答と見比べてください。",
    )


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
