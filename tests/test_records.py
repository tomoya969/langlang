from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from app.records import SCHEMA, Records, day_start, make_scheduler

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


def review_sentence(records, rating, at):
    return records.review("ko", "sentence", "s1", "", practice="sentence_cloze", rating=rating, correct=rating != "again", now=at)


def test_sentence_stage_moves_with_first_answer_of_the_day(records):
    assert review_sentence(records, "good", MORNING).card.stage == 2  # 導入のあとの最初の出題は段階 1
    assert review_sentence(records, "again", MORNING + timedelta(hours=1)).card.stage == 2  # 同じ日の 2 回目は動かさない
    day = lambda n: MORNING + timedelta(days=n)  # noqa: E731
    assert review_sentence(records, "hard", day(1)).card.stage == 2
    assert review_sentence(records, "again", day(2)).card.stage == 1
    assert review_sentence(records, "again", day(3)).card.stage == 1  # 最低は 1
    for n in range(4, 10):
        review_sentence(records, "easy", day(n))
    assert records.cards("ko", "sentence")[("s1", "")].stage == 5  # 最高は 5


def test_words_have_no_stage(records):
    assert review(records).card.stage is None
    assert "stage" not in review(records).card.to_dict()


def test_old_records_file_gets_stage_column(tmp_path):
    path = tmp_path / "records" / "langlang.db"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.replace("    stage         INTEGER,         -- 文の段階（1〜5）。単語は NULL\n", ""))
        assert "stage" not in {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
    records = Records(tmp_path, make_scheduler(fuzz=False))
    assert review_sentence(records, "good", MORNING).card.stage == 2
