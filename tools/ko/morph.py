"""Kiwi（kiwipiepy）による文の検算（docs/plan.md 6.3「文の検算」）。

文を形態素に分けて原形を取り出し、次を確かめる。
- tokens（語節）が文を空白で区切ったものと合っているか
- word_ids の単語が、その語節に本当にあるか
- word_ids に入っていない内容語（名詞・動詞・形容詞・副詞など）が、使ってよい単語か
  - 使ってよい単語で、同じ綴りの語が 1 つだけなら、word_ids に足す（直せるものは機械で直す）
  - まだ出ていない単語・一覧にない単語なら問題にする

Kiwi の分け方と単語の見出しは食い違うことがあるので、確かな誤りだけを問題にする。
- 人名などの固有名詞（NNP）で、単語の一覧にないものは名前として許す
- 依存名詞（NNB。-(으)ㄹ 수 있다 の 수 など文法の一部になる）は、一覧にないものは見ない
- 数詞の合成（스물다섯、삼십오）は、使ってよい数詞に分けられれば許す
- 表現（あいさつなど）は、文の中にその形があればよい
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

CONTENT_TAGS = {"NNG", "NNP", "NNB", "NP", "NR", "VV", "VA", "VCN", "MM", "MAG", "MAJ", "IC", "XR"}
PREDICATE_TAGS = {"VV", "VA", "VX", "VCN"}
# 前の形態素とつながって 1 つの語になるもの（공부＋하 → 공부하다、회사＋원 → 회사원）
JOINING_TAGS = {"XSN", "XSV", "XSA", "NNG", "XR"}
EXPRESSION_POS = "表現"
# 数詞の合成を分けるときに使う品詞。열두 시 の 두 のように、数を表す冠形詞（한・두・세・네）も合成に入る
NUMERAL_POS = ("数詞", "冠形詞")

_EDGE_PUNCT = re.compile(r"^[\s.,?!。、？！…·:;\"'“”‘’()\[\]「」~]+|[\s.,?!。、？！…·:;\"'“”‘’()\[\]「」~]+$")


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace(" ", "")


def eojeols(text: str) -> list[tuple[str, int, int]]:
    """文を空白で区切った語節（句読点を除いた表記、元の文での開始位置、終了位置）。"""
    result = []
    for match in re.finditer(r"\S+", text):
        surface = _EDGE_PUNCT.sub("", match.group())
        if surface:
            result.append((surface, match.start(), match.end()))
    return result


@dataclass
class Morph:
    form: str
    tag: str
    start: int

    @property
    def lemma(self) -> str:
        return self.form + "다" if self.tag in PREDICATE_TAGS else self.form


@dataclass
class Lexicon:
    """単語の一覧。allowed は使ってよい単語の id → 単語、known はすべての候補の見出し（正規化）→ どこで出るか。"""

    allowed: dict[str, dict[str, Any]]
    known: dict[str, str] = field(default_factory=dict)

    @cached_property
    def allowed_by_lemma(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for wid, word in self.allowed.items():
            result.setdefault(normalize(word["lemma"]), []).append(wid)
        return result

    @cached_property
    def numerals(self) -> dict[str, str]:
        found: dict[str, str] = {}
        # 이（二）と 이（この）のように同じ綴りがあれば、数詞を先に取る
        for pos in NUMERAL_POS:
            for wid, word in self.allowed.items():
                if word["pos"] == pos:
                    found.setdefault(normalize(word["lemma"]), wid)
        return found


@dataclass
class Check:
    problems: list[str] = field(default_factory=list)
    added: list[tuple[int, str]] = field(default_factory=list)  # (語節の番号, 足した単語の id)


class Analyzer:
    def __init__(self) -> None:
        from kiwipiepy import Kiwi  # 教材づくりでだけ使う（読み込みに数秒かかる）

        self.kiwi = Kiwi()

    def morphs(self, text: str) -> list[Morph]:
        return [Morph(t.form, t.tag.split("-")[0], t.start) for t in self.kiwi.tokenize(text)]

    def check(self, sentence: dict[str, Any], lexicon: Lexicon) -> Check:
        """sentence の ko と tokens を確かめる。直せる word_ids の抜けは sentence["tokens"] を書き換えて直す。"""
        result = Check()
        ko = sentence["ko"]
        spans = eojeols(ko)
        tokens = sentence["tokens"]
        if [t["surface"] for t in tokens] != [s for s, _, _ in spans]:
            result.problems.append("tokens が文を空白で区切った語節と合っていない")
            return result
        if re.search(r"[0-9０-９]", ko):
            result.problems.append("数字が入っている（ハングルで書く）")
        if re.search(r"[A-Za-zＡ-Ｚａ-ｚ]", ko):
            result.problems.append("ローマ字が入っている")

        by_eojeol: list[list[Morph]] = [[] for _ in spans]
        for m in self.morphs(ko):
            for i, (_, start, end) in enumerate(spans):
                if start <= m.start < end:
                    by_eojeol[i].append(m)
                    break

        sentence_text = normalize(ko)
        expression_spans: set[int] = set()
        for i, token in enumerate(tokens):
            for wid in token["word_ids"]:
                word = lexicon.allowed.get(wid)
                if word is None:
                    result.problems.append(f"使ってよい単語の一覧にない id: {wid}")
                elif word["pos"] == EXPRESSION_POS:
                    lemma = normalize(word["lemma"])
                    if lemma not in sentence_text:
                        result.problems.append(f"表現「{word['lemma']}」がそのままの形で文にない")
                    expression_spans |= {j for j, (s, _, _) in enumerate(spans) if s in lemma or lemma in s}
                elif not _found(word["lemma"], spans[i][0], by_eojeol[i]):
                    result.problems.append(f"「{spans[i][0]}」に単語 {word['lemma']}（{wid}）が見当たらない")

        for i, token in enumerate(tokens):
            if i in expression_spans:
                continue
            referenced = [normalize(lexicon.allowed[w]["lemma"]) for w in token["word_ids"] if w in lexicon.allowed]
            morphs = by_eojeol[i]
            for j, m in enumerate(morphs):
                if m.tag not in CONTENT_TAGS or any(m.form in lemma for lemma in referenced):
                    continue
                problem = self._unlisted(m, _candidates(morphs, j), token, i, lexicon, result)
                if problem:
                    result.problems.append(problem)
                else:
                    referenced = [normalize(lexicon.allowed[w]["lemma"]) for w in token["word_ids"] if w in lexicon.allowed]
        return result

    @staticmethod
    def _unlisted(m: Morph, candidates: list[str], token: dict, index: int, lexicon: Lexicon, result: Check) -> str | None:
        """word_ids にない内容語を調べる。使ってよい単語なら足して None、問題なら問題の文を返す。"""
        for lemma in candidates:
            ids = lexicon.allowed_by_lemma.get(lemma, [])
            if len(ids) == 1:
                token["word_ids"].append(ids[0])
                result.added.append((index, ids[0]))
                return None
            if len(ids) > 1:
                return f"word_ids が足りない:「{m.form}」（同じ綴りの単語が複数あるので、どれか決められない）"
        if m.tag == "NR":
            parts = _split_numeral(normalize(m.form), lexicon.numerals)
            if parts is not None:
                for wid in parts:
                    if wid not in token["word_ids"]:
                        token["word_ids"].append(wid)
                        result.added.append((index, wid))
                return None
        for lemma in candidates:
            where = lexicon.known.get(lemma)
            if where:
                return f"まだ出ていない単語「{lemma}」を使っている（{where}）"
        if m.tag in ("NNP", "NNB"):
            return None
        return f"単語の一覧にない語「{candidates[0] if candidates else m.form}」を使っている"


def _candidates(morphs: list[Morph], index: int) -> list[str]:
    """index の形態素から始まる語の原形の候補。長くつながったものから順に（공부하다 → 공부）。"""
    m = morphs[index]
    found = [m.lemma]
    if m.tag == "IC" and m.form.endswith("요") and len(m.form) > 1:
        found.append(m.form[:-1])  # 저기요 → 저기
    text = m.form
    end = m.start + len(m.form)
    for nxt in morphs[index + 1 :]:
        if nxt.tag not in JOINING_TAGS or nxt.start != end:
            break
        text += nxt.form
        end = nxt.start + len(nxt.form)
        found.append(text + "다" if nxt.tag in ("XSV", "XSA") else text)
    return [normalize(c) for c in reversed(found)]


def _found(lemma: str, surface: str, morphs: list[Morph]) -> bool:
    lemma = normalize(lemma)
    lemmas = {c for j in range(len(morphs)) for c in _candidates(morphs, j)}
    if lemma in lemmas:
        return True
    if lemma.endswith("하다") and lemma[:-2] in lemmas:
        return True  # 공부하다 を「공부를 해요」の 공부 で使っている
    stem = lemma[:-1] if lemma.endswith("다") and len(lemma) > 1 else lemma
    return stem in normalize(surface)


def _split_numeral(text: str, numerals: dict[str, str]) -> list[str] | None:
    """数詞の合成（스물다섯、삼십오）を、使ってよい数詞に分ける。分けられなければ None。"""
    if not text:
        return []
    for size in range(len(text), 0, -1):
        wid = numerals.get(text[:size])
        if wid:
            rest = _split_numeral(text[size:], numerals)
            if rest is not None:
                return [wid, *rest]
    return None
