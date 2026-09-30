"""Knowledge: FAQ ingest + retrieve (descriptive content only).

SQLite FTS5 backend (stdlib, no deps). Prices NEVER come from embeddings
or from here — only verbatim from live PMS offers (price_quote_id guard
in booking adapters). cite-or-handoff: answer from retrieved policy text
with citation, else hand off to a human.
All queries parameterized — no string-interpolated SQL anywhere.
"""

from __future__ import annotations

import sqlite3
import threading

_LOCK = threading.RLock()


def open_db(path: str = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(path, check_same_thread=False)
    with _LOCK:
        db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS faq USING fts5"
            "(doc_id UNINDEXED, title, text, lang UNINDEXED)"
        )
        db.commit()
    return db


def ingest(db: sqlite3.Connection, documents: list[dict]) -> int:
    """Store FAQ/policy docs [{doc_id, title, text, lang}]. Returns count."""
    rows = []
    for document in documents:
        if (
            not isinstance(document, dict)
            or not document.get("doc_id")
            or not document.get("text")
        ):
            raise ValueError("knowledge: doc needs doc_id and text")
        rows.append(
            (
                document["doc_id"],
                document.get("title", ""),
                document["text"],
                document.get("lang", "et"),
            )
        )
    with _LOCK:
        db.executemany(
            "INSERT INTO faq (doc_id, title, text, lang) VALUES (?, ?, ?, ?)", rows
        )
        db.commit()
    return len(rows)


def retrieve(
    db: sqlite3.Connection, query: str, lang: str = "et", top_k: int = 3
) -> list[dict]:
    """BM25-ranked passages for query, filtered to lang. Cited or handoff.

    Token-prefix OR query (each token quoted, `*`-suffixed) so Estonian
    inflections match without stemming ("spa" finds "Spaa", "saab" finds
    "saabumist"); operator characters can't break MATCH syntax and
    anything still invalid returns [] instead of raising.
    """
    if not isinstance(query, str) or not query.strip():
        return []
    query = query[:500]
    if isinstance(top_k, bool):
        limit = 3
    else:
        try:
            limit = max(1, min(int(top_k), 20))
        except (TypeError, ValueError):
            limit = 3
    phrase = " OR ".join(
        f'"{token.replace(chr(34), chr(34) * 2)}"*'
        for token in query.split()
        if token.strip()
    )
    if not phrase:
        return []
    try:
        with _LOCK:
            cursor = db.execute(
                "SELECT doc_id, title, text FROM faq "
                "WHERE faq MATCH ? AND lang = ? "
                "ORDER BY bm25(faq) LIMIT ?",
                (phrase, lang, limit),
            )
            rows = cursor.fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"doc_id": row[0], "title": row[1], "text": row[2]} for row in rows]
