"""学習の記録（docs/plan.md 7.5）。records/langlang.db（SQLite）に置くので、サーバーを止めても残る。

- cards: 単語の 1 つの面、または文 1 つごとの FSRS の状態（安定度・難しさ・次に出す日）と、文の段階。
  まだ出していない面と文の行は作らない
- reviews: 解答 1 回ごとの記録
- graded_answers: AI が判定した答え（app/graded.py が使う）
- ai_cache: 解説などの AI の結果
- traces: なぞりタイピングの速さ（流暢さの練習なので、FSRS には使わない）
- confusions: 矢印ゲームの取り違え（正解の語と、選んでしまった語）

FSRS に渡すのは、その日のその面（文）の最初の 1 回だけ（docs/plan.md 4.4・4.7）。間違えて最後尾に回ったあとの正解や、
同じ日の 2 回目の学習は、reviews に残すが FSRS も段階も動かさない（counted = 0）。
1 日 1 回の学習なので、FSRS の「日の中の学習ステップ」（1 分後・10 分後にもう一度）は使わない。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fsrs import Card, Rating, Scheduler, State

FILENAME = "langlang.db"
# 日の区切り。夜中の 0 時を過ぎてからの学習を、前の日の分として数えるため
DAY_START_HOUR = 4
RATINGS = {"again": Rating.Again, "hard": Rating.Hard, "good": Rating.Good, "easy": Rating.Easy}
# 文の段階（docs/plan.md 4.7）。0 は導入で、記録は導入のあとの最初の出題（段階 1）から作る
FIRST_STAGE = 1
LAST_STAGE = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    language      TEXT NOT NULL,
    kind          TEXT NOT NULL,   -- word / sentence
    item_id       TEXT NOT NULL,
    face          TEXT NOT NULL,   -- 単語の面（meaning / listen / reverse / spell）。文は ''
    state         INTEGER NOT NULL,
    step          INTEGER,
    stability     REAL,
    difficulty    REAL,
    due           TEXT NOT NULL,
    last_review   TEXT,
    introduced_at TEXT NOT NULL,
    stage         INTEGER,         -- 文の段階（1〜5）。単語は NULL
    PRIMARY KEY (language, kind, item_id, face)
);
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    language    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    face        TEXT NOT NULL,
    practice    TEXT NOT NULL,     -- 練習の種類（word_meaning など）
    reviewed_at TEXT NOT NULL,
    rating      TEXT NOT NULL,     -- again / hard / good / easy
    counted     INTEGER NOT NULL,  -- FSRS を動かしたか（その日のその面の最初の 1 回だけ）
    correct     INTEGER NOT NULL,
    elapsed_sec REAL,
    answer      TEXT,              -- 選んだ単語の id、打った答え
    detail      TEXT               -- そのほか（JSON。打つ練習の判定と誤りのタグなど）
);
CREATE INDEX IF NOT EXISTS reviews_item ON reviews (language, kind, item_id, reviewed_at);
CREATE TABLE IF NOT EXISTS graded_answers (
    language  TEXT NOT NULL,
    practice  TEXT NOT NULL,
    item_id   TEXT NOT NULL,
    answer    TEXT NOT NULL,       -- 正規化した答え
    expected  TEXT NOT NULL,       -- 判定したときの模範解答
    style     INTEGER NOT NULL,    -- 採点のプロンプトの版
    judgement TEXT NOT NULL,       -- JSON
    graded_at TEXT NOT NULL,
    PRIMARY KEY (language, practice, item_id, answer)
);
CREATE TABLE IF NOT EXISTS ai_cache (
    language   TEXT NOT NULL,
    kind       TEXT NOT NULL,      -- explain など
    key        TEXT NOT NULL,      -- 文の id など
    style      INTEGER NOT NULL,   -- プロンプトの版
    basis      TEXT NOT NULL,      -- 何から作ったか（教材が変わったら作り直す）
    body       TEXT NOT NULL,      -- JSON
    created_at TEXT NOT NULL,
    PRIMARY KEY (language, kind, key)
);
CREATE TABLE IF NOT EXISTS traces (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    language    TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    traced_at   TEXT NOT NULL,
    seconds     REAL NOT NULL,
    units       INTEGER NOT NULL   -- 打った単位の数（韓国語は字母）
);
CREATE TABLE IF NOT EXISTS confusions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    language    TEXT NOT NULL,
    word_id     TEXT NOT NULL,     -- 正解の語
    picked_id   TEXT NOT NULL,     -- 選んでしまった語
    face        TEXT NOT NULL,
    confused_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS confusions_word ON confusions (language, word_id);
"""


def day_start(now: datetime) -> datetime:
    """now が属する「学習の日」の始まり（その土地の時刻で朝 4 時）。"""
    local = now.astimezone()
    start = local.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
    return start - timedelta(days=1) if local < start else start


def next_day_start(now: datetime) -> datetime:
    return day_start(now) + timedelta(days=1)


def next_stage(stage: int, rating: str) -> int:
    """正解（Good・Easy）で 1 つ上へ、注意つき（Hard）ならそのまま、不正解（Again）なら 1 つ下へ（最低は 1）。"""
    if rating in ("good", "easy"):
        return min(LAST_STAGE, stage + 1)
    if rating == "again":
        return max(FIRST_STAGE, stage - 1)
    return stage


@dataclass(frozen=True)
class CardRow:
    item_id: str
    face: str
    card: Card
    introduced_at: datetime
    stage: int | None = None

    @property
    def stability(self) -> float:
        return self.card.stability or 0.0

    def is_due(self, now: datetime) -> bool:
        """今日のうちに期限が来るか。間隔は日単位なので、時刻が過ぎていなくても今日の分に入れる。"""
        return self.card.due < next_day_start(now)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "stability": round(self.stability, 1),
            "difficulty": round(self.card.difficulty, 1) if self.card.difficulty is not None else None,
            "due": self.card.due.astimezone().isoformat(timespec="minutes"),
            "last_review": self.card.last_review.astimezone().isoformat(timespec="minutes") if self.card.last_review else None,
            "introduced_at": self.introduced_at.astimezone().isoformat(timespec="minutes"),
        }
        if self.stage is not None:
            result["stage"] = self.stage
        return result


@dataclass(frozen=True)
class ReviewResult:
    counted: bool
    card: CardRow


def make_scheduler(desired_retention: float = 0.9, fuzz: bool = True) -> Scheduler:
    return Scheduler(desired_retention=desired_retention, learning_steps=(), relearning_steps=(), enable_fuzzing=fuzz)


class Records:
    def __init__(self, root: Path, scheduler: Scheduler | None = None):
        self.path = root / "records" / FILENAME
        self.scheduler = scheduler or make_scheduler()
        self._ready = False
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if not self._ready:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.path) as conn:
                    conn.executescript(SCHEMA)
                    # 文の記録より前に作った記録のファイルには、段階の列がない
                    columns = {r[1] for r in conn.execute("PRAGMA table_info(cards)")}
                    if "stage" not in columns:
                        conn.execute("ALTER TABLE cards ADD COLUMN stage INTEGER")
                self._ready = True
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def cards(self, language: str, kind: str = "word") -> dict[tuple[str, str], CardRow]:
        """(item_id, face) ごとのカード。"""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM cards WHERE language = ? AND kind = ?", (language, kind)).fetchall()
        return {(r["item_id"], r["face"]): _card_row(r) for r in rows}

    def review(
        self,
        language: str,
        kind: str,
        item_id: str,
        face: str,
        *,
        practice: str,
        rating: str,
        correct: bool,
        now: datetime,
        elapsed_sec: float | None = None,
        answer: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> ReviewResult:
        """解答を 1 つ記録する。その日のその面（文）の最初の解答なら FSRS で次に出す日を決め、文なら段階を上下させる。
        初めての面（文）ならカードを作る。"""
        if rating not in RATINGS:
            raise ValueError(f"評価は {', '.join(RATINGS)} のいずれかです: {rating}")
        now_utc = now.astimezone(timezone.utc)
        key = (language, kind, item_id, face)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cards WHERE language = ? AND kind = ? AND item_id = ? AND face = ?", key
            ).fetchone()
            first_stage = FIRST_STAGE if kind == "sentence" else None
            current = _card_row(row) if row else CardRow(item_id, face, Card(card_id=0, due=now_utc), now_utc, first_stage)
            last = current.card.last_review
            counted = last is None or last < day_start(now)
            if counted:
                card, _ = self.scheduler.review_card(current.card, RATINGS[rating], now_utc)
                stage = next_stage(current.stage, rating) if current.stage is not None else None
                current = CardRow(item_id, face, card, current.introduced_at, stage)
                conn.execute(
                    """INSERT INTO cards (language, kind, item_id, face, state, step, stability, difficulty, due, last_review, introduced_at, stage)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (language, kind, item_id, face) DO UPDATE SET
                         state = excluded.state, step = excluded.step, stability = excluded.stability,
                         difficulty = excluded.difficulty, due = excluded.due, last_review = excluded.last_review,
                         stage = excluded.stage""",
                    (
                        *key,
                        int(card.state),
                        card.step,
                        card.stability,
                        card.difficulty,
                        card.due.isoformat(),
                        card.last_review.isoformat() if card.last_review else None,
                        current.introduced_at.isoformat(),
                        stage,
                    ),
                )
            conn.execute(
                """INSERT INTO reviews (language, kind, item_id, face, practice, reviewed_at, rating, counted, correct, elapsed_sec, answer, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    *key,
                    practice,
                    now_utc.isoformat(),
                    rating,
                    int(counted),
                    int(correct),
                    elapsed_sec,
                    answer,
                    json.dumps(detail, ensure_ascii=False) if detail else None,
                ),
            )
        return ReviewResult(counted, current)

    def note(
        self,
        language: str,
        kind: str,
        item_id: str,
        face: str,
        *,
        practice: str,
        rating: str,
        correct: bool,
        now: datetime,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """FSRS を動かさず、カードも作らずに解答だけを残す（文脈の面、まだ出していない面への文の誤り）。"""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO reviews (language, kind, item_id, face, practice, reviewed_at, rating, counted, correct, elapsed_sec, answer, detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, ?)""",
                (language, kind, item_id, face, practice, now.astimezone(timezone.utc).isoformat(), rating, int(correct),
                 json.dumps(detail, ensure_ascii=False) if detail else None),
            )

    def review_count(self, language: str, kind: str, item_id: str, face: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM reviews WHERE language = ? AND kind = ? AND item_id = ? AND face = ?", (language, kind, item_id, face)
            ).fetchone()
        return int(row[0])

    def counted_reviews(self, language: str, kind: str = "word") -> list[dict[str, Any]]:
        """FSRS を動かした解答（その日のその面の最初の 1 回）を古い順に。苦手と反応時間の集計に使う。"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT item_id, face, practice, correct, elapsed_sec FROM reviews
                   WHERE language = ? AND kind = ? AND counted = 1 ORDER BY reviewed_at, id""",
                (language, kind),
            ).fetchall()
        return [{"item_id": r["item_id"], "face": r["face"], "practice": r["practice"], "correct": bool(r["correct"]), "elapsed_sec": r["elapsed_sec"]} for r in rows]

    def confuse(self, language: str, word_id: str, picked_id: str, face: str, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO confusions (language, word_id, picked_id, face, confused_at) VALUES (?, ?, ?, ?, ?)",
                (language, word_id, picked_id, face, now.astimezone(timezone.utc).isoformat()),
            )

    def confusion_counts(self, language: str) -> dict[str, dict[str, int]]:
        """正解の語 → {選んでしまった語: 回数}。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT word_id, picked_id, COUNT(*) AS n FROM confusions WHERE language = ? GROUP BY word_id, picked_id",
                (language,),
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for r in rows:
            result.setdefault(r["word_id"], {})[r["picked_id"]] = r["n"]
        return result

    def history(self, language: str, kind: str, item_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT face, practice, reviewed_at, rating, counted, correct, elapsed_sec FROM reviews
                   WHERE language = ? AND kind = ? AND item_id = ? ORDER BY reviewed_at DESC, id DESC LIMIT ?""",
                (language, kind, item_id, limit),
            ).fetchall()
        return [
            {
                "face": r["face"],
                "practice": r["practice"],
                "reviewed_at": datetime.fromisoformat(r["reviewed_at"]).astimezone().isoformat(timespec="minutes"),
                "rating": r["rating"],
                "counted": bool(r["counted"]),
                "correct": bool(r["correct"]),
                "elapsed_sec": r["elapsed_sec"],
            }
            for r in rows
        ]

    def retrievability(self, card: CardRow, now: datetime) -> float:
        return self.scheduler.get_card_retrievability(card.card, now.astimezone(timezone.utc))

    # ---- AI の判定と結果 ----

    def graded(self, language: str, practice: str, item_id: str, answer: str) -> dict[str, Any] | None:
        """保存した判定（expected・style・judgement）。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expected, style, judgement FROM graded_answers WHERE language = ? AND practice = ? AND item_id = ? AND answer = ?",
                (language, practice, item_id, answer),
            ).fetchone()
        if row is None:
            return None
        return {"expected": row["expected"], "style": row["style"], "judgement": json.loads(row["judgement"])}

    def save_graded(self, language: str, practice: str, item_id: str, answer: str, *, expected: str, style: int, judgement: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO graded_answers (language, practice, item_id, answer, expected, style, judgement, graded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (language, practice, item_id, answer, expected, style, json.dumps(judgement, ensure_ascii=False), _now_iso()),
            )

    def cached(self, language: str, kind: str, key: str, *, style: int, basis: str) -> dict[str, Any] | None:
        """保存した AI の結果。プロンプトの版か、もとにした教材（basis）が変わっていたら None。"""
        with self._connect() as conn:
            row = conn.execute("SELECT style, basis, body FROM ai_cache WHERE language = ? AND kind = ? AND key = ?", (language, kind, key)).fetchone()
        if row is None or row["style"] != style or row["basis"] != basis:
            return None
        return json.loads(row["body"])

    def save_cached(self, language: str, kind: str, key: str, body: dict[str, Any], *, style: int, basis: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ai_cache (language, kind, key, style, basis, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (language, kind, key, style, basis, json.dumps(body, ensure_ascii=False), _now_iso()),
            )

    # ---- なぞりタイピング ----

    def trace(self, language: str, sentence_id: str, *, seconds: float, units: int, now: datetime) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO traces (language, sentence_id, traced_at, seconds, units) VALUES (?, ?, ?, ?, ?)",
                (language, sentence_id, now.astimezone(timezone.utc).isoformat(), seconds, units),
            )

    def trace_speed(self, language: str, since: datetime) -> float | None:
        """since 以降のなぞりの速さ（1 分あたりの単位の数）。打った量で重みを付けた平均。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(units) AS units, SUM(seconds) AS seconds FROM traces WHERE language = ? AND traced_at >= ?",
                (language, since.astimezone(timezone.utc).isoformat()),
            ).fetchone()
        if not row["seconds"]:
            return None
        return row["units"] / row["seconds"] * 60


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _card_row(row: sqlite3.Row) -> CardRow:
    # card_id を渡さないと、Card は id を作るために 1 ミリ秒待つ（カードが多いと読み込みが遅くなる）
    card = Card(
        card_id=0,
        state=State(row["state"]),
        step=row["step"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due=datetime.fromisoformat(row["due"]),
        last_review=datetime.fromisoformat(row["last_review"]) if row["last_review"] else None,
    )
    return CardRow(row["item_id"], row["face"], card, datetime.fromisoformat(row["introduced_at"]), row["stage"])
