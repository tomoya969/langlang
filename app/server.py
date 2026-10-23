"""ブラウザ画面用の API サーバー（FastAPI）。ロジックは既存モジュール（content / session / grader / settings）を呼ぶだけ。

待ち受けは 127.0.0.1 のみ（cli.py の serve）。
静的ファイルはディスクから毎回配られるので、API を変えたら API_VERSION と画面の REQUIRED_API_VERSION を両方上げる。
"""

from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import content as content_mod
from app import grader, langs, session, settings as settings_mod
from app.content import ContentError
from app.jobs import JobStore
from app.langs.base import UnsupportedLanguage
from app.prompts import ERROR_TAGS

log = logging.getLogger("langlang.server")

API_VERSION = 1
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PAGES = {"/": "index.html", "/learn": "learn.html", "/words": "words.html", "/settings": "settings.html"}


class SessionRequest(BaseModel):
    language: str = "ko"
    unit: str | None = None
    seed: int | None = None


class AnswerRequest(BaseModel):
    language: str = "ko"
    type: str
    answer: str
    word_id: str | None = None
    sentence_id: str | None = None


def create_app(root: Path, jobs: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="langlang", docs_url=None, redoc_url=None)
    app.state.root = root
    app.state.jobs = jobs or JobStore()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    def load_content(language: str) -> content_mod.Content:
        try:
            langs.get(language)
            return content_mod.load(root, language)
        except UnsupportedLanguage as exc:
            raise HTTPException(404, str(exc)) from exc
        except ContentError as exc:
            raise HTTPException(500, str(exc)) from exc

    # ---- 画面 ----

    for route, filename in PAGES.items():
        app.get(route, include_in_schema=False)(_page(filename))

    # ---- API ----

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "languages": [pack.to_dict() for pack in langs.PACKS.values()],
            "error_tags": ERROR_TAGS,
        }

    @app.get("/api/today")
    def today(language: str = "ko") -> dict[str, Any]:
        """今日の学習の見通し。学習の記録はまだ持たないので、最初のユニットを今日の分として返す。"""
        content = load_content(language)
        cfg = settings_mod.load(root)
        unit = content.units[0] if content.units else None
        new_words = content.words_in(unit.id)[: cfg["new_words_per_day"]] if unit else []
        new_sentences = content.sentences_in(unit.id)[: cfg["new_sentences_per_day"]] if unit else []
        levels = []
        for level in sorted({u.level for u in content.units}):
            total = sum(1 for w in content.words if w.level == level)
            levels.append({"level": level, "total": total, "learning": 0, "mastered": 0})
        return {
            "language": langs.get(language).to_dict(),
            "unit": unit.to_dict() if unit else None,
            "review_count": 0,
            "new_word_count": len(new_words),
            "new_sentence_count": len(new_sentences),
            "weak_count": 0,
            "estimate_min": max(1, round((len(new_words) * 2 * 3 + len(new_sentences) * 30 + 5 * 30) / 60)),
            "levels": levels,
            "units": [
                {**u.to_dict(), "word_count": len(content.words_in(u.id)), "sentence_count": len(content.sentences_in(u.id))}
                for u in content.units
            ],
        }

    @app.post("/api/session/start")
    def session_start(req: SessionRequest) -> dict[str, Any]:
        content = load_content(req.language)
        pack = langs.get(req.language)
        unit_id = req.unit or (content.units[0].id if content.units else None)
        if unit_id is None:
            raise HTTPException(400, "教材にユニットがありません")
        try:
            content.unit(unit_id)
        except ContentError as exc:
            raise HTTPException(404, str(exc)) from exc
        rng = random.Random(req.seed) if req.seed is not None else None
        plan = session.build(content, pack, unit_id, settings_mod.load(root), rng)
        log.info("学習を開始: %s %s（%d 問、目安 %d 分）", req.language, unit_id, len(plan["items"]), plan["estimate_min"])
        return plan

    @app.post("/api/answer")
    def answer(req: AnswerRequest) -> dict[str, Any]:
        """機械採点。翻訳・作文で機械採点が決まらないときは、AI 採点の代わりの仮の判定を返す（M5 で置き換える）。"""
        content = load_content(req.language)
        pack = langs.get(req.language)
        if req.type == "word_spell":
            if not req.word_id:
                raise HTTPException(400, "word_id が要ります")
            word = _or_404(lambda: content.word(req.word_id))
            return grader.judge_machine(pack, req.answer, word.lemma).to_dict()
        if not req.sentence_id:
            raise HTTPException(400, "sentence_id が要ります")
        sentence = _or_404(lambda: content.sentence(req.sentence_id))
        if req.type == "sentence_cloze":
            if not sentence.cloze:
                raise HTTPException(400, "この文には穴埋めがありません")
            return grader.judge_machine(pack, req.answer, sentence.cloze[0]["answer"]).to_dict()
        if req.type == "sentence_dictation":
            return grader.judge_machine(pack, req.answer, sentence.ko, sentence.variants.get("ko")).to_dict()
        if req.type in ("sentence_ja_to_ko", "sentence_compose"):
            result = grader.judge_exact(pack, req.answer, sentence.ko, sentence.variants.get("ko"))
            if result is None:
                result = grader.judge_ai_placeholder(pack, req.answer, sentence.ko)
            return result.to_dict()
        raise HTTPException(400, f"採点できない種類です: {req.type}")

    @app.get("/api/units")
    def units(language: str = "ko") -> list[dict[str, Any]]:
        content = load_content(language)
        return [
            {**u.to_dict(), "word_count": len(content.words_in(u.id)), "sentence_count": len(content.sentences_in(u.id))}
            for u in content.units
        ]

    @app.get("/api/words")
    def words(
        language: str = "ko",
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
    def word_detail(word_id: str, language: str = "ko") -> dict[str, Any]:
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

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return settings_mod.load(root)

    @app.put("/api/settings")
    def put_settings(changes: dict[str, Any]) -> dict[str, Any]:
        try:
            return settings_mod.save(root, changes)
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

    return app


def _page(filename: str):  # type: ignore[no-untyped-def]
    def handler() -> FileResponse:
        return FileResponse(STATIC_DIR / filename)

    return handler


def _or_404(fn):  # type: ignore[no-untyped-def]
    try:
        return fn()
    except ContentError as exc:
        raise HTTPException(404, str(exc)) from exc
