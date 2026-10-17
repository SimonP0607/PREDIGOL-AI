"""What the provider can actually SEE, measured rather than assumed.

The live scheduler is built on claims about horizons: that ``/fixtures?date=``
returns any date, that ``/odds`` appears about fourteen days before kick-off and
keeps a seven-day history, that ``/odds/live`` publishes a fixture only in the
last minutes. On the Free plan the result horizon turned out to be THREE DAYS,
which is why eight fixtures we had prices for stayed permanently 'NS'. Nothing in
the code knew that; it was found by looking.

An upgrade does not automatically widen every range, and which ranges a plan
serves is not documented per plan. So this probe asks, with a handful of requests,
and records the answer with the payload it came from:

  * ``/fixtures?date=`` at several offsets from today, past and future: how far
    back and how far forward does this account see a fixture list at all?
  * ``/odds?fixture=`` for fixtures at increasing distances from kick-off: from
    what distance do prices exist?
  * ``/odds/live`` once: does it answer at all, and with what.

Every answer is a measurement of THIS account on THIS day. It is written down with
that date, because it can change when the plan changes and a stale measurement
presented as a capability is how the three-day horizon went unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import psycopg
import structlog

from fbi.core.clock import now
from fbi.ingestion.ledger import RunCounters, RunLedger

log = structlog.get_logger(__name__)

DEFAULT_DATE_OFFSETS: tuple[int, ...] = (-365, -90, -30, -7, -3, -1, 0, 1, 3, 7, 14, 30, 90)
"""Days from today. Chosen to bracket the horizons that matter: the three-day
result window the Free plan really had, the fourteen-day odds window the docs
describe, and a year back for the historical claim."""


@dataclass
class DateWindow:
    offset_days: int
    on: date
    results: int
    provider_errors: dict[str, Any] = field(default_factory=dict)
    payload_hash: str | None = None

    @property
    def visible(self) -> bool:
        return self.results > 0 and not self.provider_errors


@dataclass
class OddsWindow:
    provider_fixture_id: int
    minutes_to_kickoff: int
    bookmakers: int
    bets: int
    provider_errors: dict[str, Any] = field(default_factory=dict)
    payload_hash: str | None = None

    @property
    def priced(self) -> bool:
        return self.bookmakers > 0


@dataclass
class WindowReport:
    measured_at: str
    dates: list[DateWindow] = field(default_factory=list)
    odds: list[OddsWindow] = field(default_factory=list)
    live_answered: bool | None = None
    live_detail: str = ""
    requests: int = 0
    run_id: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def earliest_visible_offset(self) -> int | None:
        visible = [d.offset_days for d in self.dates if d.visible]
        return min(visible) if visible else None

    @property
    def latest_visible_offset(self) -> int | None:
        visible = [d.offset_days for d in self.dates if d.visible]
        return max(visible) if visible else None

    @property
    def furthest_priced_minutes(self) -> int | None:
        priced = [o.minutes_to_kickoff for o in self.odds if o.priced]
        return max(priced) if priced else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "measured_at": self.measured_at,
            "requests": self.requests,
            "fixture_dates": [
                {"offset_days": d.offset_days, "date": d.on.isoformat(), "results": d.results,
                 "visible": d.visible, "provider_errors": d.provider_errors or None}
                for d in self.dates
            ],
            "earliest_visible_offset": self.earliest_visible_offset,
            "latest_visible_offset": self.latest_visible_offset,
            "odds": [
                {"fixture": o.provider_fixture_id, "minutes_to_kickoff": o.minutes_to_kickoff,
                 "bookmakers": o.bookmakers, "bets": o.bets, "priced": o.priced,
                 "provider_errors": o.provider_errors or None}
                for o in self.odds
            ],
            "furthest_priced_minutes": self.furthest_priced_minutes,
            "live_answered": self.live_answered,
            "live_detail": self.live_detail,
            "notes": self.notes,
        }


def _errors(body: Any) -> dict[str, Any]:
    """API-Football reports failure INSIDE HTTP 200, in ``errors``. An empty list
    means no error; a populated object is the error."""
    if not isinstance(body, dict):
        return {}
    errors = body.get("errors")
    return dict(errors) if isinstance(errors, dict) and errors else {}


def _count(body: Any, key: str) -> int:
    if not isinstance(body, dict):
        return 0
    value = body.get(key)
    return int(value) if isinstance(value, int) else len(value) if isinstance(value, list) else 0


async def probe_windows(
    conn: psycopg.Connection,
    client: Any,
    *,
    date_offsets: tuple[int, ...] = DEFAULT_DATE_OFFSETS,
    odds_fixtures: list[tuple[int, int]] | None = None,
    include_live: bool = True,
) -> WindowReport:
    """Ask the provider what it can see. Every payload is stored and indexed.

    ``odds_fixtures`` is [(provider_fixture_id, minutes_to_kickoff)] - chosen by the
    caller from our own catalogue, so the distances are real rather than guessed.
    """
    today = now().date()
    report = WindowReport(measured_at=now().isoformat())
    ledger = RunLedger(conn)
    run_id = ledger.open("window_probe", params={"offsets": list(date_offsets)})
    report.run_id = run_id
    counters = RunCounters()

    try:
        for offset in date_offsets:
            on = today + timedelta(days=offset)
            response = await client.get("/fixtures", {"date": on.isoformat()})
            counters.api_calls += 1
            report.requests += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [_as_raw(response)])
            report.dates.append(DateWindow(
                offset_days=offset, on=on, results=_count(response.body, "results"),
                provider_errors=_errors(response.body), payload_hash=response.stored.hash,
            ))
            conn.commit()

        for provider_fixture_id, minutes in odds_fixtures or []:
            response = await client.get("/odds", {"fixture": provider_fixture_id})
            counters.api_calls += 1
            report.requests += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [_as_raw(response)])
            books, bets = _books_and_bets(response.body)
            report.odds.append(OddsWindow(
                provider_fixture_id=provider_fixture_id, minutes_to_kickoff=minutes,
                bookmakers=books, bets=bets, provider_errors=_errors(response.body),
                payload_hash=response.stored.hash,
            ))
            conn.commit()

        if include_live:
            response = await client.get("/odds/live", {})
            counters.api_calls += 1
            report.requests += 1
            counters.payloads_stored += ledger.record_payloads(run_id, [_as_raw(response)])
            errors = _errors(response.body)
            report.live_answered = not errors
            report.live_detail = (
                f"errors: {errors}" if errors
                else f"{_count(response.body, 'results')} fixture(s) in play with prices"
            )
            conn.commit()
    finally:
        ledger.close(run_id, counters, notes=f"{report.requests} probe request(s)")
        conn.commit()

    log.info("window_probe.finished", requests=report.requests,
             earliest=report.earliest_visible_offset, latest=report.latest_visible_offset,
             furthest_priced_minutes=report.furthest_priced_minutes)
    return report


def _books_and_bets(body: Any) -> tuple[int, int]:
    books = bets = 0
    if not isinstance(body, dict):
        return 0, 0
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        for book in entry.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            books += 1
            bets += len(book.get("bets") or [])
    return books, bets


def _as_raw(response: Any) -> Any:
    """The client's response as the ledger wants it. Imported lazily so this module
    does not depend on one provider package."""
    from fbi.providers.base import RawResponse

    return RawResponse(
        endpoint=response.endpoint,
        params=response.params,
        fetched_at=response.fetched_at,
        http_status=response.http_status,
        results_count=_count(response.body, "results"),
        payload_hash=response.stored.hash,
        file_path=response.stored.file_path,
        bytes_written=response.stored.bytes_written,
        body=response.body,
    )


def candidate_odds_fixtures(conn: psycopg.Connection, *, limit: int = 4) -> list[tuple[int, int]]:
    """Scheduled fixtures of tracked competitions at a spread of distances.

    Taken from our own catalogue so the distances are facts, and ordered so the
    sample brackets the documented fourteen-day odds window rather than clustering
    just before kick-off.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH upcoming AS (
                SELECT f.provider_fixture_id,
                       GREATEST(0, (EXTRACT(EPOCH FROM (f.kickoff_at - now())) / 60)::int) AS minutes
                  FROM core.fixtures f
                  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
                  JOIN core.competitions c ON c.id = cs.competition_id
                 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at > now()
            ), bucketed AS (
                SELECT provider_fixture_id, minutes,
                       width_bucket(minutes, 0, 43200, %s) AS bucket,
                       row_number() OVER (PARTITION BY width_bucket(minutes, 0, 43200, %s)
                                          ORDER BY minutes) AS n
                  FROM upcoming
            )
            SELECT provider_fixture_id, minutes FROM bucketed WHERE n = 1 ORDER BY minutes LIMIT %s
            """,
            (limit, limit, limit),
        )
        return [(int(a), int(b)) for a, b in cur.fetchall()]
