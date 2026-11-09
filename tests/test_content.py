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


def test_loaded_content_is_reused_until_a_file_changes(root):
    import os

    first = content.load(root, "ko")
    assert content.load(root, "ko") is first
    path = root / "content" / "ko" / "words.json"
    stat = path.stat()
    path.write_text(path.read_text(encoding="utf-8").replace("水", "お水"), encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    again = content.load(root, "ko")
    assert again is not first and again.word("t-w-0001").meaning == "お水"


def test_meaning_atoms_are_made_once_when_loading(root):
    w = content.load(root, "ko").word("t-w-0001")
    assert w.meaning_atoms == frozenset({"水"})


def test_l1_content_has_no_duplicate_sentences_and_casual_labels_match():
    """L1 の教材（1-11・1-18）: 同じユニットに同じ文がない。반말 の文に해요체の文法の表示が付いていない。"""
    loaded = content.load(REPO_ROOT, "ko", approved_only=False)
    seen: dict[tuple[str, str], str] = {}
    for s in loaded.sentences:
        key = (s.unit, "".join(ch for ch in s.ko if ch.isalnum()))
        assert key not in seen, f"{s.id} と {seen[key]} が同じ文"
        seen[key] = s.id
        if s.register == "반말":
            assert "-아/어요" not in s.grammar, s.id
    sibling = next(w for w in loaded.words if w.lemma == "동생")
    assert sibling.meaning == "年下のきょうだい"
    assert {m["ja"] for m in sibling.meanings} >= {"弟", "妹"}
