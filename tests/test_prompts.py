"""プロンプトの版（レベルごと）。"""

from __future__ import annotations

from app import prompts


def test_style_is_kept_per_level():
    assert prompts.style("sentences", 1) == 2  # 作り終えた L1 は前の版のまま
    assert prompts.style("sentences", 2) == 3
    assert prompts.style("sentences", 3) == 3  # 書いていないレベルは、前のいちばん近いレベルの版
    assert prompts.style("enrich", 3) == 1


def test_sentence_prompts_use_the_text_of_their_version():
    unit = {"id": "L1-U01", "title": "t", "scene": "s", "level": 1}
    words = [{"id": "ko-w-0001", "lemma": "있다", "pos": "形容詞", "meaning": "ある"}]
    grammar = [{"form": "-아/어요", "ja": "です", "new": True}]
    old = prompts.build_sentences_prompt(unit, 12, words, words, grammar, "해요체", version=2)
    new = prompts.build_sentences_prompt({**unit, "level": 2}, 12, words, words, grammar, "해요체", version=3)
    assert "반말の文はくだけた話し言葉" not in old and "반말の文はくだけた話し言葉" in new
    items = [{"key": "s1", "ko": "물 주세요.", "ja": "水", "register": "해요체", "grammar": [], "words": [], "cloze": None, "variants": {}}]
    assert "実際にそう書くか" not in prompts.build_verify_sentences_prompt(unit, items, grammar, 2)
    assert "実際にそう書くか" in prompts.build_verify_sentences_prompt(unit, items, grammar, 3)


def test_spell_grading_asks_whether_it_is_another_word():
    assert "other_word" in prompts.grade_schema("word_spell")["required"]
    assert "other_word" not in prompts.grade_schema("sentence_dictation")["properties"]
