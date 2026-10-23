"""教材（content/<言語>/）の読み込みと整合の確認。

教材は JSON ファイルで持つ（Git で差分を見られるように）。学習に出すのは status が approved のものだけ。
id は一度付けたら変えない（学習の記録が参照するため）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATUS_APPROVED = "approved"


class ContentError(Exception):
    """教材のファイルが読めない、または整合していない。"""


@dataclass(frozen=True)
class Word:
    id: str
    lemma: str
    pos: str
    level: int
    unit: str
    order: int
    meanings: tuple[dict[str, Any], ...]
    origin: str
    hanja: str | None
    confusables: tuple[str, ...]
    synonyms: tuple[str, ...]
    homographs: tuple[str, ...]
    tags: tuple[str, ...]
    tts_text: str
    status: str
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def meaning(self) -> str:
        """主な意味（primary）。多義語の 2 つ目以降は当面出題しない。"""
        for m in self.meanings:
            if m.get("primary"):
                return str(m["ja"])
        return str(self.meanings[0]["ja"]) if self.meanings else ""

    def to_dict(self) -> dict[str, Any]:
        return {**self.raw, "meaning": self.meaning}


@dataclass(frozen=True)
class Sentence:
    id: str
    unit: str
    ko: str
    ja: str
    register: str
    scene: str
    tokens: tuple[dict[str, Any], ...]
    grammar: tuple[str, ...]
    cloze: tuple[dict[str, Any], ...]
    variants: dict[str, list[str]]
    status: str
    raw: dict[str, Any] = field(repr=False, compare=False)

    @property
    def word_ids(self) -> list[str]:
        seen: list[str] = []
        for token in self.tokens:
            for wid in token.get("word_ids", []):
                if wid not in seen:
                    seen.append(wid)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass(frozen=True)
class Unit:
    id: str
    level: int
    title: str
    scene: str
    order: int
    raw: dict[str, Any] = field(repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


@dataclass
class Content:
    language: str
    units: list[Unit]
    words: list[Word]
    sentences: list[Sentence]
    grammar: list[dict[str, Any]]

    def __post_init__(self) -> None:
        self._word_by_id = {w.id: w for w in self.words}
        self._sentence_by_id = {s.id: s for s in self.sentences}
        self._unit_by_id = {u.id: u for u in self.units}

    def word(self, word_id: str) -> Word:
        try:
            return self._word_by_id[word_id]
        except KeyError:
            raise ContentError(f"単語がありません: {word_id}") from None

    def sentence(self, sentence_id: str) -> Sentence:
        try:
            return self._sentence_by_id[sentence_id]
        except KeyError:
            raise ContentError(f"文がありません: {sentence_id}") from None

    def unit(self, unit_id: str) -> Unit:
        try:
            return self._unit_by_id[unit_id]
        except KeyError:
            raise ContentError(f"ユニットがありません: {unit_id}") from None

    def words_in(self, unit_id: str) -> list[Word]:
        return sorted((w for w in self.words if w.unit == unit_id), key=lambda w: w.order)

    def sentences_in(self, unit_id: str) -> list[Sentence]:
        return [s for s in self.sentences if s.unit == unit_id]

    def units_up_to(self, unit_id: str) -> list[Unit]:
        """そのユニットまで（含む）のユニットを順に返す。文で使ってよい単語の範囲を決めるのに使う。"""
        target = self.unit(unit_id)
        return [u for u in self.units if u.order <= target.order]


def content_dir(root: Path, language: str) -> Path:
    return root / "content" / language


def load(root: Path, language: str, approved_only: bool = True) -> Content:
    """content/<言語>/ を読み込む。整合していなければ ContentError。"""
    base = content_dir(root, language)
    if not base.is_dir():
        raise ContentError(f"教材のディレクトリがありません: {base}")
    units = [_unit(u) for u in _read_json(base / "units.json")]
    units.sort(key=lambda u: u.order)
    words = [_word(w) for w in _read_json(base / "words.json")]
    sentences: list[Sentence] = []
    sentences_dir = base / "sentences"
    if sentences_dir.is_dir():
        for path in sorted(sentences_dir.glob("*.json")):
            sentences += [_sentence(s) for s in _read_json(path)]
    grammar_path = base / "grammar.json"
    grammar = _read_json(grammar_path) if grammar_path.exists() else []

    content = Content(language, units, words, sentences, grammar)
    validate(content)
    if approved_only:
        content = Content(
            language,
            units,
            [w for w in words if w.status == STATUS_APPROVED],
            [s for s in sentences if s.status == STATUS_APPROVED and all(content.word(i).status == STATUS_APPROVED for i in s.word_ids)],
            grammar,
        )
    return content


def validate(content: Content) -> None:
    """教材の整合を確かめる。id の重複、文が参照する単語の存在と範囲、穴埋めの答えが文の中にあること。"""
    problems: list[str] = []
    seen: set[str] = set()
    for w in content.words:
        if w.id in seen:
            problems.append(f"単語の id が重複: {w.id}")
        seen.add(w.id)
        if w.unit not in content._unit_by_id:
            problems.append(f"単語 {w.id} のユニットがありません: {w.unit}")
        if not w.meanings:
            problems.append(f"単語 {w.id} に意味がありません")
    seen = set()
    for s in content.sentences:
        if s.id in seen:
            problems.append(f"文の id が重複: {s.id}")
        seen.add(s.id)
        if s.unit not in content._unit_by_id:
            problems.append(f"文 {s.id} のユニットがありません: {s.unit}")
            continue
        allowed = {w.id for u in content.units_up_to(s.unit) for w in content.words_in(u.id)}
        for wid in s.word_ids:
            if wid not in content._word_by_id:
                problems.append(f"文 {s.id} が参照する単語がありません: {wid}")
            elif wid not in allowed:
                problems.append(f"文 {s.id} がまだ出ていない単語を使っています: {wid}")
        for c in s.cloze:
            if c.get("answer") not in s.ko:
                problems.append(f"文 {s.id} の穴埋めの答えが文の中にありません: {c.get('answer')}")
        for key in ("ko", "ja"):
            vs = s.variants.get(key, [])
            if len(vs) != len(set(vs)):
                problems.append(f"文 {s.id} の許容例（{key}）に重複があります")
    if problems:
        raise ContentError("教材が整合していません:\n- " + "\n- ".join(problems))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ContentError(f"教材のファイルがありません: {path}") from None
    except json.JSONDecodeError as exc:
        raise ContentError(f"教材のファイルが JSON として読めません: {path}: {exc}") from exc


def _unit(raw: dict[str, Any]) -> Unit:
    return Unit(
        id=raw["id"], level=int(raw["level"]), title=raw["title"], scene=raw.get("scene", ""), order=int(raw["order"]), raw=raw
    )


def _word(raw: dict[str, Any]) -> Word:
    return Word(
        id=raw["id"],
        lemma=raw["lemma"],
        pos=raw["pos"],
        level=int(raw["level"]),
        unit=raw["unit"],
        order=int(raw["order"]),
        meanings=tuple(raw.get("meanings", [])),
        origin=raw.get("origin", ""),
        hanja=raw.get("hanja"),
        confusables=tuple(raw.get("confusables", [])),
        synonyms=tuple(raw.get("synonyms", [])),
        homographs=tuple(raw.get("homographs", [])),
        tags=tuple(raw.get("tags", [])),
        tts_text=raw.get("tts_text") or raw["lemma"],
        status=raw.get("status", "draft"),
        raw=raw,
    )


def _sentence(raw: dict[str, Any]) -> Sentence:
    return Sentence(
        id=raw["id"],
        unit=raw["unit"],
        ko=raw["ko"],
        ja=raw["ja"],
        register=raw.get("register", ""),
        scene=raw.get("scene", ""),
        tokens=tuple(raw.get("tokens", [])),
        grammar=tuple(raw.get("grammar", [])),
        cloze=tuple(raw.get("cloze", [])),
        variants=raw.get("variants", {}),
        status=raw.get("status", "draft"),
        raw=raw,
    )
