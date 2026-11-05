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


def test_confused_twice_with_the_same_word():
    assert "w1" not in weak.analyze({}, [], {"w1": {"w2": 1, "w3": 1}}).weak
    result = weak.analyze({}, [], {"w1": {"w2": 2, "w3": 1}})
    assert result.weak["w1"] == ["confusion"]
    assert result.partners_of("w1") == ["w2", "w3"]


def test_high_difficulty(records):
    for day in range(3):
        records.review("ko", "word", "w1", "meaning", practice="word_meaning", rating="again", correct=False, now=NOW + timedelta(days=day))
    cards = records.cards("ko")
    assert cards[("w1", "meaning")].card.difficulty >= weak.DIFFICULTY
    assert "difficulty" in weak.analyze(cards, [], {}).weak["w1"]


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


def test_face_for_issue():
    assert weak.face_for_issue({"tag": "받침", "axis": "orthography"}) == "spell"
    assert weak.face_for_issue({"tag": "語彙の選択", "axis": "meaning"}) == "meaning"
    assert weak.face_for_issue({"tag": "その他", "axis": "meaning"}) == "meaning"
    assert weak.face_for_issue({"tag": "助詞", "axis": "grammar"}) is None
    assert weak.face_for_issue({"tag": "띄어쓰기", "axis": "orthography"}) is None
