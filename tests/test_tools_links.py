"""書き出しの紐づけ（類語の包含を閉じる・同じ綴りの語を 1 つに決める）。"""

from __future__ import annotations

import pytest

from tools import decisions, export
from tools.link_synonyms import closed_pairs
from tools.work import BuildError, Workspace


def test_not_similar_pairs_are_hidden_without_touching_synonyms(tmp_path):
    ws = Workspace(tmp_path, "ko")
    ws.write(decisions.DECISIONS, {"not_similar": [{"why": "テスト", "pairs": [{"a": "넷", "b": "네"}]}]})
    lemma_of = {"a": "넷", "b": "네", "c": "사"}
    words = [{"id": "a", "synonyms": ["b", "c"]}, {"id": "b", "synonyms": ["a"]}, {"id": "c", "synonyms": ["a"]}]
    assert export._hide_synonyms(words, decisions.not_similar(ws, lemma_of)) == 1
    assert words[0] == {"id": "a", "synonyms": ["b", "c"], "hidden_synonyms": ["b"]}
    assert words[1] == {"id": "b", "synonyms": ["a"], "hidden_synonyms": ["a"]}
    assert "hidden_synonyms" not in words[2]


def test_not_similar_stops_on_a_wrong_lemma(tmp_path):
    ws = Workspace(tmp_path, "ko")
    ws.write(decisions.DECISIONS, {"not_similar": [{"why": "テスト", "pairs": [{"a": "넷", "b": "네"}]}]})
    with pytest.raises(BuildError, match="見出しが違います"):
        decisions.not_similar(ws, {"a": "넷", "b": "예"})


def test_inclusion_is_closed_transitively_through_same_meaning_groups():
    found = [
        ("meat", "beef", "包含"),  # 고기 ⊃ 쇠고기
        ("beef", "beef2", "同義"),  # 쇠고기＝소고기
        ("food", "meat", "包含"),  # 음식 ⊃ 고기
        ("see", "meet", "一部が重なる"),
    ]
    linked, added = closed_pairs(found)
    assert ("beef2", "meat") in linked  # 고기 ⊃ 소고기
    assert ("beef", "food") in linked and ("beef2", "food") in linked  # 음식 ⊃ 쇠고기・소고기
    assert ("meet", "see") in linked
    assert added == 3
    # 一部が重なる組は、その組だけ（推移させない）
    assert closed_pairs([("a", "b", "一部が重なる"), ("b", "c", "一部が重なる")])[0] == {("a", "b"), ("b", "c")}


def word(wid, lemma, pos, *meanings):
    return {"id": wid, "lemma": lemma, "pos": pos, "meanings": [{"ja": m, "primary": i == 0} for i, m in enumerate(meanings)]}


def test_same_spelling_is_resolved_by_pos_then_meaning_or_dropped():
    words = [
        word("ye", "예", "感嘆詞", "はい"),
        word("ne-yes", "네", "感嘆詞", "はい"),
        word("ne-four", "네", "冠形詞", "四つの"),
        word("myeong", "명", "依存名詞", "〜人（人数）"),
        word("bun-min", "분", "依存名詞", "〜分"),
        word("bun-person", "분", "依存名詞", "方（かた）"),
    ]
    by_lemma: dict[str, list[str]] = {}
    for w in words:
        by_lemma.setdefault(w["lemma"], []).append(w["id"])
    by_id = {w["id"]: w for w in words}
    unresolved: list[dict] = []
    assert export._to_ids("類語", ["네"], by_id["ye"], by_lemma, by_id, unresolved) == ["ne-yes"]  # 品詞で決まる
    assert export._to_ids("類語", ["분"], by_id["myeong"], by_lemma, by_id, unresolved) == []  # 品詞も訳も決め手がない
    assert unresolved == [{"field": "類語", "lemma": "명", "target": "분", "candidates": ["분（依存名詞・〜分）", "분（依存名詞・方（かた））"]}]
