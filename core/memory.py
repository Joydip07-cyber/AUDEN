"""Long-term memory: durable facts plus rolling conversation history in SQLite."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable

from .config import DATA_DIR

DB_PATH = DATA_DIR / "auden.db"
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created REAL NOT NULL,
    hits INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_cat ON facts(category);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init() -> None:
    with _lock, _conn() as conn:
        conn.executescript(_SCHEMA)


init()

_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was",
    "my", "me", "i", "you", "your", "it", "that", "this", "with", "about", "what",
    "do", "does", "did", "how", "who", "when", "where", "can", "could", "would",
}


def _tokens(text: str) -> set[str]:
    return {t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1}


def remember(fact: str, category: str = "general") -> str:
    fact = (fact or "").strip()
    if not fact:
        return "Nothing to remember."
    with _lock, _conn() as conn:
        row = conn.execute("SELECT id FROM facts WHERE lower(fact)=lower(?)", (fact,)).fetchone()
        if row:
            conn.execute("UPDATE facts SET created=? WHERE id=?", (time.time(), row["id"]))
            return f"Already remembered: {fact}"
        conn.execute(
            "INSERT INTO facts(fact, category, created) VALUES(?,?,?)",
            (fact, category or "general", time.time()),
        )
    return f"Remembered: {fact}"


def search_facts(query: str, limit: int = 6) -> list[str]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM facts ORDER BY created DESC LIMIT 500").fetchall()
    if not rows:
        return []
    q = _tokens(query)
    now = time.time()
    scored = []
    for row in rows:
        text = row["fact"]
        overlap = len(q & _tokens(text)) if q else 0
        age_days = max(0.0, (now - (row["created"] or now)) / 86400)
        recency = 1.0 / (1.0 + age_days / 30.0)
        score = overlap * 2.0 + recency + min(row["hits"], 5) * 0.1
        if q and overlap == 0:
            score = 0.0
        scored.append((score, text, row["id"]))
    scored.sort(key=lambda x: -x[0])
    chosen = [s for s in scored if s[0] > 0][:limit]
    if not q:
        chosen = scored[:limit]
    ids = [c[2] for c in chosen]
    if ids:
        with _lock, _conn() as conn:
            conn.executemany("UPDATE facts SET hits=hits+1 WHERE id=?", [(i,) for i in ids])
    return [c[1] for c in chosen]


def all_facts() -> list[dict]:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT id, fact, category, created, hits FROM facts ORDER BY created DESC").fetchall()
    return [dict(r) for r in rows]


def forget(keyword: str) -> str:
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT id, fact FROM facts WHERE lower(fact) LIKE ?", (f"%{keyword.lower()}%",)).fetchall()
        if not rows:
            return f"I have no memory matching '{keyword}'."
        conn.executemany("DELETE FROM facts WHERE id=?", [(r["id"],) for r in rows])
    return f"Forgotten {len(rows)} item(s) matching '{keyword}'."


def add_message(role: str, content: str) -> None:
    if not content:
        return
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT INTO messages(role, content, created) VALUES(?,?,?)",
            (role, content, time.time()),
        )


def recent_messages(limit: int = 12) -> list[dict]:
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def clear_messages() -> None:
    with _lock, _conn() as conn:
        conn.execute("DELETE FROM messages")


def stats() -> dict:
    with _lock, _conn() as conn:
        facts = conn.execute("SELECT COUNT(*) c FROM facts").fetchone()["c"]
        msgs = conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
    return {"facts": facts, "messages": msgs, "db": str(DB_PATH)}


def seed_memory(facts: Iterable[str]) -> None:
    for fact in facts:
        remember(fact)
