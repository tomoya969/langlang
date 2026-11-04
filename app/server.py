"""ブラウザ画面用の API サーバー（FastAPI）。ロジックは既存モジュール（content / session / grader / settings）を呼ぶだけ。

画面の URL:

- `/`                      ポータル（言語を選ぶ）
- `/settings`              設定（全体の表示と、言語ごとの学習の設定）
- `/{言語}`                言語のホーム（今日の学習）
- `/{言語}/learn`          学習
- `/{言語}/words`          単語帳

言語ごとの画面は同じ HTML を返し、画面の JS が URL の最初の部分から言語を読む。
`/{言語}` は API や静的ファイルの URL にも当たる形なので、それらより後に登録する。

待ち受けは 127.0.0.1 のみ（cli.py の serve）。
静的ファイルはディスクから毎回配られるので、API を変えたら API_VERSION と画面の REQUIRED_API_VERSION を両方上げる。
"""

from __future__ import annotations

import logging
import random
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import content as content_mod
from app import claude_cli, grader, langs, session, settings as settings_mod
from app.content import ContentError
from app.graded import GradedStore
from app.jobs import JobBusy, JobStore
from app.langs.base import LanguagePack, UnsupportedLanguage
from app.prompts import ERROR_TAGS

log = logging.getLogger("langlang.server")

API_VERSION = 3
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LANGUAGE_PAGES = {"": "index.html", "learn": "learn.html", "words": "words.html"}


class SessionRequest(BaseModel):
    language: str
    unit: str | None = None
    seed: int | None = None


class AnswerRequest(BaseModel):
    language: str
    type: str
    answer: str
    word_id: str | None = None
    sentence_id: str | None = None


def create_app(root: Path, jobs: JobStore | None = None, ask: grader.AskFn | None = None) -> FastAPI:
    """ask は採点で AI を呼ぶ関数（テストで差し込む）。None なら claude_cli の採点用の設定で呼ぶ。"""
    app = FastAPI(title="langlang", docs_url=None, redoc_url=None)
    app.state.root = root
    app.state.jobs = jobs or JobStore()
    app.state.graded = GradedStore(root)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def pack_of(language: str) -> LanguagePack:
        try:
            return langs.get(language)
        except UnsupportedLanguage as exc:
            raise HTTPException(404, str(exc)) from exc

    def load_content(language: str) -> content_mod.Content:
        pack_of(language)
        try:
            return content_mod.load(root, language)
        except ContentError as exc:
            raise HTTPException(500, str(exc)) from exc

    def summary(language: str) -> dict[str, Any]:
        """言語ごとの今日の見通し。学習の記録はまだ持たないので、最初のユニットを今日の分として返す。"""
        pack = pack_of(language)
        if not content_mod.content_dir(root, language).is_dir():
            return {"language": pack.to_dict(), "available": False}
        content = load_content(language)
        cfg = settings_mod.load(root, language)
        unit = content.units[0] if content.units else None
        new_words = content.words_in(unit.id)[: cfg["new_words_per_day"]] if unit else []
        new_sentences = content.sentences_in(unit.id)[: cfg["new_sentences_per_day"]] if unit else []
        levels = []
        for level in sorted({u.level for u in content.units}):
            total = sum(1 for w in content.words if w.level == level)
            levels.append({"level": level, "total": total, "learning": 0, "mastered": 0})
        return {
            "language": pack.to_dict(),
            "available": True,
            "unit": unit.to_dict() if unit else None,
            "review_count": 0,
            "new_word_count": len(new_words),
            "new_sentence_count": len(new_sentences),
            "weak_count": 0,
            "estimate_min": max(1, round((len(new_words) * 2 * 3 + len(new_sentences) * 30 + 5 * 30) / 60)),
            "levels": levels,
            "units": [unit_summary(content, u) for u in content.units],
        }

    # ---- API ----

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "languages": [pack.to_dict() for pack in langs.PACKS.values()],
            "error_tags": ERROR_TAGS,
        }

    @app.get("/api/portal")
    def portal() -> list[dict[str, Any]]:
        """ポータルの言語のカード。教材がまだない言語も、その旨（available: false）を返す。"""
        return [summary(code) for code in langs.PACKS]

    @app.get("/api/today")
    def today(language: str) -> dict[str, Any]:
        result = summary(language)
        if not result["available"]:
            raise HTTPException(404, f"{result['language']['label']}の教材がありません")
        return result

    @app.post("/api/session/start")
    def session_start(req: SessionRequest) -> dict[str, Any]:
        content = load_content(req.language)
        pack = pack_of(req.language)
        unit_id = req.unit or (content.units[0].id if content.units else None)
        if unit_id is None:
            raise HTTPException(400, "教材にユニットがありません")
        _or_404(lambda: content.unit(unit_id))
        rng = random.Random(req.seed) if req.seed is not None else None
        plan = session.build(content, pack, unit_id, settings_mod.load(root, req.language), rng)
        log.info("学習を開始: %s %s（%d 問、目安 %d 分）", req.language, unit_id, len(plan["items"]), plan["estimate_min"])
        return plan

    @app.post("/api/answer")
    def answer(req: AnswerRequest) -> dict[str, Any]:
        """機械で決まれば判定を返す。決まらず、保存した判定もなければ AI の採点をジョブにして {"job": ...} を返す。"""
        content = load_content(req.language)
        pack = pack_of(req.language)
        norm = pack.normalize(req.answer)
        if not norm:
            raise HTTPException(400, "答えが空です")
        task = task_for(content, pack, req)
        judged = grader.judge_machine(pack, req.answer, task.expected, task.variants)
        if judged is None:
            judged = app.state.graded.get(req.language, task, norm)
        if judged is not None:
            return judged.to_dict()

        def run(_job) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            result = grader.judge_ai(pack, task, req.answer, ask or claude_cli.ask_for("grade"))
            app.state.graded.put(req.language, task, norm, result)
            log.info("AI の採点: %s %s「%s」→ %s", task.type, task.item_id, norm, result.verdict)
            return result.to_dict()

        try:
            job = app.state.jobs.submit("grade", run)
        except JobBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"job": job.to_dict()}

    @app.get("/api/units")
    def units(language: str) -> list[dict[str, Any]]:
        content = load_content(language)
        return [unit_summary(content, u) for u in content.units]

    @app.get("/api/words")
    def words(
        language: str,
        level: int | None = None,
        unit: str | None = None,
        q: str | None = Query(default=None, max_length=50),
    ) -> list[dict[str, Any]]:
        content = load_content(language)
        result = content.words
        if level is not None:
            result = [w for w in result if w.level == level]
        if unit:
            result = [w for w in result if w.unit == unit]
        if q:
            needle = q.strip().lower()
            result = [w for w in result if needle in w.lemma.lower() or needle in w.meaning.lower()]
        # 学習の記録はまだないので、状態は「未学習」固定
        return [{**w.to_dict(), "state": "new", "faces": {}} for w in sorted(result, key=lambda w: (w.level, w.order))]

    @app.get("/api/words/{word_id}")
    def word_detail(word_id: str, language: str) -> dict[str, Any]:
        content = load_content(language)
        word = _or_404(lambda: content.word(word_id))
        return {
            **word.to_dict(),
            "state": "new",
            "faces": {},
            "sentences": [s.to_dict() for s in content.sentences if word.id in s.word_ids],
            "confusable_words": [content.word(c).to_dict() for c in word.confusables if c in content._word_by_id],
            "homograph_words": [content.word(c).to_dict() for c in word.homographs if c in content._word_by_id],
            "history": [],
        }

    @app.get("/api/settings/{language}")
    def get_settings(language: str) -> dict[str, Any]:
        pack_of(language)
        return settings_mod.load(root, language)

    @app.put("/api/settings/{language}")
    def put_settings(language: str, changes: dict[str, Any]) -> dict[str, Any]:
        pack_of(language)
        try:
            return settings_mod.save(root, language, changes)
        except settings_mod.SettingsError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        found = app.state.jobs.get(job_id)
        if found is None:
            raise HTTPException(404, "ジョブがありません（サーバーが再起動した可能性があります）")
        return found.to_dict()

    @app.exception_handler(HTTPException)
    async def http_error(_request, exc: HTTPException):  # type: ignore[no-untyped-def]
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    # ---- 画面（API と静的ファイルより後に登録する） ----

    @app.get("/", include_in_schema=False)
    def portal_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "portal.html")

    @app.get("/settings", include_in_schema=False)
    def settings_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "settings.html")

    # 言語を URL に入れる前の画面の URL（開いたままのタブやブックマーク）を、最初の言語の画面へ送る
    for old in ("learn", "words"):
        app.get(f"/{old}", include_in_schema=False)(_redirect(f"/{next(iter(langs.PACKS))}/{old}"))

    @app.get("/{language}", include_in_schema=False)
    def language_home(language: str) -> FileResponse:
        pack_of(language)
        return FileResponse(STATIC_DIR / LANGUAGE_PAGES[""])

    @app.get("/{language}/{page}", include_in_schema=False)
    def language_page(language: str, page: str) -> FileResponse:
        pack_of(language)
        if not page or page not in LANGUAGE_PAGES:
            raise HTTPException(404, f"画面がありません: /{language}/{page}")
        return FileResponse(STATIC_DIR / LANGUAGE_PAGES[page])

    return app


def task_for(content: content_mod.Content, pack: LanguagePack, req: AnswerRequest) -> grader.Task:
    """解答の要求から、採点する問題（模範解答・許容例と、AI に見せる問題の中身）を作る。"""
    if req.type == "word_spell":
        if not req.word_id:
            raise HTTPException(400, "word_id が要ります")
        word = _or_404(lambda: content.word(req.word_id))
        problem = [("日本語の意味", word.meaning), ("品詞", word.pos), ("模範解答", word.lemma)]
        return grader.Task(req.type, word.id, word.lemma, context={"problem": problem, "words": [_word_brief(word)]}, word_ids=(word.id,))
    if req.type not in ("sentence_cloze", "sentence_dictation", "sentence_ja_to_ko", "sentence_compose"):
        raise HTTPException(400, f"採点できない種類です: {req.type}")
    if not req.sentence_id:
        raise HTTPException(400, "sentence_id が要ります")
    s = _or_404(lambda: content.sentence(req.sentence_id))
    variants = tuple(s.variants.get("ko", []))
    words = [content.word(w) for w in s.word_ids if w in content._word_by_id]
    common = {"words": [_word_brief(w) for w in words]}
    word_ids = tuple(w.id for w in words)
    if req.type == "sentence_cloze":
        if not s.cloze:
            raise HTTPException(400, "この文には穴埋めがありません")
        cloze = s.cloze[0]
        cloze_variants = _cloze_variants(pack, s.ko, cloze["eojeol"], variants)
        problem = [
            ("文（＿＿＿ が空欄）", _blanked(s.ko, cloze["eojeol"])),
            ("文の日本語訳", s.ja),
            ("文の文体", s.register),
            ("場面", s.scene),
            ("空欄の意味の手がかり", cloze.get("hint_ja", "")),
            ("模範解答（空欄の語節）", cloze["answer"]),
            ("許容例（空欄の語節）", "、".join(cloze_variants)),
        ]
        return grader.Task(req.type, s.id, cloze["answer"], cloze_variants, {**common, "problem": problem}, word_ids)
    if req.type == "sentence_dictation":
        problem = [("読み上げた文（模範解答）", s.ko), ("許容例", "、".join(variants)), ("文の日本語訳", s.ja), ("文の文体", s.register)]
    elif req.type == "sentence_ja_to_ko":
        problem = [("日本語の文", s.ja), ("指定の文体", s.register), ("場面", s.scene), ("模範解答", s.ko), ("許容例", "、".join(variants))]
    else:
        required = s.grammar[0] if s.grammar else "（なし。自由に書いてよい）"
        problem = [("指定の表現", required), ("例文", s.ko), ("例文の日本語訳", s.ja), ("例文の文体", s.register)]
    return grader.Task(req.type, s.id, s.ko, variants, {**common, "problem": problem}, word_ids)


def _word_brief(word: content_mod.Word) -> dict[str, str]:
    return {"id": word.id, "lemma": word.lemma, "meaning": word.meaning}


_TRAILING_PUNCT = re.compile(r"[.?!,。？！、]+$")


def _blanked(ko: str, eojeol: int) -> str:
    parts = ko.split(" ")
    if 0 <= eojeol < len(parts):
        punct = _TRAILING_PUNCT.search(parts[eojeol])
        parts[eojeol] = "＿＿＿" + (punct.group() if punct else "")
    return " ".join(parts)


def _cloze_variants(pack: LanguagePack, ko: str, eojeol: int, variants: tuple[str, ...]) -> tuple[str, ...]:
    """文の許容例のうち、空欄の語節だけが違うものから、空欄の許容例を取り出す。"""
    base = [pack.normalize(p) for p in ko.split(" ")]
    if not 0 <= eojeol < len(base):
        return ()
    found: list[str] = []
    for v in variants:
        parts = [pack.normalize(p) for p in v.split(" ")]
        if len(parts) != len(base) or any(p != b for i, (p, b) in enumerate(zip(parts, base)) if i != eojeol):
            continue
        if parts[eojeol] != base[eojeol] and parts[eojeol] not in found:
            found.append(parts[eojeol])
    return tuple(found)


def unit_summary(content: content_mod.Content, unit: content_mod.Unit) -> dict[str, Any]:
    return {**unit.to_dict(), "word_count": len(content.words_in(unit.id)), "sentence_count": len(content.sentences_in(unit.id))}


def _redirect(target: str):  # type: ignore[no-untyped-def]
    def handler(request: Request) -> RedirectResponse:
        query = request.url.query
        return RedirectResponse(f"{target}?{query}" if query else target, status_code=307)

    return handler


def _or_404(fn):  # type: ignore[no-untyped-def]
    try:
        return fn()
    except ContentError as exc:
        raise HTTPException(404, str(exc)) from exc
