from __future__ import annotations

import random
from datetime import datetime, timedelta

from app import content, langs, session, settings
from app.records import Records, make_scheduler

pack = langs.get("ko")
NOW = datetime(2026, 11, 4, 9, 0).astimezone()


def build(root, unit="T-U02", cards=None, now=NOW, **overrides):
    cfg = {**settings.DEFAULTS, **overrides}
    return session.build(content.load(root, "ko"), pack, cfg, cards or {}, now, unit, rng=random.Random(1))


def answer(records, word_id, rating="good", face="meaning", at=NOW):
    records.review("ko", "word", word_id, face, practice=f"word_{face}", rating=rating, correct=rating != "again", now=at)


def test_rounds_and_ids(root):
    plan = build(root)
    assert [r["key"] for r in plan["rounds"]] == ["words", "sentences", "output", "finish"]
    assert sum(r["count"] for r in plan["rounds"]) == len(plan["items"])
    assert len({i["id"] for i in plan["items"]}) == len(plan["items"])
    assert plan["estimate_min"] >= 1


def test_intro_comes_before_recall(root):
    plan = build(root)
    items = [i for i in plan["items"] if i["round"] == "words"]
    for word_id in {i["word"]["id"] for i in items if i["type"] == "word_intro"}:
        intro = next(k for k, i in enumerate(items) if i["type"] == "word_intro" and i["word"]["id"] == word_id)
        recall = next(k for k, i in enumerate(items) if i["type"] == "word_meaning" and i["word"]["id"] == word_id)
        assert session.RECALL_GAP[0] <= recall - intro <= session.RECALL_GAP[1] + 2


def test_new_words_limited_by_setting(root):
    plan = build(root, new_words_per_day=2)
    intros = [i for i in plan["items"] if i["type"] == "word_intro"]
    assert len(intros) == 2


def test_options_exclude_homographs_and_contain_answer(root):
    plan = build(root)
    for item in plan["items"]:
        if "options" not in item or not item["type"].startswith("word_"):
            continue
        ids = [o["word_id"] for o in item["options"]]
        assert item["answer_id"] in ids
        assert len(set(ids)) == len(ids)
        for h in item["word"]["homographs"]:
            assert h not in ids
        assert 2 <= len(ids) <= session.OPTIONS


def test_reverse_options_are_korean(root):
    plan = build(root)
    reverse = [i for i in plan["items"] if i["type"] == "word_reverse"]
    for item in reverse:
        assert item["prompt"]["text"] == item["word"]["meaning"]
        assert all("tts" in o for o in item["options"])


def test_sentence_items_have_expected(root):
    plan = build(root)
    for item in plan["items"]:
        if item["type"] in ("sentence_cloze", "sentence_dictation", "sentence_ja_to_ko", "sentence_trace", "word_spell"):
            assert item["expected"]
        if item["type"] == "sentence_cloze":
            assert item["cloze"]["answer"] in item["sentence"]["ko"]
        if item["type"] == "sentence_listen_choose":
            assert item["answer_id"] in {o["sentence_id"] for o in item["options"]}


def test_cloze_falls_back_to_dictation_without_cloze(root):
    # T-U02 の 3 つ目の文は穴埋めを持たない。導入→聞いて選ぶ→穴埋め の順なので 3 つ目は穴埋めの番だが、書き取りになる
    plan = build(root, new_sentences_per_day=3)
    kinds = [i["type"] for i in plan["items"] if i["round"] == "sentences"]
    assert kinds == ["sentence_intro", "sentence_listen_choose", "sentence_dictation"]


# ---- 記録から組む今日の学習 ----


def test_first_day_is_new_words_in_order(root):
    plan = build(root, unit=None, new_words_per_day=3)
    assert plan["mode"] == "today"
    intros = [i["word"]["lemma"] for i in plan["items"] if i["type"] == "word_intro"]
    assert intros == ["물", "빵", "커피"]
    assert plan["review_count"] == 0
    assert plan["unit"]["id"] == "T-U01"


def test_new_word_quota_counts_words_started_today(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0001")
    answer(records, "t-w-0002")
    plan = build(root, unit=None, cards=records.cards("ko"), new_words_per_day=3)
    assert [i["word"]["lemma"] for i in plan["items"] if i["type"] == "word_intro"] == ["커피"]
    # 次の日は枠が戻る
    tomorrow = build(root, unit=None, cards=records.cards("ko"), now=NOW + timedelta(days=1), new_words_per_day=3)
    assert len([i for i in tomorrow["items"] if i["type"] == "word_intro"]) == 3


def test_due_cards_become_reviews(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0001", "again")  # 翌日に出る
    answer(records, "t-w-0002", "easy")  # しばらく出ない
    cards = records.cards("ko")
    assert build(root, unit=None, cards=cards)["review_count"] == 0  # 今日はもう済んでいる
    plan = build(root, unit=None, cards=cards, now=NOW + timedelta(days=1))
    reviews = [i for i in plan["items"] if i["type"] == "word_meaning" and i["word"]["id"] in ("t-w-0001", "t-w-0002")]
    assert [i["word"]["id"] for i in reviews] == ["t-w-0001"]


def test_review_limit(root):
    records = Records(root, make_scheduler(fuzz=False))
    for wid in ("t-w-0001", "t-w-0002", "t-w-0003"):
        answer(records, wid, "again")
    plan = build(root, unit=None, cards=records.cards("ko"), now=NOW + timedelta(days=1), review_limit=2, new_words_per_day=0)
    assert plan["review_count"] == 2


def test_faces_unlock_as_meaning_settles(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0003", "easy")  # 安定度 8 日ほど
    cards = records.cards("ko")
    assert session.unlocked_faces("t-w-0003", cards, settings.DEFAULTS) == ["listen", "reverse"]
    answer(records, "t-w-0003", "easy", face="reverse")
    assert "spell" in session.unlocked_faces("t-w-0003", records.cards("ko"), settings.DEFAULTS)
    plan = build(root, unit=None, cards=records.cards("ko"), now=NOW + timedelta(days=1))
    faces = {i["face"] for i in plan["items"] if i.get("word", {}).get("id") == "t-w-0003" and i["type"] != "word_intro"}
    assert {"listen", "spell"} <= faces


def test_word_state(root):
    records = Records(root, make_scheduler(fuzz=False))
    assert session.word_state("t-w-0001", {}, 21) == "new"
    answer(records, "t-w-0001")
    assert session.word_state("t-w-0001", records.cards("ko"), 21) == "learning"
    assert session.word_state("t-w-0001", records.cards("ko"), 1) == "mastered"


def test_unit_practice_reviews_started_words_of_the_unit(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0007")
    plan = build(root, unit="T-U02", cards=records.cards("ko"))
    assert plan["mode"] == "unit"
    assert "t-w-0007" not in {i["word"]["id"] for i in plan["items"] if i["type"] == "word_intro"}
    assert "t-w-0007" in {i["word"]["id"] for i in plan["items"] if i["type"] == "word_meaning"}


def test_sentences_prefer_new_words_and_skip_unseen(root):
    plan = build(root, unit=None, new_words_per_day=1)  # 新出は 물 だけ
    sentence_ids = {i["sentence"]["id"] for i in plan["items"] if i["round"] == "sentences"}
    # 물 주세요（まだ見ていない語なし）と 커피가 있어요（1 語）は出せる。빵을 먹어요（2 語）は出せない
    assert "t-s-U02-001" not in sentence_ids
    first = next(i for i in plan["items"] if i["round"] == "sentences")
    assert first["sentence"]["id"] == "t-s-U01-001"
