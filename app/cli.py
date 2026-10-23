"""コマンドラインの入口。

    langlang serve [--port 8766]
    langlang validate [--language ko]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from app import content
from app.content import ContentError

ENV_ROOT = "LANGLANG_ROOT"
ENV_PORT = "LANGLANG_PORT"
DEFAULT_PORT = 8766
SERVE_HOST = "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    try:
        return args.func(args, root)
    except ContentError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="langlang", description="ローカルの語学学習アプリ")
    parser.add_argument("--root", default=os.environ.get(ENV_ROOT, "."), help="リポジトリのルート（既定: カレントディレクトリ）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="ブラウザ画面を起動する（Ctrl+C で停止）")
    p_serve.add_argument("--port", type=int, default=int(os.environ.get(ENV_PORT, DEFAULT_PORT)))
    p_serve.set_defaults(func=cmd_serve)

    p_validate = sub.add_parser("validate", help="教材の整合を確かめる")
    p_validate.add_argument("--language", default="ko")
    p_validate.set_defaults(func=cmd_validate)
    return parser


def cmd_serve(args: argparse.Namespace, root: Path) -> int:
    import uvicorn

    from app.server import create_app

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    print(f"langlang: http://{SERVE_HOST}:{args.port}/ （Ctrl+C で停止）")
    uvicorn.run(create_app(root), host=SERVE_HOST, port=args.port, log_level="warning")
    return 0


def cmd_validate(args: argparse.Namespace, root: Path) -> int:
    loaded = content.load(root, args.language, approved_only=False)
    approved = content.load(root, args.language)
    print(
        f"{args.language}: ユニット {len(loaded.units)}、単語 {len(loaded.words)}（approved {len(approved.words)}）、"
        f"文 {len(loaded.sentences)}（approved {len(approved.sentences)}）"
    )
    return 0
