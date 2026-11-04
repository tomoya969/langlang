"""「今日の学習」の組み立て（docs/plan.md 4.8）。

単語ラウンド → 文ラウンド → 産出ラウンド → 仕上げ、の順に問題の列を作る。
画面は列を上から順に出し、矢印ゲームで間違えた問題はその場で最後尾に回す（列の操作は画面側 arrow-game.js）。

単語は学習の記録（app/records.py のカード）から組む。期限が来た面と、出し始める面（4.5）を復習に、
まだ出していない単語を学ぶ順に新出にする。ユニットを指定したときは、そのユニットの単語だけで組む（ユニットの練習）。
文はまだ記録を持たないので、今日の新出と復習の単語を含む文を選ぶ。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.content import Content, Sentence, Unit, Word
from app.langs.base import LanguagePack
from app.records import CardRow, day_start

# 1 枚の初見カードのあと、同じ単語を何枚あとに出すか
RECALL_GAP = (3, 5)
OPTIONS = 4
WORD_FACES = ("meaning", "listen", "reverse", "spell")

Cards = dict[tuple[str, str], CardRow]
Priority = Callable[[CardRow], float]


@dataclass
class WordPlan:
    new: list[Word]
    reviews: list[tuple[Word, str]]  # (単語, 面)
    unit: Unit | None


def plan_words(
    content: Content, settings: dict[str, Any], cards: Cards, now: datetime, unit_id: str | None = None, priority: Priority | None = None
) -> WordPlan:
    """新出と復習の単語を決める。priority はカードの思い出せる確率で、復習が多すぎるときは低いものから出す。"""
    words = {w.id: w for w in content.words}
    introduced = {wid for wid, face in cards if face == "meaning" and wid in words}
    if unit_id:
        unit_words = content.words_in(unit_id)
        in_unit = {w.id for w in unit_words}
        new = [w for w in unit_words if w.id not in introduced][: settings["new_words_per_day"]]
        reviews = [(w, "meaning") for w in unit_words if w.id in introduced]
        reviews += [(words[wid], face) for (wid, face), c in cards.items() if face != "meaning" and wid in in_unit and c.is_due(now)]
        return WordPlan(new, reviews, content.unit(unit_id))

    started = day_start(now)
    new_today = sum(1 for (wid, face), c in cards.items() if face == "meaning" and c.introduced_at >= started)
    quota = max(0, settings["new_words_per_day"] - new_today)
    new = [w for w in learning_order(content) if w.id not in introduced][:quota]

    due = [((wid, face), c) for (wid, face), c in cards.items() if wid in words and c.is_due(now)]
    due.sort(key=lambda kv: priority(kv[1]) if priority else kv[1].card.due.timestamp())
    reviews = [(words[wid], face) for (wid, face), _ in due]
    for wid in sorted(introduced, key=lambda i: words[i].order):
        reviews += [(words[wid], face) for face in unlocked_faces(wid, cards, settings, started)]
    unit = content.unit(new[0].unit) if new else _last_started_unit(content, introduced)
    return WordPlan(new, reviews[: settings["review_limit"]], unit)


def unlocked_faces(word_id: str, cards: Cards, settings: dict[str, Any], today: datetime | None = None) -> list[str]:
    """出し始める面（docs/plan.md 4.5）。意味が定着してきたら聞き取りと逆引き、逆引きが定着してきたら綴り。

    today（今日の始まり）を渡すと、もとになる面を今日答えた単語は、次の面を明日から出す
    （初めての単語を「簡単」と答えた日に、聞き取りと逆引きまで出てくると多すぎるため）。
    """
    meaning = _settled(cards.get((word_id, "meaning")), today)
    reverse = _settled(cards.get((word_id, "reverse")), today)
    faces = []
    if meaning and meaning.stability >= settings["unlock_listen_days"] and (word_id, "listen") not in cards:
        faces.append("listen")
    if meaning and meaning.stability >= settings["unlock_reverse_days"] and (word_id, "reverse") not in cards:
        faces.append("reverse")
    if reverse and reverse.stability >= settings["unlock_spell_days"] and (word_id, "spell") not in cards:
        faces.append("spell")
    return faces


def _settled(card: CardRow | None, today: datetime | None) -> CardRow | None:
    if card is None or today is None:
        return card
    return card if card.card.last_review and card.card.last_review < today else None


def learning_order(content: Content) -> list[Word]:
    """新出の順。レベル → ユニット → ユニットの中の順。"""
    unit_order = {u.id: u.order for u in content.units}
    return sorted(content.words, key=lambda w: (w.level, unit_order.get(w.unit, 0), w.order))


def _last_started_unit(content: Content, introduced: set[str]) -> Unit | None:
    started = [u for u in content.units if any(w.id in introduced for w in content.words_in(u.id))]
    return started[-1] if started else (content.units[0] if content.units else None)


def word_state(word_id: str, cards: Cards, mastered_days: float) -> str:
    """未学習（new）/ 学習中（learning）/ 定着（mastered。出している面すべての安定度が mastered_days 以上）。"""
    faces = [cards[(word_id, f)] for f in WORD_FACES if (word_id, f) in cards]
    if not faces:
        return "new"
    return "mastered" if all(c.stability >= mastered_days for c in faces) else "learning"


def pick_sentences(content: Content, plan: WordPlan, cards: Cards, count: int, unit_id: str | None = None) -> list[Sentence]:
    """文ラウンドの文。まだ見ていない語が 1 語以下の文（4.8）のうち、今日の新出の単語、次に復習の単語を多く含むもの。"""
    if unit_id:
        return content.sentences_in(unit_id)
    new_ids = {w.id for w in plan.new}
    review_ids = {w.id for w, _ in plan.reviews}
    seen = {wid for wid, face in cards if face == "meaning"} | new_ids
    candidates = [s for s in content.sentences if sum(1 for w in s.word_ids if w not in seen) <= 1]
    candidates.sort(key=lambda s: (-sum(w in new_ids for w in s.word_ids), -sum(w in review_ids for w in s.word_ids)))
    return candidates[:count]


def build(
    content: Content,
    pack: LanguagePack,
    settings: dict[str, Any],
    cards: Cards,
    now: datetime,
    unit_id: str | None = None,
    priority: Priority | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    rng = rng or random.Random()
    plan = plan_words(content, settings, cards, now, unit_id, priority)
    sentences = pick_sentences(content, plan, cards, settings["new_sentences_per_day"], unit_id)

    word_round = _word_round(content, pack, plan.new, plan.reviews, rng)
    sentence_round = _sentence_round(content, pack, sentences[: settings["new_sentences_per_day"]], plan.new, rng)
    output_round = _output_round(sentences, rng)
    finish_round = _finish_round(sentences, rng)

    items: list[dict[str, Any]] = []
    rounds = []
    for key, label, round_items in (
        ("words", "単語", word_round),
        ("sentences", "文", sentence_round),
        ("output", "産出", output_round),
        ("finish", "仕上げ", finish_round),
    ):
        for item in round_items:
            item["id"] = f"{key}-{len(items) + 1}"
            item["round"] = key
            items.append(item)
        rounds.append({"key": key, "label": label, "count": len(round_items)})
    return {
        "language": pack.code,
        "mode": "unit" if unit_id else "today",
        "unit": plan.unit.to_dict() if plan.unit else None,
        "new_word_count": len(plan.new),
        "review_count": len(plan.reviews),
        "sentence_count": len(sentence_round),
        "rounds": rounds,
        "items": items,
        "estimate_min": estimate_minutes(items),
    }


def estimate_minutes(items: list[dict[str, Any]]) -> int:
    """目安の時間。単語カード 1 枚 3 秒、文 1 問 30 秒で概算する。"""
    seconds = sum(3 if item["type"].startswith("word_") else 30 for item in items)
    return max(1, round(seconds / 60))


# ---- 単語ラウンド ----


def _word_round(
    content: Content, pack: LanguagePack, new_words: list[Word], reviews: list[tuple[Word, str]], rng: random.Random
) -> list[dict[str, Any]]:
    """初見カードを順に出し、それぞれ 3〜5 枚あとに同じ単語の意味の問題を混ぜる。復習は 3 枚ごとに 1 つ混ぜ、残りは最後に出す。"""
    pool = content.words
    review_items = [_word_item(face, word, pool, pack, rng) for word, face in reviews]
    rng.shuffle(review_items)

    result: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any]]] = []

    def flush() -> None:
        while pending and pending[0][0] <= len(result):
            result.append(pending.pop(0)[1])

    for word in new_words:
        flush()
        result.append({"type": "word_intro", "word": word.to_dict(), "tts": word.tts_text})
        due = len(result) + rng.randint(*RECALL_GAP)
        pending.append((due, _word_item("meaning", word, pool, pack, rng)))
        pending.sort(key=lambda p: p[0])
        if review_items and len(result) % 3 == 0:
            flush()
            result.append(review_items.pop())
    while pending:
        flush()
        if pending:
            result.append(pending.pop(0)[1])
    result.extend(review_items)
    return result


def _word_item(face: str, word: Word, pool: list[Word], pack: LanguagePack, rng: random.Random) -> dict[str, Any]:
    item: dict[str, Any] = {"type": f"word_{face}", "word": word.to_dict(), "face": face, "tts": word.tts_text}
    if face == "spell":
        item["expected"] = word.lemma
        item["prompt"] = {"text": word.meaning, "tts": word.tts_text}
        return item
    distractors = _distractors(word, pool, rng)
    if face == "reverse":
        item["prompt"] = {"text": word.meaning, "tts": None}
        item["options"] = [{"word_id": w.id, "label": w.lemma, "tts": w.tts_text} for w in [word, *distractors]]
    else:
        item["prompt"] = {"text": word.lemma if face == "meaning" else None, "tts": word.tts_text}
        item["options"] = [{"word_id": w.id, "label": w.meaning} for w in [word, *distractors]]
    rng.shuffle(item["options"])
    item["answer_id"] = word.id
    return item


def _distractors(word: Word, pool: list[Word], rng: random.Random) -> list[Word]:
    """同じ品詞から選ぶ。同義語と同じ綴りの別語は入れない。足りなければほかの品詞から補う。"""
    excluded = {word.id, *word.synonyms, *word.homographs}
    same_pos = [w for w in pool if w.pos == word.pos and w.id not in excluded and w.meaning != word.meaning]
    others = [w for w in pool if w.pos != word.pos and w.id not in excluded and w.meaning != word.meaning]
    picked = rng.sample(same_pos, min(len(same_pos), OPTIONS - 1))
    if len(picked) < OPTIONS - 1:
        picked += rng.sample(others, min(len(others), OPTIONS - 1 - len(picked)))
    return picked


# ---- 文ラウンド ----


def _sentence_round(content: Content, pack: LanguagePack, sentences: list[Sentence], new_words: list[Word], rng: random.Random) -> list[dict[str, Any]]:
    """文の記録（段階）はまだないので、導入 → 聞いて選ぶ → 穴埋め → 書き取り を順に回す。"""
    new_ids = {w.id for w in new_words}
    kinds = ["intro", "listen_choose", "cloze", "dictation"]
    items: list[dict[str, Any]] = []
    for i, sentence in enumerate(sentences):
        kind = kinds[i % len(kinds)]
        if kind == "cloze" and not sentence.cloze:
            kind = "dictation"
        items.append(_sentence_item(kind, sentence, content, new_ids, rng))
    return items


def _sentence_item(kind: str, sentence: Sentence, content: Content, new_ids: set[str], rng: random.Random) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": f"sentence_{kind}",
        "sentence": _sentence_view(sentence, content, new_ids),
    }
    if kind == "listen_choose":
        pool = [s for s in content.sentences if s.id != sentence.id and s.ja != sentence.ja]
        options = [sentence, *rng.sample(pool, min(len(pool), OPTIONS - 1))]
        rng.shuffle(options)
        item["options"] = [{"sentence_id": s.id, "label": s.ja} for s in options]
        item["answer_id"] = sentence.id
    elif kind == "cloze":
        cloze = dict(sentence.cloze[0])
        item["cloze"] = cloze
        item["expected"] = cloze["answer"]
    elif kind in ("dictation", "ja_to_ko", "trace"):
        item["expected"] = sentence.ko
    return item


def _sentence_view(sentence: Sentence, content: Content, new_ids: set[str]) -> dict[str, Any]:
    view = sentence.to_dict()
    view["tokens"] = [
        {
            **token,
            "is_new": any(wid in new_ids for wid in token.get("word_ids", [])),
            "words": [content.word(wid).to_dict() for wid in token.get("word_ids", []) if wid in content._word_by_id],
        }
        for token in sentence.tokens
    ]
    return view


# ---- 産出・仕上げ ----


def _output_round(sentences: list[Sentence], rng: random.Random) -> list[dict[str, Any]]:
    items = []
    for sentence in rng.sample(sentences, min(len(sentences), 2)):
        items.append({"type": "sentence_ja_to_ko", "sentence": sentence.to_dict(), "expected": sentence.ko})
    if sentences:
        s = rng.choice(sentences)
        items.append({
            "type": "sentence_compose",
            "sentence": s.to_dict(),
            "required": s.grammar[0] if s.grammar else "",
            "task": f"「{s.grammar[0]}」を使って、自分のことを 1 文で書いてください" if s.grammar else "自分のことを 1 文で書いてください",
        })
    return items


def _finish_round(sentences: list[Sentence], rng: random.Random) -> list[dict[str, Any]]:
    return [
        {"type": "sentence_trace", "sentence": s.to_dict(), "expected": s.ko}
        for s in rng.sample(sentences, min(len(sentences), 3))
    ]
