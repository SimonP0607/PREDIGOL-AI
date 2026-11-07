"""What each reader has seen of the welcome tour and of the guides of each screen (plan UX-032; PLAN_BIENVENIDA_RECORRIDO).

One engine of guides in the page (UX-051 to UX-054): an optional general tour, an optional first-visit guide for each screen
and the first guide of Perfil, which is owed once. This module is only their memory - what the reader has seen, per guide and
per version of the content - and the rules that keep it coherent. It decides nothing about what the guides say, never changes
a pick, a model or a market, and is never used for analytics.

    guide        a closed list of ten (``GUIDES``); each has a closed number of steps (``STEPS``).
    version      the version of the content the reader saw (1 to 99); the page holds the current one. A write with a higher
                 version starts the guide over for that version (the reader sees it once more, when the page decides it is
                 a considerable change); a write with a lower one - a PWA left open from before - changes nothing.
    status       ``pending`` (the screen was visited, the guide not yet shown) < ``in_progress`` < ``skipped`` < ``completed``.
                 Within one version the status never goes down: «completed» is not erased by a replay that is skipped, and a
                 replay that is paused does not undo a skip.
    step         the last step reached (0-based): to resume, and to know where a guide was skipped.
    profile      the first guide of Perfil is owed: it cannot be recorded as skipped until it is completed (409), and
                 FBI_GUIDES=0 stops the page from showing any guide.

Writes are idempotent and a reader only ever touches their own rows. ``FBI_GUIDES`` is on while absent (like
``FBI_ONBOARDING``); ``=0`` stops every guide from showing without a deploy (the state already recorded stays).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, get_args

import psycopg

from fbi.customer.db import CustomerError, write_connection
from fbi.customer.favorites import _switch

GuideKey = Literal["general", "home", "matches", "live", "match", "picks", "parlays", "odds", "my_picks", "profile"]
GuideStatus = Literal["pending", "in_progress", "completed", "skipped"]

GUIDES: Final[tuple[str, ...]] = get_args(GuideKey)
STATUSES: Final[tuple[str, ...]] = get_args(GuideStatus)
RANK: Final = {"pending": 0, "in_progress": 1, "skipped": 2, "completed": 3}
"""The order a status never goes down in, within one version."""
STEPS: Final = {"general": 6, "profile": 6, **{g: 3 for g in GUIDES if g not in ("general", "profile")}}
"""The most steps each guide has (the general tour: its welcome card and 5 steps; a screen: 3; Perfil: 6). A step is 0-based."""
MANDATORY: Final = frozenset({"profile"})
MAX_VERSION: Final = 99
SWITCH: Final = "FBI_GUIDES"


def guides_on() -> bool:
    """``FBI_GUIDES``: the guides in the page; =0 stops every one of them (the recorded state stays)."""
    return _switch(SWITCH)


@dataclass(frozen=True)
class Progress:
    guide: str
    version: int
    status: str
    step: int
    first_seen_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    skipped_at: datetime | None


COLUMNS: Final = "guide, version, status, step, first_seen_at, started_at, completed_at, skipped_at"


def _progress(row: tuple[Any, ...]) -> Progress:
    return Progress(str(row[0]), int(row[1]), str(row[2]), int(row[3]), row[4], row[5], row[6], row[7])


def progress(conn: psycopg.Connection[Any], user_id: int) -> list[Progress]:
    """Every guide the reader has a row for, in the closed list's order."""
    rows = conn.execute(f"SELECT {COLUMNS} FROM customer.guide_progress WHERE user_id = %s", (user_id,)).fetchall()
    order = {g: i for i, g in enumerate(GUIDES)}
    return sorted((_progress(r) for r in rows), key=lambda p: order[p.guide])


def auto(conn: psycopg.Connection[Any], user_id: int) -> bool:
    """The reader's own switch: the guide of each screen on the first visit (on until they turn it off)."""
    row = conn.execute("SELECT guides_auto FROM customer.preferences WHERE user_id = %s", (user_id,)).fetchone()
    return True if row is None else bool(row[0])


def set_auto(user_id: int, value: bool, *, at: datetime) -> None:
    with write_connection() as conn:
        conn.execute(
            "INSERT INTO customer.preferences (user_id, guides_auto, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET guides_auto = EXCLUDED.guides_auto, updated_at = EXCLUDED.updated_at",
            (user_id, value, at))


def check(guide: str, version: int, status: str, step: int) -> None:
    """The closed lists: an unknown guide, version, status or step is refused (422), never trimmed."""
    if guide not in GUIDES:
        raise CustomerError(422, "unknown_guide", f"no guide called {guide}")
    if not 1 <= version <= MAX_VERSION:
        raise CustomerError(422, "invalid_version", f"version {version} is out of 1..{MAX_VERSION}")
    if status not in STATUSES:
        raise CustomerError(422, "invalid_status", f"no status called {status}")
    if not 0 <= step < STEPS[guide]:
        raise CustomerError(422, "invalid_step", f"{guide} has {STEPS[guide]} steps: {step} is out of range")


def record(user_id: int, guide: str, *, version: int, status: str, step: int, at: datetime) -> Progress:
    """Records what the reader did with a guide and answers its state. Idempotent; the rules are in the module's docstring."""
    check(guide, version, status, step)
    with write_connection() as conn:
        # a reader's two tabs may write at once: the row is locked while it is decided
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"guide:{user_id}:{guide}",))
        row = conn.execute(f"SELECT {COLUMNS} FROM customer.guide_progress WHERE user_id = %s AND guide = %s",
                           (user_id, guide)).fetchone()
        current = _progress(row) if row is not None else None
        if current is not None and version < current.version:
            return current  # a PWA left open from before: what is recorded for a newer version stays
        if status == "skipped" and guide in MANDATORY and (current is None or current.status != "completed"):
            raise CustomerError(409, "guide_mandatory", f"{guide} is owed: it cannot be skipped before it is done")
        if current is not None and version == current.version and (
                RANK[status] < RANK[current.status] or status == current.status in ("completed", "skipped")):
            return current  # never down within a version; a repeat keeps its first moment
        first_seen = current.first_seen_at if current is not None else at
        keep = current is not None and version == current.version
        started = (current.started_at if keep and current is not None else None)
        if status != "pending" and started is None:
            started = at
        completed = at if status == "completed" else None
        skipped = at if status == "skipped" else None
        saved = conn.execute(
            f"INSERT INTO customer.guide_progress (user_id, guide, version, status, step, first_seen_at, started_at, "
            f"completed_at, skipped_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT (user_id, guide) DO UPDATE SET version = EXCLUDED.version, status = EXCLUDED.status, "
            f"step = EXCLUDED.step, started_at = EXCLUDED.started_at, completed_at = EXCLUDED.completed_at, "
            f"skipped_at = EXCLUDED.skipped_at, updated_at = EXCLUDED.updated_at RETURNING {COLUMNS}",
            (user_id, guide, version, status, step, first_seen, started, completed, skipped, at)).fetchone()
    assert saved is not None
    return _progress(saved)
