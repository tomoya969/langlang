from __future__ import annotations

import pytest

from app import settings


def test_defaults_when_missing(tmp_path):
    assert settings.load(tmp_path) == settings.DEFAULTS


def test_save_and_load(tmp_path):
    saved = settings.save(tmp_path, {"new_words_per_day": 10, "tts_rate": 0.75, "keyboard_show_latin": False})
    assert saved["new_words_per_day"] == 10
    assert saved["tts_rate"] == 0.75
    assert settings.load(tmp_path)["keyboard_show_latin"] is False


def test_save_rejects_bad_values(tmp_path):
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, {"nope": 1})
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, {"new_words_per_day": -1})
    with pytest.raises(settings.SettingsError):
        settings.save(tmp_path, {"keyboard_show_latin": "yes"})


def test_broken_file_falls_back_to_defaults(tmp_path):
    p = settings.path(tmp_path)
    p.parent.mkdir()
    p.write_text("{broken", encoding="utf-8")
    assert settings.load(tmp_path) == settings.DEFAULTS
