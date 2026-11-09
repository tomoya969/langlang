"""やさしさのスコア・レベル分け・ユニット分け（docs/plan.md 6.1 の 4〜7）。

- levels（機械）: すべての候補にやさしさのスコア（0〜4、小さいほどやさしい）を付けて並べ、上から語数で L1〜L3 に分ける。
  残りは L4 候補。固定枠の語はスコアに関係なく L1 に入れる
- units（AI）: レベルの語を、場面ごとに 20〜30 語のユニットにまとめる。
  スコアの順に約 200 語ずつの帯に分け、帯の中で場面ごとにまとめる。場面のまとまりを保ちながら、
  帯の順（＝やさしい順）にユニットが並ぶので、難しさがなだらかに上がる。L1 の最初の帯は固定枠の語
- 単語の id は、ユニットに入れたときに学ぶ順に付け、work/ids.json に残す。一度付けた id は変えない
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from app.claude_cli import AskFn
from app.prompts import build_units_prompt, style, units_schema
from tools import batch, candidates
from tools.batch import BadOutput
from tools.ko.fixed import GREETING, fixed_categories
from tools.supplement import KIND_GREETING
from tools.tag_candidates import TAGS
from tools.work import BuildError, Workspace, fingerprint

log = logging.getLogger("langlang.build")

RANKING = "ranking.json"
UNITS = "units.json"
IDS = "ids.json"

LEVEL_SIZES = {1: 1000, 2: 900, 3: 1100}
LEVEL_REST = 4
HANKEN_SCORES = {"5級": 0.3, "4級": 0.8, "3級": 1.5, "準2級": 2.5, "2級以上": 3.5}
# 国立国語院の段階ごとのスコアの幅。段階の中では頻度順位で割り振る
STAGE_RANGES = {1: (0.0, 1.0), 2: (1.0, 3.0), 3: (3.0, 4.0)}
JA_COGNATE_BONUS = 0.2
NO_EXCLUSION = "なし"

BAND_SIZE = 200
UNIT_SIZE = 25
# AI が入れ忘れた語がこの割合までなら、機械でユニットに足す。それより多ければやり直させる
MAX_LEFTOVER_RATE = 0.1


# ---- levels ----


def nikl_scores(items: list[dict[str, Any]]) -> dict[str, float]:
    """国立国語院の段階と頻度順位から、0〜4 のスコアを付ける。順位のない語は段階の最後に並べる。"""
    scores: dict[str, float] = {}
    for stage, (low, high) in STAGE_RANGES.items():
        group = [c for c in items if c.get("nikl", {}).get("stage") == stage]
        group.sort(key=lambda c: (c["nikl"]["rank"] is None, c["nikl"]["rank"] or 0))
        positions: dict[Any, list[int]] = {}
        for i, c in enumerate(group):
            positions.setdefault(c["nikl"]["rank"] if c["nikl"]["rank"] is not None else "none", []).append(i)
        span = max(1, len(group) - 1)
        for c in group:
            same = positions[c["nikl"]["rank"] if c["nikl"]["rank"] is not None else "none"]
            scores[c["key"]] = low + (high - low) * (sum(same) / len(same)) / span
    return scores


def score_of(nikl_score: float | None, tag: dict[str, Any]) -> float:
    """2 つの平均（片方しかなければその値）。日本語の漢字語とそのまま対応する漢字語は少しやさしくする。"""
    parts = [s for s in (nikl_score, HANKEN_SCORES[tag["hanken"]]) if s is not None]
    score = sum(parts) / len(parts)
    if tag.get("ja_cognate") and tag.get("origin") == "漢字語":
        score -= JA_COGNATE_BONUS
    return round(max(0.0, score), 3)


def fixed_category(candidate: dict[str, Any]) -> str | None:
    if candidate.get("kind") == KIND_GREETING:
        return GREETING
    return fixed_categories().get(candidate["key"])


def rank(ws: Workspace, sizes: dict[int, int] | None = None) -> str:
    sizes = sizes or LEVEL_SIZES
    items = candidates.load(ws)
    tags = ws.read(TAGS, {})
    untagged = [c["key"] for c in items if not c.get("excluded") and c["key"] not in tags]
    if untagged:
        raise BuildError(f"粗い付与が済んでいない候補が {len(untagged)} 語あります。先に `langlang-build tag` を実行してください")
    known_fixed = set(fixed_categories())
    missing_fixed = known_fixed - {c["key"] for c in items}
    if missing_fixed:
        log.warning("固定枠の見出しが候補にありません: %s", "、".join(sorted(missing_fixed)))

    nikl = nikl_scores(items)
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for c in items:
        category = fixed_category(c)
        tag = tags.get(c["key"])
        reason = c.get("excluded") or (tag["exclude"] if tag and tag["exclude"] != NO_EXCLUSION else None)
        if reason and not category:
            excluded.append({"key": c["key"], "lemma": c["lemma"], "excluded": reason})
            continue
        included.append(
            {
                "key": c["key"],
                "lemma": c["lemma"],
                "pos": c.get("pos") or tag["pos"],
                "score": score_of(nikl.get(c["key"]), tag),
                "nikl_score": round(nikl[c["key"]], 3) if c["key"] in nikl else None,
                "hanken": tag["hanken"],
                "fixed": category,
                "_rank": c.get("nikl", {}).get("rank"),
            }
        )
    included.sort(key=lambda e: (e["fixed"] is None, e["score"], e["_rank"] is None, e["_rank"] or 0))
    position = 0
    for level in sorted(sizes):
        for entry in included[position : position + sizes[level]]:
            entry["level"] = level
        position += sizes[level]
    for entry in included[position:]:
        entry["level"] = LEVEL_REST
    for entry in included:
        del entry["_rank"]
    included.sort(key=lambda e: (e["level"], e["fixed"] is None, e["score"]))
    ws.write(RANKING, [*included, *excluded])
    counts = "、".join(f"L{lv} {sum(1 for e in included if e['level'] == lv)} 語" for lv in [*sorted(sizes), LEVEL_REST])
    fixed = sum(1 for e in included if e["fixed"])
    return f"{counts}（L4 は候補として残す）。固定枠 {fixed} 語、除外 {len(excluded)} 語"


def level_entries(ws: Workspace, level: int) -> list[dict[str, Any]]:
    entries = [e for e in ws.require(RANKING, "levels") if e.get("level") == level]
    if not entries:
        raise BuildError(f"L{level} の語がありません。`langlang-build levels` を確かめてください")
    return entries


# ---- units ----


def bands(entries: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """固定枠の帯（あれば）と、残りをスコアの順に約 BAND_SIZE 語ずつに分けた帯。"""
    fixed = [e for e in entries if e.get("fixed")]
    rest = sorted((e for e in entries if not e.get("fixed")), key=lambda e: e["score"])
    count = max(1, round(len(rest) / BAND_SIZE))
    size, extra = divmod(len(rest), count)
    result = [fixed] if fixed else []
    start = 0
    for i in range(count):
        end = start + size + (1 if i < extra else 0)
        result.append(rest[start:end])
        start = end
    return [b for b in result if b]


def _band_fingerprint(band: list[dict[str, Any]], first: bool, level: int) -> str:
    return fingerprint({"style": style("units", level), "keys": [e["key"] for e in band], "first": first})


def run_units(ws: Workspace, ask: AskFn, level: int = 1) -> str:
    """帯ごとに AI にユニットを分けさせる。帯の語が前回と同じなら、前回の分け方を使う。

    前の帯のユニットの名前を見せて名前の重なりを避けるので、帯は順に 1 つずつ分ける。
    """
    entries = level_entries(ws, level)
    by_key = {c["key"]: c for c in candidates.load(ws)}
    saved: dict[str, list[dict[str, Any]]] = ws.read(UNITS, {})
    previous = {r["fingerprint"]: r for r in saved.get(f"L{level}", [])}
    level_bands = bands(entries)
    records: list[dict[str, Any]] = []
    done = 0
    for index, band in enumerate(level_bands):
        first = index == 0 and level == 1 and bool(band[0].get("fixed"))
        fp = _band_fingerprint(band, first, level)
        if fp in previous:
            records.append(previous[fp])
            continue
        earlier = [{"title": u["title"], "scene": u["scene"]} for r in records for u in r["units"]]
        unit_count = max(1, round(len(band) / UNIT_SIZE))
        keys = [e["key"] for e in band]
        words = [candidates.prompt_item(by_key[e["key"]], pos=e["pos"], category=e.get("fixed")) for e in band]

        def work(_: None, words=words, keys=keys, unit_count=unit_count, earlier=earlier, first=first) -> list[dict[str, Any]]:
            result = ask(build_units_prompt(level, words, unit_count, earlier, first), units_schema(keys))
            return settle_units(result["units"], keys)

        results: list[list[dict[str, Any]]] = []
        name = f"L{level} の帯 {index + 1}/{len(level_bands)}"
        outcome = batch.run("units", [None], work, lambda _, r: results.append(r), label=lambda _, name=name: name)
        if outcome.failed:
            raise BuildError(f"{name} のユニット分けに失敗しました: {outcome.failed[0][1]}")
        records.append({"fingerprint": fp, "keys": keys, "units": results[0]})
        saved[f"L{level}"] = records
        ws.write(UNITS, saved)
        done += 1
    saved[f"L{level}"] = records
    ws.write(UNITS, saved)
    units = layout(ws, level)
    assign_ids(ws, [key for u in units for key in u["keys"]])
    return f"L{level}: {len(level_bands)} 帯のうち {done} 帯を分け直し、{len(units)} ユニット"


def settle_units(units: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    """AI のユニット分けを、すべての語がちょうど 1 回ずつ入る形に整える。

    2 回目以降に出てきた語は除き、入れ忘れた語は語数のいちばん少ないユニットに足す。
    入れ忘れが多すぎるときは BadOutput（やり直させる）。
    """
    seen: set[str] = set()
    settled = []
    allowed = set(keys)
    for unit in units:
        unit_keys = []
        for key in unit["keys"]:
            if key in allowed and key not in seen:
                seen.add(key)
                unit_keys.append(key)
        if unit_keys:
            settled.append({"title": unit["title"].strip(), "scene": unit["scene"].strip(), "keys": unit_keys})
    leftover = [k for k in keys if k not in seen]
    if not settled or len(leftover) > len(keys) * MAX_LEFTOVER_RATE:
        raise BadOutput(f"ユニットに入っていない語が {len(leftover)} 語あります")
    for key in leftover:
        min(settled, key=lambda u: len(u["keys"]))["keys"].append(key)
    if leftover:
        log.warning("ユニットに入っていなかった %d 語を機械で足しました: %s", len(leftover), "、".join(leftover))
    return settled


def layout(ws: Workspace, level: int) -> list[dict[str, Any]]:
    """レベルのユニットの並び。id・順・名前・場面と、学ぶ順に並べた単語の見出し（keys）。"""
    records = ws.require(UNITS, "units").get(f"L{level}")
    if not records:
        raise BuildError(f"L{level} のユニットがありません。先に `langlang-build units --level {level}` を実行してください")
    entries = level_entries(ws, level)
    scores = {e["key"]: e["score"] for e in entries}
    fixed = {e["key"] for e in entries if e.get("fixed")}
    ordered: list[dict[str, Any]] = []
    for record in records:
        units = [{**u, "keys": sorted(u["keys"], key=lambda k: scores.get(k, 9.0))} for u in record["units"]]
        # 固定枠の帯は、AI が学ぶ順に並べたまま（1 つ目をあいさつにするため）
        if not set(record["keys"]) & fixed:
            units.sort(key=lambda u: statistics.mean(scores.get(k, 9.0) for k in u["keys"]))
        ordered.extend(units)
    return [
        {"id": f"L{level}-U{i:02d}", "level": level, "order": i, "title": u["title"], "scene": u["scene"], "keys": u["keys"]}
        for i, u in enumerate(ordered, start=1)
    ]


def assign_ids(ws: Workspace, keys: list[str]) -> dict[str, str]:
    """まだ id のない見出しに、渡された順で id を付ける。一度付けた id は変えない。"""
    ids: dict[str, str] = ws.read(IDS, {})
    next_number = max((int(v.rsplit("-", 1)[1]) for v in ids.values()), default=0) + 1
    for key in keys:
        if key not in ids:
            ids[key] = f"{ws.language}-w-{next_number:04d}"
            next_number += 1
    ws.write(IDS, ids)
    return ids
