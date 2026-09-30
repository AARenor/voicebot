"""Staff dashboard: holds queue + transcripts + confirm/cancel buttons.

FastAPI stub; full queue UI lands with Phase 2 phone step.
No-show SMS reminders (T-24h/T-3h) hook in here, daytime-only EE sends.
"""

from __future__ import annotations


def pending_holds() -> list[dict]:
    raise NotImplementedError
