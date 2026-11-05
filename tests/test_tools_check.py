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
    "w-이거": {"lemma": "이거", "pos": "代名詞"},
    "w-뭐": {"lemma": "뭐", "pos": "代名詞"},
    "w-하다": {"lemma": "하다", "pos": "動詞"},
    "w-결혼": {"lemma": "결혼", "pos": "名詞"},
    "w-역사": {"lemma": "역사", "pos": "名詞"},
    "w-책": {"lemma": "책", "pos": "名詞"},
    "w-읽다": {"lemma": "읽다", "pos": "動詞"},
    "w-없다": {"lemma": "없다", "pos": "形容詞"},
    "w-여권": {"lemma": "여권", "pos": "名詞"},
    "w-지갑": {"lemma": "지갑", "pos": "名詞"},
    "w-찾다": {"lemma": "찾다", "pos": "動詞"},
    "w-있다": {"lemma": "있다", "pos": "形容詞"},
}
LEXICON = Lexicon(
    allowed=WORDS,
    known={"사과": "L1-U09「果物」で出る語", "이것": "L1-U03「お店で買い物」で出る語", "수": "L4 候補の語"},
)
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


def test_contracted_demonstrative_counts_as_the_listed_word(checker):
    # Kiwi は 이게 を 이것＋이 に戻すが、見出しの 이거 と同じ語として扱う
    s = sentence("이게 커피예요?", [("이게", ["w-이거"]), ("커피예요", ["w-커피"])], eojeol=1)
    assert checker.check(s, LEXICON, UNIT) == []
    s = sentence("이게 뭐예요?", [("이게", []), ("뭐예요", ["w-뭐"])])
    checker.check(s, LEXICON, UNIT)
    assert s["tokens"][0]["word_ids"] == ["w-이거"]


def test_noun_with_hada_suffix_may_list_hada(checker):
    # 결혼했어요 の 하 は Kiwi では接尾辞（XSV）だが、単語の 하다 を付けてよい
    s = sentence("오월에 결혼했어요.", [("오월에", []), ("결혼했어요", ["w-결혼", "w-하다"])], eojeol=1)
    assert not any("見当たらない" in p for p in checker.check(s, LEXICON, UNIT))


def test_dependent_noun_in_grammar_and_compound_noun(checker):
    # -(으)ㄹ 수 없다 の 수 は文法の一部。L4 の「수（数）」と取り違えない
    s = sentence("역사책을 읽을 수 없어요.", [("역사책을", []), ("읽을", ["w-읽다"]), ("수", []), ("없어요", ["w-없다"])])
    problems = checker.check(s, LEXICON, UNIT)
    assert not any("수" in p or "역사책" in p for p in problems)
    assert s["tokens"][0]["word_ids"] == ["w-역사", "w-책"]


@pytest.mark.parametrize(
    "ko, target, lemma",
    [
        ("부모님이 거기 사세요.", "사세요", "살다"),  # ㄹ が落ちる活用。Kiwi は 사다 と読む
        ("할머니는 안 계세요.", "계세요", "계시다"),  # 尊敬の -시- が縮まった形
        ("할머니는 지금 집에 계세요?", "계세요", "계시다"),  # 文によっては Kiwi が 계세＋요 と読む
        ("할머니께서 많이 잡수셨어요.", "잡수셨어요", "잡수시다"),
        ("말씀 좀 물어볼게요.", "물어볼게요", "물어보다"),  # 文の中では 묻＋보 に分かれる
        ("밤에 들어와도 돼요?", "들어와도", "들어오다"),
        ("이 핸드폰은 어때요?", "어때요", "어떠하다"),  # Kiwi では 어떻다
    ],
)
def test_conjugated_predicates_are_found(checker, ko, target, lemma):
    words = {
        **WORDS,
        "w-x": {"lemma": lemma, "pos": "動詞"},
        "w-사다": {"lemma": "사다", "pos": "動詞"},
        "w-부모님": {"lemma": "부모님", "pos": "名詞"},
        "w-할머니": {"lemma": "할머니", "pos": "名詞"},
        "w-안": {"lemma": "안", "pos": "副詞"},
        "w-많이": {"lemma": "많이", "pos": "副詞"},
        "w-말씀": {"lemma": "말씀", "pos": "名詞"},
        "w-좀": {"lemma": "좀", "pos": "副詞"},
        "w-밤": {"lemma": "밤", "pos": "名詞"},
        "w-되다": {"lemma": "되다", "pos": "動詞"},
        "w-거기": {"lemma": "거기", "pos": "代名詞"},
        "w-핸드폰": {"lemma": "핸드폰", "pos": "名詞"},
        "w-지금": {"lemma": "지금", "pos": "副詞"},
        "w-집": {"lemma": "집", "pos": "名詞"},
    }
    lexicon = Lexicon(allowed=words, known={})
    s = sentence(ko, [(e, ["w-x"] if e == target else []) for e, _, _ in eojeols(ko)])
    problems = checker.check(s, lexicon, {"w-x"})
    assert not any("見当たらない" in p or "一覧にない" in p for p in problems), problems
    assert "w-사다" not in {w for t in s["tokens"] for w in t["word_ids"]}


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


def test_hada_on_the_particle_hago_is_removed(checker):
    # 커피하고 の 하고 は助詞（〜と）。하다 の id は外す
    s = sentence("커피하고 물 주세요.", [("커피하고", ["w-커피", "w-하다"]), ("물", ["w-물"]), ("주세요", ["w-주다"])])
    assert checker.check(s, LEXICON, UNIT) == []
    assert s["tokens"][0]["word_ids"] == ["w-커피"]
    # Kiwi が 여권＋하（動詞）＋고 と読み違える形でも、하다 を外し、足し直さない
    s = sentence("여권하고 지갑을 찾고 있어요.", [("여권하고", ["w-여권", "w-하다"]), ("지갑을", ["w-지갑"]), ("찾고", ["w-찾다"]), ("있어요", [])])
    assert checker.check(s, LEXICON, {"w-여권"}) == []
    assert s["tokens"][0]["word_ids"] == ["w-여권"]
    # 결혼하고 の 하 は 하다（결혼＋하다）なので残す
    s = sentence("결혼하고 공부해요.", [("결혼하고", ["w-결혼", "w-하다"]), ("공부해요", ["w-공부하다"])], eojeol=1)
    assert checker.check(s, LEXICON, UNIT) == []
    assert s["tokens"][0]["word_ids"] == ["w-결혼", "w-하다"]
