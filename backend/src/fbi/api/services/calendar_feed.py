"""The iCalendar file of a reader's followed teams (Plan Maestro PM, PM-14-06, OP-43; BE-084), RFC 5545.

WHAT IT HOLDS. The fixtures of the teams the reader follows (``customer.favorites``, kind ``team``) from ``PAST_DAYS`` ago to ``AHEAD_DAYS``
ahead, at most ``MAX_EVENTS``: one ``VEVENT`` each with a stable ``UID`` (``fixture-<id>@predigol``, so a client updates a moved match
instead of duplicating it), the kick-off in UTC, ``DURATION`` of two hours, the summary «Local vs Visitante», the competition and its
round, and the venue when known. A postponed or cancelled match says so (``STATUS:CANCELLED``); a kick-off still to be defined
(``TBD``) is ``TENTATIVE``. NOTHING ELSE: no price, no probability, no pick, no score prediction, no link that signs in, no account
data - not even the reader's name: the calendar's own name is «PrediGol · Mis equipos».

THE FORMAT. CRLF line ends, lines folded at 75 octets (never inside a UTF-8 character), TEXT escaped (backslash, semicolon, comma,
newline), ``VERSION:2.0``, ``PRODID``, ``CALSCALE:GREGORIAN``, ``METHOD:PUBLISH``, the refresh hints read by Apple and Outlook
(``REFRESH-INTERVAL`` / ``X-PUBLISHED-TTL``, six hours) and ``DTSTAMP`` from the moment of the file. Pure but for ``events_for`` (one
read of the favourites and one of the fixtures, on the API's read-only connection).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg

PAST_DAYS: Final = 14
AHEAD_DAYS: Final = 120
MAX_EVENTS: Final = 400
DURATION: Final = "PT2H"
REFRESH: Final = "PT6H"
PRODID: Final = "-//PrediGol//Mis equipos 1.0//ES"
NAME: Final = "PrediGol · Mis equipos"
FOLD_AT: Final = 75

EVENTS_SQL: Final = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group, f.round, f.venue_name, f.venue_city,
       th.name AS home_name, ta.name AS away_name, c.name AS competition
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (f.home_team_id = ANY(%(teams)s) OR f.away_team_id = ANY(%(teams)s))
   AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""
TEAMS_SQL: Final = "SELECT ref_id FROM customer.favorites WHERE user_id = %(u)s AND kind = 'team' ORDER BY ref_id"


@dataclass(frozen=True, slots=True)
class Event:
    fixture_id: int
    kickoff_at: datetime
    status_short: str | None
    status_group: str | None
    home: str
    away: str
    competition: str
    round: str | None = None
    venue: str | None = None
    city: str | None = None


def escape(text: str) -> str:
    """RFC 5545 TEXT: backslash, semicolon and comma escaped, a line end as ``\\n``; other control characters dropped."""
    out = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return "".join(ch for ch in out if ch == "\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F))


def fold(line: str) -> str:
    """A content line folded at 75 octets: CRLF and one space before each continuation, never splitting a UTF-8 character."""
    raw = line.encode("utf-8")
    if len(raw) <= FOLD_AT:
        return line
    parts: list[str] = []
    current = b""
    limit = FOLD_AT
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
            limit = FOLD_AT - 1  # the continuation's leading space counts
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _status(e: Event) -> str:
    if e.status_group in ("postponed", "cancelled") or e.status_short in ("PST", "CANC", "ABD", "AWD", "WO"):
        return "CANCELLED"
    if e.status_short == "TBD":
        return "TENTATIVE"
    return "CONFIRMED"


def vevent(e: Event, *, at: datetime) -> list[str]:
    description = e.competition + (f" · {e.round}" if e.round else "")
    lines = [
        "BEGIN:VEVENT",
        f"UID:fixture-{e.fixture_id}@predigol",
        f"DTSTAMP:{_utc(at)}",
        f"DTSTART:{_utc(e.kickoff_at)}",
        f"DURATION:{DURATION}",
        f"SUMMARY:{escape(f'{e.home} vs {e.away}')}",
        f"DESCRIPTION:{escape(description)}",
        f"STATUS:{_status(e)}",
        "TRANSP:TRANSPARENT",
    ]
    where = ", ".join(x for x in (e.venue, e.city) if x)
    if where:
        lines.insert(7, f"LOCATION:{escape(where)}")
    lines.append("END:VEVENT")
    return lines


def render(events: Iterable[Event], *, at: datetime) -> str:
    """The whole file: CRLF line ends, folded, ending with a CRLF."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{escape(NAME)}", "X-WR-TIMEZONE:UTC", f"REFRESH-INTERVAL;VALUE=DURATION:{REFRESH}",
             f"X-PUBLISHED-TTL:{REFRESH}"]
    for e in events:
        lines += vevent(e, at=at)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


def followed_teams(conn: psycopg.Connection[Any], user_id: int) -> list[int]:
    return [int(r[0]) for r in conn.execute(TEAMS_SQL, {"u": user_id}).fetchall()]


def events_for(conn: psycopg.Connection[Any], teams: Sequence[int], *, at: datetime) -> list[Event]:
    if not teams:
        return []
    rows = conn.execute(EVENTS_SQL, {"teams": list(teams), "since": at - timedelta(days=PAST_DAYS),
                                     "until": at + timedelta(days=AHEAD_DAYS), "limit": MAX_EVENTS}).fetchall()
    return [Event(int(r[0]), r[1], r[2], r[3], str(r[7]), str(r[8]), str(r[9]), r[4], r[5], r[6]) for r in rows]


def calendar_of(conn: psycopg.Connection[Any], user_id: int, *, at: datetime) -> str:
    return render(events_for(conn, followed_teams(conn, user_id), at=at), at=at)


__all__ = ["AHEAD_DAYS", "MAX_EVENTS", "PAST_DAYS", "Event", "calendar_of", "escape", "events_for", "fold", "followed_teams", "render",
           "vevent"]
