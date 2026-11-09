from __future__ import annotations

import random
from datetime import datetime, timedelta

from app import content, langs, session, settings
from app.records import Records, make_scheduler
from app.weak import Analysis
from conftest import word as conftest_word

pack = langs.get("ko")
NOW = datetime(2026, 11, 4, 9, 0).astimezone()


def build(root, unit="T-U02", cards=None, now=NOW, records=None, **overrides):
    cfg = {**settings.DEFAULTS, **overrides}
    if records is not None:
        cards = records.cards("ko")
        sentence_cards = {sid: c for (sid, _), c in records.cards("ko", "sentence").items()}
    else:
        sentence_cards = {}
    return session.build(content.load(root, "ko"), pack, cfg, cards or {}, now, unit, rng=random.Random(1), sentence_cards=sentence_cards)


def answer(records, word_id, rating="good", face="meaning", at=NOW):
    records.review("ko", "word", word_id, face, practice=f"word_{face}", rating=rating, correct=rating != "again", now=at)


def answer_sentence(records, sentence_id, *ratings, start=NOW):
    """1 日ずつ空けて答える（どれも、その日の最初の解答として段階を動かす）。"""
    for days, rating in enumerate(ratings):
        records.review("ko", "sentence", sentence_id, "", practice="sentence_listen_choose", rating=rating, correct=rating != "again", now=start + timedelta(days=days))


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


def test_new_sentence_is_introduced_then_asked_after_a_gap(root):
    plan = build(root, unit=None)
    items = [i for i in plan["items"] if i["round"] == "sentences"]
    intros = [i["sentence"]["id"] for i in items if i["type"] == "sentence_intro"]
    assert len(intros) == plan["new_sentence_count"] == 5
    gaps = []
    for sid in intros:
        intro = next(k for k, i in enumerate(items) if i["type"] == "sentence_intro" and i["sentence"]["id"] == sid)
        first = next(k for k, i in enumerate(items) if i["type"] != "sentence_intro" and i["sentence"]["id"] == sid)
        assert items[first]["type"] == "sentence_listen_choose"  # 段階 1
        gaps.append(first - intro - 1)
    # 復習がなく、列の終わりで間を埋めるものが尽きても、導入を前に出してはさむ
    assert all(g >= session.SENTENCE_GAP[0] for g in gaps)
    # まだ段階 3 の文がないので、産出ラウンドはない
    assert not [i for i in plan["items"] if i["round"] == "output"]


def test_new_sentence_quota_counts_sentences_started_today(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer_sentence(records, "t-s-U01-001", "good")
    plan = build(root, unit=None, records=records, new_sentences_per_day=2)
    assert plan["new_sentence_count"] == 1
    # 今日答えた文は、今日はもう出ない
    assert "t-s-U01-001" not in {i["sentence"]["id"] for i in plan["items"] if i["round"] in ("sentences", "output")}


def test_due_sentences_get_the_practice_of_their_stage(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer_sentence(records, "t-s-U01-001", "again")  # 段階 1 のまま。翌日に出る
    answer_sentence(records, "t-s-U02-003", "good")  # 段階 2。穴埋めがない文
    later = NOW + timedelta(days=30)
    plan = build(root, unit=None, records=records, now=later, new_sentences_per_day=0)
    kinds = {i["sentence"]["id"]: i["type"] for i in plan["items"] if i["round"] == "sentences"}
    assert kinds == {"t-s-U01-001": "sentence_ko_to_ja", "t-s-U02-003": "sentence_dictation"}  # 段階 1 の復習は韓→日訳
    assert plan["review_count"] == 2


def test_output_round_takes_stage_three_and_up_within_the_limit(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer_sentence(records, "t-s-U01-001", "good", "good", "good")  # 段階 4。文法あり → 応用作文
    answer_sentence(records, "t-s-U02-003", "good", "good", "good")  # 段階 4。文法なし → 日→韓
    answer_sentence(records, "t-s-U01-002", "good", "good")  # 段階 3
    answer_sentence(records, "t-s-U02-001", "good", "good", "good", "good")  # 段階 5
    answer_sentence(records, "t-s-U02-002", "good", "good")  # 段階 3
    plan = build(root, unit=None, records=records, now=NOW + timedelta(days=365))
    output = [i for i in plan["items"] if i["round"] == "output"]
    assert len(output) == session.OUTPUT_ITEMS
    by_id = {i["sentence"]["id"]: i for i in plan["items"] if i["round"] in ("sentences", "output")}
    if "t-s-U01-001" in {i["sentence"]["id"] for i in output}:
        assert by_id["t-s-U01-001"]["type"] == "sentence_compose"
        assert by_id["t-s-U01-001"]["required"] == "-(으)세요"
    assert by_id["t-s-U02-003"]["type"] in ("sentence_ja_to_ko", "sentence_dictation")
    # 産出に回らなかった段階 3〜5 の文は書き取り
    rest = [i for i in plan["items"] if i["round"] == "sentences"]
    assert len(rest) == 2 and all(i["type"] == "sentence_dictation" for i in rest)
    assert {i["stage"] for i in [*output, *rest]} <= {3, 4, 5}


def test_unit_practice_includes_started_sentences_of_the_unit(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer_sentence(records, "t-s-U02-001", "good")  # 段階 2。期限はまだ
    plan = build(root, unit="T-U02", records=records)
    items = [i for i in plan["items"] if i["round"] == "sentences"]
    assert {i["sentence"]["unit"] for i in items} == {"T-U02"}
    assert any(i["sentence"]["id"] == "t-s-U02-001" and i["type"] == "sentence_cloze" for i in items)
    assert "t-s-U02-001" not in {i["sentence"]["id"] for i in items if i["type"] == "sentence_intro"}


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


# ---- 苦手と取り違え ----


def weak_of(*word_ids, partners=None):
    return Analysis(weak={w: ["misses"] for w in word_ids}, partners=partners or {})


def test_weak_slots_add_weak_words_before_they_are_due(root):
    records = Records(root, make_scheduler(fuzz=False))
    for wid in ("t-w-0001", "t-w-0002", "t-w-0003"):
        answer(records, wid)  # 翌日はまだ期限が来ず、ほかの面も出し始めない
    tomorrow = NOW + timedelta(days=1)
    cards = records.cards("ko")
    plan = session.build(
        content.load(root, "ko"), pack, {**settings.DEFAULTS, "weak_slots": 2, "new_words_per_day": 0}, cards, tomorrow,
        rng=random.Random(1), analysis=weak_of("t-w-0001", "t-w-0002", "t-w-0003"),
    )
    weak_items = [i for i in plan["items"] if i.get("weak")]
    assert len(weak_items) == plan["weak_slot_count"] == 2
    assert {i["type"] for i in weak_items} == {"word_meaning"}
    # 今日もう答えた単語は、苦手枠に入れない（FSRS を動かせないため）
    today = session.build(content.load(root, "ko"), pack, {**settings.DEFAULTS, "new_words_per_day": 0}, cards, NOW, rng=random.Random(1), analysis=weak_of("t-w-0001"))
    assert today["weak_slot_count"] == 0


def test_weak_only_practice(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0001")
    answer(records, "t-w-0001", face="listen")
    answer(records, "t-w-0002")
    plan = session.build(content.load(root, "ko"), pack, dict(settings.DEFAULTS), records.cards("ko"), NOW, rng=random.Random(1), analysis=weak_of("t-w-0001"), weak_only=True)
    assert plan["mode"] == "weak"
    assert sorted((i["word"]["id"], i["face"]) for i in plan["items"]) == [("t-w-0001", "listen"), ("t-w-0001", "meaning")]
    assert [r["key"] for r in plan["rounds"] if r["count"]] == ["words"]


def word_obj(num, lemma, ja, tags=(), pos="名詞", **extra):
    return content._word(conftest_word(num, lemma, ja, "T-U01", pos=pos, tags=list(tags), **extra))


def test_distractors_include_confused_words_and_avoid_shared_scenes():
    target = word_obj(1, "사다", "買う", tags=["買い物"], pos="動詞", confusables=["t-w-0002"])
    near = word_obj(2, "싸다", "安い", tags=["買い物"], pos="動詞")
    partner = word_obj(3, "자다", "寝る", tags=["家"], pos="動詞")
    same_scene = [word_obj(10 + i, f"가{i}", f"買い物{i}", tags=["買い物"], pos="動詞") for i in range(5)]
    distant = [word_obj(20 + i, f"나{i}", f"遠い{i}", tags=["天気"], pos="動詞") for i in range(5)]
    pool = [target, near, partner, *same_scene, *distant]
    rng = random.Random(0)
    for _ in range(20):
        picked = session._distractors(target, pool, rng, familiar=False, partners=["t-w-0003"])
        assert partner in picked  # 取り違えた相手は必ず入れる
        assert near not in picked  # 慣れるまでは形の近い語を入れない
        assert not [w for w in picked if w in same_scene]  # 場面のタグが重ならない語から選ぶ
    familiar = session._distractors(target, pool, rng, familiar=True, partners=["t-w-0003"])
    assert partner in familiar and near in familiar


def test_sentences_prefer_weak_words(root):
    records = Records(root, make_scheduler(fuzz=False))
    for wid in ("t-w-0001", "t-w-0003", "t-w-0004", "t-w-0008"):
        answer(records, wid)
    later = NOW + timedelta(days=1)
    cfg = {**settings.DEFAULTS, "new_words_per_day": 0, "new_sentences_per_day": 1}
    c = content.load(root, "ko")
    plan = session.build(c, pack, cfg, records.cards("ko"), later, rng=random.Random(1), analysis=weak_of("t-w-0008"))
    first = next(i for i in plan["items"] if i["round"] == "sentences")
    assert first["sentence"]["id"] == "t-s-U02-002"  # 우유를 마셔요（마시다 が苦手）


def test_start_level_skips_earlier_levels(root):
    import json

    path = root / "content" / "ko" / "units.json"
    units = json.loads(path.read_text(encoding="utf-8"))
    units[1]["level"] = 2
    path.write_text(json.dumps(units, ensure_ascii=False), encoding="utf-8")
    words_path = root / "content" / "ko" / "words.json"
    words = json.loads(words_path.read_text(encoding="utf-8"))
    for w in words:
        if w["unit"] == "T-U02":
            w["level"] = 2
    words_path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
    plan = build(root, unit=None, start_level=2, new_words_per_day=2)
    assert [i["word"]["unit"] for i in plan["items"] if i["type"] == "word_intro"] == ["T-U02", "T-U02"]
    assert plan["unit"]["id"] == "T-U02"


def test_distractors_never_include_synonyms_or_words_sharing_a_meaning():
    target = word_obj(1, "보다", "見る", pos="動詞", meanings=[{"ja": "見る", "primary": True}, {"ja": "会う", "primary": False}])
    shares = word_obj(2, "만나다", "会う", pos="動詞")  # 보다 の主な意味でない訳と同じ
    linked = word_obj(3, "구경하다", "見物する", pos="動詞", synonyms=["t-w-0001"])  # 相手の側からだけ紐づいている
    hidden = word_obj(4, "살펴보다", "調べる", pos="動詞", synonyms=["t-w-0001"], hidden_synonyms=["t-w-0001"])  # 単語帳に出さない組もダミーにしない
    others = [word_obj(10 + i, f"다{i}", f"別の意味{i}", pos="動詞") for i in range(6)]
    pool = [target, shares, linked, hidden, *others]
    rng = random.Random(0)
    for _ in range(50):
        picked = session._distractors(target, pool, rng)
        assert shares not in picked and linked not in picked and hidden not in picked
        assert len(picked) == session.OPTIONS - 1


def test_listen_choose_skips_sentences_with_the_same_translation(root):
    import json

    path = root / "content" / "ko" / "sentences" / "T-U02.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[1]["ja"] = "水を、ください！"  # t-s-U01-001 の許容訳「水をください。」と記号を除けば同じ
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    c = content.load(root, "ko")
    rng = random.Random(0)
    for _ in range(30):
        item = session._sentence_item("listen_choose", c.sentence("t-s-U01-001"), c, set(), rng)
        assert "t-s-U02-002" not in {o["sentence_id"] for o in item["options"]}


# ---- クロスレビューの指摘（1-2・1-6・1-7・1-8・1-12・1-19） ----


def test_listening_options_never_sound_the_same():
    # 입（口）と 잎（葉）は発音が同じ。聞き取りでは、取り違えの相手・形の近い語に入っていても並べない
    mouth = word_obj(1, "입", "口", pos="名詞", confusables=["t-w-0002"])
    leaf = word_obj(2, "잎", "葉", pos="名詞")
    others = [word_obj(10 + i, f"말{i}", f"別{i}", pos="名詞") for i in range(6)]
    pool = [mouth, leaf, *others]
    rng = random.Random(0)
    for _ in range(50):
        item = session._word_item("listen", mouth, pool, pack, rng, True, ["t-w-0002"])
        assert "葉" not in {o["label"] for o in item["options"]}
    # 文字を見る意味の面では、見分けられるので入れてよい
    assert any("葉" in {o["label"] for o in session._word_item("meaning", mouth, pool, pack, rng, True, ["t-w-0002"])["options"]} for _ in range(10))


def test_distractors_do_not_clash_with_each_other():
    target = word_obj(1, "가다", "行く", pos="動詞")
    a = word_obj(2, "보다", "見る", pos="動詞", synonyms=["t-w-0003"])
    b = word_obj(3, "구경하다", "見物する", pos="動詞")  # a の類語
    c = word_obj(4, "놓다", "置く", pos="動詞")
    d = word_obj(5, "두다", "置く", pos="動詞")  # c と表示が同じ
    e = word_obj(6, "차", "お茶", pos="動詞", homographs=["t-w-0007"])
    f = word_obj(7, "차", "車", pos="動詞", homographs=["t-w-0006"])  # e と同じ綴り
    g = word_obj(8, "먹다", "食べる・いただく", pos="動詞")
    h = word_obj(9, "드시다", "召し上がる・いただく", pos="動詞")  # g と訳が重なる
    pool = [target, a, b, c, d, e, f, g, h]
    rng = random.Random(1)
    clashing = [{"t-w-0002", "t-w-0003"}, {"t-w-0004", "t-w-0005"}, {"t-w-0006", "t-w-0007"}, {"t-w-0008", "t-w-0009"}]
    for face in ("meaning", "reverse"):
        for _ in range(100):
            ids = {o["word_id"] for o in session._word_item(face, target, pool, pack, rng)["options"]}
            assert len(ids) == session.OPTIONS
            assert not any(pair <= ids for pair in clashing)


def test_first_questions_follow_intro_order_with_gaps():
    # 出題は導入の順（列の終わりで詰めるときも）。どの出題も導入から RECALL_GAP の最小の数以上あとに出る
    intros = [({"type": "intro", "n": n}, {"type": "first", "n": n}) for n in range(6)]
    for seed in range(50):
        items = session._interleave(intros, [{"type": "review"}] * (seed % 4), session.RECALL_GAP, random.Random(seed))
        firsts = [i["n"] for i in items if i["type"] == "first"]
        assert firsts == sorted(firsts)
        for n in range(6):
            intro = next(k for k, i in enumerate(items) if i["type"] == "intro" and i["n"] == n)
            first = next(k for k, i in enumerate(items) if i["type"] == "first" and i["n"] == n)
            assert first - intro - 1 >= session.RECALL_GAP[0]


def test_sentence_reviews_are_capped_and_output_goes_to_the_least_recently_produced(root):
    records = Records(root, make_scheduler(fuzz=False))
    for sid in ("t-s-U01-001", "t-s-U01-002", "t-s-U02-001", "t-s-U02-002"):
        answer_sentence(records, sid, "good", "good")  # 段階 3
    later = NOW + timedelta(days=365)
    c = content.load(root, "ko")
    sentence_cards = {sid: card for (sid, _), card in records.cards("ko", "sentence").items()}
    cfg = {**settings.DEFAULTS, "sentence_review_limit": 3, "new_sentences_per_day": 0}
    plan = session.build(c, pack, cfg, {}, later, rng=random.Random(1), sentence_cards=sentence_cards)
    assert sum(1 for i in plan["items"] if "stage" in i) == 3  # 文の復習は上限まで
    # 産出は、まだ産出していない文、次に最後の産出が古い文から
    produced = {"t-s-U01-001": later - timedelta(days=1), "t-s-U01-002": later - timedelta(days=30)}
    reviews = [(c.sentence(s), 3) for s in ("t-s-U01-001", "t-s-U01-002", "t-s-U02-001", "t-s-U02-002")]
    assert session.output_sentences(reviews, produced) == {"t-s-U02-001", "t-s-U02-002", "t-s-U01-002"}


def test_start_level_treats_earlier_levels_as_seen_and_skips_their_sentences(root):
    import json

    for name, key in (("units.json", "id"), ("words.json", "unit")):
        path = root / "content" / "ko" / name
        items = json.loads(path.read_text(encoding="utf-8"))
        for x in items:
            if x[key] == "T-U02":
                x["level"] = 2
        path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    plan = build(root, unit=None, start_level=2)
    new_sentences = {i["sentence"]["id"] for i in plan["items"] if i["type"] == "sentence_intro"}
    assert new_sentences and all(s.startswith("t-s-U02") for s in new_sentences)  # L1 の文は新しい文に出さない
    assert "t-s-U02-002" in new_sentences  # 우유（L1）は見た語として数えるので、まだ見ていない語は 마시다 だけ


def test_outline_counts_match_the_built_session(root):
    records = Records(root, make_scheduler(fuzz=False))
    answer(records, "t-w-0001")
    answer_sentence(records, "t-s-U01-001", "good", "good")
    cards = records.cards("ko")
    sentence_cards = {sid: card for (sid, _), card in records.cards("ko", "sentence").items()}
    later = NOW + timedelta(days=3)
    c = content.load(root, "ko")
    built = session.build(c, pack, dict(settings.DEFAULTS), cards, later, rng=random.Random(1), sentence_cards=sentence_cards)
    outlined = session.outline(session.plan(c, dict(settings.DEFAULTS), cards, later, sentence_cards=sentence_cards))
    for key in ("new_word_count", "new_sentence_count", "review_count", "weak_slot_count", "estimate_min", "unit"):
        assert outlined[key] == built[key], key
