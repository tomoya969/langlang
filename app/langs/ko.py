"""韓国語の言語パック（サーバー側）。"""

from __future__ import annotations

from app.langs.base import LanguagePack

REGISTERS = ("합니다체", "해요체", "반말", "한다체")

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = ("", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ")

# 二重받침の、後ろに母音が来たときに残る字と移る字
_SPLIT = {"ㄳ": ("ㄱ", "ㅅ"), "ㄵ": ("ㄴ", "ㅈ"), "ㄶ": ("ㄴ", "ㅎ"), "ㄺ": ("ㄹ", "ㄱ"), "ㄻ": ("ㄹ", "ㅁ"), "ㄼ": ("ㄹ", "ㅂ"),
          "ㄽ": ("ㄹ", "ㅅ"), "ㄾ": ("ㄹ", "ㅌ"), "ㄿ": ("ㄹ", "ㅍ"), "ㅀ": ("ㄹ", "ㅎ"), "ㅄ": ("ㅂ", "ㅅ")}
# 받침の代表音
_REPRESENTATIVE = {"ㄲ": "ㄱ", "ㅋ": "ㄱ", "ㄳ": "ㄱ", "ㄺ": "ㄱ", "ㅅ": "ㄷ", "ㅆ": "ㄷ", "ㅈ": "ㄷ", "ㅊ": "ㄷ", "ㅌ": "ㄷ",
                   "ㅎ": "ㄷ", "ㅍ": "ㅂ", "ㅄ": "ㅂ", "ㄿ": "ㅂ", "ㄵ": "ㄴ", "ㄶ": "ㄴ", "ㄼ": "ㄹ", "ㄽ": "ㄹ", "ㄾ": "ㄹ",
                   "ㅀ": "ㄹ", "ㄻ": "ㅁ"}
_ASPIRATE = {"ㄱ": "ㅋ", "ㄷ": "ㅌ", "ㅂ": "ㅍ", "ㅈ": "ㅊ"}
_TENSE = {"ㄱ": "ㄲ", "ㄷ": "ㄸ", "ㅂ": "ㅃ", "ㅅ": "ㅆ", "ㅈ": "ㅉ"}
_NASAL = {"ㄱ": "ㅇ", "ㄷ": "ㄴ", "ㅂ": "ㅁ"}
_GLIDE_DROP = {"ㅑ": "ㅏ", "ㅕ": "ㅓ", "ㅛ": "ㅗ", "ㅠ": "ㅜ"}
_VOWEL_MERGE = {"ㅐ": "ㅔ", "ㅒ": "ㅖ", "ㅙ": "ㅞ", "ㅚ": "ㅞ"}


def pronounce(text: str) -> str:
    """発音どおりの形に直す。綴りは違っても発音が同じ答え（미안해요 と 미야내요）を見つけるためのもので、
    よく出る規則（連音、ㅎ の脱落と激音化、받침の代表音、鼻音化、流音化、濃音化、口蓋音化、母音の合流）だけを扱う。

    空白は除いてから直す（空白だけの違いは別に扱うため）。どちらの答えにも同じ直し方をするので、
    語の境目をまたいだ連音のような、実際の発音と少しずれるところは比べる妨げにならない。
    """
    syllables: list[list[str] | str] = []
    for ch in text.replace(" ", ""):
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            syllables.append([_CHO[code // 588], _JUNG[code % 588 // 28], _JONG[code % 28]])
        else:
            syllables.append(ch)

    for prev, cur in zip(syllables, syllables[1:]):
        if isinstance(prev, str) or isinstance(cur, str) or not prev[2]:
            continue
        _join(prev, cur)

    for i, s in enumerate(syllables):
        if isinstance(s, str):
            continue
        s[2] = _REPRESENTATIVE.get(s[2], s[2])
        prev = syllables[i - 1] if i > 0 else None
        prev_open = isinstance(prev, list) and not prev[2]
        if s[0] == "ㅇ" and prev_open and prev[1] == "ㅣ":
            s[1] = _GLIDE_DROP.get(s[1], s[1])
        s[1] = _VOWEL_MERGE.get(s[1], s[1])
        # 예・례 以外の ㅖ は [ㅔ]。母音の後の 예（뭐예요 など）も [에] と発音する
        if s[1] == "ㅖ" and (s[0] not in "ㅇㄹ" or (s[0] == "ㅇ" and prev_open)):
            s[1] = "ㅔ"
        if s[1] == "ㅢ" and (s[0] != "ㅇ" or i > 0):
            s[1] = "ㅣ"

    for prev, cur in zip(syllables, syllables[1:]):
        if isinstance(prev, str) or isinstance(cur, str) or not prev[2]:
            continue
        if prev[2] in _NASAL and cur[0] in "ㄴㅁ":
            prev[2] = _NASAL[prev[2]]
        elif prev[2] in _NASAL and cur[0] in _TENSE:
            cur[0] = _TENSE[cur[0]]
        if prev[2] in "ㅁㅇ" and cur[0] == "ㄹ":
            cur[0] = "ㄴ"
        elif (prev[2], cur[0]) in (("ㄴ", "ㄹ"), ("ㄹ", "ㄴ")):
            prev[2] = cur[0] = "ㄹ"

    return "".join(s if isinstance(s, str) else _compose(*s) for s in syllables)


def _join(prev: list[str], cur: list[str]) -> None:
    """받침と次の字の頭の子音のあいだで起きる変化（連音・ㅎ・口蓋音化）。代表音にする前に行う。"""
    jong, cho = prev[2], cur[0]
    keep, move = _SPLIT.get(jong, ("", jong))
    if cho == "ㅇ":
        if jong == "ㅇ":
            return
        if move == "ㅎ":
            # ㅎ は落ち、ㄶ・ㅀ は残りの ㄴ・ㄹ が移る（많아 → 마나）
            keep, move = "", keep
        if move in ("ㄷ", "ㅌ") and cur[1] == "ㅣ":
            move = "ㅈ" if move == "ㄷ" else "ㅊ"
        prev[2] = keep
        if move:
            cur[0] = move
    elif cho == "ㅎ":
        if jong in ("ㄴ", "ㄹ", "ㅁ"):
            prev[2], cur[0] = "", jong
        elif jong == "ㅇ":
            cur[0] = "ㅇ"
        else:
            base = _REPRESENTATIVE.get(move, move)
            if base in _ASPIRATE:
                prev[2], cur[0] = keep, _ASPIRATE[base]
    elif move == "ㅎ":
        if cho in _ASPIRATE:
            prev[2], cur[0] = keep, _ASPIRATE[cho]
        elif cho == "ㅅ":
            prev[2], cur[0] = keep, "ㅆ"
        elif cho == "ㄴ":
            prev[2] = keep or "ㄴ"


def _compose(cho: str, jung: str, jong: str) -> str:
    return chr(0xAC00 + (_CHO.index(cho) * 21 + _JUNG.index(jung)) * 28 + _JONG.index(jong))


PACK = LanguagePack(
    code="ko",
    label="韓国語",
    native="한국어",
    tts_lang="ko-KR",
    tts_sample="안녕하세요. 만나서 반갑습니다.",
    registers=REGISTERS,
    spacing_tag="띄어쓰기",
    pronounce=pronounce,
    spelling_tag="綴り",
)
