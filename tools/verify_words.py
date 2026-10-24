"""単語の検算（langlang-build verify-words。docs/plan.md 6.1 の 9）。

詳しい付与とは別の呼び出しで、意味・漢字・語種を確かめる。食い違いは「要確認」にし、2 つの案を残す（6.5）。
付与をやり直したら、その語の検算もやり直す（検算した付与の指紋を of に残して見比べる）。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import VERIFY_WORDS_STYLE, build_verify_words_prompt, verify_words_schema
from tools import batch, candidates
from tools.batch import BadOutput
from tools.enrich_words import ENRICH, level_words
from tools.work import Workspace, chunks, fingerprint

VERIFY_WORDS = "verify-words.json"
BATCH_SIZE = 50
NO_HANJA = "なし"


def run(ws: Workspace, ask: AskFn, level: int = 1, parallel: int = 3) -> str:
    enrich: dict[str, Any] = ws.read(ENRICH, {})
    verified: dict[str, Any] = ws.read(VERIFY_WORDS, {})
    words = [w for w in level_words(ws, level) if w["key"] in enrich]
    todo = [w for w in words if not _current(verified.get(w["key"]), enrich[w["key"]])]
    if not todo:
        return f"済み（L{level} の {len(words)} 語）"

    def work(group: list[dict[str, Any]]) -> dict[str, Any]:
        keys = [w["key"] for w in group]
        items = [
            candidates.prompt_item(w, pos=w["pos"], origin=w["origin"], meanings=enrich[w["key"]]["meanings"], hanja=enrich[w["key"]]["hanja"])
            for w in group
        ]
        result = ask(build_verify_words_prompt(items), verify_words_schema(keys))["words"]
        missing = [k for k in keys if k not in result]
        if missing:
            raise BadOutput(f"検算が返ってこなかった語があります: {'、'.join(missing[:5])}")
        return result

    def save(group: list[dict[str, Any]], result: dict[str, Any]) -> None:
        for w in group:
            verified[w["key"]] = {**result[w["key"]], "of": fingerprint(enrich[w["key"]]), "style": VERIFY_WORDS_STYLE}
        ws.write(VERIFY_WORDS, verified)

    outcome = batch.run(
        "verify-words", chunks(todo, BATCH_SIZE), work, save, label=lambda g: f"{g[0]['lemma']}〜{g[-1]['lemma']}", parallel=parallel
    )
    flagged = sum(1 for w in words if w["key"] in verified and problems(verified[w["key"]]))
    return f"L{level} の {len(todo)} 語: {outcome.summary()}。要確認 {flagged} 語"


def _current(result: dict[str, Any] | None, enriched: dict[str, Any]) -> bool:
    return bool(result) and result.get("style") == VERIFY_WORDS_STYLE and result.get("of") == fingerprint(enriched)


def problems(result: dict[str, Any]) -> list[str]:
    found = []
    if not result["meaning_ok"]:
        found.append("意味")
    if not result["hanja_ok"]:
        found.append("漢字")
    if not result["origin_ok"]:
        found.append("語種")
    return found


def suggestion(result: dict[str, Any], enriched: dict[str, Any], origin: str) -> dict[str, Any]:
    """検算の案（直されていないところは付与のまま）。"""
    primary = next(m["ja"] for m in enriched["meanings"] if m["primary"])
    hanja = enriched["hanja"]
    if not result["hanja_ok"]:
        hanja = None if result["suggested_hanja"].strip() in ("", NO_HANJA) else result["suggested_hanja"].strip()
    return {
        "meaning": result["suggested_meaning"].strip() if not result["meaning_ok"] and result["suggested_meaning"].strip() else primary,
        "hanja": hanja,
        "origin": result["suggested_origin"] if not result["origin_ok"] and result["suggested_origin"] else origin,
    }
