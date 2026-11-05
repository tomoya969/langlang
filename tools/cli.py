"""教材づくりの CLI（docs/plan.md 6.4）。

    langlang-build status                     どこまで済んだか
    langlang-build import [--source PATH]     国立国語院のリストを候補に取り込む（content/ko/sources/nikl.txt）
    langlang-build supplement                 あいさつの表現と現代の日常語を補う（AI）
    langlang-build tag [--parallel 4]         すべての候補に粗い付与（AI）
    langlang-build levels                     スコアを付けて L1〜L3 に分ける
    langlang-build units [--level 1]          ユニットに分ける（AI）
    langlang-build grammar [--level 1]        文法リストを作る（AI）
    langlang-build enrich [--level 1]         詳しい付与（AI）
    langlang-build verify-words [--level 1]   単語の検算（AI）
    langlang-build sentences [--level 1] [--units L1-U01,L1-U02] [--recheck]   文の生成と検算（AI）
    langlang-build reopen ko-s-L1-U02-008 ...  work/ で直した文を機械で確かめ、AI の検算待ちに戻す
    langlang-build variants [--level 1] [--units L1-U01,L1-U02]   許容例の生成と検算（AI）
    langlang-build export                     content/ko/ に書き出す（ユニット分けまで済んだすべてのレベル）
    langlang-build all [--level 1]            上を順に全部

どの段階も、途中で止まっても再実行すれば済んだところを飛ばして続きから進む。
利用枠の上限に当たったら止まる（終了コード 3）。時間をおいて同じコマンドを実行する。
"""

from __future__ import annotations

import argparse
import functools
import logging
import os
import sys
from pathlib import Path
from typing import Callable

from app import claude_cli
from app.claude_cli import AskFn
from app.content import ContentError
from tools import (
    assign_levels,
    enrich_words,
    export,
    gen_grammar,
    gen_sentences,
    gen_variants,
    import_nikl,
    supplement,
    tag_candidates,
    verify_words,
)
from tools.batch import StopRun
from tools.work import BuildError, Workspace

ENV_ROOT = "LANGLANG_ROOT"
SUPPORTED = ("ko",)
# 質を優先するモデルで 15 文を作るのは時間がかかるので、claude_cli の既定より長く待つ
TIMEOUT_SEC = 1200

log = logging.getLogger("langlang.build")


def asker(purpose: str) -> AskFn:
    settings = claude_cli.settings_for(purpose)
    log.info("用途 %s: model=%s effort=%s", purpose, settings.model, settings.effort or "既定")
    return functools.partial(claude_cli.ask, model=settings.model, effort=settings.effort, timeout=TIMEOUT_SEC)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr)
    if args.language not in SUPPORTED:
        print(f"エラー: 教材づくりは今は {', '.join(SUPPORTED)} だけです", file=sys.stderr)
        return 2
    ws = Workspace(Path(args.root).expanduser().resolve(), args.language)
    try:
        for name, step in steps_for(args):
            print(f"[{name}] {step(ws)}")
    except StopRun as exc:
        print(f"止めました: {exc}\n時間をおいて同じコマンドを実行すると、続きから進みます", file=sys.stderr)
        return 3
    except (BuildError, ContentError, claude_cli.ClaudeError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="langlang-build", description="教材づくり（docs/plan.md 6 章）")
    parser.add_argument("--root", default=os.environ.get(ENV_ROOT, "."), help="リポジトリのルート（既定: カレントディレクトリ）")
    parser.add_argument("--language", default="ko")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="どこまで済んだか")
    p = sub.add_parser("import", help="国立国語院のリストを候補に取り込む")
    p.add_argument("--source", type=Path, help="リストの txt（既定: content/<言語>/sources/nikl.txt）")
    sub.add_parser("supplement", help="あいさつの表現と現代の日常語を補う（AI）")
    p = sub.add_parser("tag", help="すべての候補に粗い付与（AI）")
    p.add_argument("--parallel", type=int, default=4)
    sub.add_parser("levels", help="スコアを付けてレベルに分ける")
    for name, text in (("units", "ユニットに分ける（AI）"), ("grammar", "文法リストを作る（AI）")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--level", type=int, default=1)
    sub.add_parser("export", help="content/ に書き出す（ユニット分けまで済んだすべてのレベル）")
    for name, text in (("enrich", "詳しい付与（AI）"), ("verify-words", "単語の検算（AI）")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--level", type=int, default=1)
        p.add_argument("--parallel", type=int, default=3)
    for name, text in (("sentences", "文の生成と検算（AI）"), ("variants", "許容例の生成と検算（AI）"), ("all", "すべての段階を順に")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--level", type=int, default=1)
        p.add_argument("--parallel", type=int, default=3)
        p.add_argument("--units", help="作るユニット（カンマ区切り。既定: すべて）")
    sub.choices["sentences"].add_argument(
        "--recheck", action="store_true", help="機械の検算で要確認になった文を、今の検算で確かめ直してから進める"
    )
    p = sub.add_parser("reopen", help="work/ で直した文を機械で確かめ、AI の検算待ちに戻す（次の sentences で検算）")
    p.add_argument("--level", type=int, default=1)
    p.add_argument("ids", nargs="+", help="文の id（ko-s-L1-U02-008 など）")
    return parser


Step = Callable[[Workspace], str]


def steps_for(args: argparse.Namespace) -> list[tuple[str, Step]]:
    level = getattr(args, "level", 1)
    parallel = getattr(args, "parallel", 3)
    unit_ids = [u.strip() for u in args.units.split(",") if u.strip()] if getattr(args, "units", None) else None
    steps: dict[str, Step] = {
        "status": status,
        "import": lambda ws: import_nikl.run(ws, getattr(args, "source", None)),
        "supplement": lambda ws: supplement.run(ws, asker("enrich")),
        "tag": lambda ws: tag_candidates.run(ws, asker("tag"), parallel=getattr(args, "parallel", 4)),
        "levels": assign_levels.rank,
        "units": lambda ws: assign_levels.run_units(ws, asker("enrich"), level),
        "grammar": lambda ws: gen_grammar.run(ws, asker("enrich"), level),
        "enrich": lambda ws: enrich_words.run(ws, asker("enrich"), level, parallel),
        "verify-words": lambda ws: verify_words.run(ws, asker("verify"), level, parallel),
        "sentences": lambda ws: gen_sentences.run(ws, asker("enrich"), asker("verify"), level, unit_ids, parallel),
        "variants": lambda ws: gen_variants.run(ws, asker("enrich"), asker("verify"), level, unit_ids, parallel),
        "export": export.run,
        "reopen": lambda ws: gen_sentences.reopen(ws, getattr(args, "ids", []), level),
    }
    if args.command == "sentences" and args.recheck:
        return [("recheck", lambda ws: gen_sentences.recheck(ws, level, unit_ids)), ("sentences", steps["sentences"])]
    if args.command == "all":
        # 取り込み済みなら元のリストがなくても続けられるように、取り込みは候補がないときだけ
        steps["import"] = lambda ws: "済み" if ws.exists(import_nikl.CANDIDATES) else import_nikl.run(ws)
        steps["tag"] = lambda ws: tag_candidates.run(ws, asker("tag"), parallel=max(parallel, 4))
        order = ["import", "supplement", "tag", "levels", "units", "grammar", "enrich", "verify-words", "sentences", "variants", "export"]
        return [(name, steps[name]) for name in order]
    return [(args.command, steps[args.command])]


def status(ws: Workspace) -> str:
    lines = []
    cands = ws.read(import_nikl.CANDIDATES)
    lines.append(f"import: {'候補 ' + str(len(cands)) + ' 語' if cands else 'まだ'}")
    sup = ws.read(supplement.SUPPLEMENT)
    lines.append(f"supplement: {'あいさつ ' + str(len(sup['greetings'])) + '、現代の語 ' + str(len(sup['modern'])) if sup else 'まだ'}")
    if cands:
        lines.append(f"tag: 残り {len(tag_candidates.pending(ws))} 語")
    ranking = ws.read(assign_levels.RANKING)
    if not ranking:
        lines.append("levels: まだ")
        return "\n".join(lines)
    by_level: dict[int, int] = {}
    for e in ranking:
        if not e.get("excluded"):
            by_level[e["level"]] = by_level.get(e["level"], 0) + 1
    lines.append("levels: " + "、".join(f"L{lv} {n} 語" for lv, n in sorted(by_level.items())))
    units = ws.read(assign_levels.UNITS, {})
    for level in sorted(int(k[1:]) for k in units):
        layout = assign_levels.layout(ws, level)
        keys = [k for u in layout for k in u["keys"]]
        enriched = ws.read(enrich_words.ENRICH, {})
        verified = ws.read(verify_words.VERIFY_WORDS, {})
        grammar = ws.read(gen_grammar.GRAMMAR, {}).get(f"L{level}")
        done_units = [u for u in layout if (ws.read(gen_sentences.unit_path(u["id"])) or {}).get("status") == gen_sentences.STATE_DONE]
        variants_left = sum(len(gen_variants.pending_sentences(ws, u)) for u in layout)
        lines += [
            f"L{level} units: {len(layout)} ユニット",
            f"L{level} grammar: {str(len(grammar['items'])) + ' 個' if grammar else 'まだ'}",
            f"L{level} enrich: {sum(1 for k in keys if k in enriched)}/{len(keys)} 語",
            f"L{level} verify-words: {sum(1 for k in keys if k in verified)}/{len(keys)} 語"
            f"（要確認 {sum(1 for k in keys if k in verified and verify_words.problems(verified[k]))}）",
            f"L{level} sentences: {len(done_units)}/{len(layout)} ユニット",
            f"L{level} variants: 残り {variants_left} 文",
        ]
    return "\n".join(lines)
