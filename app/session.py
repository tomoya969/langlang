"""「今日の学習」の組み立て（docs/plan.md 4.8）。

単語ラウンド → 文ラウンド → 産出ラウンド → 仕上げ、の順に問題の列を作る。
画面は列を上から順に出し、矢印ゲームで間違えた問題はその場で最後尾に回す（列の操作は画面側 arrow-game.js）。

現段階（UI を作る段階）では学習の記録を持たないので、指定したユニットの単語と文から列を作る。
FSRS による期限と新出の枠は M2 以降で足す。そのときもこのモジュールが列を組み立てる。
"""

from __future__ import annotations

import random
from typing import Any

from app.content import Content, Sentence, Word
from app.langs.base import LanguagePack

# 1 枚の初見カードのあと、同じ単語を何枚あとに出すか
RECALL_GAP = (3, 5)
OPTIONS = 4


def build(content: Content, pack: LanguagePack, unit_id: str, settings: dict[str, Any], rng: random.Random | None = None) -> dict[str, Any]:
    rng = rng or random.Random()
    unit = content.unit(unit_id)
    words = content.words_in(unit_id)[: settings["new_words_per_day"]]
    earlier_units = [u for u in content.units_up_to(unit_id) if u.id != unit_id]
    earlier_words = [w for u in earlier_units for w in content.words_in(u.id)]
    sentences = content.sentences_in(unit_id)

    word_round = _word_round(content, pack, words, earlier_words, rng)
    sentence_round = _sentence_round(content, pack, sentences[: settings["new_sentences_per_day"]], words, rng)
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
        "unit": unit.to_dict(),
        "rounds": rounds,
        "items": items,
        "estimate_min": estimate_minutes(items),
    }


def estimate_minutes(items: list[dict[str, Any]]) -> int:
    """目安の時間。単語カード 1 枚 3 秒、文 1 問 30 秒で概算する。"""
    seconds = sum(3 if item["type"].startswith("word_") else 30 for item in items)
    return max(1, round(seconds / 60))


# ---- 単語ラウンド ----


def _word_round(content: Content, pack: LanguagePack, new_words: list[Word], earlier: list[Word], rng: random.Random) -> list[dict[str, Any]]:
    """初見カードを順に出し、それぞれ 3〜5 枚あとに同じ単語の意味の問題を混ぜる。
    前のユニットの単語があれば、聞き取り・逆引き・綴りの問題も復習として混ぜる。"""
    pool = content.words
    reviews: list[dict[str, Any]] = []
    for word in rng.sample(earlier, min(len(earlier), 6)):
        face = rng.choice(["listen", "reverse", "spell"])
        reviews.append(_word_item(face, word, pool, pack, rng))
    rng.shuffle(reviews)

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
        if reviews and len(result) % 3 == 0:
            flush()
            result.append(reviews.pop())
    while pending:
        flush()
        if pending:
            result.append(pending.pop(0)[1])
    result.extend(reviews)
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
    """記録がないので、導入 → 聞いて選ぶ → 穴埋め → 書き取り を順に回して、各練習の画面を確かめられるようにする。"""
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
