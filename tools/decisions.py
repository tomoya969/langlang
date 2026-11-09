"""人が決めたこと（work/decisions.json）。AI の付与と検算より優先する（docs/plan.md 6.5 の「要確認」の決着）。

    {"words": {"<単語の id>": {"lemma": "그래", "pos": "副詞", "meanings": [...], "hanja": null, "origin": "固有語", "note": "なぜそう決めたか"}},
     "not_similar": [{"why": "なぜ出さないか", "pairs": [{"ko-w-0010": "네", "ko-w-0043": "넷"}]}]}

lemma は読む人のためのもので、id の単語と違えば止める（id の打ち間違いで別の語を書き換えないように）。
pos・meanings・hanja・origin は書いたものだけを上書きする。決めた語は検算の食い違いがあっても approved にする。
not_similar は、類語のうち意味が合わないので単語帳の「類語・意味の近い語」に出さない組。類語の段階はダミーを外すために
「迷ったら挙げる」ので合わない組も混ざるが、ダミーから外れて困ることはないので、ダミーからは外したままにする。
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


def not_similar(ws: Workspace, lemma_of: dict[str, str]) -> dict[str, set[str]]:
    """単語の id → 単語帳に出さない相手の id（両方向）。"""
    hidden: dict[str, set[str]] = {}
    for group in (ws.read(DECISIONS) or {}).get("not_similar", []):
        for pair in group["pairs"]:
            if len(pair) != 2:
                raise BuildError(f"{DECISIONS}: not_similar の組は 2 語にします: {pair}")
            for wid, lemma in pair.items():
                if lemma_of.get(wid) != lemma:
                    raise BuildError(f"{DECISIONS}: not_similar の {wid} の見出しが違います（{lemma} と書いてありますが、{lemma_of.get(wid)} です）")
            a, b = pair
            hidden.setdefault(a, set()).add(b)
            hidden.setdefault(b, set()).add(a)
    return hidden

