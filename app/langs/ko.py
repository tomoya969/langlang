"""韓国語の言語パック（サーバー側）。"""

from __future__ import annotations

from app.langs.base import LanguagePack

REGISTERS = ("합니다체", "해요체", "반말", "한다체")

PACK = LanguagePack(
    code="ko",
    label="韓国語",
    native="한국어",
    tts_lang="ko-KR",
    tts_sample="안녕하세요. 만나서 반갑습니다.",
    registers=REGISTERS,
    spacing_tag="띄어쓰기",
)
