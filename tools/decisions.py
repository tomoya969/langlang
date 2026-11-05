"""人が決めたこと（work/decisions.json）。AI の付与と検算より優先する（docs/plan.md 6.5 の「要確認」の決着）。

    {"words": {"<単語の id>": {"lemma": "그래", "pos": "副詞", "meanings": [...], "hanja": null, "origin": "固有語", "note": "なぜそう決めたか"}}}

lemma は読む人のためのもので、id の単語と違えば止める（id の打ち間違いで別の語を書き換えないように）。
pos・meanings・hanja・origin は書いたものだけを上書きする。決めた語は検算の食い違いがあっても approved にする。
"""

from __future__ import annotations

from typing import Any

from tools.work import BuildError, Workspace

DECISIONS = "decisions.json"
WORD_FIELDS = ("pos", "meanings", "hanja", "origin")


def words(ws: Workspace, lemma_of: dict[str, str]) -> dict[str, dict[str, Any]]:
    """単語の id → 決めたこと。lemma_of は単語の id → 見出し（食い違いを確かめるため）。"""
    decided: dict[str, dict[str, Any]] = (ws.read(DECISIONS) or {}).get("words", {})
    for wid, d in decided.items():
        if wid not in lemma_of:
            raise BuildError(f"{DECISIONS}: 単語がありません: {wid}")
        if d.get("lemma") != lemma_of[wid]:
            raise BuildError(f"{DECISIONS}: {wid} の見出しが違います（{d.get('lemma')} と書いてありますが、{lemma_of[wid]} です）")
        meanings = d.get("meanings")
        if meanings is not None and sum(1 for m in meanings if m.get("primary")) != 1:
            raise BuildError(f"{DECISIONS}: {wid} の meanings は primary を 1 つだけにします")
    return decided

