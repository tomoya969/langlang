from __future__ import annotations

from app import grader, langs, prompts
from app.langs import ko
from app.langs.base import normalize_default

pack = langs.get("ko")


def test_normalize():
    assert normalize_default("  학교에  가요. ") == "학교에 가요"
    assert normalize_default("뭐예요?") == "뭐예요"
    assert normalize_default("안녕하세요。") == "안녕하세요"
    # NFC: 分解された字母（NFD）を合成する
    assert normalize_default("한") == "한"


def test_exact_and_variant():
    assert grader.judge_machine(pack, "물 주세요", "물 주세요.").source == "exact"
    assert grader.judge_machine(pack, "물 좀 주세요!", "물 주세요.", ["물 좀 주세요."]).source == "variant"
    assert grader.judge_machine(pack, "커피 주세요", "물 주세요.") is None


def test_spacing_only_is_correct_with_notes():
    result = grader.judge_machine(pack, "물주세요", "물 주세요.")
    assert result.verdict == "correct_with_notes"
    assert result.rating == "hard"
    assert result.issues[0]["tag"] == "띄어쓰기"


def test_same_pronunciation_is_correct_with_notes():
    result = grader.judge_machine(pack, "민수는 누구애요", "민수는 누구예요?")
    assert result.verdict == "correct_with_notes"
    assert result.source == "pronunciation"
    assert result.issues[0]["tag"] == "綴り"
    assert ("extra", "애") in [(d["kind"], d["text"]) for d in result.diff]
    assert grader.judge_machine(pack, "미야내요", "미안합니다", ["미안해요"]).corrected == "미안해요"


def test_different_pronunciation_is_left_to_ai():
    # 1 字違いでも意味が変わるものがあるので、機械では不正解にも注意にもしない
    assert grader.judge_machine(pack, "커피가 없어요", "커피가 있어요.") is None
    assert grader.judge_machine(pack, "학교를 가요", "학교에 가요.") is None


def test_pronounce_ko():
    same = [
        ("미안해요", "미야내요"),
        ("누구예요", "누구애요"),
        ("감사합니다", "감사함니다"),
        ("같이", "가치"),
        ("좋아요", "조아요"),
        ("많아요", "마나요"),
        ("축하해요", "추카해요"),
        ("있어요", "이써요"),
        ("있는", "인는"),
        ("학교", "학꾜"),
        ("돼요", "되요"),
        ("신라", "실라"),
    ]
    for a, b in same:
        assert ko.pronounce(a) == ko.pronounce(b), (a, b)
    for a, b in [("있어요", "없어요"), ("해요", "했어요"), ("학교에", "학교를"), ("커피", "코피")]:
        assert ko.pronounce(a) != ko.pronounce(b), (a, b)


TASK = grader.Task("sentence_dictation", "s1", "커피가 있어요.", context={"problem": [("読み上げた文", "커피가 있어요.")], "words": []}, word_ids=("w1",))


def fake_ask(result):
    calls = []

    def ask(prompt, schema):
        calls.append(prompt)
        return result

    ask.calls = calls
    return ask


def test_ai_judgement_and_diff_against_corrected():
    ask = fake_ask({
        "verdict": "incorrect",
        "meaning_ok": False,
        "issues": [{"axis": "meaning", "tag": "語彙の選択", "span": "없어요", "note": "「ない」になり意味が逆です", "suggestion": "있어요", "word_id": "zzz"}],
        "corrected": "커피가 있어요",
        "comment_ja": "있어요 と 없어요 で意味が逆になるので不正解です。",
    })
    result = grader.judge_ai(pack, TASK, "커피가 없어요", ask)
    assert result.verdict == "incorrect"
    assert result.source == "ai"
    assert result.corrected == "커피가 있어요."  # 模範解答と同じなら模範解答の書き方にそろえる
    assert result.issues[0]["word_id"] is None  # 問題の単語にない id は捨てる
    assert ("extra", "없") in [(d["kind"], d["text"]) for d in result.diff]
    assert "커피가 없어요" in ask.calls[0]


def test_ai_correct_with_issues_becomes_notes():
    ask = fake_ask({
        "verdict": "correct",
        "meaning_ok": True,
        "issues": [{"axis": "orthography", "tag": "綴り", "span": "이써요", "note": "綴り", "suggestion": "있어요"}],
        "corrected": "커피가 있어요",
        "comment_ja": "",
    })
    assert grader.judge_ai(pack, TASK, "커피가 잇어요", ask).verdict == "correct_with_notes"


def test_grade_prompt_covers_every_practice():
    for practice in ("word_spell", "sentence_cloze", "sentence_dictation", "sentence_ja_to_ko", "sentence_compose"):
        text = prompts.build_grade_prompt(practice, {"problem": [("模範解答", "물")], "words": []}, "무")
        assert "# 判定の手順" in text and "무" in text


def test_char_diff_merges_runs():
    assert grader.char_diff("가나다", "가나다") == [{"kind": "same", "text": "가나다"}]
    assert grader.char_diff("", "가") == [{"kind": "missing", "text": "가"}]
    assert grader.char_diff("가", "") == [{"kind": "extra", "text": "가"}]
