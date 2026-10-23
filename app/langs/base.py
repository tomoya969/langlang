"""言語パックの決まりごと。ほかの言語を足すときは、この形で langs/<言語>.py を作る。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable


class UnsupportedLanguage(Exception):
    pass


_TRAILING_PUNCT = re.compile(r"[.?!。？！\s]+$")
_SPACES = re.compile(r"\s+")


def normalize_default(text: str) -> str:
    """答えの正規化（docs/plan.md 5.4）。Unicode NFC、前後の空白を除く、連続する空白を 1 つに、文末の記号を除く。"""
    text = unicodedata.normalize("NFC", text)
    text = _TRAILING_PUNCT.sub("", text.strip())
    return _SPACES.sub(" ", text).strip()


@dataclass(frozen=True)
class LanguagePack:
    code: str  # "ko"
    label: str  # 画面の表示名（日本語）
    tts_lang: str  # Web Speech API の言語コード
    registers: tuple[str, ...]  # 文体の種類
    normalize: Callable[[str], str] = normalize_default
    # 空白の扱いだけが違う答えを「正解（注意つき）」にするとき、注意に付けるタグ
    spacing_tag: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "tts_lang": self.tts_lang, "registers": list(self.registers)}
