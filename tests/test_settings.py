from __future__ import annotations

import json

import pytest

from app import settings


def test_defaults_when_missing(tmp_path):
    assert settings.load(tmp_path, "ko") == settings.DEFAULTS


def test_save_and_load(tmp_path):
    saved = settings.save(tmp_path, "ko", {"new_words_per_day": 10, "tts_rate": 0.75, "keyboard_show_latin": False})
    assert saved["new_words_per_day"] == 10
    assert saved["tts_rate"] == 0.75
    assert settings.load(tmp_path, "ko")["keyboard_show_latin"] is False


def test_languages_are_separate(tmp_path):
    settings.save(tmp_path, "ko", {"new_words_per_day": 10})
    settings.save(tmp_path, "en", {"new_words_per_day": 30})
    assert settings.load(tmp_path, "ko")["new_words_per_day"] == 10
    assert settings.load(tmp_path, "en")["new_words_per_day"] == 30
    assert settings.load(tmp_path, "zh") == settings.DEFAULTS
    raw = json.loads(settings.path(tmp_path).read_text(encoding="utf-8"))
    assert set(raw["languages"]) == {"ko", "en"}


def test_flat_file_is_read_for_every_language(tmp_path):
    p = settings.path(tmp_path)
    p.parent.mkdir()
    p.write_text(json.dumps({"new_words_per_day": 12}), encoding="utf-8")
    assert settings.load(tmp_path, "ko")["new_words_per_day"] == 12
    settings.save(tmp_path, "ko", {"weak_slots": 3})
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw == {"languages": {"ko": {**settings.DEFAULTS, "new_words_per_day": 12, "weak_slots": 3}}}


def test_save_rejects_bad_values(tmp_path):
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, "ko", {"nope": 1})
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, "ko", {"new_words_per_day": -1})
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, "ko", {"keyboard_show_latin": "yes"})


def test_broken_file_falls_back_to_defaults(tmp_path):
    p = settings.path(tmp_path)
    p.parent.mkdir()
    p.write_text("{broken", encoding="utf-8")
    assert settings.load(tmp_path, "ko") == settings.DEFAULTS
