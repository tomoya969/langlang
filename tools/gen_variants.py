"""許容例の作り直し（langlang-build variants。docs/plan.md 5.4・6.3）。

採点は、答えが模範解答か許容例に一致すれば AI を呼ばずに正解にするので、学習者が書きそうな正しい言い方を許容例に集める。
文は作り直さず、できている文（approved と要確認）に許容例を足す。ユニットごとに

1. 作る（質を優先するモデル）: 日→韓の許容例（ko）、韓→日の許容例（ja）、穴埋めの空欄の許容例（cloze）
2. 機械で除く: 模範解答と同じ、空白だけが違う、発音が同じ（綴りの誤りを正解にしてしまうため）、数字・ローマ字を含む
3. 文を作ったときの許容例と合わせて、AI で検算する（別の呼び出し）。受け入れられないものを除く

結果は work/variants/<ユニット>.json に文の枠（slot）ごとに残す。文の中身（ko・ja・文体・穴埋め）か
プロンプトの版が変わった文だけを作り直す。書き出し（export）がこれを文の許容例にする。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app import langs
from app.claude_cli import AskFn
from app.content import blank_eojeol
from app.prompts import (
    build_variants_prompt,
    build_verify_variants_prompt,
    style,
    variants_schema,
    verify_variants_schema,
)
from tools import batch
from tools.assign_levels import layout
from tools.batch import BadOutput
from tools.gen_sentences import APPROVED, NEEDS_REVIEW, unit_path
from tools.work import BuildError, Workspace, fingerprint, now_iso

log = logging.getLogger("langlang.build")

VARIANTS_DIR = "variants"
MAX_KO = 12
MAX_JA = 6
MAX_CLOZE = 5
_NOT_HANGUL_TEXT = re.compile(r"[0-9A-Za-z]")


def variants_path(unit_id: str) -> str:
    return f"{VARIANTS_DIR}/{unit_id}.json"


def sentence_fingerprint(sentence: dict[str, Any], level: int) -> str:
    return fingerprint(
        {
            "style": [style("variants", level), style("verify_variants", level)],
            "ko": sentence["ko"],
            "ja": sentence["ja"],
            "register": sentence["register"],
            "cloze": sentence["cloze"],
        }
    )


def lookup(ws: Workspace, unit: dict[str, Any], sentence: dict[str, Any]) -> dict[str, list[str]] | None:
    """書き出し用。文の今の中身で作った許容例（ko・ja・cloze）があれば返す。"""
    entry = (ws.read(variants_path(unit["id"])) or {}).get("sentences", {}).get(str(sentence["slot"]))
    if not entry or entry.get("fingerprint") != sentence_fingerprint(sentence, unit["level"]):
        return None
    return {"ko": entry["ko"], "ja": entry["ja"], "cloze": entry["cloze"]}


def run(ws: Workspace, ask_write: AskFn, ask_check: AskFn, level: int = 1, unit_ids: list[str] | None = None, parallel: int = 3) -> str:
    units = layout(ws, level)
    targets = [u for u in units if not unit_ids or u["id"] in unit_ids]
    if unit_ids and len(targets) != len(set(unit_ids)):
        raise BuildError(f"ユニットがありません: {'、'.join(sorted(set(unit_ids) - {u['id'] for u in targets}))}")
    todo = [(u, pending) for u in targets if (pending := pending_sentences(ws, u))]
    if not todo:
        return "作る許容例はありません（済みか、文がまだのユニットだけ）"

    def save(task: tuple[dict[str, Any], list[dict[str, Any]]], entries: dict[str, dict[str, Any]]) -> None:
        unit = task[0]
        with ws.lock:
            saved = ws.read(variants_path(unit["id"])) or {"unit": unit["id"], "sentences": {}}
            saved["sentences"].update(entries)
            saved["sentences"] = dict(sorted(saved["sentences"].items(), key=lambda kv: int(kv[0])))
            saved["updated_at"] = now_iso()
            ws.write(variants_path(unit["id"]), saved)

    outcome = batch.run(
        "variants",
        todo,
        lambda task: build_unit(task[0], task[1], ask_write, ask_check),
        save,
        label=lambda task: task[0]["id"],
        parallel=parallel,
    )
    count = sum(len(p) for _, p in todo)
    return f"{len(todo)} ユニット・{count} 文: {outcome.summary()}"


def pending_sentences(ws: Workspace, unit: dict[str, Any]) -> list[dict[str, Any]]:
    """許容例を作る文（できている文のうち、今の中身で作った許容例がないもの）。"""
    state = ws.read(unit_path(unit["id"]))
    if not state:
        return []
    return [
        s
        for s in sorted(state["sentences"], key=lambda s: s["slot"])
        if s["status"] in (APPROVED, NEEDS_REVIEW) and lookup(ws, unit, s) is None
    ]


def build_unit(unit: dict[str, Any], sentences: list[dict[str, Any]], ask_write: AskFn, ask_check: AskFn) -> dict[str, dict[str, Any]]:
    keys = [f"s{s['slot']}" for s in sentences]
    items = [_prompt_item(key, s) for key, s in zip(keys, sentences)]
    made = ask_write(build_variants_prompt(unit, items), variants_schema(keys))["sentences"]
    _require_keys(made, keys, "許容例")

    candidates: dict[str, dict[str, list[str]]] = {}
    for key, s in zip(keys, sentences):
        old = s["variants"]
        candidates[key] = {
            "ko": filter_ko(s["ko"], [*old.get("ko", []), *made[key]["ko"]])[:MAX_KO],
            "ja": filter_ja(s["ja"], [*old.get("ja", []), *made[key]["ja"]])[:MAX_JA],
            "cloze": filter_cloze(s["cloze"], made[key]["cloze"])[:MAX_CLOZE] if _has_cloze(s) else [],
        }
    checked = ask_check(
        build_verify_variants_prompt(unit, [{**item, "candidates": candidates[item["key"]]} for item in items]),
        verify_variants_schema(keys),
    )["sentences"]
    _require_keys(checked, keys, "許容例の検算")

    entries: dict[str, dict[str, Any]] = {}
    for key, s in zip(keys, sentences):
        bad = {(b["kind"], " ".join(b["text"].split())) for b in checked[key]["bad"]}
        entry: dict[str, Any] = {"fingerprint": sentence_fingerprint(s, unit["level"])}
        for kind in ("ko", "ja", "cloze"):
            entry[kind] = [v for v in candidates[key][kind] if (kind, v) not in bad]
        entry["rejected"] = [{"kind": b["kind"], "text": b["text"], "reason": b["reason"]} for b in checked[key]["bad"]]
        entries[str(s["slot"])] = entry
    return entries


def _prompt_item(key: str, s: dict[str, Any]) -> dict[str, Any]:
    cloze = None
    if _has_cloze(s):
        c = s["cloze"]
        cloze = {"blanked": blank_eojeol(s["ko"], c["eojeol"]), "hint_ja": c["hint_ja"], "answer": c["answer"]}
    return {
        "key": key,
        "ko": s["ko"],
        "ja": s["ja"],
        "register": s["register"],
        "scene": s["scene"],
        "cloze": cloze,
        "variants": {"ko": s["variants"].get("ko", []), "ja": s["variants"].get("ja", []), "cloze": []},
    }


def _has_cloze(s: dict[str, Any]) -> bool:
    return 0 <= s["cloze"]["eojeol"] < len(s["tokens"])


def _require_keys(result: dict[str, Any], keys: list[str], what: str) -> None:
    missing = [k for k in keys if k not in result]
    if missing:
        raise BadOutput(f"{what}が返ってこなかった文があります: {'、'.join(missing)}")


def filter_ko(original: str, values: list[str]) -> list[str]:
    """韓国語の許容例の機械の確認。模範解答と空白だけ・綴りだけ（発音が同じ）が違うものは、採点が注意つきにするので除く。"""
    pack = langs.get("ko")
    base = pack.normalize(original)
    seen = {base}
    sounds = {pack.pronounce(base)} if pack.pronounce else set()
    out: list[str] = []
    for v in values:
        v = " ".join(v.split())
        norm = pack.normalize(v)
        if not norm or norm in seen or _NOT_HANGUL_TEXT.search(v) or norm.replace(" ", "") == base.replace(" ", ""):
            continue
        if pack.pronounce and pack.pronounce(norm) in sounds:
            continue
        seen.add(norm)
        out.append(v)
    return out


def filter_ja(original: str, values: list[str]) -> list[str]:
    seen = {original.strip()}
    out = []
    for v in values:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def filter_cloze(cloze: dict[str, Any], values: list[str]) -> list[str]:
    """空欄の許容例は 1 つの語節だけ。答えと発音が同じものは除く。"""
    return [v for v in filter_ko(cloze["answer"], values) if " " not in v]
