"""書き出し（langlang-build export）。work/ の途中のデータから、画面が読む教材（content/<言語>/ の JSON）を作る。AI は使わない。

- 単語の status: 検算を通った語は approved、食い違った語は needs_review（2 つの案を review に残す）、検算がまだの語は draft。
  詳しい付与がまだの語は書き出さない（意味がないと画面に出せないため）
- 取り違えやすい語・同義語は、書き出す単語の中から辞書形で探して id にする。見つからない語は落とす
- 文は needs_review も書き出す（学習に出すのは approved だけ。content.load が除く）
- 文の許容例は、許容例の段階（gen_variants）が今の文の中身で作ったものがあれば、それに置き換える
- 書き出したら content.validate で整合を確かめ、work/report.md に結果をまとめる
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app import content as content_mod
from tools import candidates, gen_grammar, gen_variants
from tools.assign_levels import IDS, LEVEL_REST, RANKING, layout
from tools.enrich_words import ENRICH
from tools.gen_sentences import APPROVED, NEEDS_REVIEW, STATE_DONE, unit_path
from tools.ko.morph import normalize
from tools.tag_candidates import TAGS
from tools.verify_words import VERIFY_WORDS, origin_of, problems, suggestion
from tools.work import Workspace, now_iso, write_json

REPORT = "report.md"
# 漢字表記が要る語種。混種語は 카톡하다（外来語＋하다）のように漢字を含まないこともあるので入れない
HANJA_ORIGINS = ("漢字語",)


def run(ws: Workspace, level: int = 1) -> str:
    units = layout(ws, level)
    words = build_words(ws, level, units)
    grammar = build_grammar(ws, level)
    sentences = {u["id"]: build_sentences(ws, u) for u in units}

    write_json(ws.content / "units.json", [{k: u[k] for k in ("id", "level", "order", "title", "scene")} for u in units])
    write_json(ws.content / "words.json", words)
    write_json(ws.content / "grammar.json", grammar)
    sentences_dir = ws.content / "sentences"
    sentences_dir.mkdir(exist_ok=True)
    for path in sentences_dir.glob("*.json"):
        if path.stem not in sentences or not sentences[path.stem]:
            path.unlink()
    for unit_id, items in sentences.items():
        if items:
            write_json(sentences_dir / f"{unit_id}.json", items, style="keys")

    loaded = content_mod.load(ws.root, ws.language, approved_only=False)
    approved = content_mod.load(ws.root, ws.language)
    write_report(ws, level, units, words, sentences)
    return (
        f"ユニット {len(loaded.units)}、単語 {len(loaded.words)}（approved {len(approved.words)}）、"
        f"文 {len(loaded.sentences)}（approved {len(approved.sentences)}）を書き出しました。報告: {ws.path(REPORT)}"
    )


def build_words(ws: Workspace, level: int, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids: dict[str, str] = ws.read(IDS, {})
    by_key = {c["key"]: c for c in candidates.load(ws)}
    ranking = {e["key"]: e for e in ws.require(RANKING, "levels")}
    tags = ws.read(TAGS, {})
    enrich = ws.read(ENRICH, {})
    verified = ws.read(VERIFY_WORDS, {})

    words: list[dict[str, Any]] = []
    order = 0
    for unit in units:
        for key in unit["keys"]:
            order += 1
            if key not in enrich:
                continue
            c, e, tag = by_key[key], enrich[key], tags[key]
            result = verified.get(key)
            origin = origin_of(result, tag["origin"])
            word: dict[str, Any] = {
                "id": ids[key],
                "lemma": c["lemma"],
                "pos": ranking[key]["pos"],
                "level": level,
                "unit": unit["id"],
                "order": order,
                "meanings": e["meanings"],
                "origin": origin,
                "hanja": e["hanja"],
                "confusables": e["confusables"],
                "synonyms": e["synonyms"],
                "homographs": [],
                "tags": e["tags"],
                "tts_text": c["lemma"],
                "sources": _sources(c, tag),
                "score": ranking[key]["score"],
                "status": "draft",
            }
            if result and result.get("of"):
                found = problems(result)
                if not found and origin in HANJA_ORIGINS and not e["hanja"]:
                    found = ["漢字（漢字語なのに漢字がない）"]
                word["status"] = "needs_review" if found else "approved"
                if found:
                    word["review"] = {
                        "problems": found,
                        "note": result.get("note", ""),
                        "proposals": [
                            {"by": "付与", "meaning": next(m["ja"] for m in e["meanings"] if m["primary"]), "hanja": e["hanja"], "origin": tag["origin"]},
                            {"by": "検算", **suggestion(result, e, tag["origin"])},
                        ],
                    }
            words.append(word)

    by_lemma: dict[str, list[str]] = {}
    for w in words:
        by_lemma.setdefault(normalize(w["lemma"]), []).append(w["id"])
    for w in words:
        own = normalize(w["lemma"])
        w["confusables"] = _to_ids(w["confusables"], by_lemma, w["id"])
        w["synonyms"] = _to_ids(w["synonyms"], by_lemma, w["id"])
        w["homographs"] = [i for i in by_lemma[own] if i != w["id"]]
    return words


def _sources(c: dict[str, Any], tag: dict[str, Any]) -> dict[str, Any]:
    if c["source"] == "nikl":
        return {
            "nikl_headword": c["nikl"]["headword"],
            "nikl_stage": c["nikl"]["stage"],
            "nikl_rank": c["nikl"]["rank"],
            "hanken_level": tag["hanken"],
            "hanken_estimated": True,
        }
    return {"supplement": c["kind"], "hanken_level": tag["hanken"], "hanken_estimated": True}


def _to_ids(lemmas: list[str], by_lemma: dict[str, list[str]], own: str) -> list[str]:
    found: list[str] = []
    for lemma in lemmas:
        for wid in by_lemma.get(normalize(lemma), []):
            if wid != own and wid not in found:
                found.append(wid)
    return found


def build_grammar(ws: Workspace, level: int) -> list[dict[str, Any]]:
    return [
        {"id": f"{ws.language}-g-{i:03d}", "level": level, "form": g["form"], "ja": g["ja"], "example": g["example"], "unit": g["unit"]}
        for i, g in enumerate(gen_grammar.items(ws, level), start=1)
    ]


def build_sentences(ws: Workspace, unit: dict[str, Any]) -> list[dict[str, Any]]:
    state = ws.read(unit_path(unit["id"]))
    if not state:
        return []
    items = []
    for s in sorted(state["sentences"], key=lambda s: s["slot"]):
        if s["status"] not in (APPROVED, NEEDS_REVIEW):
            continue
        cloze = dict(s["cloze"])
        variants = gen_variants.lookup(ws, unit["id"], s)
        if variants is not None:
            cloze["variants"] = variants["cloze"]
        item: dict[str, Any] = {
            "id": f"{ws.language}-s-{unit['id']}-{s['slot']:03d}",
            "unit": unit["id"],
            "ko": s["ko"],
            "ja": s["ja"],
            "register": s["register"],
            "scene": s["scene"],
            "tokens": [{"surface": t["surface"], "word_ids": t["word_ids"], "eojeol": i} for i, t in enumerate(s["tokens"])],
            "grammar": s["grammar"],
            "cloze": [cloze] if 0 <= cloze["eojeol"] < len(s["tokens"]) else [],
            "variants": {"ko": variants["ko"], "ja": variants["ja"]} if variants is not None else s["variants"],
            "status": s["status"],
        }
        if s["status"] == NEEDS_REVIEW:
            item["review"] = {"problems": s["problems"]}
        items.append(item)
    return items


def write_report(
    ws: Workspace, level: int, units: list[dict[str, Any]], words: list[dict[str, Any]], sentences: dict[str, list[dict[str, Any]]]
) -> None:
    ranking = ws.require(RANKING, "levels")
    included = [e for e in ranking if not e.get("excluded")]
    excluded = [e for e in ranking if e.get("excluded")]
    levels = Counter(e["level"] for e in included)
    status = Counter(w["status"] for w in words)
    all_sentences = [s for items in sentences.values() for s in items]
    sentence_status = Counter(s["status"] for s in all_sentences)
    lines = [
        f"# 教材づくりの報告（L{level}）",
        "",
        f"`langlang-build export` が {now_iso()} に書き出した結果。`content/{ws.language}/` の教材の中身と、確認が要るもの。",
        "",
        "## 数",
        "",
        f"- 候補: {len(ranking)} 語（除外 {len(excluded)} 語）",
        "- レベル: " + "、".join(f"L{lv} {levels[lv]} 語" for lv in sorted(levels) if lv != LEVEL_REST) + f"、L4 候補 {levels[LEVEL_REST]} 語",
        f"- L{level}: ユニット {len(units)}、書き出した単語 {len(words)} 語（approved {status['approved']}、要確認 {status['needs_review']}、検算待ち {status['draft']}）",
        f"- 文: {len(all_sentences)} 文（approved {sentence_status[APPROVED]}、要確認 {sentence_status[NEEDS_REVIEW]}）、"
        f"文があるユニット {sum(1 for v in sentences.values() if v)}/{len(units)}",
        "",
        "## ユニット",
        "",
        "| ユニット | 名前 | 場面 | 単語 | 文 | どの文にも出てこない単語 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for u in units:
        state = ws.read(unit_path(u["id"])) or {}
        uncovered = "、".join(state.get("uncovered", [])) if state.get("status") == STATE_DONE else "（未作成）"
        approved = sum(1 for s in sentences[u["id"]] if s["status"] == APPROVED)
        lines.append(f"| {u['id']} | {u['title']} | {u['scene']} | {len(u['keys'])} | {approved} | {uncovered} |")
    review_words = [w for w in words if w["status"] == "needs_review"]
    lines += ["", f"## 要確認の単語（{len(review_words)} 語）", ""]
    if review_words:
        lines += ["| 単語 | 問題 | 付与の案 | 検算の案 | メモ |", "| --- | --- | --- | --- | --- |"]
        for w in review_words:
            a, b = w["review"]["proposals"]
            lines.append(
                f"| {w['lemma']}（{w['id']}） | {'・'.join(w['review']['problems'])} | {_proposal(a)} | {_proposal(b)} | {w['review']['note']} |"
            )
    review_sentences = [s for s in all_sentences if s["status"] == NEEDS_REVIEW]
    lines += ["", f"## 要確認の文（{len(review_sentences)} 文）", ""]
    if review_sentences:
        lines += ["| 文 | 訳 | 問題 |", "| --- | --- | --- |"]
        for s in review_sentences:
            lines.append(f"| {s['id']}: {s['ko']} | {s['ja']} | {' / '.join(s['review']['problems'])} |")
    tags = ws.read(TAGS, {})
    key_of = {wid: key for key, wid in ws.read(IDS, {}).items()}
    fixed_origin = [
        f"{w['lemma']}（{tags[key_of[w['id']]]['origin']} → {w['origin']}）"
        for w in words
        if w["origin"] != tags[key_of[w["id"]]]["origin"]
    ]
    lines += ["", f"## 語種を検算の案に直した語（{len(fixed_origin)} 語）", "", "、".join(fixed_origin) or "（なし）"]
    reasons = Counter(e["excluded"] for e in excluded)
    lines += ["", "## 除外した語", ""]
    for reason, count in reasons.most_common():
        examples = "、".join(e["lemma"] for e in excluded if e["excluded"] == reason)
        lines.append(f"- {reason}（{count} 語）: {examples}")
    in_sentences = {w for s in all_sentences if s["status"] == APPROVED for t in s["tokens"] for w in t["word_ids"]}
    unused = [w for w in words if w["status"] == "approved" and w["id"] not in in_sentences]
    lines += ["", f"## 文に出てこない approved の単語（{len(unused)} 語）", "", "、".join(w["lemma"] for w in unused) or "（なし）", ""]
    ws.path(REPORT).write_text("\n".join(lines), encoding="utf-8")


def _proposal(p: dict[str, Any]) -> str:
    return f"{p['meaning']}／{p['hanja'] or '漢字なし'}／{p['origin']}"
