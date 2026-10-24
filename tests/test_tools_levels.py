from __future__ import annotations

import pytest

from tools import assign_levels
from tools.assign_levels import bands, nikl_scores, rank, score_of, settle_units
from tools.batch import BadOutput
from tools.ko import nikl
from tools.work import Workspace

NIKL_TEXT = "\r\n".join(
    [
        "순위\t단어\t품사\t풀이\t등급",
        "",
        "25\t가다01\t동\t\tA",
        "150\t가다01\t보\t\tA",
        "1195\t가게\t명\t\tA",
        "898\t가격03\t명\t價格\tB",
        "\t서울\t고\t\tA",
        "6\t수02\t의\t방법\tA",
        "3000\t싶다\t보\t\tA",
        "\t구십\t수\t九十\tA",
    ]
)


def test_parse_merges_pos_and_keeps_rankless_rows():
    rows = nikl.parse(NIKL_TEXT)
    assert len(rows) == 8
    cands = {c["key"]: c for c in nikl.candidates(rows)}
    assert cands["가다01"]["lemma"] == "가다"
    assert cands["가다01"]["pos"] == "動詞"
    assert cands["가다01"]["nikl"]["pos"] == ["동", "보"]
    assert cands["가다01"]["nikl"]["rank"] == 25
    assert cands["서울"]["nikl"]["rank"] is None
    assert cands["싶다"]["excluded"] == "補助用言"
    assert "excluded" not in cands["가게"]


def test_lemma_drops_number_and_alias():
    assert nikl.lemma_of("도쿄(동경)") == "도쿄"
    assert nikl.lemma_of("가구03") == "가구"


def _cand(key, stage, rank):
    return {"key": key, "nikl": {"stage": stage, "rank": rank}}


def test_nikl_scores_spread_within_stage_and_put_rankless_last():
    scores = nikl_scores([_cand("a", 1, 10), _cand("b", 1, 20), _cand("c", 1, None), _cand("d", 2, 5), _cand("e", 3, 1)])
    assert scores["a"] == 0.0
    assert scores["b"] == pytest.approx(0.5)
    assert scores["c"] == 1.0
    assert scores["d"] == 1.0  # 2 段階が 1 語だけなら幅の下端
    assert scores["e"] == 3.0


def test_nikl_scores_share_position_on_ties():
    scores = nikl_scores([_cand("a", 1, 10), _cand("b", 1, 10), _cand("c", 1, 30)])
    assert scores["a"] == scores["b"] == pytest.approx(0.25)


def test_score_is_mean_with_cognate_bonus():
    tag = {"hanken": "5級", "origin": "固有語", "ja_cognate": False}
    assert score_of(0.5, tag) == pytest.approx(0.4)
    assert score_of(None, tag) == pytest.approx(0.3)
    cognate = {"hanken": "4級", "origin": "漢字語", "ja_cognate": True}
    assert score_of(1.0, cognate) == pytest.approx(0.7)
    assert score_of(0.0, {**cognate, "hanken": "5級"}) == 0.0


def _tag(hanken="5級", exclude="なし", pos="名詞"):
    return {"hanken": hanken, "origin": "固有語", "pos": pos, "ja_cognate": False, "exclude": exclude, "style": 1}


def test_rank_puts_fixed_words_in_l1_and_drops_excluded(tmp_path):
    ws = Workspace(tmp_path, "ko")
    cands = nikl.candidates(nikl.parse(NIKL_TEXT))
    ws.write("candidates.json", cands)
    tags = {c["key"]: _tag() for c in cands if not c.get("excluded")}
    tags["가다01"] = _tag(hanken="2級以上", pos="動詞")  # 固定枠なのでスコアが低くても L1
    tags["수02"] = _tag(exclude="文法")
    tags["구십"] = _tag(pos="数詞")
    ws.write("tags.json", tags)
    message = rank(ws, sizes={1: 2, 2: 1, 3: 1})
    assert "除外 2 語" in message
    ranking = ws.read("ranking.json")
    by_key = {e["key"]: e for e in ranking}
    assert by_key["가다01"]["level"] == 1 and by_key["가다01"]["fixed"] == "基本の用言"
    assert by_key["수02"]["excluded"] == "文法"
    assert by_key["싶다"]["excluded"] == "補助用言"
    levels = [by_key[k]["level"] for k in ("가게", "가격03", "서울", "구십")]
    assert sorted(levels) == [1, 2, 3, 4]


def test_bands_put_fixed_first_and_split_rest_evenly():
    entries = [{"key": f"f{i}", "fixed": "数", "score": 3.0} for i in range(3)]
    entries += [{"key": f"w{i}", "fixed": None, "score": i / 1000} for i in range(450)]
    result = bands(entries)
    assert [len(b) for b in result] == [3, 225, 225]
    assert result[1][0]["key"] == "w0" and result[2][-1]["key"] == "w449"


def test_settle_units_removes_duplicates_and_fills_leftovers():
    keys = [f"k{i}" for i in range(20)]
    units = [
        {"title": " A ", "scene": "s", "keys": keys[:12] + ["k0"]},
        {"title": "B", "scene": "s", "keys": keys[12:19] + ["unknown"]},
    ]
    settled = settle_units(units, keys)
    assert settled[0]["title"] == "A"
    assert settled[0]["keys"] == keys[:12]
    assert settled[1]["keys"] == keys[12:19] + ["k19"]


def test_settle_units_rejects_too_many_leftovers():
    keys = [f"k{i}" for i in range(20)]
    with pytest.raises(BadOutput):
        settle_units([{"title": "A", "scene": "s", "keys": keys[:10]}], keys)


def test_assign_ids_never_changes_existing(tmp_path):
    ws = Workspace(tmp_path, "ko")
    first = assign_levels.assign_ids(ws, ["a", "b"])
    assert first == {"a": "ko-w-0001", "b": "ko-w-0002"}
    second = assign_levels.assign_ids(ws, ["c", "b", "a"])
    assert second == {"a": "ko-w-0001", "b": "ko-w-0002", "c": "ko-w-0003"}
