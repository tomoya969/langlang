"""学習の設定（新出の数、苦手枠、反応時間の基準など）。records/settings.json に置く。

表示の好み（テーマなど）はブラウザの localStorage に残し、ここには入れない。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FILENAME = "settings.json"

DEFAULTS: dict[str, Any] = {
    "new_words_per_day": 15,
    "new_sentences_per_day": 7,
    "weak_slots": 5,
    "review_limit": 200,
    # 反応時間の基準（秒）。記録がたまったら自分の中央値を基準にする
    "fast_sec": 1.5,
    "slow_sec": 4.0,
    "timeout_sec": 10.0,
    # 面を出し始める安定度（日）
    "unlock_listen_days": 3,
    "unlock_reverse_days": 3,
    "unlock_spell_days": 7,
    "mastered_days": 21,
    # 読み上げ
    "tts_rate": 1.0,
    # キーボード部品
    "keyboard_show_latin": True,
}


class SettingsError(Exception):
    pass


def path(root: Path) -> Path:
    return root / "records" / FILENAME


def load(root: Path) -> dict[str, Any]:
    p = path(root)
    if not p.exists():
        return dict(DEFAULTS)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULTS)
    return {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}


def save(root: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """知らないキーと型の違う値は受け付けない。"""
    current = load(root)
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise SettingsError(f"知らない設定です: {key}")
        default = DEFAULTS[key]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise SettingsError(f"{key} は真偽値です")
        elif isinstance(default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise SettingsError(f"{key} は 0 以上の数です")
            value = type(default)(value)
        current[key] = value
    p = path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    return current
