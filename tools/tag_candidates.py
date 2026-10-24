"""粗い付与（langlang-build tag。docs/plan.md 6.1 の 3）。

すべての候補に、ハン検の推定級・語種・品詞・日本語の漢字語と対応するか・除外するかを、50 語ずつ速いモデルで付ける。
付けた結果は候補の見出しごとに work/tags.json に残し、再実行したときは済んだ見出しを飛ばす。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import TAG_STYLE, build_tag_prompt, tag_schema
from tools import batch, candidates
from tools.batch import BadOutput
from tools.work import Workspace, chunks

TAGS = "tags.json"
BATCH_SIZE = 50


def pending(ws: Workspace) -> list[dict[str, Any]]:
    tags = ws.read(TAGS, {})
    return [
        c for c in candidates.load(ws) if not c.get("excluded") and tags.get(c["key"], {}).get("style") != TAG_STYLE
    ]


def run(ws: Workspace, ask: AskFn, parallel: int = 4) -> str:
    tags: dict[str, Any] = ws.read(TAGS, {})
    todo = pending(ws)
    if not todo:
        return f"済み（{len(tags)} 語）"

    def work(group: list[dict[str, Any]]) -> dict[str, Any]:
        keys = [c["key"] for c in group]
        result = ask(build_tag_prompt([candidates.prompt_item(c) for c in group]), tag_schema(keys))["tags"]
        missing = [k for k in keys if k not in result]
        if missing:
            raise BadOutput(f"付与が返ってこなかった候補があります: {'、'.join(missing[:5])}")
        return result

    def save(group: list[dict[str, Any]], result: dict[str, Any]) -> None:
        for c in group:
            tags[c["key"]] = {**result[c["key"]], "style": TAG_STYLE}
        ws.write(TAGS, tags)

    outcome = batch.run(
        "tag", chunks(todo, BATCH_SIZE), work, save, label=lambda g: f"{g[0]['key']}〜{g[-1]['key']}", parallel=parallel
    )
    return f"{len(todo)} 語を {BATCH_SIZE} 語ずつ: {outcome.summary()}"
