"""Kiwi（kiwipiepy）による文の検算（docs/plan.md 6.3「文の検算」）。

文を形態素に分けて原形を取り出し、次を確かめる。
- tokens（語節）が文を空白で区切ったものと合っているか
- word_ids の単語が、その語節に本当にあるか
  - 用言の語幹が助詞の一部としてしか現れないもの（여권하고 の 하고 に付けた 하다）は、word_ids から外す
- word_ids に入っていない内容語（名詞・動詞・形容詞・副詞など）が、使ってよい単語か
  - 使ってよい単語で、同じ綴りの語が 1 つだけなら、word_ids に足す（直せるものは機械で直す）
  - まだ出ていない単語・一覧にない単語なら問題にする

Kiwi の分け方と単語の見出しは食い違うことがあるので、確かな誤りだけを問題にする。
- 人名などの固有名詞（NNP）で、単語の一覧にないものは名前として許す
- 依存名詞（NNB。-(으)ㄹ 수 있다 の 수 など文法の一部になる）は、使ってよい単語にないものは見ない
- 数詞の合成（스물다섯、삼십오）と名詞の合成（역사책）は、使ってよい語に分けられれば許す
- 表現（あいさつなど）は、文の中にその形があればよい
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

CONTENT_TAGS = {"NNG", "NNP", "NNB", "NP", "NR", "VV", "VA", "VCN", "MM", "MAG", "MAJ", "IC", "XR"}
# 原形に「다」を付ける形態素。결혼했어요 の 하（XSV）も、単語の 하다 として word_ids に付けてよい
PREDICATE_TAGS = {"VV", "VA", "VX", "VCN", "XSV", "XSA"}
# 前の形態素とつながって 1 つの語になるもの（공부＋하 → 공부하다、회사＋원 → 회사원）
JOINING_TAGS = {"XSN", "XSV", "XSA", "NNG", "XR"}
# Kiwi は縮約形を元の形に戻す（이게 → 이것＋이）。見出しには縮約した形（이거）もあるので、同じ語として扱う。
# 어때요 は Kiwi では 어떻다、国立国語院の見出しでは 어떠하다
_SAME_WORDS = {
    "이것": "이거", "그것": "그거", "저것": "저거", "것": "거", "무엇": "뭐",
    "어떻다": "어떠하다", "이렇다": "이러하다", "그렇다": "그러하다", "저렇다": "저러하다",
}
SAME_WORDS = {**_SAME_WORDS, **{v: k for k, v in _SAME_WORDS.items()}}
EXPRESSION_POS = "表現"
# word_ids の用言が語節にあれば、その語節の用言はそれで覆われたものとする（사세요 の 사 を 사다 と取り違えない）
COVERED_PREDICATE_TAGS = {"VV", "VA", "VCN"}
# Kiwi が文の中で 1 つに決め打ちした解析で見つからないとき、語節だけを解析し直して上位いくつまで見るか
ALTERNATIVES = 5
_RIEUL = 8  # ハングルの音節の終声 ㄹ の番号
_HONORIFIC = "세셨시십실신셔"  # 尊敬の -시- が語尾と縮まった音節（계세요、잡수셨어요）
# 数詞の合成を分けるときに使う品詞。열두 시 の 두 のように、数を表す冠形詞（한・두・세・네）も合成に入る
NUMERAL_POS = ("数詞", "冠形詞")
NOUN_POS = ("名詞", "依存名詞", "固有名詞")

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

    @cached_property
    def nouns(self) -> dict[str, str]:
        """合成語を分けるのに使う名詞。同じ綴りの名詞が複数あるもの（どれか決められない）は入れない。"""
        found: dict[str, list[str]] = {}
        for wid, word in self.allowed.items():
            if word["pos"] in NOUN_POS:
                found.setdefault(normalize(word["lemma"]), []).append(wid)
        return {lemma: ids[0] for lemma, ids in found.items() if len(ids) == 1}


@dataclass
class Check:
    problems: list[str] = field(default_factory=list)
    added: list[tuple[int, str]] = field(default_factory=list)  # (語節の番号, 足した単語の id)
    removed: list[tuple[int, str]] = field(default_factory=list)  # (語節の番号, 外した単語の id)


class Analyzer:
    def __init__(self) -> None:
        from kiwipiepy import Kiwi  # 教材づくりでだけ使う（読み込みに数秒かかる）

        self.kiwi = Kiwi()

    def morphs(self, text: str) -> list[Morph]:
        return [Morph(t.form, t.tag.split("-")[0], t.start) for t in self.kiwi.tokenize(text)]

    def alternatives(self, surface: str) -> set[str]:
        """語節だけを解析したときの、上位の解析すべての原形の候補（물어볼게요 → 물어보다 など）。"""
        found: set[str] = set()
        for tokens, _ in self.kiwi.analyze(surface, top_n=ALTERNATIVES):
            morphs = [Morph(t.form, t.tag.split("-")[0], t.start) for t in tokens]
            found |= {c for j in range(len(morphs)) for c in _candidates(morphs, j)}
        return found

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
        # 表現が覆う語節と、Kiwi の最上位の解析とは別の読みで単語が見つかった語節。どちらも残りの形態素は問わない
        settled: set[int] = set()
        for i, token in enumerate(tokens):
            for wid in list(token["word_ids"]):
                word = lexicon.allowed.get(wid)
                if word is None:
                    result.problems.append(f"使ってよい単語の一覧にない id: {wid}")
                elif word["pos"] == EXPRESSION_POS:
                    lemma = normalize(word["lemma"])
                    if lemma not in sentence_text:
                        result.problems.append(f"表現「{word['lemma']}」がそのままの形で文にない")
                    settled |= {j for j, (s, _, _) in enumerate(spans) if s in lemma or lemma in s}
                elif _in_particle_only(word["lemma"], by_eojeol[i]):
                    token["word_ids"].remove(wid)
                    result.removed.append((i, wid))
                elif _found(word["lemma"], spans[i][0], by_eojeol[i]):
                    continue
                elif _conjugated(word["lemma"], spans[i][0]) or normalize(word["lemma"]) in self.alternatives(spans[i][0]):
                    settled.add(i)
                else:
                    result.problems.append(f"「{spans[i][0]}」に単語 {word['lemma']}（{wid}）が見当たらない")

        for i, token in enumerate(tokens):
            if i in settled:
                continue
            morphs = by_eojeol[i]
            for j, m in enumerate(morphs):
                referenced = _referenced(token, lexicon)
                if m.tag not in CONTENT_TAGS or any(m.form in lemma for lemma in referenced) or _particle_ha(morphs, j):
                    continue
                if m.tag in COVERED_PREDICATE_TAGS and any(lemma.endswith("다") for lemma in referenced):
                    continue
                problem = self._unlisted(m, _candidates(morphs, j), token, i, lexicon, result)
                if problem:
                    result.problems.append(problem)
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
        if m.tag == "NNB":
            return None
        if m.tag in ("NR", "NNG"):
            parts = _split(normalize(m.form), lexicon.numerals if m.tag == "NR" else lexicon.nouns)
            if parts is not None and (m.tag == "NR" or len(parts) > 1):
                for wid in parts:
                    if wid not in token["word_ids"]:
                        token["word_ids"].append(wid)
                        result.added.append((index, wid))
                return None
        for lemma in candidates:
            where = lexicon.known.get(lemma)
            if where:
                return f"まだ出ていない単語「{lemma}」を使っている（{where}）"
        if m.tag == "NNP":
            return None
        return f"単語の一覧にない語「{candidates[0] if candidates else m.form}」を使っている"


def _referenced(token: dict[str, Any], lexicon: Lexicon) -> list[str]:
    """語節の word_ids の単語の見出し（同じ語として扱う縮約形も含む）。"""
    lemmas = [normalize(lexicon.allowed[w]["lemma"]) for w in token["word_ids"] if w in lexicon.allowed]
    return lemmas + [SAME_WORDS[lemma] for lemma in lemmas if lemma in SAME_WORDS]


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
    result = [normalize(c) for c in reversed(found)]
    return result + [SAME_WORDS[c] for c in result if c in SAME_WORDS]


def _found(lemma: str, surface: str, morphs: list[Morph]) -> bool:
    lemma = normalize(lemma)
    lemmas = {c for j in range(len(morphs)) for c in _candidates(morphs, j)}
    if lemma in lemmas:
        return True
    if lemma.endswith("하다") and lemma[:-2] in lemmas:
        return True  # 공부하다 を「공부를 해요」の 공부 で使っている
    stem = lemma[:-1] if lemma.endswith("다") and len(lemma) > 1 else lemma
    return stem in normalize(surface)


def _in_particle_only(lemma: str, morphs: list[Morph]) -> bool:
    """用言の語幹が、語節の中では助詞の一部としてしか現れないか（여권하고 の 하고 に付けた 하다）。
    _found は語幹が表記に含まれていれば見つかったことにするので、その前に確かめる。

    名詞のすぐあとの 하고 を、Kiwi は助詞（JKB・JC）と読むか、名詞に空白なしで付いた独立の 하（VV）と読む。
    名詞＋하다 の動詞（결혼하고）なら 하 は XSV になり、独立の動詞なら名詞とは分かち書きするので、
    名詞に付いた VV の 하 は助詞として扱う。"""
    lemma = normalize(lemma)
    if not lemma.endswith("다") or len(lemma) < 2:
        return False
    stem = lemma[:-1]
    holders = [j for j, m in enumerate(morphs) if stem in m.form]
    return bool(holders) and all(morphs[j].tag.startswith("J") or _particle_ha(morphs, j) for j in holders)


def _particle_ha(morphs: list[Morph], index: int) -> bool:
    """名詞に空白なしで付いた独立の 하（VV）。助詞 하고 を Kiwi が読み違えたもの（_in_particle_only）。"""
    m = morphs[index]
    prev = morphs[index - 1] if index > 0 else None
    return m.form == "하" and m.tag == "VV" and prev is not None and prev.tag.startswith("N") and prev.start + len(prev.form) == m.start


def _conjugated(lemma: str, surface: str) -> bool:
    """Kiwi が別の語と読みやすい活用の形か（살다 → 사세요、계시다 → 계세요）。"""
    lemma = normalize(lemma)
    surface = normalize(surface)
    if not lemma.endswith("다") or len(lemma) < 2:
        return False
    stem = lemma[:-1]
    last = ord(stem[-1]) - 0xAC00
    if 0 <= last < 11172 and last % 28 == _RIEUL and surface.startswith(stem[:-1] + chr(ord(stem[-1]) - _RIEUL)):
        return True  # ㄹ 語幹の ㄹ が落ちる活用（살다 → 사세요）
    base = lemma[:-2]
    return lemma.endswith("시다") and bool(base) and surface.startswith(base) and surface[len(base) : len(base) + 1] in _HONORIFIC


def _split(text: str, parts: dict[str, str]) -> list[str] | None:
    """合成語（스물다섯、역사책）を、使ってよい語（parts の見出し → id）に分ける。分けられなければ None。"""
    if not text:
        return []
    for size in range(len(text), 0, -1):
        wid = parts.get(text[:size])
        if wid:
            rest = _split(text[size:], parts)
            if rest is not None:
                return [wid, *rest]
    return None
