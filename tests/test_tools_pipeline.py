"""教材づくりの段階を、偽の AI で取り込みから書き出しまで通す。"""

from __future__ import annotations

import re

import pytest

from app import content
from tools import (
    assign_levels,
    decisions,
    enrich_words,
    export,
    gen_grammar,
    gen_sentences,
    gen_variants,
    import_nikl,
    supplement,
    tag_candidates,
    verify_words,
)
from tools.work import BuildError, Workspace

pytest.importorskip("kiwipiepy")

NIKL_TEXT = "\n".join(
    [
        "순위\t단어\t품사\t풀이\t등급",
        "357\t네03\t감\t\tA",
        "56\t저03\t대\t일인칭 대명사\tA",
        "2\t하다01\t동\t\tA",
        "2\t하다01\t보\t\tA",
        "23\t주다01\t동\t\tA",
        "25\t가다01\t동\t\tA",
        "70\t물\t명\t\tA",
        "150\t커피\t명\t\tA",
        "365\t마시다\t동\t\tA",
        "48\t학교\t명\t學校\tA",
        "\t부산\t고\t釜山\tA",
        "3000\t싶다\t보\t\tA",
    ]
)
MEANINGS = {
    "네": "はい", "저": "私", "하다": "する", "주다": "くれる", "가다": "行く",
    "물": "水", "커피": "コーヒー", "마시다": "飲む", "학교": "学校", "안녕하세요": "こんにちは",
}
GRAMMAR = ["-아/어요", "-(으)세요", "은/는", "을/를", "에", "도"] + [f"文法{i}" for i in range(14)]


class FakeAI:
    """スキーマの形で、どの段階の呼び出しかを見分けて答える。"""

    def __init__(self):
        self.calls: list[str] = []
        self.verified: dict[str, int] = {}

    def __call__(self, prompt: str, schema: dict) -> dict:
        field = next(iter(schema["properties"]))
        props = schema["properties"][field]
        if field == "greetings":
            self.calls.append("supplement")
            return {"greetings": [{"lemma": "안녕하세요", "ja": "こんにちは", "pos": "表現"}, {"lemma": "물", "ja": "重複", "pos": "名詞"}], "modern": []}
        if field == "tags":
            self.calls.append("tag")
            return {"tags": {key: self._tag(key) for key in props["required"]}}
        if field == "units":
            self.calls.append("units")
            keys = props["items"]["properties"]["keys"]["items"]["enum"]
            title = "あいさつ" if "네03" in keys else "カフェ"
            return {"units": [{"title": title, "scene": "場面", "keys": keys}]}
        if field == "items":
            self.calls.append("grammar")
            unit = props["items"]["properties"]["unit"]["enum"][0]
            return {"items": [{"form": f, "ja": f, "example": "예", "unit": unit} for f in GRAMMAR]}
        if field == "words" and "meanings" in str(props):
            self.calls.append("enrich")
            return {"words": {key: self._enrich(key) for key in props["required"]}}
        if field == "words":
            self.calls.append("verify-words")
            return {"words": {key: self._verify_word(key) for key in props["required"]}}
        if field == "sentences" and props["type"] == "array":
            self.calls.append("sentences")
            return {"sentences": self._sentences(prompt)}
        item = props["properties"][props["required"][0]]["properties"]
        if "cloze" in item:
            self.calls.append("variants")
            return {"sentences": {key: self._variants(key, prompt) for key in props["required"]}}
        if "bad" in item:
            self.calls.append("verify-variants")
            return {"sentences": {key: self._verify_variants(key, prompt) for key in props["required"]}}
        self.calls.append("verify-sentences")
        return {"sentences": {key: self._verify_sentence(key, prompt) for key in props["required"]}}

    @staticmethod
    def _variants(key, prompt):
        ko = re.search(r"- ko（模範解答）: (.+)", prompt.split(f"## {key}\n", 1)[1]).group(1)
        if ko == "물 주세요.":
            # 発音が同じだけのもの・空白だけ違うもの・数字は機械で除く。「물 좀 주세요.」は検算で除く
            return {"ko": ["물 좀 주세요.", "물주세요.", "물 주새요.", "물 2잔 주세요.", "물 주세요!"], "ja": ["水を下さい。"], "cloze": ["물을", "물 좀"]}
        return {"ko": [], "ja": [], "cloze": []}

    @staticmethod
    def _verify_variants(key, prompt):
        block = prompt.split(f"## {key}\n", 1)[1]
        bad = [{"kind": "ko", "text": "물 좀 주세요.", "reason": "テストの除外"}] if "물 좀 주세요." in block else []
        return {"bad": bad}

    @staticmethod
    def _tag(key):
        return {
            "hanken": "5級",
            "origin": "漢字語" if key in ("학교", "네03") else "固有語",
            "pos": "表現" if key.startswith("s:") else "名詞",
            "ja_cognate": key == "학교",
            "exclude": "固有名詞" if key == "부산" else "なし",
        }

    @staticmethod
    def _enrich(key):
        lemma = re.sub(r"^s:|\d+$", "", key)
        return {
            "meanings": [{"ja": MEANINGS[lemma], "primary": False}],
            "hanja": "学校" if lemma == "학교" else "",
            "confusables": ["물"] if lemma == "커피" else [],
            "synonyms": [],
            "tags": ["テスト"],
        }

    @staticmethod
    def _verify_word(key):
        bad = key == "커피"
        return {
            "meaning_ok": not bad,
            "hanja_ok": True,
            "origin_ok": key != "네03",
            "suggested_meaning": "コーヒー（飲み物）" if bad else "",
            "suggested_hanja": "",
            "suggested_origin": "固有語" if key == "네03" else "",
            "note": "",
        }

    def _sentences(self, prompt):
        ids = dict((lemma, wid) for wid, lemma in re.findall(r"^(ko-w-\d{4}): (.+?)（", prompt, re.M))

        def s(ko, words, ja="訳"):
            tokens = [{"surface": e.strip(".,"), "word_ids": [ids[w] for w in words.get(e.strip(".,"), [])]} for e in ko.split()]
            return {
                "ko": ko, "ja": ja, "register": "해요체", "scene": "場面", "tokens": tokens, "grammar": ["-아/어요"],
                "cloze": {"eojeol": 0, "answer": tokens[0]["surface"], "hint_ja": "ヒント"},
                "variants": {"ko": [], "ja": ["別訳"]},
            }

        if "代わりの文" in prompt:
            replacements = {
                "우유 마셔요.": s("물 마셔요.", {"물": ["물"], "마셔요": ["마시다"]}),
                "학교에 가요.": s("학교에 가요.", {"학교에": ["학교"], "가요": ["가다"]}),
            }
            return [replacements[ko] for ko in re.findall(r"^- (.+)\n  問題:", prompt, re.M)]
        if "L1-U01" in prompt:
            return [
                s("안녕하세요.", {"안녕하세요": ["안녕하세요"]}),
                s("네, 가요.", {"네": ["네"], "가요": ["가다"]}),
                s("저도 해요.", {"저도": ["저"], "해요": ["하다"]}),
                s("주세요.", {"주세요": ["주다"]}),
            ]
        return [
            s("물 주세요.", {"물": ["물"], "주세요": ["주다"]}),
            s("커피 마셔요.", {"커피": ["커피"], "마셔요": ["마시다"]}),
            s("학교에 가요.", {"학교에": ["학교"], "가요": ["가다"]}),
            s("우유 마셔요.", {"마셔요": ["마시다"]}),
        ]

    def _verify_sentence(self, key, prompt):
        block = prompt.split(f"## {key}\n", 1)[1]
        ko = re.search(r"- ko: (.+)", block).group(1)
        self.verified[ko] = self.verified.get(ko, 0) + 1
        if ko == "학교에 가요." and self.verified[ko] == 1:
            return {"ok": False, "problems": ["テストの不合格"], "grammar": [], "bad_ko_variants": [], "bad_ja_variants": []}
        grammar = ["-(으)세요"] if "주세요" in ko else ["-아/어요"]
        return {"ok": True, "problems": [], "grammar": grammar, "bad_ko_variants": [], "bad_ja_variants": ["別訳"]}


def test_pipeline_from_list_to_content(tmp_path):
    ws = Workspace(tmp_path, "ko")
    ws.sources.mkdir(parents=True)
    (ws.sources / "nikl.txt").write_text(NIKL_TEXT, encoding="utf-8")
    ai = FakeAI()

    import_nikl.run(ws)
    supplement.run(ws, ai)
    assert [c["lemma"] for c in supplement.candidates(ws)] == ["안녕하세요"]
    tag_candidates.run(ws, ai, parallel=2)
    assert tag_candidates.pending(ws) == []
    assignment = assign_levels.rank(ws, sizes={1: 10})
    assert "除外 2 語" in assignment
    assign_levels.run_units(ws, ai, 1)
    units = assign_levels.layout(ws, 1)
    assert [u["title"] for u in units] == ["あいさつ", "カフェ"]
    gen_grammar.run(ws, ai, 1)
    enrich_words.run(ws, ai, 1)
    verify_words.run(ws, ai, 1)
    gen_sentences.run(ws, ai, ai, 1)
    gen_variants.run(ws, ai, ai, 1)
    message = export.run(ws, 1)
    assert "ユニット 2" in message

    loaded = content.load(tmp_path, "ko", approved_only=False)
    words = {w.lemma: w for w in loaded.words}
    assert words["안녕하세요"].unit == "L1-U01" and words["안녕하세요"].pos == "表現"
    assert words["학교"].hanja == "学校"
    assert words["네"].meanings[0]["primary"] is True
    assert words["네"].origin == "固有語" and words["네"].status == "approved"  # 語種だけの食い違いは検算の案に直す
    assert words["커피"].status == "needs_review"
    assert words["커피"].raw["review"]["proposals"][1]["meaning"] == "コーヒー（飲み物）"
    assert words["커피"].confusables == (words["물"].id,)
    assert words["물"].status == "approved"

    by_ko = {s.ko: s for s in loaded.sentences}
    assert "우유 마셔요." not in by_ko and by_ko["물 마셔요."].status == "approved"
    assert by_ko["학교에 가요."].status == "approved"  # 1 回目は不合格、作り直して合格
    assert by_ko["물 주세요."].variants == {"ko": [], "ja": ["水を下さい。"]}  # 文の検算と許容例の検算で取り除いた許容例
    assert by_ko["물 주세요."].cloze[0]["variants"] == ["물을"]  # 1 つの語節だけ
    assert by_ko["물 주세요."].grammar == ("-(으)세요",)  # 検算が直した文法の表示
    assert by_ko["물 주세요."].word_ids == [words["물"].id, words["주다"].id]
    approved = content.load(tmp_path, "ko")
    assert "커피 마셔요." not in {s.ko for s in approved.sentences}  # 要確認の単語を含む文は出さない

    # 再実行しても AI は呼ばない
    before = len(ai.calls)
    supplement.run(ws, ai)
    tag_candidates.run(ws, ai)
    assign_levels.run_units(ws, ai, 1)
    gen_grammar.run(ws, ai, 1)
    enrich_words.run(ws, ai, 1)
    verify_words.run(ws, ai, 1)
    gen_sentences.run(ws, ai, ai, 1)
    gen_variants.run(ws, ai, ai, 1)
    assert len(ai.calls) == before
    assert (ws.dir / "report.md").read_text(encoding="utf-8").startswith("# 教材づくりの報告（L1）")

    # 機械の検算で要確認になった文は、検算を直したあとに --recheck で AI の検算に回せる
    path = gen_sentences.unit_path("L1-U02")
    state = ws.read(path)
    target = next(s for s in state["sentences"] if s["ko"] == "물 주세요.")
    target.update(status="needs_review", failures=2, checked=False, problems=["機械の誤検出"], failed_by="machine")
    state["status"] = "done"
    ws.write(path, state)
    assert "1 文" in gen_sentences.recheck(ws, 1)
    gen_sentences.run(ws, ai, ai, 1)
    assert next(s for s in ws.read(path)["sentences"] if s["ko"] == "물 주세요.")["status"] == "approved"
    assert ai.calls[-1] == "verify-sentences"

    # 人が決めた語（work/decisions.json）は、決めた意味で approved にする
    coffee = words["커피"].id
    ws.write(decisions.DECISIONS, {"words": {coffee: {"lemma": "커피", "meanings": [{"ja": "コーヒー", "primary": True}], "note": "テスト"}}})
    export.run(ws, 1)
    decided = {w.lemma: w for w in content.load(tmp_path, "ko", approved_only=False).words}["커피"]
    assert decided.status == "approved" and decided.meaning == "コーヒー" and "review" not in decided.raw
    ws.write(decisions.DECISIONS, {"words": {coffee: {"lemma": "물"}}})
    with pytest.raises(BuildError, match="見出しが違います"):
        export.run(ws, 1)
    ws.write(decisions.DECISIONS, {})

    # work/ で直した要確認の文は、reopen で機械の検算を通してから AI の検算に回す
    state = ws.read(path)
    target = next(s for s in state["sentences"] if s["ko"] == "물 주세요.")
    target.update(status="needs_review", failures=2, checked=False, problems=["AI の指摘"], failed_by="ai")
    ws.write(path, state)
    sid = f"ko-s-L1-U02-{target['slot']:03d}"
    assert "AI の検算に回します" in gen_sentences.reopen(ws, [sid], 1)
    gen_sentences.run(ws, ai, ai, 1)
    assert next(s for s in ws.read(path)["sentences"] if s["ko"] == "물 주세요.")["status"] == "approved"
    state = ws.read(path)
    broken = next(s for s in state["sentences"] if s["ko"] == "물 주세요.")
    broken["tokens"][0]["surface"] = "물을"
    ws.write(path, state)
    assert "機械の検算で落ちました" in gen_sentences.reopen(ws, [sid], 1)
    with pytest.raises(BuildError, match="id の形"):
        gen_sentences.reopen(ws, ["L1-U02"], 1)
