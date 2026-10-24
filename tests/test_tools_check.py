from __future__ import annotations

import pytest

from app.claude_cli import KIND_OVERLOADED, KIND_USAGE_LIMIT, ClaudeError
from tools import batch
from tools.batch import BadOutput, StopRun
from tools.ko.morph import Lexicon, eojeols
from tools.verify_sentences import Checker, clean

pytest.importorskip("kiwipiepy")

WORDS = {
    "w-저": {"lemma": "저", "pos": "代名詞"},
    "w-물": {"lemma": "물", "pos": "名詞"},
    "w-주다": {"lemma": "주다", "pos": "動詞"},
    "w-커피": {"lemma": "커피", "pos": "名詞"},
    "w-마시다": {"lemma": "마시다", "pos": "動詞"},
    "w-공부하다": {"lemma": "공부하다", "pos": "動詞"},
    "w-스물": {"lemma": "스물", "pos": "数詞"},
    "w-다섯": {"lemma": "다섯", "pos": "数詞"},
    "w-살": {"lemma": "살", "pos": "依存名詞"},
    "w-이-この": {"lemma": "이", "pos": "冠形詞"},
    "w-이": {"lemma": "이", "pos": "数詞"},
    "w-십": {"lemma": "십", "pos": "数詞"},
    "w-오": {"lemma": "오", "pos": "数詞"},
    "w-차1": {"lemma": "차", "pos": "名詞"},
    "w-차2": {"lemma": "차", "pos": "名詞"},
    "w-안녕히가세요": {"lemma": "안녕히 가세요", "pos": "表現"},
    "w-이름": {"lemma": "이름", "pos": "名詞"},
}
LEXICON = Lexicon(allowed=WORDS, known={"사과": "L1-U09「果物」で出る語"})
UNIT = {"w-물", "w-커피", "w-마시다", "w-공부하다", "w-차1", "w-스물", "w-다섯", "w-안녕히가세요"}


@pytest.fixture(scope="module")
def checker():
    return Checker()


def sentence(ko, tokens, eojeol=0):
    return {"ko": ko, "tokens": [{"surface": s, "word_ids": list(ids)} for s, ids in tokens], "cloze": {"eojeol": eojeol}}


def test_eojeols_strip_punctuation():
    assert [s for s, _, _ in eojeols("네, 감사합니다.")] == ["네", "감사합니다"]


def test_good_sentence_passes(checker):
    s = sentence("커피 마셔요.", [("커피", ["w-커피"]), ("마셔요", ["w-마시다"])])
    assert checker.check(s, LEXICON, UNIT) == []


def test_missing_word_id_is_added(checker):
    s = sentence("물 주세요.", [("물", ["w-물"]), ("주세요", [])])
    assert checker.check(s, LEXICON, UNIT) == []
    assert s["tokens"][1]["word_ids"] == ["w-주다"]


def test_contraction_and_hada_verb(checker):
    s = sentence("제 이름을 공부해요.", [("제", ["w-저"]), ("이름을", ["w-이름"]), ("공부해요", ["w-공부하다"])], eojeol=2)
    assert checker.check(s, LEXICON, UNIT) == []


def test_word_from_later_unit_is_a_problem(checker):
    s = sentence("사과 주세요.", [("사과", []), ("주세요", ["w-주다"])])
    problems = checker.check(s, LEXICON, UNIT)
    assert any("まだ出ていない単語「사과」" in p for p in problems)


def test_unknown_word_is_a_problem_but_names_are_allowed(checker):
    s = sentence("민수 씨, 커피 마셔요.", [("민수", []), ("씨", []), ("커피", ["w-커피"]), ("마셔요", ["w-마시다"])], eojeol=2)
    assert checker.check(s, LEXICON, UNIT) == []
    s = sentence("우유 마셔요.", [("우유", []), ("마셔요", ["w-마시다"])], eojeol=1)
    assert any("一覧にない語「우유」" in p for p in checker.check(s, LEXICON, UNIT))


def test_listed_word_must_be_in_its_eojeol(checker):
    s = sentence("커피 마셔요.", [("커피", ["w-물"]), ("마셔요", ["w-마시다"])])
    assert any("물" in p and "見当たらない" in p for p in checker.check(s, LEXICON, UNIT))


def test_homographs_need_an_explicit_id(checker):
    s = sentence("차 마셔요.", [("차", []), ("마셔요", ["w-마시다"])])
    assert any("同じ綴り" in p for p in checker.check(s, LEXICON, UNIT))


def test_numeral_compound_and_expression(checker):
    s = sentence("스물다섯 살이에요.", [("스물다섯", []), ("살이에요", ["w-살"])])
    assert checker.check(s, LEXICON, UNIT) == []
    assert s["tokens"][0]["word_ids"] == ["w-스물", "w-다섯"]
    s = sentence("이십오 살이에요.", [("이십오", []), ("살이에요", ["w-살"])])
    assert "このユニットの単語が入っていない" in checker.check(s, LEXICON, UNIT)
    assert s["tokens"][0]["word_ids"] == ["w-이", "w-십", "w-오"]
    s = sentence("안녕히 가세요.", [("안녕히", ["w-안녕히가세요"]), ("가세요", [])])
    assert checker.check(s, LEXICON, UNIT) == []


def test_unit_word_count_and_digits(checker):
    s = sentence("저 주세요.", [("저", ["w-저"]), ("주세요", ["w-주다"])])
    assert "このユニットの単語が入っていない" in checker.check(s, LEXICON, UNIT)
    s = sentence("커피 2잔 주세요.", [("커피", ["w-커피"]), ("2잔", []), ("주세요", ["w-주다"])])
    assert any("数字" in p for p in checker.check(s, LEXICON, UNIT))


def test_tokens_must_match_the_sentence(checker):
    s = sentence("커피 마셔요.", [("커피마셔요", ["w-커피"])])
    assert any("tokens" in p for p in checker.check(s, LEXICON, UNIT))


def test_clean_rebuilds_tokens_and_answer():
    raw = {
        "ko": " 커피  마셔요. ",
        "ja": "コーヒーを飲みます。",
        "register": "해요체",
        "scene": "カフェで",
        "tokens": [{"surface": "커피", "word_ids": ["w-커피", "w-커피"]}, {"surface": "마셔요.", "word_ids": ["w-마시다"]}],
        "grammar": ["-아/어요", "-아/어요"],
        "cloze": {"eojeol": 1, "answer": "마셔", "hint_ja": "飲みます"},
        "variants": {"ko": ["커피 마셔요.", "커피를 마셔요."], "ja": ["コーヒー飲みます。"]},
    }
    s = clean(raw)
    assert s["ko"] == "커피 마셔요."
    assert s["tokens"] == [{"surface": "커피", "word_ids": ["w-커피"]}, {"surface": "마셔요", "word_ids": []}]
    assert s["cloze"]["answer"] == "마셔요"
    assert s["grammar"] == ["-아/어요"]
    assert s["variants"]["ko"] == ["커피를 마셔요."]


# ---- batch ----


def test_batch_retries_once_then_counts_failure():
    calls = []

    def work(task):
        calls.append(task)
        if task == "bad":
            raise BadOutput("だめ")
        if task == "flaky" and calls.count("flaky") == 1:
            raise ClaudeError("混んでいます", kind=KIND_OVERLOADED)
        return task.upper()

    saved = {}
    outcome = batch.run("t", ["ok", "bad", "flaky"], work, saved.__setitem__, label=str)
    assert saved == {"ok": "OK", "flaky": "FLAKY"}
    assert outcome.done == 2 and [f[0] for f in outcome.failed] == ["bad"]
    assert calls.count("bad") == 2


def test_batch_stops_on_usage_limit_and_keeps_finished_work():
    saved = {}

    def work(task):
        if task == "b":
            raise ClaudeError("利用枠の上限", kind=KIND_USAGE_LIMIT)
        return task

    with pytest.raises(StopRun, match="利用枠"):
        batch.run("t", ["a", "b", "c"], work, saved.__setitem__, label=str, parallel=1)
    assert saved == {"a": "a"}
