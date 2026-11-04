from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.records import Records, day_start, make_scheduler

MORNING = datetime(2026, 11, 4, 9, 0).astimezone()


@pytest.fixture
def records(tmp_path):
    return Records(tmp_path, make_scheduler(fuzz=False))


def review(records, rating="good", at=MORNING, face="meaning"):
    return records.review("ko", "word", "w1", face, practice="word_meaning", rating=rating, correct=rating != "again", now=at, elapsed_sec=1.2, answer="w2")


def test_first_review_creates_card_and_schedules(records):
    result = review(records, "good")
    assert result.counted
    card = records.cards("ko")[("w1", "meaning")]
    assert card.stability > 0
    assert card.card.due.date() >= (MORNING + timedelta(days=2)).date()
    assert (records.path).exists()


def test_only_first_review_of_the_day_counts(records):
    review(records, "again")
    before = records.cards("ko")[("w1", "meaning")]
    second = review(records, "good", at=MORNING + timedelta(hours=1))
    assert not second.counted
    assert records.cards("ko")[("w1", "meaning")].card.due == before.card.due
    assert review(records, "good", at=MORNING + timedelta(days=1)).counted
    history = records.history("ko", "word", "w1")
    assert [h["counted"] for h in history] == [True, False, True]
    assert history[-1]["rating"] == "again"


def test_day_starts_at_four(records):
    late = datetime(2026, 11, 5, 2, 0).astimezone()  # 夜中の 2 時は前の日
    assert day_start(late) == datetime(2026, 11, 4, 4, 0).astimezone()
    review(records, "good", at=datetime(2026, 11, 4, 23, 0).astimezone())
    assert not review(records, "good", at=late).counted


def test_due_is_judged_by_day(records):
    review(records, "again", at=datetime(2026, 11, 4, 21, 0).astimezone())
    card = records.cards("ko")[("w1", "meaning")]
    # 翌日 21 時が期限でも、翌日の朝の学習で出す
    assert card.is_due(datetime(2026, 11, 5, 8, 0).astimezone())
    assert not card.is_due(datetime(2026, 11, 4, 22, 0).astimezone())


def test_cards_are_kept_per_language_and_face(records):
    review(records)
    review(records, face="listen")
    records.review("xx", "word", "w1", "meaning", practice="word_meaning", rating="good", correct=True, now=MORNING)
    assert set(records.cards("ko")) == {("w1", "meaning"), ("w1", "listen")}
    assert set(records.cards("xx")) == {("w1", "meaning")}


def test_bad_rating(records):
    with pytest.raises(ValueError):
        review(records, "great")
