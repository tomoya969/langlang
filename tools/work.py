"""教材づくりの途中のデータ（content/<言語>/work/）の読み書き。

AI の結果は項目ごと（候補の見出しやユニットごと）に保存し、再実行したときは済んだ項目を飛ばす。
途中のデータも Git で管理する（教材を作り直すときに AI を呼び直さずに済むように）。
元の語彙リストは content/<言語>/sources/ に置く（配布元の利用条件に従い、Git には入れない）。
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.content import content_dir


class BuildError(Exception):
    """教材づくりを続けられない（前の段階が済んでいない、元のリストがない など）。"""


class Workspace:
    def __init__(self, root: Path, language: str):
        self.root = root
        self.language = language
        self.content = content_dir(root, language)
        self.dir = self.content / "work"
        self.sources = self.content / "sources"
        # 並列に動く AI の呼び出しが同じファイルに書くので、書き込みを順に行う
        self.lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.dir / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def read(self, name: str, default: Any = None) -> Any:
        path = self.path(name)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def require(self, name: str, step: str) -> Any:
        if not self.exists(name):
            raise BuildError(f"{self.path(name)} がありません。先に `langlang-build {step}` を実行してください")
        return self.read(name)

    def write(self, name: str, data: Any) -> None:
        write_json(self.path(name), data)


def write_json(path: Path, data: Any, style: str = "lines") -> None:
    """一時ファイルに書いてから置き換える（途中で止まっても壊れたファイルを残さない）。

    style="lines" は最上位の要素を 1 行ずつ（差分を見やすくする）、"keys" はリストの各オブジェクトのキーを 1 行ずつ。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dumps_keys(data) if style == "keys" else dumps_lines(data)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def dumps_lines(data: Any) -> str:
    if isinstance(data, list):
        if not data:
            return "[]\n"
        return "[\n" + ",\n".join(f"  {_compact(v)}" for v in data) + "\n]\n"
    if isinstance(data, dict):
        if not data:
            return "{}\n"
        return "{\n" + ",\n".join(f"  {_compact(k)}: {_compact(v)}" for k, v in data.items()) + "\n}\n"
    return _compact(data) + "\n"


def dumps_keys(items: list[dict[str, Any]]) -> str:
    if not items:
        return "[]\n"
    blocks = []
    for item in items:
        lines = ",\n".join(f"    {_compact(k)}: {_compact(v)}" for k, v in item.items())
        blocks.append("  {\n" + lines + "\n  }")
    return "[\n" + ",\n".join(blocks) + "\n]\n"


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def fingerprint(value: Any) -> str:
    """入力の指紋。入力（単語の並びやプロンプトの版）が変わったら、保存してある AI の結果を使わずに作り直す。"""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
