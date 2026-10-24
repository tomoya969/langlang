"""国立国語院のリストを語彙の候補として取り込む（langlang-build import。docs/plan.md 6.1 の 1・2）。AI は使わない。"""

from __future__ import annotations

from pathlib import Path

from tools.ko import nikl
from tools.work import BuildError, Workspace

CANDIDATES = "candidates.json"


def run(ws: Workspace, source: Path | None = None) -> str:
    path = source or ws.sources / nikl.SOURCE_NAME
    if not path.exists():
        raise BuildError(
            f"{path} がありません。{nikl.SOURCE_URL} から「한국어 학습용 어휘 목록.txt」をダウンロードして、この名前で置いてください"
        )
    rows = nikl.parse(nikl.read_text(path))
    candidates = nikl.candidates(rows)
    ws.write(CANDIDATES, candidates)
    excluded = sum(1 for c in candidates if c.get("excluded"))
    return f"{len(rows)} 行から {len(candidates)} 語の候補を作りました（補助用言だけの {excluded} 語は除外）"
