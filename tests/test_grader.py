from __future__ import annotations

from app import grader, langs
from app.langs.base import normalize_default

pack = langs.get("ko")


def test_normalize():
    assert normalize_default("  학교에  가요. ") == "학교에 가요"
    assert normalize_default("뭐예요?") == "뭐예요"
    assert normalize_default("안녕하세요。") == "안녕하세요"
    # NFC: 分解された字母（NFD）を合成する
    assert normalize_default("한") == "한"


def test_exact_and_variant():
    assert grader.judge_exact(pack, "물 주세요", "물 주세요.").source == "exact"
    assert grader.judge_exact(pack, "물 좀 주세요!", "물 주세요.", ["물 좀 주세요."]).source == "variant"
    assert grader.judge_exact(pack, "커피 주세요", "물 주세요.") is None


def test_spacing_only_is_correct_with_notes():
    result = grader.judge_exact(pack, "물주세요", "물 주세요.")
    assert result.verdict == "correct_with_notes"
    assert result.rating == "hard"
    assert result.issues[0]["tag"] == "띄어쓰기"


def test_machine_incorrect_has_diff():
    result = grader.judge_machine(pack, "학교를 가요", "학교에 가요.")
    assert result.verdict == "incorrect"
    assert result.rating == "again"
    assert result.corrected == "학교에 가요."
    kinds = [(d["kind"], d["text"]) for d in result.diff]
    assert ("extra", "를") in kinds
    assert ("missing", "에") in kinds


def test_char_diff_merges_runs():
    assert grader.char_diff("가나다", "가나다") == [{"kind": "same", "text": "가나다"}]
    assert grader.char_diff("", "가") == [{"kind": "missing", "text": "가"}]
    assert grader.char_diff("가", "") == [{"kind": "extra", "text": "가"}]


def test_ai_placeholder_points_at_first_different_word():
    result = grader.judge_ai_placeholder(pack, "학교를 가요", "학교에 가요.")
    assert result.verdict == "incorrect"
    assert result.source == "placeholder"
    assert result.issues[0]["span"] == "학교를"
