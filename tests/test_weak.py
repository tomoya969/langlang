from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import weak
from app.records import Records, make_scheduler

NOW = datetime(2026, 11, 4, 9, 0).astimezone()


@pytest.fixture
def records(tmp_path):
    return Records(tmp_path, make_scheduler(fuzz=False))


def answers(word="w1", face="meaning", results=(), elapsed=1.0):
    return [{"item_id": word, "face": face, "practice": f"word_{face}", "correct": ok, "elapsed_sec": elapsed} for ok in results]


def test_nothing_is_weak_without_records():
    result = weak.analyze({}, [], {})
    assert result.weak == {} and result.medians == {} and result.timing() == {}


def test_misses_need_enough_answers():
    # 1 回目の不正解だけでは苦手にしない
    assert "w1" not in weak.analyze({}, answers(results=[False]), {}).weak
    # 直近 10 回のうち 4 回まちがい（40%）
    result = weak.analyze({}, answers(results=[True] * 6 + [False, True, False, True, False, False]), {})
    assert result.weak["w1"] == ["misses"]
    # 古いまちがいは直近 10 回から外れる
    assert "w1" not in weak.analyze({}, answers(results=[False] * 5 + [True] * 10), {}).weak


def test_confused_on_two_recent_days_with_the_same_word():
    # 直近 CONFUSION_DAYS 日に、同じ相手と 2 日以上（日数は records が 1 日 1 組 1 回で数える）
    assert "w1" not in weak.analyze({}, [], {"w1": {"w2": 1, "w3": 1}}, {"w1": {"w2": 1, "w3": 1}}).weak
    assert "w1" not in weak.analyze({}, [], {"w1": {"w2": 5}}, {"w1": {"w2": 1}}).weak  # 前に何度も取り違えたが、今は 1 日だけ
    result = weak.analyze({}, [], {"w1": {"w2": 2, "w3": 1}}, {"w1": {"w2": 2}})
    assert result.weak["w1"] == ["confusion"]
    assert result.partners_of("w1") == ["w2", "w3"]


def test_high_difficulty_counts_only_while_the_last_answer_is_wrong(records):
    for day in range(3):
        records.review("ko", "word", "w1", "meaning", practice="word_meaning", rating="again", correct=False, now=NOW + timedelta(days=day))
    cards = records.cards("ko")
    assert cards[("w1", "meaning")].card.difficulty >= weak.DIFFICULTY
    assert "difficulty" in weak.analyze(cards, records.counted_reviews("ko"), {}).weak["w1"]
    # 直近の解答が正解になれば、難しさが高いままでも苦手ではない（今はつまずいていない）
    records.review("ko", "word", "w1", "meaning", practice="word_meaning", rating="good", correct=True, now=NOW + timedelta(days=3))
    cards = records.cards("ko")
    assert cards[("w1", "meaning")].card.difficulty >= weak.DIFFICULTY
    assert "w1" not in weak.analyze(cards, records.counted_reviews("ko"), {}).weak


def test_spell_difficulty_is_not_counted(records):
    for day in range(3):
        records.review("ko", "word", "w1", "spell", practice="word_spell", rating="again", correct=False, now=NOW + timedelta(days=day))
    reviews = records.counted_reviews("ko")
    assert "difficulty" not in weak.analyze(records.cards("ko"), reviews, {}).weak.get("w1", [])


def test_slow_answers_against_own_median():
    base = answers(word="w0", results=[True] * weak.MEDIAN_MIN, elapsed=1.5)
    result = weak.analyze({}, base + answers(results=[True] * 3, elapsed=3.2), {})
    assert result.medians["meaning"] == 1.5
    assert result.weak["w1"] == ["slow"]
    # 3 回続かなければ苦手にしない
    assert "w1" not in weak.analyze({}, base + answers(results=[True, True], elapsed=3.2) + answers(results=[True], elapsed=1.0), {}).weak
    # 中央値がたまっていない面では見ない
    assert "w1" not in weak.analyze({}, answers(results=[True] * 3, elapsed=9.0), {}).weak


def test_timing_from_median():
    result = weak.analyze({}, answers(word="w0", face="listen", results=[True] * weak.MEDIAN_MIN, elapsed=2.0), {})
    assert result.timing() == {"listen": {"fast": 1.4, "slow": 3.0, "median": 2.0}}


def test_face_for_issue_depends_on_the_practice():
    meaning = {"tag": "語彙の選択", "axis": "meaning"}
    assert weak.face_for_issue({"tag": "받침", "axis": "orthography"}, "sentence_dictation") == "spell"
    assert weak.face_for_issue(meaning, "sentence_ko_to_ja") == "meaning"  # 韓国語を見て意味を答える
    assert weak.face_for_issue(meaning, "sentence_ja_to_ko") == "reverse"  # 意味から韓国語を出す
    assert weak.face_for_issue(meaning, "sentence_compose") == "reverse"
    assert weak.face_for_issue(meaning, "sentence_cloze") == "reverse"
    assert weak.face_for_issue(meaning, "sentence_dictation") == "listen"  # 聞いて書く
    assert weak.face_for_issue({"tag": "その他", "axis": "meaning"}, "sentence_ko_to_ja") == "meaning"
    assert weak.face_for_issue({"tag": "助詞", "axis": "grammar"}, "sentence_ja_to_ko") is None
    assert weak.face_for_issue({"tag": "띄어쓰기", "axis": "orthography"}, "sentence_ja_to_ko") is None
