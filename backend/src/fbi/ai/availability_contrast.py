"""How often a report of availability is contradicted by the official match sheet, by level of source (plan RP-4.4, second tranche, ``availability-contrast-v1``).

``fbi.people.availability`` (IA-091) already gives each player of a match ONE state with the source that decides it (precedence: official > provider > two
outlets > one outlet; between equals the newer). What the plan asks of that state is a measurement: «la tasa de reportes desmentidos medida por nivel de fuente»,
against the official match sheets of past matches. This module is that measurement, read-only.

THE QUESTION. For a played match whose two official sheets exist, take the state of every player as it was known ``LEAD`` (90 minutes) before kick-off, the
moment before the official sheet comes out: the provider's report as of then (``fbi.ai.absences``) and the typed facts of the press and of official sources
(``ai.evidence``), resolved by the precedence above. Then look at the sheet:

* a player reported out (``baja`` or ``sancionado``) who is named on the match sheet - in the eleven or on the bench - was CONTRADICTED: the report was
  wrong, or too old, or the player was cleared in time. It is counted per level of the source that decided his state.
* a player reported ``duda`` is not right or wrong: the table says how many were in the eleven, on the bench or off the sheet.
* a player reported ``disponible`` by a source (not by default: this module never invents it) and off the sheet is an unannounced absence of a player a source
  had called available; counted apart.

It does not say which level is «better»: a rate with its Wilson interval and the number of reports it rests on. Few reports at a level (``MIN_REPORTS``) is
said as such and gives no verdict. It writes nothing and reads no health detail: the provider's reason is read only to tell a suspension from an injury
(``people.availability.provider_status``) and is dropped.

Pure parts: ``wilson``, ``summarize``, ``lines``. Reads: ``observations`` (one match), ``collect`` (a window of matches).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import absences as provider_absences
from fbi.ai import evidence as ai_evidence
from fbi.people import availability as av

VERSION: Final = "availability-contrast-v1"
LEAD: Final = timedelta(minutes=90)
"""How long before kick-off the state is read: before the official sheet, which comes out about 20 minutes before at the median."""
MIN_REPORTS: Final = 30
"""Fewer reports than this at a level: the rate is shown with its interval and no verdict is drawn from it."""
OUT: Final = frozenset({"baja", "sancionado"})
LEVELS: Final = tuple(sorted(av.RANK, key=av.RANK.__getitem__))
Z: Final = 1.96

FIXTURES_SQL = """
SELECT f.id AS fixture_id, f.kickoff_at
  FROM core.fixtures f
 WHERE f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND (SELECT count(DISTINCT l.team_side) FROM core.fixture_lineups l WHERE l.fixture_id = f.id) = 2
 ORDER BY f.kickoff_at DESC, f.id DESC
 LIMIT %(limit)s
"""
SHEET_SQL = """
SELECT DISTINCT p.provider_player_id, p.is_starter
  FROM core.fixture_lineup_players p
 WHERE p.fixture_id = %(fixture)s AND p.provider_player_id IS NOT NULL
"""


@dataclass(frozen=True, slots=True)
class Obs:
    """One player of one match: the state that decided, its level, and whether the official sheet names him (``started``: in the eleven)."""

    fixture_id: int
    provider_player_id: int
    status: str
    basis: str
    on_sheet: bool
    started: bool


@dataclass(frozen=True, slots=True)
class Rate:
    """A proportion with its Wilson interval (fractions); ``enough`` says whether the level has ``MIN_REPORTS`` reports."""

    n: int
    hits: int
    share: float | None
    low: float | None
    high: float | None
    enough: bool

    def as_json(self) -> dict[str, Any]:
        return {"n": self.n, "hits": self.hits, "share": self.share, "low": self.low, "high": self.high, "enough": self.enough}


def wilson(hits: int, n: int, *, z: float = Z) -> tuple[float, float, float] | None:
    """(share, low, high) of ``hits`` in ``n`` by the Wilson interval, or None when ``n`` is 0."""
    if n <= 0:
        return None
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def rate(hits: int, n: int) -> Rate:
    w = wilson(hits, n)
    return Rate(n, hits, None if w is None else w[0], None if w is None else w[1], None if w is None else w[2], n >= MIN_REPORTS)


def summarize(observations: Iterable[Obs]) -> dict[str, Any]:
    """The contradiction rate of ``baja``/``sancionado`` reports by level, the table of ``duda`` and the unannounced absences of ``disponible``."""
    out_n: dict[str, int] = defaultdict(int)
    out_hit: dict[str, int] = defaultdict(int)
    doubt: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # eleven, bench, off the sheet
    avail_n: dict[str, int] = defaultdict(int)
    avail_off: dict[str, int] = defaultdict(int)
    fixtures: set[int] = set()
    total = 0
    for o in observations:
        fixtures.add(o.fixture_id)
        total += 1
        if o.status in OUT:
            out_n[o.basis] += 1
            out_hit[o.basis] += int(o.on_sheet)
        elif o.status == "duda":
            doubt[o.basis][0 if o.started else 1 if o.on_sheet else 2] += 1
        elif o.status == "disponible":
            avail_n[o.basis] += 1
            avail_off[o.basis] += int(not o.on_sheet)
    return {
        "version": VERSION, "lead_minutes": int(LEAD.total_seconds() // 60), "fixtures_with_reports": len(fixtures), "reports": total,
        "contradicted_out": {b: rate(out_hit[b], out_n[b]).as_json() for b in LEVELS},
        "doubt": {b: {"eleven": doubt[b][0], "bench": doubt[b][1], "off_sheet": doubt[b][2]} for b in LEVELS},
        "available_but_absent": {b: rate(avail_off[b], avail_n[b]).as_json() for b in LEVELS},
        "rule": {"min_reports": MIN_REPORTS, "interval": "Wilson 95 %"}}


def lines(doc: Mapping[str, Any]) -> list[str]:
    names = {"oficial": "oficial", "proveedor": "proveedor", "dos_origenes": "dos medios", "un_medio": "un medio"}
    out = [f"Reportes de bajas desmentidos por la planilla oficial ({doc['version']}, estado leído {doc['lead_minutes']} min antes del saque): "
           f"{doc['reports']} reportes en {doc['fixtures_with_reports']} partidos"]
    for b in LEVELS:
        r = doc["contradicted_out"][b]
        if r["n"] == 0:
            out.append(f"  baja/sancionado · {names[b]}: sin reportes")
            continue
        enough = "" if r["enough"] else f" (menos de {doc['rule']['min_reports']} reportes: sin veredicto)"
        out.append(f"  baja/sancionado · {names[b]}: {r['hits']} de {r['n']} desmentidos ({r['share'] * 100:.1f} %, intervalo {r['low'] * 100:.1f} a {r['high'] * 100:.1f} %){enough}")
    for b in LEVELS:
        d = doc["doubt"][b]
        if d["eleven"] + d["bench"] + d["off_sheet"]:
            out.append(f"  duda · {names[b]}: {d['eleven']} en el once, {d['bench']} en el banquillo, {d['off_sheet']} fuera de la planilla")
    for b in LEVELS:
        r = doc["available_but_absent"][b]
        if r["n"]:
            out.append(f"  disponible · {names[b]}: {r['hits']} de {r['n']} no estaban en la planilla")
    return out


# ── database ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def _press_row(r: Mapping[str, Any]) -> dict[str, Any]:
    """A v1 item of ``ai.evidence`` as availability reads it: kind, assertion, level, source and time - nothing of its text."""
    raw = r.get("attributes")
    attributes: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return {"provider_player_id": r["provider_player_id"], "kind": r["kind"], "assertion": attributes.get("assertion"), "status": r["status"],
            "source_tier": r["source_tier"], "source_name": r["source_domain"], "known_at": r["retrieved_at"], "fixture_id": r["fixture_id"],
            "player_name": attributes.get("player_name")}


def observations(conn: psycopg.Connection[Any], fixture_id: int, kickoff: datetime, *, lead: timedelta = LEAD) -> list[Obs]:
    """The state of each player named by a report as known ``lead`` before ``kickoff``, against the official sheet of the played match."""
    at = kickoff - lead
    with conn.cursor(row_factory=dict_row) as cur:
        sheet = {int(r["provider_player_id"]): bool(r["is_starter"]) for r in cur.execute(SHEET_SQL, {"fixture": fixture_id}).fetchall()}
        press = [_press_row(r) for r in cur.execute(ai_evidence.CONTEXT_SQL, {"fixture": fixture_id, "at": at}).fetchall()
                 if r["kind"] != "lineup" and r["provider_player_id"]]
    listed = provider_absences.absences_as_of(conn, fixture_id, at)
    states = av.resolve(av.provider_reports(listed, fixture_id=fixture_id) + av.press_reports(press))
    return [Obs(fixture_id, pid, s.status, s.basis, pid in sheet, sheet.get(pid, False)) for pid, s in sorted(states.items())]


def collect(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, limit: int = 3000, lead: timedelta = LEAD) -> list[Obs]:
    """The observations of the played matches of ``[since, until)`` with both official sheets, newest first, at most ``limit`` matches. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(FIXTURES_SQL, {"since": since, "until": until, "limit": limit}).fetchall()
    out: list[Obs] = []
    for r in rows:
        out += observations(conn, int(r["fixture_id"]), r["kickoff_at"], lead=lead)
    return out


def matches_read(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, limit: int = 3000) -> int:
    """How many played matches with both official sheets the window holds (capped at ``limit``): the denominator of the coverage."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM ({FIXTURES_SQL}) x", {"since": since, "until": until, "limit": limit})
        row = cur.fetchone()
    return int(row[0]) if row else 0


__all__ = ["LEAD", "LEVELS", "MIN_REPORTS", "VERSION", "Obs", "Rate", "collect", "lines", "matches_read", "observations", "rate", "summarize", "wilson"]
