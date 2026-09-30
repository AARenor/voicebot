"""Knowledge: FAQ ingest + retrieve (descriptive content only).

Prices NEVER come from embeddings — only verbatim from live PMS offers
(price_quote_id guard enforced in booking adapters). cite-or-handoff:
answer from retrieved policy text with citation, else hand off to human.
Backend: Postgres + pgvector now (SQLite FTS fallback for $0 demo).
"""

from __future__ import annotations


def ingest(documents: list[dict]) -> int:
    """Store FAQ/policy docs. Returns count. Wired in Phase 1."""
    raise NotImplementedError


def retrieve(query: str, top_k: int = 3) -> list[dict]:
    """Return cited passages for query. Wired in Phase 1."""
    raise NotImplementedError
