"""ブラウザ画面用の API サーバー（FastAPI）。ロジックは既存モジュール（content / session / grader / records / settings）を呼ぶだけ。

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

import hashlib
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import content as content_mod
from app import claude_cli, grader, langs, session, settings as settings_mod
from app.content import ContentError, meaning_atoms
from app.graded import GradedStore
from app.jobs import JobBusy, JobStore
from app.langs.base import LanguagePack, UnsupportedLanguage
from app.prompts import ERROR_TAGS, EXPLAIN_SCHEMA, EXPLAIN_STYLE, build_explain_prompt
from app.records import RATINGS, Records
from app import weak as weak_mod

log = logging.getLogger("langlang.server")

API_VERSION = 8
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
LANGUAGE_PAGES = {"": "index.html", "learn": "learn.html", "words": "words.html"}


class SessionRequest(BaseModel):
    language: str
    unit: str | None = None
    weak: bool = False
    seed: int | None = None


class ReviewRequest(BaseModel):
    language: str
    kind: str  # word / sentence
    item_id: str
    face: str = ""  # 単語の面。文は空
    practice: str
    rating: str
    correct: bool
    elapsed_sec: float | None = None
    answer: str | None = None
    detail: dict[str, Any] | None = None  # 打つ練習の判定（verdict・source・issues）


class TraceRequest(BaseModel):
    language: str
    sentence_id: str
    seconds: float
    units: int


class ExplainRequest(BaseModel):
    language: str


class AnswerRequest(BaseModel):
    language: str
    type: str
    answer: str
    word_id: str | None = None
    sentence_id: str | None = None


def create_app(
    root: Path,
    jobs: JobStore | None = None,
    ask: grader.AskFn | None = None,
    records: Records | None = None,
    clock: Callable[[], datetime] | None = None,
) -> FastAPI:
    """ask は採点と解説で AI を呼ぶ関数、clock は今の時刻（どちらもテストで差し込む）。
    ask が None なら claude_cli の用途ごとの設定（grade / explain）で呼ぶ。"""
    app = FastAPI(title="langlang", docs_url=None, redoc_url=None)
    app.state.root = root
    app.state.jobs = jobs or JobStore()
    app.state.records = records or Records(root)
    app.state.graded = GradedStore(app.state.records)
    now = clock or (lambda: datetime.now().astimezone())
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

    def cards_of(language: str) -> session.Cards:
        return app.state.records.cards(language)

    def sentence_cards_of(language: str) -> session.SentenceCards:
        return {sid: card for (sid, _), card in app.state.records.cards(language, "sentence").items()}

    def priority(at: datetime) -> session.Priority:
        return lambda card: app.state.records.retrievability(card, at)

    def analysis_of(language: str, cards: session.Cards) -> weak_mod.Analysis:
        records = app.state.records
        return weak_mod.analyze(cards, records.counted_reviews(language), records.confusion_counts(language))

    def summary(language: str) -> dict[str, Any]:
        """言語ごとの今日の見通し（復習・新出の数、目安の時間、レベルとユニットの進み、苦手の数）。"""
        pack = pack_of(language)
        if not content_mod.content_dir(root, language).is_dir():
            return {"language": pack.to_dict(), "available": False}
        content = load_content(language)
        cfg = settings_mod.load(root, language)
        cards = cards_of(language)
        analysis = analysis_of(language, cards)
        at = now()
        plan = session.build(
            content, pack, cfg, cards, at, priority=priority(at), rng=random.Random(0), sentence_cards=sentence_cards_of(language), analysis=analysis
        )
        states = {w.id: session.word_state(w.id, cards, cfg["mastered_days"]) for w in content.words}
        levels = []
        for level in sorted({u.level for u in content.units}):
            in_level = [states[w.id] for w in content.words if w.level == level]
            levels.append({
                "level": level,
                "total": len(in_level),
                "learning": in_level.count("learning"),
                "mastered": in_level.count("mastered"),
            })
        return {
            "language": pack.to_dict(),
            "available": True,
            "unit": plan["unit"],
            "review_count": plan["review_count"],
            "new_word_count": plan["new_word_count"],
            "new_sentence_count": plan["new_sentence_count"],
            "weak_count": sum(1 for wid in analysis.weak if wid in content._word_by_id),
            "estimate_min": plan["estimate_min"],
            "levels": levels,
            "units": [unit_summary(content, u, states) for u in content.units],
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
        """今日の学習の問題の列。unit を指定したときは、そのユニットの練習。weak なら苦手な単語だけの練習。"""
        content = load_content(req.language)
        pack = pack_of(req.language)
        if not content.units:
            raise HTTPException(400, "教材にユニットがありません")
        if req.unit:
            _or_404(lambda: content.unit(req.unit))
        rng = random.Random(req.seed) if req.seed is not None else None
        at = now()
        cfg = settings_mod.load(root, req.language)
        cards = cards_of(req.language)
        plan = session.build(
            content, pack, cfg, cards, at, req.unit, priority(at), rng, sentence_cards_of(req.language), analysis_of(req.language, cards), req.weak
        )
        log.info(
            "学習を開始: %s %s（新出 %d 語・%d 文、復習 %d（苦手枠 %d）、%d 問、目安 %d 分）",
            req.language, "苦手の練習" if req.weak else req.unit or "今日の学習", plan["new_word_count"], plan["new_sentence_count"],
            plan["review_count"], plan["weak_slot_count"], len(plan["items"]), plan["estimate_min"],
        )
        return plan

    @app.post("/api/review")
    def review(req: ReviewRequest) -> dict[str, Any]:
        """単語の面か文の解答を記録する。その日の最初の解答なら、FSRS で次に出す日を決める（文は段階も上下させる）。"""
        content = load_content(req.language)
        if req.kind == "word":
            _or_404(lambda: content.word(req.item_id))
            if req.face not in session.WORD_FACES:
                raise HTTPException(400, f"面は {', '.join(session.WORD_FACES)} のいずれかです: {req.face}")
        elif req.kind == "sentence":
            _or_404(lambda: content.sentence(req.item_id))
            if req.face:
                raise HTTPException(400, "文には面がありません")
        else:
            raise HTTPException(400, f"記録できない種類です: {req.kind}")
        if req.rating not in RATINGS:
            raise HTTPException(400, f"評価は {', '.join(RATINGS)} のいずれかです: {req.rating}")
        at = now()
        records = app.state.records
        result = records.review(
            req.language,
            req.kind,
            req.item_id,
            req.face,
            practice=req.practice,
            rating=req.rating,
            correct=req.correct,
            now=at,
            elapsed_sec=req.elapsed_sec,
            answer=req.answer,
            detail=req.detail,
        )
        if req.kind == "word" and not req.correct and req.face in weak_mod.ARROW_FACES and req.answer in content._word_by_id and req.answer != req.item_id:
            records.confuse(req.language, req.item_id, req.answer, req.face, at)
        if req.kind == "sentence":
            feed_words(req.language, content.sentence(req.item_id), req, at)
        return {"counted": result.counted, "card": result.card.to_dict()}

    def feed_words(language: str, sentence: content_mod.Sentence, req: ReviewRequest, at: datetime) -> None:
        """文の解答を単語に返す（docs/plan.md 4.5）。文の単語には文脈の記録を残し、不正解の理由になった単語の誤りは、
        誤りの種類に応じた面に Again を記録する（まだ出していない面なら記録だけ）。"""
        records = app.state.records
        detail = req.detail or {}
        for wid in sentence.word_ids:
            records.note(language, "word", wid, "context", practice=req.practice, rating=req.rating, correct=req.correct, now=at, detail={"sentence_id": sentence.id})
        if detail.get("verdict") != grader.VERDICT_INCORRECT:
            return
        cards = cards_of(language)
        returned: set[tuple[str, str]] = set()
        for issue in detail.get("issues") or []:
            wid, face = issue.get("word_id"), weak_mod.face_for_issue(issue)
            if not face or wid not in sentence.word_ids or (wid, face) in returned:
                continue
            returned.add((wid, face))
            fields = {"practice": req.practice, "rating": "again", "correct": False, "now": at, "detail": {"sentence_id": sentence.id, "tag": issue.get("tag")}}
            if (wid, face) in cards:
                records.review(language, "word", wid, face, **fields)
            else:
                records.note(language, "word", wid, face, **fields)

    @app.post("/api/trace")
    def trace(req: TraceRequest) -> dict[str, Any]:
        """なぞりタイピングの速さを記録する（FSRS には使わない）。"""
        content = load_content(req.language)
        _or_404(lambda: content.sentence(req.sentence_id))
        if req.seconds <= 0 or req.units <= 0:
            raise HTTPException(400, "時間と打った数は正の値です")
        app.state.records.trace(req.language, req.sentence_id, seconds=req.seconds, units=req.units, now=now())
        return {"per_min": round(req.units / req.seconds * 60)}

    @app.post("/api/explain/{sentence_id}")
    def explain(sentence_id: str, req: ExplainRequest) -> dict[str, Any]:
        """文の解説。保存してあればそれを返し、なければ作るジョブにして {"job": ...} を返す。"""
        content = load_content(req.language)
        sentence = _or_404(lambda: content.sentence(sentence_id))
        prompt = explain_prompt(content, sentence)
        basis = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cached = app.state.records.cached(req.language, "explain", sentence.id, style=EXPLAIN_STYLE, basis=basis)
        if cached is not None:
            return {"explanation": cached}

        def run(_job) -> dict[str, Any]:  # type: ignore[no-untyped-def]
            result = clean_explanation((ask or claude_cli.ask_for("explain"))(prompt, EXPLAIN_SCHEMA))
            app.state.records.save_cached(req.language, "explain", sentence.id, result, style=EXPLAIN_STYLE, basis=basis)
            log.info("解説を作成: %s", sentence.id)
            return result

        try:
            job = app.state.jobs.submit("explain", run)
        except JobBusy as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"job": job.to_dict()}

    @app.post("/api/answer")
    def answer(req: AnswerRequest) -> dict[str, Any]:
        """機械で決まれば判定を返す。決まらず、保存した判定もなければ AI の採点をジョブにして {"job": ...} を返す。"""
        content = load_content(req.language)
        pack = pack_of(req.language)
        task = task_for(content, pack, req)
        norm = task.normalize(pack, req.answer)
        if not norm:
            raise HTTPException(400, "答えが空です")
        judged = grader.judge_task(pack, task, req.answer)
        if judged is None and req.type == "word_spell":
            judged = _synonym_answer(content, pack, content.word(task.item_id), req.answer)
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
        cards = cards_of(language)
        analysis = analysis_of(language, cards)
        mastered = settings_mod.load(root, language)["mastered_days"]
        return [
            {**w.to_dict(), "state": session.word_state(w.id, cards, mastered), "faces": _faces(w.id, cards), **_weak_view(w.id, analysis)}
            for w in sorted(result, key=lambda w: (w.level, w.order))
        ]

    @app.get("/api/words/{word_id}")
    def word_detail(word_id: str, language: str) -> dict[str, Any]:
        content = load_content(language)
        word = _or_404(lambda: content.word(word_id))
        cards = cards_of(language)
        analysis = analysis_of(language, cards)
        picked = analysis.partners.get(word.id, {})
        return {
            **word.to_dict(),
            "state": session.word_state(word.id, cards, settings_mod.load(root, language)["mastered_days"]),
            "faces": _faces(word.id, cards),
            **_weak_view(word.id, analysis),
            "sentences": [s.to_dict() for s in content.sentences if word.id in s.word_ids],
            "synonym_words": [content.word(c).to_dict() for c in word.synonyms if c in content._word_by_id],
            "confusable_words": [content.word(c).to_dict() for c in word.confusables if c in content._word_by_id],
            "homograph_words": [content.word(c).to_dict() for c in word.homographs if c in content._word_by_id],
            "confused_with": [{**content.word(p).to_dict(), "times": picked[p]} for p in analysis.partners_of(word.id) if p in content._word_by_id],
            "context_count": app.state.records.review_count(language, "word", word.id, "context"),
            "history": app.state.records.history(language, "word", word.id),
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
    if req.type not in ("sentence_cloze", "sentence_dictation", "sentence_ja_to_ko", "sentence_ko_to_ja", "sentence_compose"):
        raise HTTPException(400, f"採点できない種類です: {req.type}")
    if not req.sentence_id:
        raise HTTPException(400, "sentence_id が要ります")
    s = _or_404(lambda: content.sentence(req.sentence_id))
    variants = tuple(s.variants.get("ko", []))
    words = [content.word(w) for w in s.word_ids if w in content._word_by_id]
    common = {"words": [_word_brief(w) for w in words]}
    word_ids = tuple(w.id for w in words)
    if req.type == "sentence_ko_to_ja":
        ja_variants = tuple(s.variants.get("ja", []))
        problem = [("韓国語の文", s.ko), ("文の文体", s.register), ("場面", s.scene), ("模範訳", s.ja), ("許容訳", "、".join(ja_variants))]
        return grader.Task(req.type, s.id, s.ja, ja_variants, {**common, "problem": problem}, word_ids, native=True)
    if req.type == "sentence_cloze":
        if not s.cloze:
            raise HTTPException(400, "この文には穴埋めがありません")
        cloze = s.cloze[0]
        cloze_variants = tuple(dict.fromkeys([*cloze.get("variants", []), *_cloze_variants(pack, s.ko, cloze["eojeol"], variants)]))
        problem = [
            ("文（＿＿＿ が空欄）", content_mod.blank_eojeol(s.ko, cloze["eojeol"])),
            ("文の日本語訳", s.ja),
            ("文の文体", s.register),
            ("場面", s.scene),
            ("空欄の意味の手がかり", cloze.get("hint_ja", "")),
            ("模範解答（空欄の語節）", cloze["answer"]),
            ("許容例（空欄の語節）", "、".join(cloze_variants)),
        ]
        return grader.Task(req.type, s.id, cloze["answer"], cloze_variants, {**common, "problem": problem}, word_ids)
    if req.type == "sentence_dictation":
        # 許容例は言い方の違いなので、書き取りでは読み上げた文とだけ比べる
        problem = [("読み上げた文（模範解答）", s.ko), ("文の日本語訳", s.ja), ("文の文体", s.register)]
        return grader.Task(req.type, s.id, s.ko, (), {**common, "problem": problem}, word_ids)
    if req.type == "sentence_ja_to_ko":
        problem = [("日本語の文", s.ja), ("指定の文体", s.register), ("場面", s.scene), ("模範解答", s.ko), ("許容例", "、".join(variants))]
    else:
        required = s.grammar[0] if s.grammar else "（なし。自由に書いてよい）"
        problem = [("指定の表現", required), ("例文", s.ko), ("例文の日本語訳", s.ja), ("例文の文体", s.register)]
    return grader.Task(req.type, s.id, s.ko, variants, {**common, "problem": problem}, word_ids)


def _synonym_answer(content: content_mod.Content, pack: LanguagePack, word: content_mod.Word, answer: str) -> grader.Judgement | None:
    """綴りの面で、問題に出した意味（主な意味）にも合う別の語を書いた答えは正解にする（複数に解釈できる答えはどれも正解）。
    合う語は、類語と、訳が問題の意味と重なる語。"""
    norm = pack.normalize(answer)
    asked = meaning_atoms(word.meaning)
    for other in content.words:
        if other.id == word.id or pack.normalize(other.lemma) != norm:
            continue
        if other.id in word.synonyms or word.id in other.synonyms or asked & other.meaning_atoms:
            comment = f"「{other.lemma}」も「{word.meaning}」の意味なので正解です。読み上げた語は「{word.lemma}」です。"
            return grader.Judgement(grader.VERDICT_CORRECT, "synonym", corrected=other.lemma, comment_ja=comment)
    return None


def _word_brief(word: content_mod.Word) -> dict[str, str]:
    # 主な意味だけだと、別の意味で正しく使った答えを AI が不正解にしかねないので、すべての意味を見せる
    return {"id": word.id, "lemma": word.lemma, "meaning": word.all_meanings}


def explain_prompt(content: content_mod.Content, sentence: content_mod.Sentence) -> str:
    words = [content.word(w) for w in sentence.word_ids if w in content._word_by_id]
    by_form = {g["form"]: g for g in content.grammar}
    grammar = [by_form[g] for g in sentence.grammar if g in by_form]
    level = content.unit(sentence.unit).level
    return build_explain_prompt(sentence.to_dict(), [{"lemma": w.lemma, "pos": w.pos, "meaning": w.all_meanings} for w in words], grammar, level)


def clean_explanation(raw: dict[str, Any]) -> dict[str, Any]:
    """画面がそのまま描けるように、項目をそろえて空のものを除く。"""
    return {
        "summary": (raw.get("summary") or "").strip(),
        "parts": [p for p in raw.get("parts") or [] if p.get("surface") and p.get("breakdown")],
        "grammar": [g for g in raw.get("grammar") or [] if g.get("form") and g.get("explanation")],
        "register": (raw.get("register") or "").strip(),
        "pronunciation": (raw.get("pronunciation") or "").strip(),
        "tips": [t.strip() for t in raw.get("tips") or [] if t and t.strip()],
    }


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


def unit_summary(content: content_mod.Content, unit: content_mod.Unit, states: dict[str, str] | None = None) -> dict[str, Any]:
    """ユニットの単語と文の数。states（単語ごとの状態）を渡すと、出し始めた単語の数も入れる。"""
    words = content.words_in(unit.id)
    result = {**unit.to_dict(), "word_count": len(words), "sentence_count": len(content.sentences_in(unit.id))}
    if states is not None:
        result["started_count"] = sum(1 for w in words if states.get(w.id, "new") != "new")
    return result


def _weak_view(word_id: str, analysis: weak_mod.Analysis) -> dict[str, Any]:
    reasons = analysis.weak.get(word_id, [])
    return {"weak": bool(reasons), "weak_reasons": [weak_mod.REASONS[r] for r in reasons]}


def _faces(word_id: str, cards: session.Cards) -> dict[str, Any]:
    return {face: cards[(word_id, face)].to_dict() for face in session.WORD_FACES if (word_id, face) in cards}


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
