from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobStore
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
    assert data["new_word_count"] == 5
    assert data["levels"][0]["total"] == 10
    assert [u["id"] for u in data["units"]] == ["T-U01", "T-U02"]


def test_today_unknown_language(client):
    assert client.get("/api/today?language=xx").status_code == 404


def test_session_start(client):
    res = client.post("/api/session/start", json={"language": "ko", "unit": "T-U02", "seed": 3})
    assert res.status_code == 200
    plan = res.json()
    assert plan["unit"]["id"] == "T-U02"
    assert plan["items"]
    assert client.post("/api/session/start", json={"language": "ko", "unit": "nope"}).status_code == 404


def test_answer_cloze_and_dictation(client):
    ok = client.post("/api/answer", json={"language": "ko", "type": "sentence_cloze", "sentence_id": "t-s-U01-001", "answer": "물"}).json()
    assert ok["verdict"] == "correct"
    ng = client.post("/api/answer", json={"language": "ko", "type": "sentence_dictation", "sentence_id": "t-s-U01-001", "answer": "물 조세요"}).json()
    assert ng["verdict"] == "incorrect"
    assert ng["diff"]
    variant = client.post("/api/answer", json={"language": "ko", "type": "sentence_dictation", "sentence_id": "t-s-U01-001", "answer": "물 좀 주세요"}).json()
    assert variant["verdict"] == "correct"


def test_answer_spell(client):
    ok = client.post("/api/answer", json={"language": "ko", "type": "word_spell", "word_id": "t-w-0003", "answer": "커피"}).json()
    assert ok["verdict"] == "correct"
    assert client.post("/api/answer", json={"language": "ko", "type": "word_spell", "answer": "커피"}).status_code == 400


def test_answer_ja_to_ko_placeholder(client):
    data = client.post("/api/answer", json={"language": "ko", "type": "sentence_ja_to_ko", "sentence_id": "t-s-U01-002", "answer": "커피가 없어요"}).json()
    assert data["verdict"] == "incorrect"
    assert data["source"] == "placeholder"


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
