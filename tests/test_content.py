from __future__ import annotations

import copy

import pytest

from app import content
from app.content import ContentError
from tests.conftest import REPO_ROOT, SENTENCES_U01, SENTENCES_U02, WORDS, write_content


def test_load_filters_unapproved(root):
    loaded = content.load(root, "ko")
    assert "t-w-0011" not in {w.id for w in loaded.words}
    everything = content.load(root, "ko", approved_only=False)
    assert "t-w-0011" in {w.id for w in everything.words}


def test_word_meaning_and_lookup(root):
    loaded = content.load(root, "ko")
    assert loaded.word("t-w-0001").meaning == "水"
    assert [w.lemma for w in loaded.words_in("T-U02")][:2] == ["차", "먹다"]
    assert [u.id for u in loaded.units_up_to("T-U02")] == ["T-U01", "T-U02"]
    with pytest.raises(ContentError, match="単語がありません"):
        loaded.word("nope")


def test_sentence_word_ids_in_order(root):
    loaded = content.load(root, "ko")
    assert loaded.sentence("t-s-U02-001").word_ids == ["t-w-0002", "t-w-0007"]


def test_validate_rejects_unknown_word(tmp_path):
    bad = copy.deepcopy(SENTENCES_U01)
    bad[0]["tokens"][0]["word_ids"] = ["t-w-9999"]
    write_content(tmp_path, sentences={"T-U01": bad, "T-U02": SENTENCES_U02})
    with pytest.raises(ContentError, match="参照する単語がありません"):
        content.load(tmp_path, "ko")


def test_validate_rejects_word_from_later_unit(tmp_path):
    bad = copy.deepcopy(SENTENCES_U01)
    bad[0]["tokens"][0]["word_ids"] = ["t-w-0007"]  # T-U02 の単語
    write_content(tmp_path, sentences={"T-U01": bad, "T-U02": SENTENCES_U02})
    with pytest.raises(ContentError, match="まだ出ていない単語"):
        content.load(tmp_path, "ko")


def test_validate_rejects_cloze_not_in_sentence(tmp_path):
    bad = copy.deepcopy(SENTENCES_U01)
    bad[0]["cloze"][0]["answer"] = "없는말"
    write_content(tmp_path, sentences={"T-U01": bad, "T-U02": SENTENCES_U02})
    with pytest.raises(ContentError, match="穴埋めの答え"):
        content.load(tmp_path, "ko")


def test_validate_rejects_duplicate_ids(tmp_path):
    words = copy.deepcopy(WORDS)
    words[1]["id"] = words[0]["id"]
    write_content(tmp_path, words=words)
    with pytest.raises(ContentError, match="重複"):
        content.load(tmp_path, "ko")


def test_repo_content_is_consistent():
    """リポジトリの教材（content/ko/）が整合していること。"""
    loaded = content.load(REPO_ROOT, "ko")
    assert loaded.units and loaded.words and loaded.sentences
    for w in loaded.words:
        if w.origin == "漢字語":
            assert w.hanja, f"漢字語に漢字表記がありません: {w.lemma}"
        assert sum(1 for m in w.meanings if m.get("primary")) == 1, f"主な意味がちょうど 1 つではありません: {w.lemma}"


def test_meaning_atoms():
    from app.content import meaning_atoms

    assert meaning_atoms("グラス・コップ") == {"グラス", "コップ"}
    assert meaning_atoms("（値段が）安い") == {"安い"}
    assert meaning_atoms("〜杯") == {"杯"}
    assert meaning_atoms("うん／そう") == {"うん", "そう"}
