"""詳しい付与（langlang-build enrich。docs/plan.md 6.1 の 8）。今学ぶレベルの語にだけ付ける。

日本語の意味・漢字（日本の字体）・取り違えやすい語・同義語・場面のタグを、40 語ずつ質を優先するモデルで付ける。
取り違えやすい語と同義語は AI には辞書形で書かせ、書き出すとき（export）に単語の id に置き換える。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import ENRICH_STYLE, build_enrich_prompt, enrich_schema
from tools import batch, candidates
from tools.assign_levels import layout, level_entries
from tools.batch import BadOutput
from tools.tag_candidates import TAGS
from tools.work import Workspace, chunks

ENRICH = "enrich.json"
BATCH_SIZE = 40


def level_words(ws: Workspace, level: int) -> list[dict[str, Any]]:
    """レベルの語を学ぶ順に。候補の情報に、ユニット・品詞（確定したもの）・語種を足したもの。"""
    by_key = {c["key"]: c for c in candidates.load(ws)}
    entries = {e["key"]: e for e in level_entries(ws, level)}
    tags = ws.read(TAGS, {})
    words = []
    for unit in layout(ws, level):
        for key in unit["keys"]:
            words.append({**by_key[key], "pos": entries[key]["pos"], "origin": tags[key]["origin"], "unit": unit})
    return words


def run(ws: Workspace, ask: AskFn, level: int = 1, parallel: int = 3) -> str:
    enrich: dict[str, Any] = ws.read(ENRICH, {})
    todo = [w for w in level_words(ws, level) if enrich.get(w["key"], {}).get("style") != ENRICH_STYLE]
    if not todo:
        return f"済み（L{level}）"

    def work(group: list[dict[str, Any]]) -> dict[str, Any]:
        keys = [w["key"] for w in group]
        items = [candidates.prompt_item(w, pos=w["pos"], origin=w["origin"], unit=w["unit"]["title"]) for w in group]
        result = ask(build_enrich_prompt(items), enrich_schema(keys))["words"]
        for key in keys:
            if key not in result or not result[key]["meanings"]:
                raise BadOutput(f"意味が返ってこなかった語があります: {key}")
        return result

    def save(group: list[dict[str, Any]], result: dict[str, Any]) -> None:
        for w in group:
            enrich[w["key"]] = {**settle(result[w["key"]]), "style": ENRICH_STYLE}
        ws.write(ENRICH, enrich)

    outcome = batch.run(
        "enrich", chunks(todo, BATCH_SIZE), work, save, label=lambda g: f"{g[0]['lemma']}〜{g[-1]['lemma']}", parallel=parallel
    )
    return f"L{level} の {len(todo)} 語: {outcome.summary()}"


def settle(item: dict[str, Any]) -> dict[str, Any]:
    """主な意味をちょうど 1 つにし、空の漢字を null にそろえる。"""
    meanings = [{"ja": m["ja"].strip(), "primary": bool(m["primary"])} for m in item["meanings"] if m["ja"].strip()]
    first = next((i for i, m in enumerate(meanings) if m["primary"]), 0)
    meanings = [{**m, "primary": i == first} for i, m in enumerate(meanings)]
    hanja = (item.get("hanja") or "").strip() or None
    return {
        "meanings": meanings,
        "hanja": hanja,
        "confusables": _lemmas(item.get("confusables", [])),
        "synonyms": _lemmas(item.get("synonyms", [])),
        "tags": [t.strip() for t in item.get("tags", []) if t.strip()][:3],
    }


def _lemmas(values: list[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))
