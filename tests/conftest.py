from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

UNITS = [
    {"id": "T-U01", "level": 1, "order": 1, "title": "テスト 1", "scene": "場面 1"},
    {"id": "T-U02", "level": 1, "order": 2, "title": "テスト 2", "scene": "場面 2"},
]


def word(num: int, lemma: str, ja: str, unit: str, pos: str = "名詞", **extra):
    return {
        "id": f"t-w-{num:04d}",
        "lemma": lemma,
        "pos": pos,
        "level": 1,
        "unit": unit,
        "order": num,
        "meanings": [{"ja": ja, "primary": True}],
        "origin": "固有語",
        "hanja": None,
        "confusables": [],
        "synonyms": [],
        "homographs": [],
        "tags": [],
        "tts_text": lemma,
        "status": "approved",
        **extra,
    }


WORDS = [
    word(1, "물", "水", "T-U01"),
    word(2, "빵", "パン", "T-U01"),
    word(3, "커피", "コーヒー", "T-U01"),
    word(4, "우유", "牛乳", "T-U01"),
    word(5, "차", "お茶", "T-U01", homographs=["t-w-0006"]),
    word(6, "차", "車", "T-U02", homographs=["t-w-0005"]),
    word(7, "먹다", "食べる", "T-U02", pos="動詞"),
    word(8, "마시다", "飲む", "T-U02", pos="動詞"),
    word(9, "가다", "行く", "T-U02", pos="動詞"),
    word(10, "오다", "来る", "T-U02", pos="動詞"),
    word(11, "미안", "未承認", "T-U02", status="draft"),
]

SENTENCES_U01 = [
    {
        "id": "t-s-U01-001",
        "unit": "T-U01",
        "ko": "물 주세요.",
        "ja": "お水ください。",
        "register": "해요체",
        "scene": "カフェ",
        "tokens": [{"surface": "물", "word_ids": ["t-w-0001"], "eojeol": 0}, {"surface": "주세요", "word_ids": [], "eojeol": 1}],
        "grammar": ["-(으)세요"],
        "cloze": [{"eojeol": 0, "answer": "물", "hint_ja": "水"}],
        "variants": {"ko": ["물 좀 주세요."], "ja": ["水をください。"]},
        "status": "approved",
    },
    {
        "id": "t-s-U01-002",
        "unit": "T-U01",
        "ko": "커피가 있어요.",
        "ja": "コーヒーがあります。",
        "register": "해요체",
        "scene": "カフェ",
        "tokens": [{"surface": "커피가", "word_ids": ["t-w-0003"], "eojeol": 0}, {"surface": "있어요", "word_ids": [], "eojeol": 1}],
        "grammar": ["이/가"],
        "cloze": [{"eojeol": 0, "answer": "커피가", "hint_ja": "コーヒーが"}],
        "variants": {"ko": [], "ja": []},
        "status": "approved",
    },
]

SENTENCES_U02 = [
    {
        "id": "t-s-U02-001",
        "unit": "T-U02",
        "ko": "빵을 먹어요.",
        "ja": "パンを食べます。",
        "register": "해요체",
        "scene": "会話",
        "tokens": [{"surface": "빵을", "word_ids": ["t-w-0002"], "eojeol": 0}, {"surface": "먹어요", "word_ids": ["t-w-0007"], "eojeol": 1}],
        "grammar": ["을/를"],
        "cloze": [{"eojeol": 1, "answer": "먹어요", "hint_ja": "食べます"}],
        "variants": {"ko": [], "ja": []},
        "status": "approved",
    },
    {
        "id": "t-s-U02-002",
        "unit": "T-U02",
        "ko": "우유를 마셔요.",
        "ja": "牛乳を飲みます。",
        "register": "해요체",
        "scene": "会話",
        "tokens": [{"surface": "우유를", "word_ids": ["t-w-0004"], "eojeol": 0}, {"surface": "마셔요", "word_ids": ["t-w-0008"], "eojeol": 1}],
        "grammar": ["을/를"],
        "cloze": [{"eojeol": 1, "answer": "마셔요", "hint_ja": "飲みます"}],
        "variants": {"ko": [], "ja": []},
        "status": "approved",
    },
    {
        "id": "t-s-U02-003",
        "unit": "T-U02",
        "ko": "차로 가요.",
        "ja": "車で行きます。",
        "register": "해요체",
        "scene": "会話",
        "tokens": [{"surface": "차로", "word_ids": ["t-w-0006"], "eojeol": 0}, {"surface": "가요", "word_ids": ["t-w-0009"], "eojeol": 1}],
        "grammar": [],
        "cloze": [],
        "variants": {"ko": [], "ja": []},
        "status": "approved",
    },
]


def write_content(root: Path, words=WORDS, units=UNITS, sentences: dict[str, list] | None = None) -> Path:
    base = root / "content" / "ko"
    (base / "sentences").mkdir(parents=True, exist_ok=True)
    (base / "units.json").write_text(json.dumps(units, ensure_ascii=False), encoding="utf-8")
    (base / "words.json").write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    (base / "grammar.json").write_text("[]", encoding="utf-8")
    if sentences is None:
        sentences = {"T-U01": SENTENCES_U01, "T-U02": SENTENCES_U02}
    for name, items in sentences.items():
        (base / "sentences" / f"{name}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return base


@pytest.fixture
def root(tmp_path: Path) -> Path:
    write_content(tmp_path)
    (tmp_path / "records").mkdir()
    return tmp_path
