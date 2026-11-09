"""書き出し（langlang-build export）。work/ の途中のデータから、画面が読む教材（content/<言語>/ の JSON）を作る。AI は使わない。

- 単語の status: 検算を通った語は approved、食い違った語は needs_review（2 つの案を review に残す）、検算がまだの語は draft。
  詳しい付与がまだの語は書き出さない（意味がないと画面に出せないため）。人が決めた語（work/decisions.json）は、
  決めた品詞・意味・漢字・語種にして approved にする
- 取り違えやすい語・同義語は、書き出す単語の中から辞書形で探して id にする。見つからない語は落とす。同じ綴りの語が
  複数あるときは、品詞と訳の重なりで 1 つに決め、決まらなければ落として報告に出す（別の語に紐づけないため）
- 類語（synonyms）は、付与の同義語と類語の段階（link_synonyms）の組を両方向にそろえ、包含を推移的に閉じる。
  矢印ゲームで、正解の語の類語をダミーに出さないため（訳が 1 つでも重なるだけの語は類語ではないので入れない。
  ダミーからは出題のときに除く）。類語のうち意味が合わない組（work/decisions.json の not_similar）は hidden_synonyms にも
  入れ、単語帳に出さない
- 文は needs_review も書き出す（学習に出すのは approved だけ。content.load が除く）
- 文の許容例は、許容例の段階（gen_variants）が今の文の中身で作ったものがあれば、それに置き換える
- 書き出したら content.validate で整合を確かめ、work/report.md に結果をまとめる
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app import content as content_mod
from app.content import meaning_atoms
from tools import candidates, decisions, gen_grammar, gen_variants, link_synonyms
from tools.assign_levels import IDS, LEVEL_REST, RANKING, UNITS, layout
from tools.enrich_words import ENRICH
from tools.gen_sentences import APPROVED, NEEDS_REVIEW, STATE_DONE, unit_path
from tools.ko.morph import normalize
from tools.tag_candidates import TAGS
from tools.verify_words import VERIFY_WORDS, origin_of, problems, suggestion
from tools.work import Workspace, now_iso, write_json

REPORT = "report.md"
# 漢字表記が要る語種。混種語は 카톡하다（外来語＋하다）のように漢字を含まないこともあるので入れない
HANJA_ORIGINS = ("漢字語",)


def run(ws: Workspace) -> str:
    """ユニット分けまで済んだすべてのレベルを書き出す（content/ の教材は全部のレベルで 1 つ）。"""
    levels = work_levels(ws)
    units = [u for lv in levels for u in layout(ws, lv)]
    words, links = build_words(ws, units)
    sentences = {u["id"]: build_sentences(ws, u) for u in units}
    # 詳しい付与がまだのレベルのユニットは、単語がないので書き出さない（画面に空のユニットを出さないため）。
    # 文法リストも、ユニットを書き出すレベルの分だけにする
    with_words = {w["unit"] for w in words}
    exported = [u for u in units if u["id"] in with_words]
    grammar = [g for lv in sorted({u["level"] for u in exported}) for g in build_grammar(ws, lv)]

    write_json(ws.content / "units.json", [{k: u[k] for k in ("id", "level", "order", "title", "scene")} for u in exported])
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
    write_report(ws, exported, words, sentences, links)
    return (
        f"ユニット {len(loaded.units)}、単語 {len(loaded.words)}（approved {len(approved.words)}）、"
        f"文 {len(loaded.sentences)}（approved {len(approved.sentences)}）を書き出しました。報告: {ws.path(REPORT)}"
    )


def work_levels(ws: Workspace) -> list[int]:
    """ユニット分けまで済んだレベル。"""
    return sorted(int(key[1:]) for key in ws.read(UNITS, {}))


def build_words(ws: Workspace, units: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """units はすべてのレベルのユニット（学ぶ順）。order はレベルの中の順。
    返すのは単語と、紐づけの報告（決められなかった同じ綴りの語、類語の組の種類の数、包含を閉じて足した組の数）。"""
    ids: dict[str, str] = ws.read(IDS, {})
    by_key = {c["key"]: c for c in candidates.load(ws)}
    ranking = {e["key"]: e for e in ws.require(RANKING, "levels")}
    tags = ws.read(TAGS, {})
    enrich = ws.read(ENRICH, {})
    verified = ws.read(VERIFY_WORDS, {})
    lemma_of = {wid: by_key[key]["lemma"] for key, wid in ids.items() if key in by_key}
    decided = decisions.words(ws, lemma_of)

    words: list[dict[str, Any]] = []
    order: Counter[int] = Counter()
    for unit in units:
        level = unit["level"]
        for key in unit["keys"]:
            order[level] += 1
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
                "order": order[level],
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
            decision = decided.get(word["id"])
            if decision:
                word.update({f: decision[f] for f in decisions.WORD_FIELDS if f in decision})
                word["status"] = "approved"
                word.pop("review", None)
            words.append(word)

    by_lemma: dict[str, list[str]] = {}
    for w in words:
        by_lemma.setdefault(normalize(w["lemma"]), []).append(w["id"])
    by_id = {w["id"]: w for w in words}
    unresolved: list[dict[str, Any]] = []
    for w in words:
        own = normalize(w["lemma"])
        w["confusables"] = _to_ids("取り違えやすい語", w["confusables"], w, by_lemma, by_id, unresolved)
        w["synonyms"] = _to_ids("類語", w["synonyms"], w, by_lemma, by_id, unresolved)
        w["homographs"] = [i for i in by_lemma[own] if i != w["id"]]
    found = link_synonyms.pairs(ws)
    closed, added = link_synonyms.closed_pairs(found)
    _link_synonyms(words, closed)
    hidden = _hide_synonyms(words, decisions.not_similar(ws, lemma_of))
    links = {"unresolved": unresolved, "kinds": Counter(kind for _, _, kind in found), "closed": added, "hidden": hidden}
    return words, links


def _hide_synonyms(words: list[dict[str, Any]], not_similar: dict[str, set[str]]) -> int:
    """単語帳に出さない類語を hidden_synonyms に入れて、組の数を返す。synonyms は変えない（ダミーから外すのに使うため）。"""
    total = 0
    for w in words:
        hidden = [other for other in w["synonyms"] if other in not_similar.get(w["id"], ())]
        if hidden:
            w["hidden_synonyms"] = hidden
            total += len(hidden)
    return total // 2


def _link_synonyms(words: list[dict[str, Any]], extra: set[tuple[str, str]]) -> None:
    """類語を両方向にそろえ、類語の段階の組（包含を閉じたもの）を足す。"""
    linked = {w["id"]: list(w["synonyms"]) for w in words}

    def link(a: str, b: str) -> None:
        if a == b or a not in linked or b not in linked:
            return
        for x, y in ((a, b), (b, a)):
            if y not in linked[x]:
                linked[x].append(y)

    for w in words:
        for other in w["synonyms"]:
            link(w["id"], other)
    for a, b in extra:
        link(a, b)
    for w in words:
        w["synonyms"] = linked[w["id"]]


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


def _to_ids(
    field: str,
    lemmas: list[str],
    source: dict[str, Any],
    by_lemma: dict[str, list[str]],
    by_id: dict[str, dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> list[str]:
    """辞書形の一覧を単語の id にする。同じ綴りの語が複数あるときは、元の語と品詞が同じ語、次に訳が重なる語に絞り、
    1 つに決まらなければ落として unresolved に残す（同じ綴りの別の語を、類語や取り違えやすい語にしないため）。"""
    found: list[str] = []
    for lemma in lemmas:
        candidates = [i for i in by_lemma.get(normalize(lemma), []) if i != source["id"]]
        chosen = _pick(candidates, source, by_id)
        if chosen is None and len(candidates) > 1:
            unresolved.append({"field": field, "lemma": source["lemma"], "target": lemma, "candidates": [_label(by_id[i]) for i in candidates]})
        if chosen and chosen not in found:
            found.append(chosen)
    return found


def _pick(candidates: list[str], source: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str | None:
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    same_pos = [i for i in candidates if by_id[i]["pos"] == source["pos"]]
    if len(same_pos) == 1:
        return same_pos[0]
    own = _atoms(source)
    overlapping = [i for i in same_pos or candidates if _atoms(by_id[i]) & own]
    return overlapping[0] if len(overlapping) == 1 else None


def _atoms(word: dict[str, Any]) -> set[str]:
    return {a for m in word["meanings"] for a in meaning_atoms(m["ja"])}


def _label(word: dict[str, Any]) -> str:
    return f"{word['lemma']}（{word['pos']}・{next(m['ja'] for m in word['meanings'] if m['primary'])}）"


def build_grammar(ws: Workspace, level: int) -> list[dict[str, Any]]:
    """そのレベルの文法リスト。まだ作っていなければ空。"""
    if f"L{level}" not in ws.read(gen_grammar.GRAMMAR, {}):
        return []
    return [
        {"id": f"{ws.language}-g-L{level}-{i:03d}", "level": level, "form": g["form"], "ja": g["ja"], "example": g["example"], "unit": g["unit"]}
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
        variants = gen_variants.lookup(ws, unit, s)
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
    ws: Workspace, units: list[dict[str, Any]], words: list[dict[str, Any]], sentences: dict[str, list[dict[str, Any]]], links: dict[str, Any]
) -> None:
    ranking = ws.require(RANKING, "levels")
    included = [e for e in ranking if not e.get("excluded")]
    excluded = [e for e in ranking if e.get("excluded")]
    levels = Counter(e["level"] for e in included)
    exported_levels = sorted({u["level"] for u in units})
    all_sentences = [s for items in sentences.values() for s in items]
    lines = [
        "# 教材づくりの報告",
        "",
        f"`langlang-build export` が {now_iso()} に書き出した結果。`content/{ws.language}/` の教材の中身と、確認が要るもの。",
        "",
        "## 数",
        "",
        f"- 候補: {len(ranking)} 語（除外 {len(excluded)} 語）",
        "- レベル: " + "、".join(f"L{lv} {levels[lv]} 語" for lv in sorted(levels) if lv != LEVEL_REST) + f"、L4 候補 {levels[LEVEL_REST]} 語",
    ]
    for lv in exported_levels:
        level_units = [u for u in units if u["level"] == lv]
        status = Counter(w["status"] for w in words if w["level"] == lv)
        level_sentences = [s for u in level_units for s in sentences[u["id"]]]
        sentence_status = Counter(s["status"] for s in level_sentences)
        lines += [
            f"- L{lv}: ユニット {len(level_units)}、書き出した単語 {sum(status.values())} 語"
            f"（approved {status['approved']}、要確認 {status['needs_review']}、検算待ち {status['draft']}）、"
            f"文 {len(level_sentences)} 文（approved {sentence_status[APPROVED]}、要確認 {sentence_status[NEEDS_REVIEW]}）、"
            f"文があるユニット {sum(1 for u in level_units if sentences[u['id']])}/{len(level_units)}",
        ]
    lines += [
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
    lines += ["", f"## 文に出てこない approved の単語（{len(unused)} 語）", "", "、".join(w["lemma"] for w in unused) or "（なし）"]
    kinds = "、".join(f"{kind} {n}" for kind, n in links["kinds"].most_common()) or "（なし）"
    lines += [
        "",
        "## 類語",
        "",
        f"- 類語のある語: {sum(1 for w in words if w['synonyms'])} / {len(words)} 語",
        f"- 類語の段階の組: {kinds}。包含を推移的に閉じて足した組: {links['closed']}",
        f"- 意味が合わないので単語帳に出さない組（ダミーからは外したまま）: {links['hidden']}",
    ]
    unresolved = links["unresolved"]
    lines += ["", f"## 同じ綴りの語が複数あって、どれか決められずに落とした類語・取り違えやすい語（{len(unresolved)} 件）", ""]
    if unresolved:
        lines += ["| 種類 | 単語 | 挙がった語 | 同じ綴りの語 |", "| --- | --- | --- | --- |"]
        lines += [f"| {u['field']} | {u['lemma']} | {u['target']} | {'、'.join(u['candidates'])} |" for u in unresolved]
    lines.append("")
    ws.path(REPORT).write_text("\n".join(lines), encoding="utf-8")


def _proposal(p: dict[str, Any]) -> str:
    return f"{p['meaning']}／{p['hanja'] or '漢字なし'}／{p['origin']}"
