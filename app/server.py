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
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import content as content_mod
from app import grader, langs, session, settings as settings_mod
from app.content import ContentError
from app.jobs import JobStore
from app.langs.base import LanguagePack, UnsupportedLanguage
from app.prompts import ERROR_TAGS

log = logging.getLogger("langlang.server")

API_VERSION = 2
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


def create_app(root: Path, jobs: JobStore | None = None) -> FastAPI:
    app = FastAPI(title="langlang", docs_url=None, redoc_url=None)
    app.state.root = root
    app.state.jobs = jobs or JobStore()
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
        """機械採点。翻訳・作文で機械採点が決まらないときは、AI 採点の代わりの仮の判定を返す（M5 で置き換える）。"""
        content = load_content(req.language)
        pack = pack_of(req.language)
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
