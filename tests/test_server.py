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
    for path in ("/", "/learn", "/words", "/settings"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert "<!doctype html>" in res.text.lower()
    assert client.get("/static/style.css").status_code == 200


def test_meta(client):
    data = client.get("/api/meta").json()
    assert data["api_version"] == API_VERSION
    assert data["languages"][0]["code"] == "ko"
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
    ok = client.post("/api/answer", json={"type": "sentence_cloze", "sentence_id": "t-s-U01-001", "answer": "물"}).json()
    assert ok["verdict"] == "correct"
    ng = client.post("/api/answer", json={"type": "sentence_dictation", "sentence_id": "t-s-U01-001", "answer": "물 조세요"}).json()
    assert ng["verdict"] == "incorrect"
    assert ng["diff"]
    variant = client.post("/api/answer", json={"type": "sentence_dictation", "sentence_id": "t-s-U01-001", "answer": "물 좀 주세요"}).json()
    assert variant["verdict"] == "correct"


def test_answer_spell(client):
    ok = client.post("/api/answer", json={"type": "word_spell", "word_id": "t-w-0003", "answer": "커피"}).json()
    assert ok["verdict"] == "correct"
    assert client.post("/api/answer", json={"type": "word_spell", "answer": "커피"}).status_code == 400


def test_answer_ja_to_ko_placeholder(client):
    data = client.post("/api/answer", json={"type": "sentence_ja_to_ko", "sentence_id": "t-s-U01-002", "answer": "커피가 없어요"}).json()
    assert data["verdict"] == "incorrect"
    assert data["source"] == "placeholder"


def test_answer_unknown_type(client):
    assert client.post("/api/answer", json={"type": "nope", "sentence_id": "t-s-U01-001", "answer": "x"}).status_code == 400


def test_words_and_detail(client):
    words = client.get("/api/words?language=ko&unit=T-U01").json()
    assert [w["lemma"] for w in words] == ["물", "빵", "커피", "우유", "차"]
    assert client.get("/api/words?language=ko&q=コーヒー").json()[0]["id"] == "t-w-0003"
    detail = client.get("/api/words/t-w-0005?language=ko").json()
    assert detail["homograph_words"][0]["id"] == "t-w-0006"
    assert client.get("/api/words/nope").status_code == 404


def test_settings_roundtrip(client):
    data = client.get("/api/settings").json()
    assert data["new_words_per_day"] == 15
    updated = client.put("/api/settings", json={"new_words_per_day": 20, "keyboard_show_latin": False}).json()
    assert updated["new_words_per_day"] == 20
    assert updated["keyboard_show_latin"] is False
    assert client.get("/api/settings").json()["new_words_per_day"] == 20
    assert client.put("/api/settings", json={"unknown": 1}).status_code == 400
    assert client.put("/api/settings", json={"new_words_per_day": "many"}).status_code == 400


def test_job_not_found(client):
    assert client.get("/api/jobs/nope").status_code == 404
