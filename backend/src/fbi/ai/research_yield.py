"""What the web research yields per match and per dollar, by level of importance (plan RP-9.8, experiment EXP-E8, ``research-yield-v1``).

EXP-E8 asks whether any rule for sharing the research gives more confirmed facts per match and per dollar than today's share. Its protocol
(``fbi.research.exp_protocol.E8``) is descriptive and starts with *30 days of counters*: this module is that first step. It counts, for the matches
of a window, what the web search and the extraction cost (the ledger's own path, ``fbi.ai.cost_paths.path_of`` = ``research``) and how many facts
the web gave and how many of them ended CONFIRMED, and groups them by the level of the research order (``fbi.ai.research_order.level_of``, A to D)
as the day plan recorded it when the day opened.

It decides and changes nothing. The criteria to compare (``CRITERIA``: today's share, by uncertainty, by importance) and the sample the protocol asks
for (300 matches per criterion) are the protocol's; ``progress`` says how far the counters are from that sample, so nobody reads a ratio over a
handful of matches as a result. A match with no research cost and no web fact is counted as *not researched*, and is never in a ratio's divisor.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import cost_paths, cost_paths_readers, research_order
from fbi.ai.day import DayFixture

VERSION: Final = "research-yield-v1"
CRITERIA: Final = ("reparto actual", "por incertidumbre", "por importancia")
"""The three criteria of EXP-E8 (the protocol's own words); this step measures only the first, the share in force."""
REQUIRED_PER_CRITERION: Final = 300
"""The sample the protocol asks for, per criterion."""
RESEARCH_PATH: Final = "research"

PLANS_SQL: Final = """
SELECT DISTINCT ON (day) day, universe
  FROM ai.day_plans
 WHERE stage = 'opened' AND created_at >= %(since)s AND created_at < %(until)s
 ORDER BY day, created_at DESC
"""
FACTS_SQL: Final = """
SELECT fixture_id, count(*) AS facts, count(*) FILTER (WHERE status = 'CONFIRMED') AS confirmed
  FROM ai.evidence
 WHERE origin = 'web' AND fixture_id IS NOT NULL AND retrieved_at >= %(since)s AND retrieved_at < %(until)s
 GROUP BY fixture_id
"""


@dataclass(frozen=True, slots=True)
class Match:
    """One match of the window: its level, what the research cost it and what the web gave."""

    fixture_id: int
    level: str
    cost: Decimal = Decimal(0)
    calls: int = 0
    facts: int = 0
    confirmed: int = 0

    @property
    def researched(self) -> bool:
        return self.calls > 0 or self.facts > 0


def fixture_of(entry: Mapping[str, Any]) -> DayFixture:
    """A match of a day plan's universe (the JSON ``DayFixture.as_json`` wrote) as the object the research order reads."""
    odds = entry.get("odds_at")
    league = entry.get("provider_league_id")
    return DayFixture(
        int(entry["fixture_id"]),
        datetime.fromisoformat(str(entry["kickoff_at"])),
        int(entry.get("competition_id") or 0),
        str(entry.get("competition") or ""),
        entry.get("country"),
        None if entry.get("tier") is None else int(entry["tier"]),
        str(entry.get("home") or ""),
        str(entry.get("away") or ""),
        bool(entry.get("has_market")),
        None if odds is None else datetime.fromisoformat(str(odds)),
        None if entry.get("n_bookmakers") is None else int(entry["n_bookmakers"]),
        float(entry.get("priority") or 0.0),
        bool(entry.get("important")),
        None if league is None else int(league),
    )


def levels(plans: Iterable[Sequence[Mapping[str, Any]]]) -> dict[int, str]:
    """The level of each match by the plan of its day (the first plan that lists it wins: a match is listed on one Bogotá day)."""
    out: dict[int, str] = {}
    for universe in plans:
        for entry in universe:
            fixture = fixture_of(entry)
            out.setdefault(fixture.fixture_id, research_order.level_of(fixture))
    return out


def costs(calls: Iterable[cost_paths.Call]) -> dict[int, tuple[Decimal, int]]:
    """The cost and the number of calls of the research (search and extraction) by match; calls with no match belong to none."""
    usd: dict[int, Decimal] = defaultdict(Decimal)
    n: dict[int, int] = defaultdict(int)
    for c in calls:
        if c.fixture_id is None or cost_paths.path_of(c)[0] != RESEARCH_PATH:
            continue
        usd[c.fixture_id] += c.cost
        n[c.fixture_id] += 1
    return {k: (usd[k], n[k]) for k in usd}


def matches(
    level_by_fixture: Mapping[int, str],
    spent: Mapping[int, tuple[Decimal, int]],
    facts: Mapping[int, tuple[int, int]],
) -> list[Match]:
    """Every match with a level, with its cost and its facts (zero when it has none)."""
    out = []
    for fid in sorted(level_by_fixture):
        usd, calls = spent.get(fid, (Decimal(0), 0))
        total, confirmed = facts.get(fid, (0, 0))
        out.append(Match(fid, level_by_fixture[fid], usd, calls, total, confirmed))
    return out


def _ratio(num: Decimal | int, den: Decimal | int) -> float | None:
    return None if not den else float(Decimal(num) / Decimal(den))


def _line(rows: Sequence[Match]) -> dict[str, Any]:
    researched = [m for m in rows if m.researched]
    usd = sum((m.cost for m in researched), Decimal(0))
    facts, confirmed = sum(m.facts for m in researched), sum(m.confirmed for m in researched)
    return {
        "matches": len(rows),
        "researched": len(researched),
        "not_researched": len(rows) - len(researched),
        "cost_usd": float(usd),
        "calls": sum(m.calls for m in researched),
        "facts": facts,
        "confirmed": confirmed,
        "confirmed_share": _ratio(confirmed, facts),
        "confirmed_per_match": _ratio(confirmed, len(researched)),
        "confirmed_per_usd": _ratio(confirmed, usd),
        "usd_per_confirmed": _ratio(usd, confirmed),
    }


def report(rows: Sequence[Match], *, since: datetime, until: datetime) -> dict[str, Any]:
    """The counters of the window: all together and by level, and how far they are from the sample the protocol asks for."""
    by_level = {lv: _line([m for m in rows if m.level == lv]) for lv in research_order.LEVELS}
    total = _line(rows)
    return {
        "version": VERSION,
        "experiment": "EXP-E8",
        "criterion": CRITERIA[0],
        "since": since.isoformat(),
        "until": until.isoformat(),
        "total": total,
        "levels": by_level,
        "progress": {
            "required_per_criterion": REQUIRED_PER_CRITERION,
            "researched": total["researched"],
            "enough": total["researched"] >= REQUIRED_PER_CRITERION,
            "note": "Descriptive counters of the share in force; no criterion is compared until each has its sample.",
        },
    }


def read(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> list[Match]:
    """The matches of the window with their cost and facts, in one read-only snapshot of the caller's connection."""
    window = {"since": since, "until": until}
    with conn.cursor(row_factory=dict_row) as cur:
        plans = [list(r["universe"]) for r in cur.execute(PLANS_SQL, window).fetchall()]
        calls = [
            cost_paths_readers.call_of(r)
            for r in cur.execute(cost_paths_readers.CALLS_SQL, window).fetchall()
        ]
        facts = {
            int(r["fixture_id"]): (int(r["facts"]), int(r["confirmed"]))
            for r in cur.execute(FACTS_SQL, window).fetchall()
        }
    return matches(levels(plans), costs(calls), facts)


def lines(doc: Mapping[str, Any]) -> list[str]:
    """The report in Spanish, one line per level."""

    def row(name: str, d: Mapping[str, Any]) -> str:
        per_match = (
            "sin dato" if d["confirmed_per_match"] is None else f"{d['confirmed_per_match']:.2f}"
        )
        per_usd = "sin dato" if d["confirmed_per_usd"] is None else f"{d['confirmed_per_usd']:.1f}"
        return (
            f"{name}: {d['researched']} investigados de {d['matches']}; US$ {d['cost_usd']:.2f}; hechos {d['facts']}, "
            f"confirmados {d['confirmed']}; por partido {per_match}; por dólar {per_usd}"
        )

    out = [
        f"EXP-E8 · hechos confirmados por partido y por dólar ({doc['criterion']}) · {doc['since'][:10]} a {doc['until'][:10]}",
        row("Total", doc["total"]),
    ]
    out += [row(f"Nivel {lv}", d) for lv, d in doc["levels"].items()]
    p = doc["progress"]
    out.append(
        f"Muestra: {p['researched']} de {p['required_per_criterion']} partidos por criterio"
        + (
            " (suficiente para comparar)"
            if p["enough"]
            else " (todavía insuficiente: solo contadores)"
        )
    )
    return out


__all__ = [
    "CRITERIA",
    "REQUIRED_PER_CRITERION",
    "VERSION",
    "Match",
    "costs",
    "fixture_of",
    "levels",
    "lines",
    "matches",
    "read",
    "report",
]
