"""文の生成と検算（langlang-build sentences。docs/plan.md 6.3）。

ユニットごとに、そのユニットまでの単語と文法だけで 12〜15 文を作り、検算する。
1. 作る（質を優先するモデル）→ 機械の検算（Kiwi）
2. 機械の検算を通った文を AI で検算する（別の呼び出し）
3. どちらかで落ちた文は、問題を添えて作り直させる。2 回落ちた文は「要確認」にする
4. 最後に、まだどの文にも出てこないユニットの単語があれば、その単語の文を 1 回だけ足す

ユニットの途中の状態は AI を呼ぶたびに work/sentences/<ユニット>.json に残す。止まっても、再実行すれば続きから進む。
文の id はユニットの中の枠の番号（slot）で決まり、作り直しても同じ枠なら変わらない。
落ちた文には、どちらの検算で落ちたか（failed_by）を残す。機械の検算を直したら、--recheck で
機械の検算で要確認になった文だけを確かめ直し、通った文を AI の検算に回せる。
"""

from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass
from typing import Any

from app.claude_cli import AskFn
from app.content import all_meanings_text
from app.prompts import SENTENCES_STYLE, VERIFY_SENTENCES_STYLE, build_sentences_prompt, sentences_schema
from tools import batch, candidates, decisions, gen_grammar
from tools.assign_levels import IDS, LEVEL_REST, RANKING, layout
from tools.batch import BadOutput
from tools.enrich_words import ENRICH
from tools.ko.morph import Lexicon, normalize
from tools.verify_sentences import Checker, ai_check, apply_fixes, clean
from tools.verify_words import VERIFY_WORDS
from tools.work import BuildError, Workspace, fingerprint, now_iso

log = logging.getLogger("langlang.build")

SENTENCES_DIR = "sentences"
MIN_SENTENCES = 12
MAX_SENTENCES = 15
MAX_FAILURES = 2
MAX_UNIT_WORDS_PER_SENTENCE = 3
REGISTER_RULES = {
    1: "해요체 を中心にする。あいさつなどの決まった表現をそのまま使う文だけは 합니다체 にしてよい（多くても 3 文）",
    2: "해요체 を中心にし、改まった場面（発表・案内・面接・店の放送など）の文は 합니다체、友達・家族・年下との会話の文は 반말 にする"
    "（합니다체 と 반말 はそれぞれ 2〜4 文ほど）。話し手と聞き手の関係に合う文体にし、scene に誰が誰に言うかを書く",
    3: "해요체 を中心にし、합니다체 と 반말 も場面に合わせて使う。日記・説明文・記事・メモなどの書き言葉の文は 한다체 にする"
    "（한다체 は 2〜4 文ほど）。scene に誰が誰に言うか、何に書くかを書く",
}

PENDING = "pending"
APPROVED = "approved"
NEEDS_REVIEW = "needs_review"
STATE_WORKING = "working"
STATE_DONE = "done"
FAILED_BY_MACHINE = "machine"
FAILED_BY_AI = "ai"


def sentence_count(word_count: int) -> int:
    """1 文に 2 語ずつ入れれば、そのユニットの単語がどれも 1 文以上に出る数（12〜15 文）。"""
    return max(MIN_SENTENCES, min(MAX_SENTENCES, math.ceil(word_count / 2)))


def unit_path(unit_id: str) -> str:
    return f"{SENTENCES_DIR}/{unit_id}.json"


@dataclass
class Context:
    """文を作るのに要る単語（id ごとの見出し・品詞・意味・ユニット）と、どの語がどこで出るか。
    単語は、そのレベルと前のレベルのもの（L2 の文は L1 の単語も使う）。unit_order は（レベル, ユニットの順）。"""

    ws: Workspace
    level: int
    units: list[dict[str, Any]]
    words: dict[str, dict[str, Any]]
    known: dict[str, str]

    @classmethod
    def load(cls, ws: Workspace, level: int) -> Context:
        units = layout(ws, level)
        earlier_units = [u for lv in range(1, level) for u in layout(ws, lv)]
        ids: dict[str, str] = ws.read(IDS, {})
        enrich = ws.read(ENRICH, {})
        verified = ws.read(VERIFY_WORDS, {})
        ranking = ws.require(RANKING, "levels")
        by_key = {c["key"]: c for c in candidates.load(ws)}
        pos = {e["key"]: e.get("pos") for e in ranking}
        decided = decisions.words(ws, {wid: by_key[key]["lemma"] for key, wid in ids.items() if key in by_key})
        words: dict[str, dict[str, Any]] = {}
        known: dict[str, str] = {}
        for unit in [*earlier_units, *units]:
            for key in unit["keys"]:
                known.setdefault(normalize(by_key[key]["lemma"]), f"{unit['id']}「{unit['title']}」で出る語")
                if key not in enrich:
                    continue
                decision = decided.get(ids[key], {})
                words[ids[key]] = {
                    "id": ids[key],
                    "key": key,
                    "lemma": by_key[key]["lemma"],
                    "pos": decision.get("pos", pos[key]),
                    "meaning": _meanings(enrich[key], verified.get(key), decision),
                    "unit": unit["id"],
                    "unit_order": (unit["level"], unit["order"]),
                }
        for entry in ranking:
            if entry.get("excluded"):
                where = "教材から除いた語"
            elif entry["level"] == LEVEL_REST:
                where = "L4 候補の語"
            elif entry["level"] > level:
                where = f"L{entry['level']} の語"
            else:
                continue
            known.setdefault(normalize(entry["lemma"]), where)
        return cls(ws, level, units, words, known)

    def unit_words(self, unit: dict[str, Any]) -> list[dict[str, Any]]:
        return [w for w in self.words.values() if w["unit"] == unit["id"]]

    def earlier_words(self, unit: dict[str, Any]) -> list[dict[str, Any]]:
        return [w for w in self.words.values() if w["unit_order"] < (unit["level"], unit["order"])]

    def lexicon(self, unit: dict[str, Any]) -> Lexicon:
        allowed = {w["id"]: w for w in self.words.values() if w["unit_order"] <= (unit["level"], unit["order"])}
        return Lexicon(allowed=allowed, known=self.known)

    def missing_words(self, unit: dict[str, Any]) -> int:
        """そのユニットまでで、詳しい付与がまだの語の数（意味が分からないと文を作れない）。"""
        enriched = {w["key"] for w in self.words.values()}
        return sum(1 for u in self.units if u["order"] <= unit["order"] for k in u["keys"] if k not in enriched)


def _meanings(enriched: dict[str, Any], verified: dict[str, Any] | None, decision: dict[str, Any]) -> str:
    """文に使う意味。主な意味が先で、ほかの意味も並べる（主な意味だけだと、別の意味で使った正しい文を検算が落とすため）。
    人が決めた意味があればそれ、検算で主な意味が直されていれば検算の案を主な意味にする（要確認の語でも文は作る）。"""
    if decision.get("meanings"):
        return all_meanings_text(decision["meanings"])
    meanings = list(enriched["meanings"])
    if verified and not verified.get("meaning_ok", True) and verified.get("suggested_meaning", "").strip():
        meanings = [{"ja": verified["suggested_meaning"].strip(), "primary": True}] + [m for m in meanings if not m["primary"]]
    return all_meanings_text(meanings)


def run(ws: Workspace, ask_write: AskFn, ask_check: AskFn, level: int = 1, unit_ids: list[str] | None = None, parallel: int = 3) -> str:
    if level not in REGISTER_RULES:
        raise BuildError(f"L{level} の文体の決まりがまだありません（tools/gen_sentences.py の REGISTER_RULES）")
    ctx = Context.load(ws, level)
    gen_grammar.items(ws, level)
    targets = [u for u in ctx.units if not unit_ids or u["id"] in unit_ids]
    if unit_ids and len(targets) != len(set(unit_ids)):
        raise BuildError(f"ユニットがありません: {'、'.join(sorted(set(unit_ids) - {u['id'] for u in targets}))}")
    todo = []
    for unit in targets:
        state = ws.read(unit_path(unit["id"]))
        if state and state.get("fingerprint") == unit_fingerprint(ctx, unit) and state.get("status") == STATE_DONE:
            continue
        missing = ctx.missing_words(unit)
        if missing:
            log.warning("[sentences] %s: 詳しい付与がまだの語が %d 語あるので飛ばします", unit["id"], missing)
            continue
        todo.append(unit)
    if not todo:
        return "作る文はありません（済みか、詳しい付与がまだのユニットだけ）"
    checker = Checker()
    results: dict[str, dict[str, Any]] = {}
    outcome = batch.run(
        "sentences",
        todo,
        lambda unit: build_unit(ctx, unit, checker, ask_write, ask_check),
        lambda unit, state: results.__setitem__(unit["id"], state),
        label=lambda unit: unit["id"],
        parallel=parallel,
    )
    review = sum(1 for s in results.values() for x in s["sentences"] if x["status"] == NEEDS_REVIEW)
    return f"{len(todo)} ユニット: {outcome.summary()}。要確認の文 {review} 文"


def unit_fingerprint(ctx: Context, unit: dict[str, Any]) -> str:
    """ユニットの単語・使ってよい単語・文法・プロンプトの版が変わったら作り直す。"""
    return fingerprint(
        {
            "style": [SENTENCES_STYLE, VERIFY_SENTENCES_STYLE],
            "unit": unit["id"],
            "words": [w["id"] for w in ctx.unit_words(unit)],
            "allowed": sorted(ctx.lexicon(unit).allowed),
            "grammar": [g["form"] for g in gen_grammar.allowed(ctx.ws, ctx.level, unit["id"])],
        }
    )


class UnitBuilder:
    """1 ユニットの文を作って検算する。状態（self.state）は AI を呼ぶたびに保存する。"""

    def __init__(self, ctx: Context, unit: dict[str, Any], checker: Checker, ask_write: AskFn, ask_check: AskFn):
        self.ctx = ctx
        self.unit = unit
        self.checker = checker
        self.ask_write = ask_write
        self.ask_check = ask_check
        self.path = unit_path(unit["id"])
        self.unit_words = ctx.unit_words(unit)
        self.unit_ids = {w["id"] for w in self.unit_words}
        self.lexicon = ctx.lexicon(unit)
        self.grammar = gen_grammar.allowed(ctx.ws, ctx.level, unit["id"])
        self.schema = sentences_schema(sorted(self.lexicon.allowed), [g["form"] for g in self.grammar])
        fp = unit_fingerprint(ctx, unit)
        saved = ctx.ws.read(self.path)
        if saved and saved.get("fingerprint") == fp:
            self.state = saved
        else:
            self.state = {"fingerprint": fp, "unit": unit["id"], "status": STATE_WORKING, "added": False, "sentences": []}

    @property
    def sentences(self) -> list[dict[str, Any]]:
        return self.state["sentences"]

    def save(self) -> None:
        self.state["updated_at"] = now_iso()
        self.ctx.ws.write(self.path, self.state)

    def build(self) -> dict[str, Any]:
        if not self.sentences:
            self._add(self._write(sentence_count(len(self.unit_words))))
        while self.state["status"] != STATE_DONE:
            if self._verify() or self._rewrite() or self._fill_gaps():
                continue
            covered = self._covered(self.sentences, statuses=(APPROVED,))
            self.state["uncovered"] = [w["lemma"] for w in self.unit_words if w["id"] not in covered]
            self.state["status"] = STATE_DONE
            self.save()
        return self.state

    # ---- 段階 ----

    def _verify(self) -> bool:
        """機械の検算を通って、まだ AI の検算をしていない文を検算する。検算したら True。"""
        targets = [s for s in self.sentences if s["status"] == PENDING and s["checked"]]
        if not targets:
            return False
        words = {w["id"]: w for w in self.lexicon.allowed.values()}
        verdicts = ai_check(self.ask_check, self.unit, [(f"s{s['slot']}", s) for s in targets], self.grammar, words)
        for s in targets:
            verdict = verdicts[f"s{s['slot']}"]
            if verdict["ok"]:
                apply_fixes(s, verdict)
                s.update(status=APPROVED, problems=[], failed_by=None)
            else:
                s.update(checked=False, problems=verdict["problems"] or ["検算で不合格（理由なし）"], failed_by=FAILED_BY_AI)
        self.save()
        return True

    def _rewrite(self) -> bool:
        """落ちた文を数え、まだ 2 回落ちていない文を作り直させる。作り直したら True。"""
        failed = [s for s in self.sentences if s["status"] == PENDING and not s["checked"]]
        for s in failed:
            s["failures"] += 1
            if s["failures"] >= MAX_FAILURES:
                s["status"] = NEEDS_REVIEW
        retry = [s for s in failed if s["status"] == PENDING]
        if not retry:
            if failed:
                self.save()
            return False
        others = [s for s in self.sentences if s not in retry and s["status"] != NEEDS_REVIEW]
        covered = self._covered(others, statuses=(APPROVED, PENDING))
        # 作り直す文にしか出てこない単語を先に、まだどの文にも出てこない単語をその後に
        used_by_retry = [w for w in self.unit_words if w["id"] not in covered and any(w["id"] in _ids(s) for s in retry)]
        must_use = used_by_retry + [w for w in self.unit_words if w["id"] not in covered and w not in used_by_retry]
        new = self._write(
            len(retry),
            retry=[{"ko": s["ko"], "problems": s["problems"]} for s in retry],
            must_use=must_use[: len(retry) * MAX_UNIT_WORDS_PER_SENTENCE],
            keep=[s["ko"] for s in others],
        )
        for s, raw in zip(retry, new):
            self._fill(s, raw)
        for s in retry[len(new) :]:
            s.update(status=NEEDS_REVIEW, problems=[*s["problems"], "作り直しの文が返ってこなかった"])
        self.save()
        return True

    def _fill_gaps(self) -> bool:
        """まだどの文にも出てこないユニットの単語があれば、その単語の文を 1 回だけ足す。足したら True。"""
        if self.state["added"]:
            return False
        live = [s for s in self.sentences if s["status"] != NEEDS_REVIEW]
        covered = self._covered(live, statuses=(APPROVED,))
        gaps = [w for w in self.unit_words if w["id"] not in covered]
        room = MAX_SENTENCES - len(live)
        self.state["added"] = True
        if not gaps or room <= 0:
            self.save()
            return False
        count = min(room, math.ceil(len(gaps) / 2))
        self._add(self._write(count, must_use=gaps[: count * MAX_UNIT_WORDS_PER_SENTENCE], keep=[s["ko"] for s in live]))
        return True

    # ---- 部品 ----

    def _write(self, count: int, **retry: Any) -> list[dict[str, Any]]:
        prompt = build_sentences_prompt(
            self.unit,
            count,
            self.unit_words,
            self.ctx.earlier_words(self.unit),
            self.grammar,
            REGISTER_RULES[self.ctx.level],
            **retry,
        )
        result = self.ask_write(prompt, self.schema)["sentences"]
        if not result:
            raise BadOutput("文が 1 つも返ってこなかった")
        return result[:count] if retry else result[:MAX_SENTENCES]

    def _add(self, raws: list[dict[str, Any]]) -> None:
        slot = max((s["slot"] for s in self.sentences), default=0)
        for raw in raws:
            slot += 1
            sentence = {"slot": slot, "status": PENDING, "failures": 0}
            self._fill(sentence, raw)
            self.sentences.append(sentence)
        self.save()

    def _fill(self, sentence: dict[str, Any], raw: dict[str, Any]) -> None:
        sentence.update(clean(raw))
        problems = self.checker.check(sentence, self.lexicon, self.unit_ids)
        sentence.update(checked=not problems, problems=problems, failed_by=FAILED_BY_MACHINE if problems else None)

    @staticmethod
    def _covered(sentences: list[dict[str, Any]], statuses: tuple[str, ...]) -> set[str]:
        return {w for s in sentences if s["status"] in statuses for w in _ids(s)}


def _ids(sentence: dict[str, Any]) -> set[str]:
    return {w for t in sentence.get("tokens", []) for w in t["word_ids"]}


def recheck(ws: Workspace, level: int = 1, unit_ids: list[str] | None = None) -> str:
    """機械の検算で要確認になった文を、今の機械の検算で確かめ直す。

    通った文は AI の検算待ちに戻す（作り直しはしない。AI の検算で落ちたらそのまま要確認）。
    """
    ctx = Context.load(ws, level)
    checker = Checker()
    reopened = 0
    for unit in ctx.units:
        if unit_ids and unit["id"] not in unit_ids:
            continue
        state = ws.read(unit_path(unit["id"]))
        if not state or state.get("fingerprint") != unit_fingerprint(ctx, unit):
            continue
        lexicon = ctx.lexicon(unit)
        unit_word_ids = {w["id"] for w in ctx.unit_words(unit)}
        found = 0
        for s in state["sentences"]:
            if s["status"] != NEEDS_REVIEW or s.get("failed_by") != FAILED_BY_MACHINE:
                continue
            trial = copy.deepcopy(s)
            if checker.check(trial, lexicon, unit_word_ids):
                continue
            s.update(trial, status=PENDING, checked=True, problems=[], failed_by=None, failures=MAX_FAILURES - 1)
            found += 1
        if found:
            state["status"] = STATE_WORKING
            state["updated_at"] = now_iso()
            ws.write(unit_path(unit["id"]), state)
            reopened += found
    return f"機械の検算で要確認になっていた文のうち {reopened} 文が、今の検算を通りました（AI の検算に回します）"


def reopen(ws: Workspace, sentence_ids: list[str], level: int = 1) -> str:
    """人が work/sentences/ で直した文（要確認の文など）を、機械の検算で確かめ直し、通れば AI の検算待ちに戻す。

    作り直しはしない（AI の検算で落ちたらそのまま要確認）。次の sentences で AI の検算をする。
    """
    ctx = Context.load(ws, level)
    checker = Checker()
    by_unit: dict[str, list[int]] = {}
    for sid in sentence_ids:
        unit_id, _, slot = sid.removeprefix(f"{ws.language}-s-").rpartition("-")
        if not unit_id or not slot.isdigit():
            raise BuildError(f"文の id の形が違います: {sid}（例: {ws.language}-s-L1-U02-008）")
        by_unit.setdefault(unit_id, []).append(int(slot))
    units = {u["id"]: u for u in ctx.units}
    lines = []
    for unit_id, slots in by_unit.items():
        if unit_id not in units:
            raise BuildError(f"ユニットがありません: {unit_id}")
        unit = units[unit_id]
        state = ws.read(unit_path(unit_id))
        found = {s["slot"]: s for s in (state or {}).get("sentences", [])}
        lexicon = ctx.lexicon(unit)
        unit_word_ids = {w["id"] for w in ctx.unit_words(unit)}
        for slot in slots:
            s = found.get(slot)
            if s is None:
                raise BuildError(f"文がありません: {unit_id} の {slot}")
            problems = checker.check(s, lexicon, unit_word_ids)
            if problems:
                lines.append(f"{unit_id}-{slot:03d}: 機械の検算で落ちました（{' / '.join(problems)}）")
                continue
            s.update(status=PENDING, checked=True, problems=[], failed_by=None, failures=MAX_FAILURES - 1)
            lines.append(f"{unit_id}-{slot:03d}: AI の検算に回します")
        state["status"] = STATE_WORKING
        state["updated_at"] = now_iso()
        ws.write(unit_path(unit_id), state)
    return "\n".join(lines)


def build_unit(ctx: Context, unit: dict[str, Any], checker: Checker, ask_write: AskFn, ask_check: AskFn) -> dict[str, Any]:
    return UnitBuilder(ctx, unit, checker, ask_write, ask_check).build()
