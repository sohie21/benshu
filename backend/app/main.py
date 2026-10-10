"""Benshu MVP — API (FastAPI).

Запуск локально:  uvicorn app.main:app --reload --port 8000  (из папки backend)
Документация API: http://localhost:8000/docs
"""
from __future__ import annotations

import json
import os
import random
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import llm, storage
from .core.dictionary import DATA_DIR, get_dictionary
from .core.rankers import rank
from .core.segment import segment

DEFAULT_METHOD = os.getenv("BENSHU_METHOD", "llm")  # llm → без ключа автоматически context
MAX_TEXT = 3000

@asynccontextmanager
async def lifespan(_app: FastAPI):
    storage.init_db()
    get_dictionary()
    segment("你好。")  # прогрев jieba
    yield


app = FastAPI(title="Benshu MVP API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _uid(x_user_id: str | None) -> str:
    if not x_user_id or len(x_user_id) > 64:
        raise HTTPException(400, "Нужен заголовок X-User-Id")
    return x_user_id


# ---------- схемы ----------
class SessionIn(BaseModel):
    preferred_group: str | None = Field(None, description="Только для демо: control | benshu")
    force: bool = False


class SegmentIn(BaseModel):
    text: str = Field(..., max_length=MAX_TEXT)


class RankIn(BaseModel):
    sentence: str = Field(..., max_length=500)
    word: str = Field(..., max_length=20)
    method: str | None = None


class CardIn(BaseModel):
    word: str
    pinyin: str | None = None
    sense_id: str
    gloss: str
    sentence: str | None = None
    explanation: str | None = None
    method: str | None = None
    ms_since_select: float | None = None


class ReviewIn(BaseModel):
    remembered: bool


class EventIn(BaseModel):
    event: str = Field(..., max_length=40)
    payload: dict = Field(default_factory=dict)


# ---------- эндпоинты ----------
@app.get("/api/health")
def health() -> dict:
    d = get_dictionary()
    return {
        "status": "ok",
        "words": len(d.entries),
        "cedict": d.cedict_loaded,
        "llm_configured": llm.is_configured(),
        "default_method": DEFAULT_METHOD,
    }


@app.post("/api/session")
def session(body: SessionIn, x_user_id: str | None = Header(None)) -> dict:
    """Регистрирует анонимного пользователя и закрепляет A/B-группу (50/50)."""
    uid = _uid(x_user_id)
    wanted = body.preferred_group if body.preferred_group in ("control", "benshu") else None
    allow_force = os.getenv("BENSHU_DEMO_SWITCH", "1") == "1"
    grp = storage.ensure_user(uid, wanted or random.choice(["control", "benshu"]),
                              force=bool(wanted and body.force and allow_force))
    return {"user_id": uid, "group": grp}


@app.get("/api/texts")
def texts() -> list[dict]:
    return json.loads((DATA_DIR / "sample_texts.json").read_text(encoding="utf-8"))


@app.post("/api/segment")
def do_segment(body: SegmentIn) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "Пустой текст")
    return {"sentences": segment(body.text)}


@app.post("/api/rank")
def do_rank(body: RankIn, x_user_id: str | None = Header(None)) -> dict:
    d = get_dictionary()
    entry = d.get(body.word)
    if entry is None:
        return {"word": body.word, "found": False, "senses": [], "top": []}
    method = body.method or DEFAULT_METHOD
    res = rank(body.sentence, body.word, entry, method=method)
    senses = [
        {**s.to_dict(), "pinyin": s.pinyin or entry.pinyin, "score": sc}
        for s, sc in zip(res.ranked, res.scores)
    ]
    # Показываем 1 значение, второе — только если модель не уверена
    top_n = 1 if res.confidence >= 0.75 or len(senses) == 1 else 2
    out = {
        "word": entry.word,
        "found": True,
        "pinyin": senses[0]["pinyin"],
        "source": entry.source,
        "method": res.method,
        "fallback_reason": res.fallback_reason,
        "confidence": res.confidence,
        "low_confidence": res.low_confidence,
        "explanation": res.explanation,
        "evidence": res.evidence,
        "latency_ms": res.latency_ms,
        "top": senses[:top_n],
        "senses": senses,
        "dictionary_order": [{**s.to_dict(), "pinyin": s.pinyin or entry.pinyin} for s in entry.senses],
    }
    if x_user_id:
        storage.log_event(x_user_id, "meaning_shown", {
            "word": entry.word, "method": res.method, "confidence": res.confidence,
            "latency_ms": res.latency_ms, "top_sense": senses[0]["id"], "n_senses": len(senses),
        })
    return out


@app.get("/api/cards")
def get_cards(x_user_id: str | None = Header(None)) -> list[dict]:
    return storage.list_cards(_uid(x_user_id))


@app.post("/api/cards")
def post_card(body: CardIn, x_user_id: str | None = Header(None)) -> dict:
    uid = _uid(x_user_id)
    card, created = storage.add_card(uid, body.model_dump())
    if created:
        storage.log_event(uid, "card_saved", {
            "word": body.word, "sense_id": body.sense_id, "method": body.method,
            "ms_since_select": body.ms_since_select,
        })
    return {"card": card, "created": created}


@app.delete("/api/cards/{card_id}")
def del_card(card_id: int, x_user_id: str | None = Header(None)) -> dict:
    if not storage.delete_card(_uid(x_user_id), card_id):
        raise HTTPException(404, "Карточка не найдена")
    return {"deleted": card_id}


@app.get("/api/review")
def get_review(x_user_id: str | None = Header(None)) -> list[dict]:
    return storage.due_cards(_uid(x_user_id))


@app.post("/api/review/{card_id}")
def post_review(card_id: int, body: ReviewIn, x_user_id: str | None = Header(None)) -> dict:
    uid = _uid(x_user_id)
    card = storage.review_card(uid, card_id, body.remembered)
    if card is None:
        raise HTTPException(404, "Карточка не найдена")
    storage.log_event(uid, "card_reviewed", {"card_id": card_id, "remembered": body.remembered, "box": card["box"]})
    return card


ALLOWED_EVENTS = {"text_opened", "word_selected", "feedback", "show_all_senses", "review_started", "page_view"}


@app.post("/api/events")
def post_event(body: EventIn, x_user_id: str | None = Header(None)) -> dict:
    uid = _uid(x_user_id)
    if body.event not in ALLOWED_EVENTS:
        raise HTTPException(400, f"Неизвестное событие: {body.event}")
    storage.log_event(uid, body.event, body.payload)
    return {"ok": True}


@app.get("/api/stats")
def get_stats() -> dict:
    return storage.stats()


# ---------- фронтенд (если бэкенд запущен без nginx) ----------
FRONTEND_DIR = os.getenv("FRONTEND_DIR")
if FRONTEND_DIR and os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
