from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobStore
from app.records import Records
from app.server import API_VERSION, create_app


@pytest.fixture
def client(root):
    app = create_app(root, jobs=JobStore(inline=True))
    with TestClient(app) as c:
        yield c


def test_pages_and_static(client):
    pages = {"/": "portal", "/settings": "settings", "/ko": "language", "/ko/learn": "language", "/ko/words": "language"}
    for path, scope in pages.items():
        res = client.get(path)
        assert res.status_code == 200, path
        assert f'data-scope="{scope}"' in res.text, path
    assert client.get("/static/style.css").status_code == 200


def test_unknown_language_and_page_are_404(client):
    assert client.get("/xx").status_code == 404
    assert client.get("/xx/learn").status_code == 404
    assert client.get("/ko/nope").status_code == 404


def test_old_urls_redirect_to_first_language(client):
    res = client.get("/learn?unit=T-U02", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/ko/learn?unit=T-U02"
    assert client.get("/words", follow_redirects=False).headers["location"] == "/ko/words"


def test_portal(client, root):
    cards = client.get("/api/portal").json()
    assert [c["language"]["code"] for c in cards] == ["ko"]
    assert cards[0]["available"] is True
    assert cards[0]["unit"]["id"] == "T-U01"


def test_portal_language_without_content(client, root):
    import shutil

    shutil.rmtree(root / "content" / "ko")
    cards = client.get("/api/portal").json()
    assert cards[0]["available"] is False
    assert client.get("/api/today?language=ko").status_code == 404


def test_meta(client):
    data = client.get("/api/meta").json()
    assert data["api_version"] == API_VERSION
    assert data["languages"][0]["code"] == "ko"
    assert data["languages"][0]["tts_lang"] == "ko-KR"
    assert data["languages"][0]["native"] == "한국어"
    assert "助詞" in data["error_tags"]


def test_today(client):
    data = client.get("/api/today?language=ko").json()
    assert data["unit"]["id"] == "T-U01"
    assert data["new_word_count"] == 10  # 新出は 1 日 15 語まで。テストの教材は 10 語
    assert data["review_count"] == 0
    assert data["levels"][0]["total"] == 10
    assert [u["id"] for u in data["units"]] == ["T-U01", "T-U02"]
    assert data["units"][0]["started_count"] == 0


def test_review_is_recorded_and_changes_today(client):
    body = {"language": "ko", "kind": "word", "item_id": "t-w-0001", "face": "meaning", "practice": "word_meaning", "rating": "good", "correct": True, "elapsed_sec": 1.8, "answer": "t-w-0001"}
    res = client.post("/api/review", json=body).json()
    assert res["counted"] is True
    assert res["card"]["stability"] > 0
    assert client.post("/api/review", json=body).json()["counted"] is False  # 同じ日の 2 回目
    today = client.get("/api/today?language=ko").json()
    assert today["new_word_count"] == 9
    assert today["levels"][0]["learning"] == 1
    assert today["units"][0]["started_count"] == 1
    words = {w["id"]: w for w in client.get("/api/words?language=ko").json()}
    assert words["t-w-0001"]["state"] == "learning"
    assert "meaning" in words["t-w-0001"]["faces"]
    detail = client.get("/api/words/t-w-0001?language=ko").json()
    assert [h["counted"] for h in detail["history"]] == [False, True]


def test_sentence_review_is_recorded_with_stage(client):
    assert client.get("/api/today?language=ko").json()["new_sentence_count"] == 5
    body = {"language": "ko", "kind": "sentence", "item_id": "t-s-U01-001", "practice": "sentence_listen_choose", "rating": "good", "correct": True}
    res = client.post("/api/review", json=body).json()
    assert res["counted"] is True
    assert res["card"]["stage"] == 2
    assert client.get("/api/today?language=ko").json()["new_sentence_count"] == 4


def test_review_rejects_bad_input(client):
    body = {"language": "ko", "kind": "word", "item_id": "t-w-0001", "face": "meaning", "practice": "word_meaning", "rating": "good", "correct": True}
    assert client.post("/api/review", json={**body, "face": "nope"}).status_code == 400
    assert client.post("/api/review", json={**body, "rating": "great"}).status_code == 400
    assert client.post("/api/review", json={**body, "item_id": "nope"}).status_code == 404
    assert client.post("/api/review", json={**body, "kind": "nope"}).status_code == 400
    sentence = {**body, "kind": "sentence", "item_id": "t-s-U01-001"}
    assert client.post("/api/review", json=sentence).status_code == 400  # 文に面はない
    assert client.post("/api/review", json={**sentence, "face": "", "item_id": "nope"}).status_code == 404


def test_today_unknown_language(client):
    assert client.get("/api/today?language=xx").status_code == 404


def test_session_start(client):
    res = client.post("/api/session/start", json={"language": "ko", "unit": "T-U02", "seed": 3})
    assert res.status_code == 200
    plan = res.json()
    assert plan["unit"]["id"] == "T-U02"
    assert plan["items"]
    assert client.post("/api/session/start", json={"language": "ko", "unit": "nope"}).status_code == 404


AI_INCORRECT = {
    "verdict": "incorrect",
    "meaning_ok": False,
    "issues": [{"axis": "meaning", "tag": "語彙の選択", "span": "없어요", "note": "意味が逆です", "suggestion": "있어요", "word_id": None}],
    "corrected": "커피가 있어요.",
    "comment_ja": "있어요 と 없어요 で意味が逆なので不正解です。",
}


@pytest.fixture
def ai(root):
    """AI の代わり。呼ばれたプロンプトを calls に残し、result を返す。"""

    class FakeAI:
        result = AI_INCORRECT
        calls: list[str] = []

        def __call__(self, prompt, schema):
            self.calls.append(prompt)
            return self.result

    return FakeAI()


@pytest.fixture
def ai_client(root, ai):
    app = create_app(root, jobs=JobStore(inline=True), ask=ai)
    with TestClient(app) as c:
        yield c


def test_answer_machine(ai_client, ai):
    def post(**body):
        return ai_client.post("/api/answer", json={"language": "ko", **body}).json()

    assert post(type="sentence_cloze", sentence_id="t-s-U01-001", answer="물")["verdict"] == "correct"
    assert post(type="sentence_ja_to_ko", sentence_id="t-s-U01-001", answer="물 좀 주세요")["verdict"] == "correct"
    assert post(type="sentence_dictation", sentence_id="t-s-U01-002", answer="커피가 이써요")["source"] == "pronunciation"
    assert post(type="word_spell", word_id="t-w-0003", answer="커피")["verdict"] == "correct"
    assert not ai.calls


def test_dictation_ignores_variants(ai_client, ai):
    # 許容例は言い方の違いなので、読み上げと違う言い方は書き取りでは正解にしない
    res = ai_client.post("/api/answer", json={"language": "ko", "type": "sentence_dictation", "sentence_id": "t-s-U01-001", "answer": "물 좀 주세요"}).json()
    assert "job" in res
    assert "- 許容例" not in ai.calls[0]


def test_cloze_uses_its_own_variants(root, ai):
    import json

    path = root / "content" / "ko" / "sentences" / "T-U01.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[1]["cloze"][0]["variants"] = ["커피는"]
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    app = create_app(root, jobs=JobStore(inline=True), ask=ai)
    with TestClient(app) as c:
        res = c.post("/api/answer", json={"language": "ko", "type": "sentence_cloze", "sentence_id": "t-s-U01-002", "answer": "커피는"}).json()
    assert res["source"] == "variant"


def test_cloze_variants_come_from_sentence_variants():
    from app import langs
    from app.server import _cloze_variants

    pack = langs.get("ko")
    variants = ("미안해요. 괜찮아요?", "미안합니다. 괜찮으세요?", "정말 미안해요. 괜찮아요?")
    # 空欄の語節だけが違う許容例だけを使う
    assert _cloze_variants(pack, "미안합니다. 괜찮아요?", 0, variants) == ("미안해요",)


def test_answer_goes_to_ai_and_is_saved(ai_client, ai, root):
    body = {"language": "ko", "type": "sentence_dictation", "sentence_id": "t-s-U01-002", "answer": "커피가 없어요"}
    first = ai_client.post("/api/answer", json=body).json()
    job = first["job"]
    assert job["status"] == "done"
    assert job["result"]["verdict"] == "incorrect"
    assert job["result"]["comment_ja"].startswith("있어요")
    assert job["result"]["diff"]
    assert "読み上げた文（模範解答）: 커피가 있어요." in ai.calls[0]
    assert Records(root).graded("ko", "sentence_dictation", "t-s-U01-002", "커피가 없어요") is not None

    again = ai_client.post("/api/answer", json={**body, "answer": "커피가  없어요."}).json()
    assert again["source"] == "cache"
    assert again["verdict"] == "incorrect"
    assert len(ai.calls) == 1


def test_saved_judgement_is_ignored_when_sentence_changes(ai_client, ai, root):
    import json

    body = {"language": "ko", "type": "sentence_ja_to_ko", "sentence_id": "t-s-U01-002", "answer": "커피가 없어요"}
    ai_client.post("/api/answer", json=body)
    path = root / "content" / "ko" / "sentences" / "T-U01.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[1]["ko"] = "커피가 있어요!"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    assert "job" in ai_client.post("/api/answer", json=body).json()
    assert len(ai.calls) == 2


def test_answer_cloze_prompt_shows_blank(ai_client, ai):
    ai_client.post("/api/answer", json={"language": "ko", "type": "sentence_cloze", "sentence_id": "t-s-U02-001", "answer": "먹어"})
    assert "빵을 ＿＿＿." in ai.calls[0]
    assert "t-w-0007: 먹다（食べる）" in ai.calls[0]


def test_answer_ai_failure_is_job_error(root):
    from app.claude_cli import ClaudeError

    def broken(prompt, schema):
        raise ClaudeError("Claude の利用枠の上限に達しました")

    app = create_app(root, jobs=JobStore(inline=True), ask=broken)
    with TestClient(app) as c:
        job = c.post("/api/answer", json={"language": "ko", "type": "word_spell", "word_id": "t-w-0003", "answer": "코피"}).json()["job"]
    assert job["status"] == "error"
    assert "利用枠" in job["error"]
    assert Records(root).graded("ko", "word_spell", "t-w-0003", "코피") is None


def test_answer_requires_ids_and_text(client):
    assert client.post("/api/answer", json={"language": "ko", "type": "word_spell", "answer": "커피"}).status_code == 400
    assert client.post("/api/answer", json={"language": "ko", "type": "word_spell", "word_id": "t-w-0003", "answer": " . "}).status_code == 400


def test_answer_unknown_type(client):
    assert client.post("/api/answer", json={"language": "ko", "type": "nope", "sentence_id": "t-s-U01-001", "answer": "x"}).status_code == 400


def test_words_and_detail(client):
    words = client.get("/api/words?language=ko&unit=T-U01").json()
    assert [w["lemma"] for w in words] == ["물", "빵", "커피", "우유", "차"]
    assert client.get("/api/words?language=ko&q=コーヒー").json()[0]["id"] == "t-w-0003"
    detail = client.get("/api/words/t-w-0005?language=ko").json()
    assert detail["homograph_words"][0]["id"] == "t-w-0006"
    assert client.get("/api/words/nope?language=ko").status_code == 404
    assert client.get("/api/words?unit=T-U01").status_code == 422


def test_settings_roundtrip(client):
    data = client.get("/api/settings/ko").json()
    assert data["new_words_per_day"] == 15
    updated = client.put("/api/settings/ko", json={"new_words_per_day": 20, "keyboard_show_latin": False}).json()
    assert updated["new_words_per_day"] == 20
    assert updated["keyboard_show_latin"] is False
    assert client.get("/api/settings/ko").json()["new_words_per_day"] == 20
    assert client.put("/api/settings/ko", json={"unknown": 1}).status_code == 400
    assert client.put("/api/settings/ko", json={"new_words_per_day": "many"}).status_code == 400
    assert client.get("/api/settings/xx").status_code == 404


def test_settings_affect_language_today(client):
    client.put("/api/settings/ko", json={"new_words_per_day": 2})
    assert client.get("/api/today?language=ko").json()["new_word_count"] == 2


def test_job_not_found(client):
    assert client.get("/api/jobs/nope").status_code == 404


# ---- 韓→日訳 ----


def test_ko_to_ja_matches_translations_ignoring_marks(ai_client, ai):
    def post(answer):
        return ai_client.post("/api/answer", json={"language": "ko", "type": "sentence_ko_to_ja", "sentence_id": "t-s-U01-001", "answer": answer}).json()

    assert post("お水ください")["source"] == "exact"
    assert post("「水を ください！」")["source"] == "variant"  # 記号・空白・全角半角は比べない
    assert not ai.calls


def test_ko_to_ja_goes_to_ai_with_translation_rules(ai_client, ai):
    ai.result = {"verdict": "correct", "meaning_ok": True, "issues": [], "corrected": "水ちょうだい", "comment_ja": "意味は合っています。"}
    res = ai_client.post("/api/answer", json={"language": "ko", "type": "sentence_ko_to_ja", "sentence_id": "t-s-U01-001", "answer": "水ちょうだい"}).json()
    assert res["job"]["result"]["verdict"] == "correct"
    prompt = ai.calls[0]
    assert "韓国語の文: 물 주세요." in prompt and "模範訳: お水ください。" in prompt
    assert "です／ます体かどうかは問いません" in prompt
    assert "받침" not in prompt  # 韓国語の答えの条件は入れない


def test_korean_grade_prompt_keeps_korean_rules(ai_client, ai):
    ai_client.post("/api/answer", json={"language": "ko", "type": "sentence_ja_to_ko", "sentence_id": "t-s-U01-002", "answer": "커피가 없어요"})
    assert "띄어쓰기の誤り" in ai.calls[0]
    assert "模範訳" not in ai.calls[0]


# ---- 解説 ----

EXPLANATION = {
    "summary": "カフェで水を頼む文です。",
    "parts": [{"surface": "물", "breakdown": "물（水）"}, {"surface": "", "breakdown": "空"}],
    "grammar": [{"form": "-(으)세요", "explanation": "丁寧に頼む言い方です。"}],
    "register": "해요체で、店員に丁寧に頼んでいます。",
    "pronunciation": "",
    "tips": ["  ", "좀 を入れるとやわらかくなります。"],
}


def test_explain_is_made_once_and_reused(ai_client, ai, root):
    import json

    ai.result = EXPLANATION
    first = ai_client.post("/api/explain/t-s-U01-001", json={"language": "ko"}).json()
    result = first["job"]["result"]
    assert result["parts"] == [{"surface": "물", "breakdown": "물（水）"}]  # 空の項目は除く
    assert result["tips"] == ["좀 を入れるとやわらかくなります。"]
    assert "韓国語: 물 주세요." in ai.calls[0]
    assert "- -(으)세요" in ai.calls[0]  # 文法リストにない文法は、文の表示のまま渡す
    again = ai_client.post("/api/explain/t-s-U01-001", json={"language": "ko"}).json()
    assert again["explanation"] == result
    assert len(ai.calls) == 1
    # 文が変わったら作り直す
    path = root / "content" / "ko" / "sentences" / "T-U01.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    items[0]["ja"] = "水をください。"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    assert "job" in ai_client.post("/api/explain/t-s-U01-001", json={"language": "ko"}).json()
    assert len(ai.calls) == 2


def test_explain_unknown_sentence(client):
    assert client.post("/api/explain/nope", json={"language": "ko"}).status_code == 404


# ---- 記録の中身 ----


def test_review_keeps_judgement_detail(client, root):
    import sqlite3

    detail = {"verdict": "incorrect", "source": "ai", "issues": [{"tag": "助詞", "axis": "grammar", "word_id": None}]}
    body = {"language": "ko", "kind": "sentence", "item_id": "t-s-U01-002", "practice": "sentence_ja_to_ko", "rating": "again", "correct": False, "answer": "커피를 있어요", "detail": detail}
    assert client.post("/api/review", json=body).status_code == 200
    with sqlite3.connect(root / "records" / "langlang.db") as conn:
        saved = conn.execute("SELECT detail FROM reviews WHERE item_id = 't-s-U01-002'").fetchone()[0]
    assert "助詞" in saved


def test_trace_is_recorded(client, root):
    from datetime import datetime, timedelta

    res = client.post("/api/trace", json={"language": "ko", "sentence_id": "t-s-U01-001", "seconds": 6.0, "units": 30})
    assert res.json() == {"per_min": 300}
    assert Records(root).trace_speed("ko", datetime.now().astimezone() - timedelta(days=1)) == 300
    assert client.post("/api/trace", json={"language": "ko", "sentence_id": "t-s-U01-001", "seconds": 0, "units": 30}).status_code == 400
    assert client.post("/api/trace", json={"language": "ko", "sentence_id": "nope", "seconds": 1, "units": 3}).status_code == 404
