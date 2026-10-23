from __future__ import annotations

import random

from app import content, langs, session, settings

pack = langs.get("ko")


def build(root, unit="T-U02", **overrides):
    cfg = {**settings.DEFAULTS, **overrides}
    return session.build(content.load(root, "ko"), pack, unit, cfg, random.Random(1))


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
