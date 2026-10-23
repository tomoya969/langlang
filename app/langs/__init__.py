"""言語パック（サーバー側）。言語ごとに替わるもの（正規化、文体の種類、誤りのタグ、表示名）をここにまとめる。"""

from __future__ import annotations

from app.langs import base, ko

PACKS: dict[str, base.LanguagePack] = {ko.PACK.code: ko.PACK}


def get(code: str) -> base.LanguagePack:
    try:
        return PACKS[code]
    except KeyError:
        raise base.UnsupportedLanguage(f"未対応の言語です: {code}") from None
