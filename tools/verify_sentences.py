"""文の検算（docs/plan.md 6.3「文の検算」）。生成の流れ（gen_sentences.py）から呼ぶ。

- 機械（Kiwi）: 語節と word_ids が文と合っているか、使ってよい単語だけでできているか、そのユニットの単語が 1〜3 語か
- AI: 韓国語の自然さ、訳の意味、文体の表示、まだ使えない文法を使っていないか、穴埋めのヒント。
  文法の表示と許容例の誤りは、文を不合格にせずに直す（表示の付け方は検算でもぶれるため）
"""

from __future__ import annotations

import threading
from typing import Any

from app.claude_cli import AskFn
from app.prompts import build_verify_sentences_prompt, verify_sentences_schema
from tools.batch import BadOutput
from tools.ko.morph import Analyzer, Lexicon, eojeols

MAX_UNIT_WORDS = 3


def clean(raw: dict[str, Any]) -> dict[str, Any]:
    """AI の出力を文データの形にそろえる。語節は文を空白で区切ったものから作り直し、AI の word_ids を表記で合わせる。"""
    ko = " ".join(raw["ko"].split())
    ja = raw["ja"].strip()
    spans = [s for s, _, _ in eojeols(ko)]
    given = [{"surface": t["surface"].strip(), "word_ids": list(dict.fromkeys(t["word_ids"]))} for t in raw["tokens"]]
    tokens = given if [t["surface"] for t in given] == spans else _align(spans, given)
    cloze = dict(raw["cloze"])
    if 0 <= cloze.get("eojeol", -1) < len(tokens):
        cloze["answer"] = tokens[cloze["eojeol"]]["surface"]
    return {
        "ko": ko,
        "ja": ja,
        "register": raw["register"],
        "scene": raw["scene"].strip(),
        "tokens": tokens,
        "grammar": list(dict.fromkeys(raw["grammar"])),
        "cloze": {"eojeol": cloze.get("eojeol", -1), "answer": cloze.get("answer", ""), "hint_ja": cloze.get("hint_ja", "").strip()},
        "variants": {
            "ko": _variants(raw["variants"]["ko"], ko),
            "ja": _variants(raw["variants"]["ja"], ja),
        },
    }


def _align(spans: list[str], given: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """AI の語節の区切りが文と違うとき、表記が同じ語節の word_ids だけを引き継ぐ（残りは機械の検算で足す）。"""
    by_surface: dict[str, list[str]] = {}
    for token in given:
        by_surface.setdefault(token["surface"], token["word_ids"])
    return [{"surface": s, "word_ids": list(by_surface.get(s, []))} for s in spans]


def _variants(values: list[str], original: str) -> list[str]:
    cleaned = (" ".join(v.split()) for v in values)
    return list(dict.fromkeys(v for v in cleaned if v and v != original))


class Checker:
    """機械の検算。Kiwi は読み込みが重いので 1 つを使い回し、並列の呼び出しは順に通す。"""

    def __init__(self) -> None:
        self._analyzer: Analyzer | None = None
        self._lock = threading.Lock()

    def check(self, sentence: dict[str, Any], lexicon: Lexicon, unit_word_ids: set[str]) -> list[str]:
        """問題の一覧（空なら合格）。直せる word_ids の抜けは sentence を書き換えて直す。"""
        with self._lock:
            if self._analyzer is None:
                self._analyzer = Analyzer()
            problems = list(self._analyzer.check(sentence, lexicon).problems)
        used = {w for t in sentence["tokens"] for w in t["word_ids"] if w in unit_word_ids}
        if not used:
            problems.append("このユニットの単語が入っていない")
        elif len(used) > MAX_UNIT_WORDS:
            problems.append(f"このユニットの単語が {len(used)} 語入っている（1 文に 1〜{MAX_UNIT_WORDS} 語）")
        if not 0 <= sentence["cloze"]["eojeol"] < len(sentence["tokens"]):
            problems.append("穴埋めの語節の番号が範囲の外")
        return problems


def ai_check(
    ask: AskFn,
    unit: dict[str, Any],
    items: list[tuple[str, dict[str, Any]]],
    grammar: list[dict[str, Any]],
    words: dict[str, dict[str, Any]],
    version: int,
) -> dict[str, dict[str, Any]]:
    """AI の検算。items は (キー, 文)、version はプロンプトの版。キーごとに ok・problems・正しい文法の表示・取り除く許容例を返す。"""
    keys = [key for key, _ in items]
    forms = [g["form"] for g in grammar]
    prompt_items = [
        {
            "key": key,
            "ko": s["ko"],
            "ja": s["ja"],
            "register": s["register"],
            "grammar": s["grammar"],
            "words": [words[w] for t in s["tokens"] for w in t["word_ids"] if w in words],
            "cloze": s["cloze"],
            "variants": s["variants"],
        }
        for key, s in items
    ]
    result = ask(build_verify_sentences_prompt(unit, prompt_items, grammar, version), verify_sentences_schema(keys, forms))["sentences"]
    missing = [k for k in keys if k not in result]
    if missing:
        raise BadOutput(f"検算が返ってこなかった文があります: {'、'.join(missing)}")
    return result


def apply_fixes(sentence: dict[str, Any], verdict: dict[str, Any]) -> None:
    """検算が直した文法の表示に置き換え、受け入れられない許容例を取り除く。"""
    sentence["grammar"] = list(dict.fromkeys(verdict["grammar"]))
    bad_ko = {" ".join(v.split()) for v in verdict["bad_ko_variants"]}
    bad_ja = {v.strip() for v in verdict["bad_ja_variants"]}
    sentence["variants"]["ko"] = [v for v in sentence["variants"]["ko"] if v not in bad_ko]
    sentence["variants"]["ja"] = [v for v in sentence["variants"]["ja"] if v not in bad_ja]
