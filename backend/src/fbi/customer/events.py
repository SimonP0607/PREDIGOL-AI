"""Product analytics (plan UX, A6 and section 39): the events of a closed catalog, their daily aggregate, their purge
and the owner's view of them.

* **The catalog** (``events_catalog.json``, the same in ``web/src/lib/track.ts``): 40 events, each with the only
  properties it may carry - an enumeration, a bounded integer, a boolean, a slug or an id. Anything else is refused:
  an unknown event, an unknown property, a value out of its kind. No free text, no address, no IP.
* **Who:** a pseudonym (``fbi.auth.crypto.product_id``: an HMAC of the account's id under its own key), never the id.
  The owner (SUPER_ADMIN) and the synthetic journey's account are never recorded.
* **When:** ``FBI_PRODUCT_EVENTS`` is born off; ``on`` records every reader, ``consent`` only those whose latest
  ``analytics`` consent is granted (if the lawyer asks for a separate box, P5). The browser's events go through
  ``POST /api/v1/events`` (behind the consent gate); the server's (activation, membership, tickets) through
  ``record_server`` in the caller's transaction.
* **Aggregate and purge** (the messenger, every cycle): the last two Bogotá days are recomputed from the raw events, so
  the aggregate always equals them; raw events older than 90 days and aggregates older than 13 months are deleted only
  with ``FBI_EVENTS_PURGE=on`` - born ``dry``, which counts and deletes nothing until the owner says so.
* **The owner's view** (``overview``): global figures only with at least ``FBI_PRODUCT_MIN_SUBJECTS`` (20) readers
  active in the window; below that, the number and nothing else. Its breakdowns (the screens by group, the markets of
  the picks saved and the legs added to a parlay, the leagues and the teams of the matches opened) list a line only
  when at least that many readers are behind it, and the leagues and teams are worked out here, at the time of the
  reading, from the ``match_id`` of ``match_opened`` - nothing is collected for them.

Nothing here reaches a model, the decision layer or the AI's package (tests/unit/test_user_layer_isolation.py).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Json

from fbi.auth import crypto
from fbi.customer import consents
from fbi.customer.db import CustomerError, write_connection

log = structlog.get_logger(__name__)

CATALOG_FILE = Path(__file__).resolve().parent / "events_catalog.json"
BOGOTA = ZoneInfo("America/Bogota")
SLUG = re.compile(r"^[A-Za-z0-9_.+-]{1,40}$")
MAX_ID = 2**53 - 1
MAX_BATCH = 20
RAW_DAYS = 90
DAILY_DAYS = 396
"""13 months and a day: the aggregate of a day leaves after the same day of the year after next month."""
DEFAULT_MIN_SUBJECTS = 20
Source = Literal["web", "server"]
Mode = Literal["off", "on", "consent"]
PurgeMode = Literal["off", "dry", "on"]


@dataclass(frozen=True, slots=True)
class PropSpec:
    kind: Literal["enum", "int", "bool", "slug", "id"]
    values: tuple[str, ...] = ()
    lo: int = 0
    hi: int = 0


@dataclass(frozen=True, slots=True)
class EventSpec:
    name: str
    group: str
    source: Source
    props: dict[str, PropSpec]


class EventError(CustomerError):
    """An event the catalog refuses: 422 with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(422, code, message)


def _prop(name: str, raw: Mapping[str, Any]) -> PropSpec:
    if "enum" in raw:
        return PropSpec("enum", values=tuple(str(v) for v in raw["enum"]))
    if "int" in raw:
        lo, hi = raw["int"]
        return PropSpec("int", lo=int(lo), hi=int(hi))
    for kind in ("bool", "slug", "id"):
        if raw.get(kind) is True:
            return PropSpec(kind)
    raise ValueError(f"events_catalog.json: property {name!r} has no kind")


@cache
def catalog() -> dict[str, EventSpec]:
    data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["events"]
    out: dict[str, EventSpec] = {}
    for name, spec in data.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", name) or spec["source"] not in ("web", "server"):
            raise ValueError(f"events_catalog.json: {name!r} is not a valid event")
        out[name] = EventSpec(name=name, group=str(spec["group"]), source=spec["source"],
                              props={k: _prop(k, v) for k, v in spec["props"].items()})
    return out


def check(name: object, props: object, *, source: Source) -> dict[str, Any]:
    """The event's properties as the catalog allows them, or EventError. Every property is optional."""
    spec = catalog().get(name) if isinstance(name, str) else None
    if spec is None:
        raise EventError("unknown_event", f"no event {str(name)[:40]!r} in the catalog")
    if spec.source != source:
        raise EventError("server_event", f"{spec.name} is recorded by the server, not sent")
    if props is None:
        props = {}
    if not isinstance(props, dict):
        raise EventError("invalid_properties", f"{spec.name}: the properties are an object")
    clean: dict[str, Any] = {}
    for key, value in props.items():
        prop = spec.props.get(key)
        if prop is None:
            raise EventError("unknown_property", f"{spec.name} has no property {str(key)[:40]!r}")
        ok = (
            (prop.kind == "enum" and isinstance(value, str) and value in prop.values)
            or (prop.kind == "int" and isinstance(value, int) and not isinstance(value, bool)
                and prop.lo <= value <= prop.hi)
            or (prop.kind == "bool" and isinstance(value, bool))
            or (prop.kind == "slug" and isinstance(value, str) and SLUG.fullmatch(value) is not None)
            or (prop.kind == "id" and isinstance(value, int) and not isinstance(value, bool) and 0 < value <= MAX_ID)
        )
        if not ok:
            raise EventError("invalid_property", f"{spec.name}.{key}: not a value of its kind ({prop.kind})")
        clean[key] = value
    return clean


def mode() -> Mode:
    raw = os.environ.get("FBI_PRODUCT_EVENTS", "").strip().lower()
    if raw == "consent":
        return "consent"
    return "on" if raw in ("1", "on", "true", "yes") else "off"


def purge_mode() -> PurgeMode:
    raw = os.environ.get("FBI_EVENTS_PURGE", "dry").strip().lower()
    if raw in ("on", "1", "true", "yes"):
        return "on"
    return "off" if raw in ("off", "0", "false", "no") else "dry"


def min_subjects() -> int:
    try:
        return max(1, int(os.environ.get("FBI_PRODUCT_MIN_SUBJECTS", str(DEFAULT_MIN_SUBJECTS))))
    except ValueError:
        return DEFAULT_MIN_SUBJECTS


def _analytics_consented(conn: psycopg.Connection[Any], user_id: int) -> bool:
    latest = consents.latest(conn, user_id).get("analytics")
    return bool(latest and latest.granted)


def _recordable(conn: psycopg.Connection[Any], user_id: int, email: str, *, super_admin: bool) -> str | None:
    """The reader's pseudonym when their events are to be recorded now, else None."""
    current = mode()
    if current == "off" or consents.exempt(email, super_admin=super_admin):
        return None
    if current == "consent" and not _analytics_consented(conn, user_id):
        return None
    return crypto.product_id(user_id)


def subject_now(conn: psycopg.Connection[Any], user_id: int, email: str, *, super_admin: bool) -> str | None:
    """The reader's pseudonym while their events are being recorded now (the mode, their consent, never the owner or the
    robot), else None: what reads a reader's own events for them (plan UX, B2: fbi.customer.personal) uses them only then."""
    return _recordable(conn, user_id, email, super_admin=super_admin)


def record(user_id: int, email: str, events: Sequence[tuple[object, object]], *, super_admin: bool) -> int:
    """The browser's batch: every event is checked first (one wrong event refuses the batch - a bug in the page, never
    a reader's input), then written in one statement. How many were recorded (0 when nothing is to be)."""
    if len(events) > MAX_BATCH:
        raise EventError("batch_too_large", f"at most {MAX_BATCH} events at a time")
    clean = [(str(name), check(name, props, source="web")) for name, props in events]
    if not clean:
        return 0
    with write_connection() as conn:
        subject = _recordable(conn, user_id, email, super_admin=super_admin)
        if subject is None:
            return 0
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO customer.product_events (subject, name, props) VALUES (%s, %s, %s)",
                            [(subject, name, Json(props)) for name, props in clean])
    return len(clean)


def record_server(conn: psycopg.Connection[Any], user_id: int, name: str, props: Mapping[str, object] | None = None,
                  ) -> bool:
    """A server event (activation, membership, a ticket) in the caller's transaction. True when it was recorded."""
    clean = check(name, dict(props or {}), source="server")
    row = conn.execute("SELECT email, role FROM auth.users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        return False
    subject = _recordable(conn, user_id, str(row[0]), super_admin=row[1] == "SUPER_ADMIN")
    if subject is None:
        return False
    conn.execute("INSERT INTO customer.product_events (subject, name, props) VALUES (%s, %s, %s)",
                 (subject, name, Json(clean)))
    return True


# ── the messenger: the daily aggregate and the purge ──────────────────────────────────

def bogota_day(at: datetime) -> date:
    return at.astimezone(BOGOTA).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=BOGOTA)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def rollup(conn: psycopg.Connection[Any], days: Iterable[date]) -> int:
    """Recompute the aggregate of these Bogotá days from the raw events (it then equals them). Rows written. The
    caller commits."""
    written = 0
    for day in sorted(set(days)):
        start, end = day_bounds(day)
        conn.execute("DELETE FROM customer.activity_daily WHERE day = %s", (day,))
        cur = conn.execute("""
            INSERT INTO customer.activity_daily (day, subject, events, counts, first_at, last_at)
            SELECT %s, subject, sum(n)::int, jsonb_object_agg(name, n), min(first_at), max(last_at)
              FROM (SELECT subject, name, count(*) AS n, min(at) AS first_at, max(at) AS last_at
                      FROM customer.product_events WHERE at >= %s AND at < %s GROUP BY subject, name) per_name
             GROUP BY subject
        """, (day, start, end))
        written += max(cur.rowcount, 0)
    return written


@dataclass(frozen=True, slots=True)
class PurgeReport:
    mode: PurgeMode
    raw: int
    daily: int


def purge(conn: psycopg.Connection[Any], *, at: datetime, mode_: PurgeMode | None = None) -> PurgeReport:
    """Raw events older than 90 days and aggregates older than 13 months: counted (``dry``, the default) or deleted
    (``on``, the owner's decision). The caller commits."""
    current = purge_mode() if mode_ is None else mode_
    raw_before = at - timedelta(days=RAW_DAYS)
    daily_before = bogota_day(at) - timedelta(days=DAILY_DAYS)
    if current == "off":
        return PurgeReport("off", 0, 0)
    if current == "dry":
        raw = conn.execute("SELECT count(*) FROM customer.product_events WHERE at < %s", (raw_before,)).fetchone()
        daily = conn.execute("SELECT count(*) FROM customer.activity_daily WHERE day < %s", (daily_before,)).fetchone()
        return PurgeReport("dry", int(raw[0]) if raw else 0, int(daily[0]) if daily else 0)
    raw_n = conn.execute("DELETE FROM customer.product_events WHERE at < %s", (raw_before,)).rowcount
    daily_n = conn.execute("DELETE FROM customer.activity_daily WHERE day < %s", (daily_before,)).rowcount
    if raw_n or daily_n:
        log.info("events.purged", raw=raw_n, daily=daily_n)
    return PurgeReport("on", max(raw_n, 0), max(daily_n, 0))


# ── the owner's view ───────────────────────────────────────────────────────────────────

@dataclass
class Overview:
    mode: Mode
    purge: PurgeMode
    min_subjects: int
    status: Literal["ok", "insufficient_data", "empty"]
    active_30d: int
    active: dict[str, int] = field(default_factory=dict)
    usage: list[dict[str, Any]] = field(default_factory=list)
    funnel: list[dict[str, Any]] = field(default_factory=list)
    devices: dict[str, int] = field(default_factory=dict)
    days_active_per_week: float | None = None
    errors_per_active: float | None = None
    dau_mau: float | None = None
    screens: list[dict[str, Any]] = field(default_factory=list)
    markets: list[dict[str, Any]] = field(default_factory=list)
    leagues: list[dict[str, Any]] = field(default_factory=list)
    teams: list[dict[str, Any]] = field(default_factory=list)


FUNNEL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("activated", ("account_activated",)),
    ("onboarding_started", ("onboarding_started",)),
    ("onboarding_completed", ("onboarding_completed",)),
    ("first_value", ("match_opened", "pick_opened", "pick_saved")),
)


BREAKDOWN_ROWS = 15

SCREENS_SQL = """
SELECT props->>'screen' AS key, NULL::text AS label, count(*) AS events_30d, count(DISTINCT subject) AS subjects_30d
  FROM customer.product_events WHERE at >= %(s30)s AND name = 'screen_viewed' AND props ? 'screen'
 GROUP BY 1 HAVING count(DISTINCT subject) >= %(floor)s ORDER BY count(*) DESC, 1 LIMIT %(rows)s
"""
MARKETS_SQL = """
SELECT props->>'market' AS key, NULL::text AS label, count(*) AS events_30d, count(DISTINCT subject) AS subjects_30d
  FROM customer.product_events WHERE at >= %(s30)s AND name IN ('pick_saved', 'slip_leg_added') AND props ? 'market'
 GROUP BY 1 HAVING count(DISTINCT subject) >= %(floor)s ORDER BY count(*) DESC, 1 LIMIT %(rows)s
"""
LEAGUES_SQL = """
SELECT c.id::text AS key, c.name AS label, count(*) AS events_30d, count(DISTINCT e.subject) AS subjects_30d
  FROM customer.product_events e
  JOIN core.fixtures f ON f.id = (e.props->>'match_id')::bigint
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE e.at >= %(s30)s AND e.name = 'match_opened' AND e.props ? 'match_id'
 GROUP BY c.id, c.name HAVING count(DISTINCT e.subject) >= %(floor)s ORDER BY count(*) DESC, c.name LIMIT %(rows)s
"""
TEAMS_SQL = """
SELECT t.id::text AS key, t.name AS label, count(*) AS events_30d, count(DISTINCT e.subject) AS subjects_30d
  FROM customer.product_events e
  JOIN core.fixtures f ON f.id = (e.props->>'match_id')::bigint
  CROSS JOIN LATERAL (VALUES (f.home_team_id), (f.away_team_id)) AS s(team_id)
  JOIN core.teams t ON t.id = s.team_id
 WHERE e.at >= %(s30)s AND e.name = 'match_opened' AND e.props ? 'match_id'
 GROUP BY t.id, t.name HAVING count(DISTINCT e.subject) >= %(floor)s ORDER BY count(*) DESC, t.name LIMIT %(rows)s
"""
"""What the readers look at, in groups and never one by one: a line stands only with ``min_subjects`` readers behind it.
The leagues and the teams come from the match a reader opened (its ``match_id``), looked up when the owner reads them."""


def overview(conn: psycopg.Connection[Any], *, at: datetime) -> Overview:
    """The last 30 days, from the raw events (kept 90): who is active, how often, what they use, on which device,
    how many errors they see. The daily aggregate keeps what lasts beyond the raw events (13 months)."""
    today = bogota_day(at)
    floor = min_subjects()
    since1 = day_bounds(today)[0]
    since7, since30 = day_bounds(today - timedelta(days=6))[0], day_bounds(today - timedelta(days=29))[0]
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT count(DISTINCT subject) AS d30,
                   count(DISTINCT subject) FILTER (WHERE at >= %(s7)s) AS d7,
                   count(DISTINCT subject) FILTER (WHERE at >= %(s1)s) AS d1
              FROM customer.product_events WHERE at >= %(s30)s
        """, {"s1": since1, "s7": since7, "s30": since30})
        row = cur.fetchone() or {}
        active_30d = int(row.get("d30") or 0)
        base = Overview(mode=mode(), purge=purge_mode(), min_subjects=floor,
                        status="empty" if active_30d == 0 else "insufficient_data", active_30d=active_30d)
        if active_30d < floor:
            return base
        base.status = "ok"
        base.active = {k: int(row.get(k) or 0) for k in ("d1", "d7", "d30")}
        if base.active["d30"] >= 100:
            base.dau_mau = round(base.active["d1"] / base.active["d30"], 3)
        cur.execute("""
            SELECT avg(n)::float AS days FROM (
                SELECT subject, count(DISTINCT (at AT TIME ZONE 'America/Bogota')::date) AS n
                  FROM customer.product_events WHERE at >= %s GROUP BY subject) per_subject
        """, (since7,))
        days = (cur.fetchone() or {}).get("days")
        base.days_active_per_week = round(float(days), 2) if days is not None else None
        cur.execute("""
            SELECT name, count(*) FILTER (WHERE at >= %(s7)s) AS events_7d,
                   count(DISTINCT subject) FILTER (WHERE at >= %(s7)s) AS subjects_7d,
                   count(*) AS events_30d, count(DISTINCT subject) AS subjects_30d
              FROM customer.product_events WHERE at >= %(s30)s GROUP BY name ORDER BY count(*) DESC, name
        """, {"s7": since7, "s30": since30})
        specs = catalog()
        base.usage = [{"name": r["name"], "group": specs[r["name"]].group if r["name"] in specs else "other",
                       "events_7d": int(r["events_7d"]), "subjects_7d": int(r["subjects_7d"]),
                       "events_30d": int(r["events_30d"]), "subjects_30d": int(r["subjects_30d"])}
                      for r in cur.fetchall()]
        for step, names in FUNNEL:
            cur.execute("SELECT count(DISTINCT subject) AS n FROM customer.product_events "
                        "WHERE at >= %s AND name = ANY(%s)", (since30, list(names)))
            base.funnel.append({"step": step, "subjects": int((cur.fetchone() or {"n": 0})["n"])})
        cur.execute("SELECT props->>'device' AS device, count(*) AS n FROM customer.product_events "
                    "WHERE at >= %s AND name = 'session_started' GROUP BY 1", (since7,))
        base.devices = {str(r["device"] or "unknown"): int(r["n"]) for r in cur.fetchall()}
        errors = sum(u["events_7d"] for u in base.usage if u["name"] == "error_shown")
        base.errors_per_active = round(errors / base.active["d7"], 3) if base.active["d7"] else None
        window = {"s30": since30, "floor": floor, "rows": BREAKDOWN_ROWS}
        for attr, sql in (("screens", SCREENS_SQL), ("markets", MARKETS_SQL), ("leagues", LEAGUES_SQL),
                          ("teams", TEAMS_SQL)):
            cur.execute(sql, window)
            setattr(base, attr, [{"key": str(r["key"]), "label": r["label"], "events_30d": int(r["events_30d"]),
                                  "subjects_30d": int(r["subjects_30d"])} for r in cur.fetchall()])
    return base


def events_of(conn: psycopg.Connection[Any], user_id: int) -> dict[str, list[dict[str, Any]]]:
    """A reader's own events and daily aggregates, for their export (fbi.customer.privacy)."""
    subject = crypto.product_id(user_id)
    if subject is None:
        return {"product_events": [], "activity_daily": []}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT name, props, at FROM customer.product_events WHERE subject = %s ORDER BY at, id",
                    (subject,))
        raw = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT day, events, counts FROM customer.activity_daily WHERE subject = %s ORDER BY day",
                    (subject,))
        daily = [dict(r) for r in cur.fetchall()]
    return {"product_events": raw, "activity_daily": daily}
