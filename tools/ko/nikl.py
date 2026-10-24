"""国立国語院「한국어 학습용 어휘 목록」（2003）の取り込み（docs/plan.md 6.1 の 1・2）。

配布の txt は CP949 のタブ区切りで、列は 순위（頻度順位）・단어・품사・풀이（漢字や用例）・등급（A〜C ＝ 1〜3 段階）。
순위 が空の行がある（固有名詞や 구십 など、頻度の調査に出てこなかった語）。順位は None にする。
단어 の末尾の数字は、同じ綴りの別語を見分ける番号（가다01）。
同じ見出しが品詞違いで複数行あるとき（오늘 の名詞と副詞など）は同じ語なので、1 つの候補にまとめる。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SOURCE_NAME = "nikl.txt"
SOURCE_URL = "https://www.korean.go.kr/front_eng/down/down_02V.do?etc_seq=70"

STAGES = {"A": 1, "B": 2, "C": 3}
POS_JA = {
    "명": "名詞",
    "의": "依存名詞",
    "대": "代名詞",
    "수": "数詞",
    "동": "動詞",
    "형": "形容詞",
    "부": "副詞",
    "관": "冠形詞",
    "감": "感嘆詞",
    "고": "固有名詞",
    "보": "補助用言",
}
# 「불」（분석 불능。걔、그래서、어때 など縮約や活用した形）は品詞を AI に付けてもらう
POS_UNKNOWN = "불"
POS_AUXILIARY = "보"

_HOMOGRAPH_NUMBER = re.compile(r"\d+$")
_PARENTHESIS = re.compile(r"\(.*?\)")


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp949")


def parse(text: str) -> list[dict[str, Any]]:
    """1 行 1 件の dict（rank, headword, pos, gloss, stage）にする。見出しの行と空行は飛ばす。"""
    rows = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.rstrip("\r\n").split("\t")]
        if len(cells) < 5 or not cells[1]:
            continue
        rank, headword, pos, gloss, stage = cells[:5]
        if stage not in STAGES:
            if rank.isdigit():
                raise ValueError(f"等級が A〜C ではありません: {line!r}")
            continue
        rows.append(
            {"rank": int(rank) if rank.isdigit() else None, "headword": headword, "pos": pos, "gloss": gloss, "stage": STAGES[stage]}
        )
    return rows


def lemma_of(headword: str) -> str:
    """見出しから番号と（　）の別名を除いた、画面に出す形（가다01 → 가다、도쿄(동경) → 도쿄）。"""
    return _HOMOGRAPH_NUMBER.sub("", _PARENTHESIS.sub("", headword)).strip()


def candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """見出しごとに 1 つの候補にまとめる。順位と段階はいちばん高いもの、品詞は順位の高い順に並べる。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["headword"], []).append(row)
    result = []
    for headword, group in grouped.items():
        group.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))
        pos_list = list(dict.fromkeys(r["pos"] for r in group))
        glosses = list(dict.fromkeys(r["gloss"] for r in group if r["gloss"]))
        main_pos = next((p for p in pos_list if p not in (POS_UNKNOWN, POS_AUXILIARY)), None)
        candidate: dict[str, Any] = {
            "key": headword,
            "lemma": lemma_of(headword),
            "pos": POS_JA.get(main_pos) if main_pos else None,
            "source": "nikl",
            "nikl": {
                "headword": headword,
                "pos": pos_list,
                "rank": group[0]["rank"],
                "stage": min(r["stage"] for r in group),
                "gloss": " / ".join(glosses),
            },
        }
        if set(pos_list) == {POS_AUXILIARY}:
            candidate["excluded"] = "補助用言"
        result.append(candidate)
    return result
