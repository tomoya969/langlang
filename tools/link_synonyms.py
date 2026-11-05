"""類語の紐づけ（langlang-build synonyms）。

矢印ゲームでは、正しい答えが選択肢の中に 1 つだけになるように、正解の語の類語をダミーに出さない（app/session.py）。
類語は次の 3 つから集め、書き出し（export）で単語の synonyms に両方向で入れる。

- 詳しい付与の AI が挙げた同義語（enrich の synonyms）
- 訳が 1 つでも重なる語（機械。app.content.meaning_atoms）
- この段階で AI に挙げさせた組。そのレベルまでの単語を品詞のまとまりごとに見せ、意味を選ぶ問題でどちらを選んでも
  正解と言えてしまう組（類語・意味の一部が重なる語・片方がもう片方を含む語・敬語とふつうの言い方など）を挙げさせる

結果は work/synonyms.json に、レベルと品詞のまとまりごとに残す。単語か意味かプロンプトの版が変わったまとまりだけを作り直す。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import SYNONYMS_STYLE, build_synonyms_prompt, synonyms_schema
from tools import batch
from tools.batch import BadOutput
from tools.gen_sentences import Context
from tools.work import Workspace, fingerprint, now_iso

SYNONYMS = "synonyms.json"
# 品詞のまとまり。類語はたいてい同じまとまりの中にあり、ダミーも同じ品詞から選ぶ
GROUPS = {
    "名詞・代名詞": ("名詞", "依存名詞", "代名詞", "固有名詞"),
    "動詞・形容詞": ("動詞", "形容詞"),
    "副詞・冠形詞・感嘆詞・数詞・表現": ("副詞", "冠形詞", "感嘆詞", "数詞", "表現"),
}


def run(ws: Workspace, ask: AskFn, level: int = 1, parallel: int = 3) -> str:
    ctx = Context.load(ws, level)
    saved = ws.read(SYNONYMS, {})
    level_saved = saved.setdefault(f"L{level}", {})
    todo = []
    for group, pos in GROUPS.items():
        words = [w for w in ctx.words.values() if w["pos"] in pos]
        fp = fingerprint({"style": SYNONYMS_STYLE, "words": [[w["id"], w["lemma"], w["meaning"]] for w in words]})
        if words and level_saved.get(group, {}).get("fingerprint") != fp:
            todo.append((group, words, fp))
    if not todo:
        return f"済み（L{level}）"

    def work(task: tuple[str, list[dict[str, Any]], str]) -> list[list[str]]:
        group, words, _ = task
        ids = [w["id"] for w in words]
        result = ask(build_synonyms_prompt(group, words), synonyms_schema(ids))
        known = set(ids)
        pairs = {tuple(sorted((p["a"], p["b"]))) for p in result["pairs"] if p["a"] != p["b"]}
        if any(a not in known or b not in known for a, b in pairs):
            raise BadOutput("一覧にない id の組が返ってきた")
        return [list(p) for p in sorted(pairs)]

    def save(task: tuple[str, list[dict[str, Any]], str], pairs: list[list[str]]) -> None:
        group, _, fp = task
        level_saved[group] = {"fingerprint": fp, "created_at": now_iso(), "pairs": pairs}
        ws.write(SYNONYMS, saved)

    outcome = batch.run("synonyms", todo, work, save, label=lambda t: f"L{level} の{t[0]}", parallel=parallel)
    return f"L{level} の {len(todo)} まとまり: {outcome.summary()}"


def pairs(ws: Workspace) -> list[tuple[str, str]]:
    """この段階で挙げさせた類語の組（すべてのレベル）。"""
    return [(a, b) for groups in ws.read(SYNONYMS, {}).values() for g in groups.values() for a, b in g["pairs"]]
