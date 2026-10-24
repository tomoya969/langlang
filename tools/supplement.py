"""候補の補完（langlang-build supplement。docs/plan.md 6.1 の 1）。

国立国語院のリスト（2003 年）にない、あいさつの決まった表現と、その後に日常で使うようになった語（스마트폰 など）を
AI に挙げさせる。リストにある語と重なるものは機械で除く。あいさつの表現は固定枠（最初のユニット群）に入る。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import SUPPLEMENT_STYLE, build_supplement_prompt, supplement_schema
from tools import batch
from tools.import_nikl import CANDIDATES
from tools.ko.morph import EXPRESSION_POS, normalize
from tools.work import Workspace, now_iso

SUPPLEMENT = "supplement.json"
KEY_PREFIX = "s:"
KIND_GREETING = "greeting"
KIND_MODERN = "modern"


def run(ws: Workspace, ask: AskFn) -> str:
    saved = ws.read(SUPPLEMENT)
    if saved and saved.get("style") == SUPPLEMENT_STYLE:
        return f"済み（あいさつ {len(saved['greetings'])} 個、現代の語 {len(saved['modern'])} 語）"
    nikl = ws.require(CANDIDATES, "import")
    existing = sorted({c["lemma"] for c in nikl})

    def work(_: None) -> dict[str, Any]:
        return ask(build_supplement_prompt(existing), supplement_schema())

    def save(_: None, result: dict[str, Any]) -> None:
        seen = {normalize(lemma) for lemma in existing}
        ws.write(
            SUPPLEMENT,
            {
                "style": SUPPLEMENT_STYLE,
                "created_at": now_iso(),
                "greetings": _new_only(result["greetings"], seen, pos=EXPRESSION_POS),
                "modern": _new_only(result["modern"], seen),
            },
        )

    outcome = batch.run("supplement", [None], work, save, label=lambda _: "補完")
    if outcome.failed:
        return f"失敗しました: {outcome.failed[0][1]}"
    data = ws.read(SUPPLEMENT)
    return f"あいさつ {len(data['greetings'])} 個、現代の語 {len(data['modern'])} 語を足しました"


def _new_only(items: list[dict[str, Any]], seen: set[str], pos: str | None = None) -> list[dict[str, Any]]:
    """リストにある語と、すでに挙げた語を除く。seen は書き換える。"""
    result = []
    for item in items:
        lemma = " ".join(item["lemma"].split())
        if not lemma or normalize(lemma) in seen:
            continue
        seen.add(normalize(lemma))
        result.append({"lemma": lemma, "ja": item["ja"].strip(), "pos": pos or item["pos"]})
    return result


def candidates(ws: Workspace) -> list[dict[str, Any]]:
    data = ws.read(SUPPLEMENT)
    if not data:
        return []
    result = []
    for kind in (KIND_GREETING, KIND_MODERN):
        for item in data["greetings" if kind == KIND_GREETING else "modern"]:
            result.append(
                {
                    "key": KEY_PREFIX + item["lemma"],
                    "lemma": item["lemma"],
                    "pos": item["pos"],
                    "source": "supplement",
                    "kind": kind,
                    "hint": item["ja"],
                }
            )
    return result
