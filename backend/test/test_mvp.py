"""Тесты MVP:  cd backend && python -m pytest -q"""
import os
import tempfile

os.environ["BENSHU_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import llm, storage
from app.core.dictionary import get_dictionary
from app.core.rankers import rank
from app.core.segment import segment
from app.main import app

D = get_dictionary()


def test_segment_splits_polysemous_words():
    toks = [t["t"] for s in segment("我想买一本书，花了三十块钱。") for t in s["tokens"]]
    assert "本" in toks and "书" in toks and "块" in toks and "三十" in toks


@pytest.mark.parametrize("sentence,word,gold", [
    ("我想买一本书。", "想", "想#2"),
    ("花了三十块钱。", "花", "花#2"),
    ("我们打算给他开一个晚会。", "开", "开#3"),
    ("他也会打篮球。", "打", "打#2"),
])
def test_context_ranker(sentence, word, gold):
    assert rank(sentence, word, D.get(word), "context").ranked[0].id == gold


def test_first_sense_is_dictionary_order():
    r = rank("花了三十块钱。", "花", D.get("花"), "first_sense")
    assert r.ranked[0].id == "花#1"


def test_llm_ranker_uses_only_dictionary_candidates(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")

    def fake_post(url, json, headers, timeout):
        assert "花" in json["messages"][1]["content"]
        content = '{"best": 1, "second": null, "confidence": 0.9, "explanation": "есть 钱"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    r = rank("花了三十块钱。", "花", D.get("花"), "llm")
    assert r.method == "llm" and r.ranked[0].id == "花#2" and r.confidence == 0.9


def test_llm_fallback_on_bad_answer(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_MODEL", "m")
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: httpx.Response(
        200, json={"choices": [{"message": {"content": '{"best": 7}'}}]}, request=httpx.Request("POST", "x")))
    r = rank("花了三十块钱。", "花", D.get("花"), "llm")
    assert r.method == "context" and r.fallback_reason


def test_api_flow_and_leitner():
    with TestClient(app) as c:
        h = {"X-User-Id": "pytest-user"}
        assert c.post("/api/session", json={"preferred_group": "benshu", "force": True}, headers=h).json()["group"] == "benshu"
        r = c.post("/api/rank", json={"sentence": "花了三十块钱。", "word": "花"}, headers=h).json()
        assert r["top"][0]["id"] == "花#2"
        card = c.post("/api/cards", json={"word": "花", "sense_id": "花#2", "gloss": "тратить", "ms_since_select": 3000}, headers=h).json()
        assert card["created"]
        assert not c.post("/api/cards", json={"word": "花", "sense_id": "花#2", "gloss": "тратить"}, headers=h).json()["created"]
        cid = card["card"]["id"]
        assert len(c.get("/api/review", headers=h).json()) == 1
        assert c.post(f"/api/review/{cid}", json={"remembered": True}, headers=h).json()["box"] == 2
        assert c.get("/api/review", headers=h).json() == []
        assert c.post(f"/api/review/{cid}", json={"remembered": False}, headers=h).json()["box"] == 1
        assert c.post("/api/events", json={"event": "hack"}, headers=h).status_code == 400
        assert c.post("/api/cards", json={"word": "x", "sense_id": "x", "gloss": "x"}).status_code == 400
        st = c.get("/api/stats").json()["groups"]["benshu"]
        assert st["card_saved"] == 1 and st["median_time_to_card_s"] == 3.0
