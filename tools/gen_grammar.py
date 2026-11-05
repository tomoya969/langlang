"""レベルごとの文法リスト（langlang-build grammar。docs/plan.md 6.3・11 の 5）。

AI に、ハン検の級の範囲を目安に文法の案を作らせ、それぞれの文法を最初に例文で使ってよいユニットを決めさせる。
例文はそのユニットまでの文法で作る（最初のユニットから文を作れて、難しい文法ほど後に出るように）。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import GRAMMAR_SCOPES, GRAMMAR_STYLE, build_grammar_prompt, grammar_schema
from tools import batch, candidates
from tools.assign_levels import layout
from tools.batch import BadOutput
from tools.work import BuildError, Workspace, fingerprint, now_iso

GRAMMAR = "grammar.json"
MIN_ITEMS = 20


def _fingerprint(units: list[dict[str, Any]]) -> str:
    return fingerprint({"style": GRAMMAR_STYLE, "units": [[u["id"], u["title"], u["keys"]] for u in units]})


def run(ws: Workspace, ask: AskFn, level: int = 1) -> str:
    if level not in GRAMMAR_SCOPES:
        raise BuildError(f"L{level} の文法の範囲がまだ決まっていません（app/prompts.py の GRAMMAR_SCOPES）")
    units = layout(ws, level)
    saved = ws.read(GRAMMAR, {})
    fp = _fingerprint(units)
    if saved.get(f"L{level}", {}).get("fingerprint") == fp:
        return f"済み（L{level} の文法 {len(saved[f'L{level}']['items'])} 個）"
    lemmas = {c["key"]: c["lemma"] for c in candidates.load(ws)}
    unit_items = [{**u, "lemmas": [lemmas[k] for k in u["keys"]]} for u in units]
    unit_ids = [u["id"] for u in units]

    earlier = [g["form"] for lv in range(1, level) for g in items(ws, lv)]

    def work(_: None) -> list[dict[str, Any]]:
        result = ask(build_grammar_prompt(level, unit_items, earlier), grammar_schema(unit_ids))
        return settle_grammar(result["items"], unit_ids)

    results: list[list[dict[str, Any]]] = []
    outcome = batch.run("grammar", [None], work, lambda _, r: results.append(r), label=lambda _: f"L{level} の文法")
    if outcome.failed:
        raise BuildError(f"L{level} の文法リストを作れませんでした: {outcome.failed[0][1]}")
    saved[f"L{level}"] = {"fingerprint": fp, "created_at": now_iso(), "items": results[0]}
    ws.write(GRAMMAR, saved)
    return f"L{level} の文法 {len(results[0])} 個"


def settle_grammar(items: list[dict[str, Any]], unit_ids: list[str]) -> list[dict[str, Any]]:
    """同じ形の重なりを除き、ユニットの順に並べる。最初のユニットで使える文法がなければやり直させる。
    L2 からも、最初のユニットに新しい文法を置かせる（前のレベルの文法だけで 1 ユニット分の文を作ると、そのユニットで学ぶことがないため）。"""
    seen: set[str] = set()
    settled = []
    for item in items:
        form = " ".join(item["form"].split())
        if not form or form in seen or item["unit"] not in unit_ids:
            continue
        seen.add(form)
        settled.append({"form": form, "ja": item["ja"].strip(), "example": item["example"].strip(), "unit": item["unit"]})
    settled.sort(key=lambda g: unit_ids.index(g["unit"]))
    if len(settled) < MIN_ITEMS or settled[0]["unit"] != unit_ids[0]:
        raise BadOutput(f"文法が少ないか、最初のユニットで使える文法がありません（{len(settled)} 個）")
    return settled


def items(ws: Workspace, level: int) -> list[dict[str, Any]]:
    saved = ws.read(GRAMMAR, {}).get(f"L{level}")
    if not saved:
        raise BuildError(f"L{level} の文法リストがありません。先に `langlang-build grammar --level {level}` を実行してください")
    return saved["items"]


def allowed(ws: Workspace, level: int, unit_id: str) -> list[dict[str, Any]]:
    """そのユニットまでに使えるようになった文法（前のレベルの文法を含む）。new はそのユニットから使えるもの。"""
    result = []
    for lv in range(1, level + 1):
        unit_order = {u["id"]: u["order"] for u in layout(ws, lv)}
        limit = unit_order[unit_id] if lv == level else max(unit_order.values())
        for g in items(ws, lv):
            if unit_order[g["unit"]] <= limit:
                result.append({**g, "new": g["unit"] == unit_id})
    return result
