"""類語の紐づけ（langlang-build synonyms）。

矢印ゲームでは、正しい答えが選択肢の中に 1 つだけになるように、正解の語の類語をダミーに出さない（app/session.py）。
類語は次の 2 つから集め、書き出し（export）で単語の synonyms に両方向で入れる。
訳が 1 つでも重なるだけの語は類語ではないので入れない（ダミーからは出題のときに除く）。

- 詳しい付与の AI が挙げた同義語（enrich の synonyms）
- この段階で AI に挙げさせた組。そのレベルまでの単語を品詞のまとまりごとに見せ、意味を選ぶ問題でどちらを選んでも
  正解と言えてしまう組を、種類（同義・包含・敬語・話し言葉と書き言葉・一部が重なる）と一緒に挙げさせる。
  見落としを減らすため、挙がった組を見せてもう 1 回呼び、見落とした組だけを挙げさせる

結果は work/synonyms.json に、レベルと品詞のまとまりごとに [a, b, 種類] の組で残す（包含は a が広い語）。
単語か意味かプロンプトの版が変わったまとまりだけを作り直す。書き出しで包含を推移的に閉じる（closed_pairs）。
"""

from __future__ import annotations

from typing import Any

from app.claude_cli import AskFn
from app.prompts import SYNONYM_KINDS, build_synonyms_prompt, style, synonyms_schema
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
INCLUDES = "包含"
# 同じ意味の言い換え。この種類でつながった語は、まとめて 1 つの意味として包含を閉じる
SAME_MEANING = ("同義", "敬語", "話し言葉と書き言葉")

Pair = tuple[str, str, str]  # (a, b, 種類)


def pending(ws: Workspace, level: int) -> list[tuple[str, list[dict[str, Any]], str]]:
    """作り直すまとまり（まとまりの名前, 単語, 指紋）。単語か意味かプロンプトの版が前と違うもの。"""
    ctx = Context.load(ws, level)
    level_saved = ws.read(SYNONYMS, {}).get(f"L{level}", {})
    todo = []
    for group, pos in GROUPS.items():
        words = [w for w in ctx.words.values() if w["pos"] in pos]
        fp = fingerprint({"style": style("synonyms", level), "words": [[w["id"], w["lemma"], w["meaning"]] for w in words]})
        if words and level_saved.get(group, {}).get("fingerprint") != fp:
            todo.append((group, words, fp))
    return todo


def run(ws: Workspace, ask: AskFn, level: int = 1, parallel: int = 3) -> str:
    todo = pending(ws, level)
    if not todo:
        return f"済み（L{level}）"
    saved = ws.read(SYNONYMS, {})
    level_saved = saved.setdefault(f"L{level}", {})

    def work(task: tuple[str, list[dict[str, Any]], str]) -> list[list[str]]:
        group, words, _ = task
        ids = [w["id"] for w in words]
        known = set(ids)

        def ask_pairs(found: list[Pair] | None) -> dict[tuple[str, str], Pair]:
            result = ask(build_synonyms_prompt(group, words, found), synonyms_schema(ids))
            pairs: dict[tuple[str, str], Pair] = {}
            for p in result["pairs"]:
                a, b, kind = p["a"], p["b"], p["kind"]
                if a == b:
                    continue
                if a not in known or b not in known or kind not in SYNONYM_KINDS:
                    raise BadOutput("一覧にない id か種類の組が返ってきた")
                # 包含は向き（a が広い語）を残し、ほかは並べ方をそろえる
                key = (min(a, b), max(a, b))
                pairs.setdefault(key, (a, b, kind) if kind == INCLUDES else (*key, kind))
            return pairs

        first = ask_pairs(None)
        more = ask_pairs(sorted(first.values()))
        merged = {**more, **first}
        return [list(p) for p in sorted(merged.values())]

    def save(task: tuple[str, list[dict[str, Any]], str], pairs: list[list[str]]) -> None:
        group, _, fp = task
        level_saved[group] = {"fingerprint": fp, "created_at": now_iso(), "pairs": pairs}
        ws.write(SYNONYMS, saved)

    outcome = batch.run("synonyms", todo, work, save, label=lambda t: f"L{level} の{t[0]}", parallel=parallel)
    return f"L{level} の {len(todo)} まとまり: {outcome.summary()}"


def pairs(ws: Workspace) -> list[Pair]:
    """この段階で挙げさせた組（すべてのレベル）。"""
    return [(p[0], p[1], p[2]) for groups in ws.read(SYNONYMS, {}).values() for g in groups.values() for p in g["pairs"]]


def closed_pairs(found: list[Pair]) -> tuple[set[tuple[str, str]], int]:
    """類語として紐づける組（並べ方をそろえた (a, b)）と、包含を閉じて足した組の数。

    同じ意味の言い換え（同義・敬語・話し言葉と書き言葉）でつながった語は 1 つのまとまりにし、包含はまとまりの間で
    推移的に閉じる（고기 ⊃ 쇠고기、쇠고기＝소고기 なら 고기 ⊃ 소고기）。一部が重なる組は、その組だけを紐づける。
    """
    parent: dict[str, str] = {}

    def root(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, kind in found:
        if kind in SAME_MEANING:
            parent[root(a)] = root(b)
        else:
            root(a), root(b)
    members: dict[str, set[str]] = {}
    for x in list(parent):
        members.setdefault(root(x), set()).add(x)

    direct = {(min(a, b), max(a, b)) for a, b, _ in found}
    linked = set(direct)
    for group in members.values():
        linked |= {(a, b) for a in group for b in group if a < b}
    narrower: dict[str, set[str]] = {}
    for a, b, kind in found:
        if kind == INCLUDES and root(a) != root(b):
            narrower.setdefault(root(a), set()).add(root(b))
    for top in narrower:
        below: set[str] = set()
        stack = list(narrower[top])
        while stack:
            g = stack.pop()
            if g in below or g == top:
                continue
            below.add(g)
            stack.extend(narrower.get(g, ()))
        linked |= {(min(a, b), max(a, b)) for a in members[top] for g in below for b in members[g]}
    return linked, len(linked - direct)
