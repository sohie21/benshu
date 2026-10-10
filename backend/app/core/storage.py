"""SQLite-хранилище: пользователи (анонимные), карточки (Лейтнер), события."""
from __future__ import annotations

import json
import os
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(os.getenv("BENSHU_DB", Path(__file__).resolve().parents[2] / "data" / "benshu.db"))

# Интервалы повторения по коробкам Лейтнера (в днях)
LEITNER_DAYS = {1: 1, 2: 2, 3: 4, 4: 8, 5: 16}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    grp TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    word TEXT NOT NULL,
    pinyin TEXT,
    sense_id TEXT NOT NULL,
    gloss TEXT NOT NULL,
    sentence TEXT,
    explanation TEXT,
    method TEXT,
    box INTEGER NOT NULL DEFAULT 1,
    due_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviews INTEGER NOT NULL DEFAULT 0,
    lapses INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, word, sense_id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    grp TEXT,
    event TEXT NOT NULL,
    payload TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_user ON events(user_id, event);
CREATE INDEX IF NOT EXISTS ix_cards_due ON cards(user_id, due_at);
"""


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


@contextmanager
def conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA)


# ---------- пользователи ----------
def ensure_user(user_id: str, grp: str, force: bool = False) -> str:
    """Регистрирует анонимного пользователя; группа A/B фиксируется при первом визите.
    force=True — только для демо-переключателя (в реальном эксперименте не использовать)."""
    with conn() as c:
        row = c.execute("SELECT grp FROM users WHERE id=?", (user_id,)).fetchone()
        if row and force and row["grp"] != grp:
            c.execute("UPDATE users SET grp=? WHERE id=?", (grp, user_id))
            return grp
        if row:
            return row["grp"]
        c.execute("INSERT INTO users(id, grp, first_seen) VALUES (?,?,?)", (user_id, grp, iso(now())))
        return grp


def user_group(user_id: str) -> str | None:
    with conn() as c:
        row = c.execute("SELECT grp FROM users WHERE id=?", (user_id,)).fetchone()
        return row["grp"] if row else None


# ---------- события ----------
def log_event(user_id: str, event: str, payload: dict | None = None, grp: str | None = None) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO events(user_id, grp, event, payload, ts) VALUES (?,?,?,?,?)",
            (user_id, grp or user_group(user_id), event, json.dumps(payload or {}, ensure_ascii=False), iso(now())),
        )


# ---------- карточки ----------
def _card(row: sqlite3.Row) -> dict:
    return dict(row)


def add_card(user_id: str, data: dict) -> tuple[dict, bool]:
    with conn() as c:
        existing = c.execute(
            "SELECT * FROM cards WHERE user_id=? AND word=? AND sense_id=?",
            (user_id, data["word"], data["sense_id"]),
        ).fetchone()
        if existing:
            return _card(existing), False
        t = iso(now())
        cur = c.execute(
            """INSERT INTO cards(user_id, word, pinyin, sense_id, gloss, sentence, explanation, method,
                                 box, due_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?,?)""",
            (user_id, data["word"], data.get("pinyin"), data["sense_id"], data["gloss"],
             data.get("sentence"), data.get("explanation"), data.get("method"), t, t),
        )
        row = c.execute("SELECT * FROM cards WHERE id=?", (cur.lastrowid,)).fetchone()
        return _card(row), True


def list_cards(user_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at DESC, id DESC", (user_id,)).fetchall()
        return [_card(r) for r in rows]


def delete_card(user_id: str, card_id: int) -> bool:
    with conn() as c:
        cur = c.execute("DELETE FROM cards WHERE id=? AND user_id=?", (card_id, user_id))
        return cur.rowcount > 0


def due_cards(user_id: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM cards WHERE user_id=? AND due_at<=? ORDER BY box, due_at",
            (user_id, iso(now())),
        ).fetchall()
        return [_card(r) for r in rows]


def review_card(user_id: str, card_id: int, remembered: bool) -> dict | None:
    with conn() as c:
        row = c.execute("SELECT * FROM cards WHERE id=? AND user_id=?", (card_id, user_id)).fetchone()
        if not row:
            return None
        if remembered:
            box = min(5, row["box"] + 1)
            due = now() + timedelta(days=LEITNER_DAYS[box])
            lapses = row["lapses"]
        else:
            box = 1
            due = now() + timedelta(minutes=10)  # вернётся в этой же сессии
            lapses = row["lapses"] + 1
        c.execute(
            "UPDATE cards SET box=?, due_at=?, reviews=reviews+1, lapses=? WHERE id=?",
            (box, iso(due), lapses, card_id),
        )
        return _card(c.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone())


# ---------- метрики для гипотез H2/H3 ----------
def stats() -> dict:
    with conn() as c:
        users = c.execute("SELECT id, grp, first_seen FROM users").fetchall()
        ev = c.execute("SELECT user_id, grp, event, payload, ts FROM events").fetchall()
        cards = c.execute("SELECT user_id, created_at FROM cards").fetchall()

    by_group: dict[str, dict] = {}
    for g in ("control", "benshu"):
        by_group[g] = {"users": 0, "word_selected": 0, "card_saved": 0, "feedback_ok": 0,
                       "feedback_wrong": 0, "time_to_card_ms": [], "activated_d7": 0}
    first_seen = {u["id"]: datetime.fromisoformat(u["first_seen"]) for u in users}
    grp_of = {u["id"]: u["grp"] for u in users}
    for u in users:
        if u["grp"] in by_group:
            by_group[u["grp"]]["users"] += 1

    texts_7d: dict[str, set] = {}
    for e in ev:
        g = by_group.get(e["grp"] or grp_of.get(e["user_id"], ""), None)
        if g is None:
            continue
        p = json.loads(e["payload"] or "{}")
        if e["event"] == "word_selected":
            g["word_selected"] += 1
        elif e["event"] == "card_saved":
            g["card_saved"] += 1
            if isinstance(p.get("ms_since_select"), (int, float)):
                g["time_to_card_ms"].append(p["ms_since_select"])
        elif e["event"] == "feedback":
            g["feedback_ok" if p.get("correct") else "feedback_wrong"] += 1
        elif e["event"] == "text_opened":
            fs = first_seen.get(e["user_id"])
            if fs and datetime.fromisoformat(e["ts"]) - fs <= timedelta(days=7):
                texts_7d.setdefault(e["user_id"], set()).add(p.get("text_id") or p.get("hash"))

    cards_7d: dict[str, int] = {}
    for cd in cards:
        fs = first_seen.get(cd["user_id"])
        if fs and datetime.fromisoformat(cd["created_at"]) - fs <= timedelta(days=7):
            cards_7d[cd["user_id"]] = cards_7d.get(cd["user_id"], 0) + 1

    # D7 activation: ≥3 текстов и ≥5 карточек за первые 7 дней
    for uid, g in grp_of.items():
        if g in by_group and len(texts_7d.get(uid, ())) >= 3 and cards_7d.get(uid, 0) >= 5:
            by_group[g]["activated_d7"] += 1

    out = {}
    for name, g in by_group.items():
        fb = g["feedback_ok"] + g["feedback_wrong"]
        ttc = g.pop("time_to_card_ms")
        out[name] = {
            **g,
            "save_rate": round(g["card_saved"] / g["word_selected"], 3) if g["word_selected"] else None,
            "feedback_accuracy": round(g["feedback_ok"] / fb, 3) if fb else None,
            "median_time_to_card_s": round(statistics.median(ttc) / 1000, 1) if ttc else None,
            "d7_activation": round(g["activated_d7"] / g["users"], 3) if g["users"] else None,
        }
    return {"groups": out, "total_users": len(users), "total_events": len(ev)}
