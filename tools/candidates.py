"""語彙の候補（国立国語院のリスト＋補完）をまとめて読む。"""

from __future__ import annotations

from typing import Any

from tools import supplement
from tools.import_nikl import CANDIDATES
from tools.work import Workspace


def load(ws: Workspace) -> list[dict[str, Any]]:
    return [*ws.require(CANDIDATES, "import"), *supplement.candidates(ws)]


def prompt_item(candidate: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """プロンプトに渡す候補の情報（見出し、品詞、元のリストの補足、補完のときの意味の手がかり）。"""
    return {
        "key": candidate["key"],
        "lemma": candidate["lemma"],
        "pos": candidate.get("pos"),
        "gloss": candidate.get("nikl", {}).get("gloss", ""),
        "hint": candidate.get("hint", ""),
        **extra,
    }
