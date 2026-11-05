"""「今日の学習」の組み立て（docs/plan.md 4.8）。

単語ラウンド → 文ラウンド → 産出ラウンド → 仕上げ、の順に問題の列を作る。
画面は列を上から順に出し、矢印ゲームで間違えた問題はその場で最後尾に回す（列の操作は画面側 arrow-game.js）。

単語と文は学習の記録（app/records.py のカード）から組む。期限が来たもの（単語は出し始める面も。4.5）を復習に、
まだ出していないものを新出にする。ユニットを指定したときは、そのユニットの単語と文だけで組む（ユニットの練習）。
文の練習の種類は段階で決める（4.7）。産出（日→韓・応用作文）は時間がかかるので 1 日 OUTPUT_ITEMS 問までにし、
産出に回らなかった段階 3〜5 の文は書き取りにする。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from app.content import Content, Sentence, Unit, Word
from app.langs.base import LanguagePack
from app.records import FIRST_STAGE, CardRow, day_start

# 初見カードのあと、同じ単語の最初の出題までにはさむ問題の数
RECALL_GAP = (3, 5)
# 文の導入のあと、同じ文の最初の出題までにはさむ問題の数
SENTENCE_GAP = (2, 3)
# 復習を何問ごとに 1 つ、新出の間に混ぜるか
REVIEW_EVERY = 3
OPTIONS = 4
OUTPUT_ITEMS = 3
WORD_FACES = ("meaning", "listen", "reverse", "spell")
STAGE_PRACTICE = {1: "listen_choose", 2: "cloze", 3: "dictation", 4: "dictation", 5: "dictation"}
OUTPUT_PRACTICE = {3: "ja_to_ko", 4: "compose", 5: "ja_to_ko"}

Cards = dict[tuple[str, str], CardRow]
SentenceCards = dict[str, CardRow]
Priority = Callable[[CardRow], float]


@dataclass
class WordPlan:
    new: list[Word]
    reviews: list[tuple[Word, str]]  # (単語, 面)
    unit: Unit | None


@dataclass
class SentencePlan:
    new: list[Sentence]
    reviews: list[tuple[Sentence, int]]  # (文, 段階)


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
    due.sort(key=lambda kv: _priority_key(kv[1], priority))
    reviews = [(words[wid], face) for (wid, face), _ in due]
    for wid in sorted(introduced, key=lambda i: words[i].order):
        reviews += [(words[wid], face) for face in unlocked_faces(wid, cards, settings, started)]
    unit = content.unit(new[0].unit) if new else _last_started_unit(content, introduced)
    return WordPlan(new, reviews[: settings["review_limit"]], unit)


def plan_sentences(
    content: Content,
    settings: dict[str, Any],
    words: WordPlan,
    cards: Cards,
    sentence_cards: SentenceCards,
    now: datetime,
    unit_id: str | None = None,
    priority: Priority | None = None,
) -> SentencePlan:
    """新しい文と復習の文を決める。新しい文は、まだ見ていない語が 1 語以下の文（4.8）のうち、
    今日の新出の単語、次に復習の単語を多く含むもの。"""
    new_ids = {w.id for w in words.new}
    review_ids = {w.id for w, _ in words.reviews}
    seen = {wid for wid, face in cards if face == "meaning"} | new_ids
    pool = content.sentences_in(unit_id) if unit_id else content.sentences
    fresh = [s for s in pool if s.id not in sentence_cards and sum(1 for w in s.word_ids if w not in seen) <= 1]
    fresh.sort(key=lambda s: (-sum(w in new_ids for w in s.word_ids), -sum(w in review_ids for w in s.word_ids)))

    if unit_id:
        reviews = [(s, _stage(sentence_cards[s.id])) for s in pool if s.id in sentence_cards]
        return SentencePlan(fresh[: settings["new_sentences_per_day"]], reviews)

    started = day_start(now)
    new_today = sum(1 for c in sentence_cards.values() if c.introduced_at >= started)
    quota = max(0, settings["new_sentences_per_day"] - new_today)
    due = [c for sid, c in sentence_cards.items() if sid in content._sentence_by_id and c.is_due(now)]
    due.sort(key=lambda c: _priority_key(c, priority))
    reviews = [(content.sentence(c.item_id), _stage(c)) for c in due[: settings["review_limit"]]]
    return SentencePlan(fresh[:quota], reviews)


def _priority_key(card: CardRow, priority: Priority | None) -> float:
    return priority(card) if priority else card.card.due.timestamp()


def _stage(card: CardRow) -> int:
    return card.stage or FIRST_STAGE


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


def practice_for(sentence: Sentence, stage: int, output_room: int) -> tuple[str, bool]:
    """段階の練習と、産出ラウンドに回すか。段階 3 以上の文は、産出の枠（output_room）が残っていれば産出に回す。"""
    if stage >= 3 and output_room > 0:
        kind = OUTPUT_PRACTICE[stage]
        return ("ja_to_ko" if kind == "compose" and not sentence.grammar else kind), True
    kind = STAGE_PRACTICE[stage]
    return ("dictation" if kind == "cloze" and not sentence.cloze else kind), False


def build(
    content: Content,
    pack: LanguagePack,
    settings: dict[str, Any],
    cards: Cards,
    now: datetime,
    unit_id: str | None = None,
    priority: Priority | None = None,
    rng: random.Random | None = None,
    sentence_cards: SentenceCards | None = None,
) -> dict[str, Any]:
    rng = rng or random.Random()
    words = plan_words(content, settings, cards, now, unit_id, priority)
    sentences = plan_sentences(content, settings, words, cards, sentence_cards or {}, now, unit_id, priority)
    new_ids = {w.id for w in words.new}

    sentence_reviews: list[dict[str, Any]] = []
    output_round: list[dict[str, Any]] = []
    for sentence, stage in sentences.reviews:
        kind, is_output = practice_for(sentence, stage, OUTPUT_ITEMS - len(output_round))
        item = _sentence_item(kind, sentence, content, new_ids, rng)
        item["stage"] = stage
        (output_round if is_output else sentence_reviews).append(item)

    word_round = _word_round(content, pack, words.new, words.reviews, rng)
    sentence_round = _sentence_round(content, sentences.new, sentence_reviews, new_ids, rng)
    finish_round = _finish_round([*sentences.new, *(s for s, _ in sentences.reviews)], rng)

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
        "unit": words.unit.to_dict() if words.unit else None,
        "new_word_count": len(words.new),
        "new_sentence_count": len(sentences.new),
        "review_count": len(words.reviews) + len(sentences.reviews),
        "rounds": rounds,
        "items": items,
        "estimate_min": estimate_minutes(items),
    }


def estimate_minutes(items: list[dict[str, Any]]) -> int:
    """目安の時間。単語カード 1 枚 3 秒、文 1 問 30 秒で概算する。"""
    seconds = sum(3 if item["type"].startswith("word_") else 30 for item in items)
    return max(1, round(seconds / 60))


def _interleave(new: list[tuple[dict[str, Any], dict[str, Any]]], reviews: list[dict[str, Any]], gap: tuple[int, int], rng: random.Random) -> list[dict[str, Any]]:
    """新出の（導入, 最初の出題）を順に出し、出題は導入から gap 問あとに置く。
    復習は REVIEW_EVERY 問ごとに 1 つ混ぜ、最後の出題までの間を埋めるのにも使い、残りは最後に出す。"""
    reviews = list(reviews)
    result: list[dict[str, Any]] = []
    pending: list[tuple[int, dict[str, Any]]] = []
    intro_of: dict[int, int] = {}  # 出題の id() → 導入の id()

    def flush() -> None:
        while pending and pending[0][0] <= len(result):
            result.append(pending.pop(0)[1])

    for intro, first in new:
        flush()
        result.append(intro)
        intro_of[id(first)] = id(intro)
        pending.append((len(result) + rng.randint(*gap), first))
        pending.sort(key=lambda p: p[0])
        if reviews and len(result) % REVIEW_EVERY == 0:
            flush()
            result.append(reviews.pop())
    while pending:
        flush()
        if pending:
            result.append(reviews.pop() if reviews else pending.pop(0)[1])
    result.extend(reviews)
    _space_out_tail(result, intro_of, gap[0])
    return result


def _space_out_tail(items: list[dict[str, Any]], intro_of: dict[int, int], min_gap: int) -> None:
    """間を埋めるものが尽きて（列の終わり）、出題が導入のすぐあとになったら、導入を前に出して min_gap 問はさむ。
    新出は学ぶ順に出すので、導入はほかの導入より前には出さない。"""
    intros = set(intro_of.values())
    for q_index in range(len(items)):
        intro_id = intro_of.get(id(items[q_index]))
        if intro_id is None:
            continue
        i_index = next(k for k in range(q_index) if id(items[k]) == intro_id)
        earliest = max((k + 1 for k in range(i_index) if id(items[k]) in intros), default=0)
        target = max(earliest, q_index - min_gap - 1)
        if target < i_index:
            items.insert(target, items.pop(i_index))


# ---- 単語ラウンド ----


def _word_round(
    content: Content, pack: LanguagePack, new_words: list[Word], reviews: list[tuple[Word, str]], rng: random.Random
) -> list[dict[str, Any]]:
    pool = content.words
    review_items = [_word_item(face, word, pool, pack, rng) for word, face in reviews]
    rng.shuffle(review_items)
    new = [({"type": "word_intro", "word": w.to_dict(), "tts": w.tts_text}, _word_item("meaning", w, pool, pack, rng)) for w in new_words]
    return _interleave(new, review_items, RECALL_GAP, rng)


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


def _sentence_round(content: Content, new: list[Sentence], reviews: list[dict[str, Any]], new_ids: set[str], rng: random.Random) -> list[dict[str, Any]]:
    """新しい文は導入のあと、2〜3 問はさんで段階 1 の練習を出す（4.7）。復習の文は段階の練習。"""
    pairs = []
    for sentence in new:
        first, _ = practice_for(sentence, FIRST_STAGE, 0)
        pairs.append((_sentence_item("intro", sentence, content, new_ids, rng), _sentence_item(first, sentence, content, new_ids, rng)))
    reviews = list(reviews)
    rng.shuffle(reviews)
    return _interleave(pairs, reviews, SENTENCE_GAP, rng)


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
    elif kind == "compose":
        item["required"] = sentence.grammar[0]
        item["task"] = f"「{sentence.grammar[0]}」を使って、自分のことを 1 文で書いてください"
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


# ---- 仕上げ ----


def _finish_round(sentences: list[Sentence], rng: random.Random) -> list[dict[str, Any]]:
    """その日に扱った文から 3 文を、なぞりタイピングで打つ。"""
    return [
        {"type": "sentence_trace", "sentence": s.to_dict(), "expected": s.ko}
        for s in rng.sample(sentences, min(len(sentences), 3))
    ]
