"""Локальный индекс: только ссылки и заголовки разделов (тексты руководств здесь не хранятся)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import DocRef

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    source TEXT NOT NULL, title TEXT NOT NULL, page_url TEXT NOT NULL, anchor TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'other', engine_codes TEXT NOT NULL DEFAULT '', models TEXT NOT NULL DEFAULT '',
    UNIQUE (source, page_url, anchor)
);
CREATE TABLE IF NOT EXISTS nav (
    source TEXT NOT NULL, label TEXT NOT NULL, url TEXT NOT NULL, UNIQUE (source, url, label)
);
CREATE TABLE IF NOT EXISTS pages (
    source TEXT NOT NULL, url TEXT NOT NULL, fetched REAL NOT NULL, UNIQUE (source, url)
);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        old = self.db.execute("SELECT sql FROM sqlite_master WHERE name='nav'").fetchone()
        if old and "UNIQUE (source, url)" in old[0]:
            # старая схема хранила одну подпись на адрес: «Golf Plus» затирал «Golf 6». Список моделей
            # восстанавливается с главной страницы сайта при следующем поиске или обновлении индекса.
            with self.db:
                self.db.execute("DROP TABLE nav")
        self.db.executescript(_SCHEMA)

    def close(self) -> None:
        self.db.close()

    def upsert_docs(self, docs: list[DocRef]) -> None:
        with self.db:
            for d in docs:
                self.db.execute(
                    "INSERT INTO docs(source,title,page_url,anchor,kind,engine_codes,models) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT(source,page_url,anchor) DO UPDATE SET title=excluded.title, kind=excluded.kind, "
                    "engine_codes=excluded.engine_codes, models=excluded.models",
                    (d.source, d.title, d.page_url, d.anchor, d.kind,
                     ",".join(d.engine_codes), " | ".join(d.models)),
                )

    def docs(self, source: str) -> list[DocRef]:
        rows = self.db.execute(
            "SELECT source,title,page_url,anchor,kind,engine_codes,models FROM docs WHERE source=?", (source,)
        ).fetchall()
        return [DocRef(r[0], r[1], r[2], r[3], r[4],
                       tuple(c for c in r[5].split(",") if c),
                       tuple(m for m in r[6].split(" | ") if m)) for r in rows]

    def upsert_nav(self, source: str, items: list[tuple[str, str]]) -> None:
        with self.db:
            for label, url in items:
                self.db.execute("INSERT OR IGNORE INTO nav(source,label,url) VALUES (?,?,?)", (source, label, url))

    def nav(self, source: str) -> list[tuple[str, str]]:
        return self.db.execute("SELECT label,url FROM nav WHERE source=?", (source,)).fetchall()

    def counts(self, source: str) -> tuple[int, int]:
        d = self.db.execute("SELECT COUNT(*) FROM docs WHERE source=?", (source,)).fetchone()[0]
        n = self.db.execute("SELECT COUNT(DISTINCT url) FROM nav WHERE source=?", (source,)).fetchone()[0]
        return d, n

    def mark_page(self, source: str, url: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO pages(source,url,fetched) VALUES (?,?,?) "
                "ON CONFLICT(source,url) DO UPDATE SET fetched=excluded.fetched", (source, url, time.time()))

    def fresh_pages(self, source: str, max_age_days: float = 30) -> set[str]:
        """Страницы, разделы которых уже занесены в индекс не позже max_age_days назад."""
        limit = time.time() - max_age_days * 86400
        rows = self.db.execute("SELECT url FROM pages WHERE source=? AND fetched>=?", (source, limit)).fetchall()
        return {r[0] for r in rows}
