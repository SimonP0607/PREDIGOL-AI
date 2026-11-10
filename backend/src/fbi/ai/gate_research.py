"""The gate of research v2 (Plan Maestro IA, phase 2; the research part of Gate B, section 24): ≥ 95 % of v1's evidences with fewer searches.

«Un gate no se aprueba por esta frase»: it passes only on what the database shows over SEVEN COMPLETE DAYS in which research v2 ran in
SHADOW beside v1 - the plan's «v1 y v2 en paralelo una semana». Nothing is simulated and nothing is assumed to have happened: with fewer
complete days the verdict is ``PENDIENTE POR TIEMPO REAL``; only a complete case is ``PASA`` or ``NO PASA`` - and only those two are
recorded (``ai.feature_gates``, gate ``research_v2``, append-only, with the evidence's hash so the report can be reproduced from the
database). ``FBI_AI_RESEARCH_V2=on`` holds only while the NEWEST row of this gate says ``PASA`` (``fbi.ai.gates.research_mode``): a failing
re-run puts research v2 back in shadow by itself.

THE WINDOW. The seven Bogotá days that ended yesterday, all of them days in which EVERY pass of the cycle ran under shadow: each pass row
says which research it ran under (``counts.research_v2_shadow`` / ``research_v2_on``, written by ``fbi.ai.cycle``), so a day on which the word
changed, a deploy restarted the worker with another word, or research v2 replaced v1 is not a day of the measure. A deploy that altered what
research v2 does leaves no row of its own; declaring it (``changed_on``) can only delay the gate.

THE CHECKS (each with its figures; one that cannot be judged is ``None`` and makes the verdict pending, never a pass):

    fewer_searches      the searches research v2 would have paid ALONE (the ones it paid, plus the ones a cache answered - v1 or an earlier pass had
                        paid for them: that is conservative, it can only make the gate harder) are strictly fewer than the ones v1 paid, over
                        the passes in which both finished (a pass in which v2 failed or was cut short by a budget cannot be compared)
    coverage            of the facts v1 found for the matches of the window (who is out, who is in doubt, who plays, the coach, the
                        line-up, the news - one fact per match, side, player and class of assertion), research v2 found at least 95 %
    coverage_players    the same 95 %, asked of the facts about WHO CAN PLAY alone: the plan's «evidencias» weigh a team preview and an absent
                        striker the same, and the absences are what moves a decision (my engineering reading; it can only make the gate harder)
    shadow_invisible    no pick review and no decision of the window cites a claim of research v2: in shadow, v1 decides
    evidence_known      the nightly audit of the data-leakage rule ``evidence_known`` found 0 violations on the days of the window
    sample              at least ``MIN_FIXTURES`` matches and ``MIN_FACTS`` facts of v1 were compared: a coverage over a handful of facts says nothing

Everything here reads: the only thing written is the gate's own row, by ``record``."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai import gates
from fbi.ai.calendar import day_start, local_day
from fbi.ai.config import AiSettings
from fbi.ai.entity_research import AGENT, LEDGER_PREFIX
from fbi.ai.evidence import STALE_AFTER, normalize_name
from fbi.ai.gate_a import Check
from fbi.ai.intervals import Proportion
from fbi.core.decision_versions import DECISION_CORE

GATE: Final = "research_v2"
PASS, FAIL = "PASA", "NO PASA"
PENDING_TIME = "PENDIENTE POR TIEMPO REAL"
WINDOW_DAYS: Final = 7
LOOKBACK_DAYS: Final = 30
"""How far back the days are read to find where the current run of stable days began."""

COVERAGE_MIN: Final = Decimal("0.95")
"""Plan, phase 2 and Gate B: «≥ 95 % de las evidencias de v1»."""
MIN_FIXTURES: Final = 30
MIN_FACTS: Final = 50
"""Floors of the sample, mine: a share of fewer matches or facts says nothing. They can only delay the gate."""
EXAMPLES: Final = 20
"""How many facts of v1 that research v2 did not find the report names."""

SHADOW_MARK: Final = "research_v2_shadow"
ON_MARK: Final = "research_v2_on"
"""The keys the cycle writes in the counts of each pass (``fbi.ai.cycle._pass``)."""

PLAYS: Final = {"out": "out", "doubtful": "doubtful", "available": "plays", "starts": "plays"}
"""The assertions that are about who can play, and the class each one belongs to: «suspended» and «injured» are both «out»."""
KIND_CLASS: Final = {"coach": "coach", "lineup": "lineup", "schedule": "schedule"}
"""Every other kind of evidence that says nothing about a player is «news»."""

Fact = tuple[int, str, str, str]
"""(fixture, side, who, class): ``who`` is a player's surname or ``team``; ``class`` is out / doubtful / plays for a player and
coach / lineup / schedule / news for the rest."""


def _rate(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    return None if not den else (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{value * 100:.2f}"


# ── the window ──────────────────────────────────────────────────────────────────────────────────────────────────

DAYS_SQL = """
SELECT p.day, count(*) AS passes, count(*) FILTER (WHERE p.counts ? 'research_v2_shadow') AS shadow,
       count(*) FILTER (WHERE p.counts ? 'research_v2_on') AS replaced
  FROM ai.fixture_passes p WHERE p.day BETWEEN %(first)s AND %(last)s GROUP BY p.day
"""


@dataclass(frozen=True)
class Window:
    first: date
    last: date
    anchor: date | None
    """The first day of the run of stable days that ends at ``last`` (None when ``last`` itself is not one)."""
    anchored_by: str
    """What ended the run going back from ``last``: the day that was not stable, or a declared change."""
    stable_days: int
    eligible_on: date
    """The earliest day the seven complete days can exist, if research v2 runs in shadow every pass from the next one on."""

    @property
    def complete(self) -> bool:
        return self.stable_days >= WINDOW_DAYS

    def as_json(self) -> dict[str, Any]:
        return {"first": self.first.isoformat(), "last": self.last.isoformat(), "days": WINDOW_DAYS,
                "anchor": None if self.anchor is None else self.anchor.isoformat(), "anchored_by": self.anchored_by,
                "stable_complete_days": self.stable_days, "eligible_on": self.eligible_on.isoformat(), "complete": self.complete}


def window_of(conn: psycopg.Connection[Any], *, at: datetime, through: date | None = None, changes: Sequence[date] = ()) -> Window:
    today = local_day(at)
    last = through or today - timedelta(days=1)
    if last >= today:
        raise ValueError(f"{last} is not a complete day yet (today is {today}): the gate measures complete days only")
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(DAYS_SQL, {"first": last - timedelta(days=LOOKBACK_DAYS - 1), "last": last})
        days = {r[0]: (int(r[1]), int(r[2]), int(r[3])) for r in cur.fetchall()}
    declared = max(changes) if changes else None
    stable, day = 0, last
    blocker = "no pass ran under research v2 in shadow (FBI_AI_RESEARCH_V2 is not shadow, or the worker has not run since)"
    while stable < LOOKBACK_DAYS:
        if declared is not None and day <= declared:
            blocker = f"a change declared by whoever deployed it, on {declared}"
            break
        passes, shadow, replaced = days.get(day, (0, 0, 0))
        if passes == 0:
            blocker = f"{day} had no passes"
            break
        if shadow != passes:
            blocker = (f"{day}: {passes - shadow} of {passes} passes ran without research v2 in shadow"
                       + (f" ({replaced} of them with research v2 instead of v1)" if replaced else ""))
            break
        stable += 1
        day -= timedelta(days=1)
    else:
        blocker = f"{LOOKBACK_DAYS} days in a row"
    anchor = last - timedelta(days=stable - 1) if stable else None
    first = last - timedelta(days=WINDOW_DAYS - 1)
    return Window(first, last, anchor, blocker, stable, last + timedelta(days=WINDOW_DAYS + 1 - min(stable, WINDOW_DAYS)))


# ── the figures ─────────────────────────────────────────────────────────────────────────────────────────────────

PASSES_SQL = "SELECT p.day, p.fixture_id, p.pass, p.counts FROM ai.fixture_passes p WHERE p.day BETWEEN %(first)s AND %(last)s"

FACTS_V1_SQL = """
SELECT f.id AS fixture_id, f.home_team_id, f.away_team_id, e.team_id, e.kind, e.attributes
  FROM core.fixtures f
  JOIN ai.evidence e ON (e.fixture_id = f.id OR (e.fixture_id IS NULL AND e.team_id IN (f.home_team_id, f.away_team_id)))
 WHERE f.id = ANY(%(fixtures)s) AND e.origin = 'web' AND e.subject_type IS NULL
   AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s AND e.retrieved_at <= f.kickoff_at
"""
"""What v1 found for the matches: the items it wrote (``subject_type`` NULL), as the packet reads them (the match's, or a team's with no match)."""
FACTS_V2_SQL = """
SELECT f.id AS fixture_id, f.home_team_id, f.away_team_id, e.team_id, e.kind, e.attributes
  FROM core.fixtures f
  JOIN ai.evidence e ON (e.fixture_id = f.id OR (e.fixture_id IS NULL AND e.team_id IN (f.home_team_id, f.away_team_id)))
 WHERE f.id = ANY(%(fixtures)s) AND e.origin = 'web' AND e.subject_type IS NOT NULL
   AND e.retrieved_at >= %(since)s AND e.retrieved_at < %(until)s AND e.retrieved_at <= f.kickoff_at
   AND COALESCE(e.published_at, e.retrieved_at) > f.kickoff_at - %(stale)s
"""
"""What research v2 found for the same matches: its typed claims, as the packet would read them under ``on`` (the same 10-day bound)."""

SPEND_SQL = """
SELECT COALESCE(left(input_hash, 6) = %(prefix)s, false) AS v2, count(*) AS searches, COALESCE(sum(cost_usd), 0) AS usd
  FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok' AND at >= %(since)s AND at < %(until)s GROUP BY 1
"""
EXTRACTOR_SQL = """
SELECT status, count(*) AS n FROM ai.usage
 WHERE agent = %(agent)s AND purpose = 'evidence_extraction' AND at >= %(since)s AND at < %(until)s GROUP BY status
"""
INVALID_SQL = """
SELECT COALESCE(sum(CASE WHEN jsonb_typeof(p.counts -> 'v2_invalid') = 'number' THEN (p.counts ->> 'v2_invalid')::numeric ELSE 0 END), 0)
  FROM ai.fixture_passes p WHERE p.day BETWEEN %(first)s AND %(last)s
"""
"""Calls whose answer came back and was not ``claim-v1``: the ledger wrote them down as ``ok`` (the provider answered), the pass counted them."""
CITED_SQL = """
SELECT (SELECT count(*) FROM ai.pick_reviews r WHERE r.reviewed_at >= %(since)s AND r.reviewed_at < %(until)s
           AND r.engine IN ('rules', 'llm', 'combined')
           AND EXISTS (SELECT 1 FROM ai.evidence e WHERE e.id = ANY(r.evidence_ids) AND e.subject_type IS NOT NULL)) AS reviews,
       (SELECT count(*) FROM intel.decisions d WHERE d.known_at >= %(since)s AND d.known_at < %(until)s AND d.decision_version = %(layer)s
           AND EXISTS (SELECT 1 FROM ai.evidence e WHERE e.id = ANY(d.evidence_ids) AND e.subject_type IS NOT NULL)) AS decisions
"""
AUDIT_SQL = """
SELECT DISTINCT ON (day) day, n_checked, n_violations FROM intel.audit_checks
 WHERE rule = 'evidence_known' AND day BETWEEN %(first)s AND %(last)s ORDER BY day, checked_at DESC
"""

DAILY_KEYS: Final = ("web_searches", "web_items", "web_new", "v2_demand", "v2_paid", "v2_shared", "v2_reused", "v2_pages", "v2_pages_known",
                     "v2_pages_unread", "v2_pages_flagged", "v2_claims", "v2_invalid", "v2_new", "v2_stored_match", "v2_stored_entity",
                     "v2_failed")


@dataclass
class Searches:
    """The searches of the passes of a run of days, v1's and research v2's, over the passes in which both finished."""

    passes: int = 0
    """Passes that ran under shadow."""
    compared: int = 0
    """... and in which both finished: the ones the figures below are about."""
    failed: int = 0
    """... research v2 failed in them (``v2_failed``)."""
    cut_short: int = 0
    """... research v2 was cut short by a budget or an outage of the search (``v2_skipped_*``)."""
    totals: Counter[str] = field(default_factory=Counter)
    by_day: dict[date, Counter[str]] = field(default_factory=dict)

    @property
    def v1(self) -> int:
        return self.totals["web_searches"]

    @property
    def v2_alone(self) -> int:
        """What research v2 would have paid without v1 beside it: the ones it paid and the ones a cache answered."""
        return self.totals["v2_paid"] + self.totals["v2_shared"]

    @property
    def reuse(self) -> Decimal | None:
        """The share of the needs of research v2 that a fresh answer already satisfied."""
        return _rate(self.totals["v2_reused"], self.totals["v2_reused"] + self.totals["v2_demand"])

    def as_json(self) -> dict[str, Any]:
        saved = self.v1 - self.v2_alone
        return {"passes_in_shadow": self.passes, "passes_compared": self.compared, "passes_v2_failed": self.failed,
                "passes_v2_cut_short": self.cut_short, "searches_v1": self.v1, "searches_v2_alone": self.v2_alone,
                "v2_demand": self.totals["v2_demand"], "v2_paid": self.totals["v2_paid"], "v2_shared": self.totals["v2_shared"],
                "v2_reused": self.totals["v2_reused"], "reuse_pct": _pct(self.reuse), "saved": saved,
                "saved_pct": _pct(_rate(saved, self.v1)),
                "pages_read": self.totals["v2_pages"], "pages_known": self.totals["v2_pages_known"],
                "pages_unread": self.totals["v2_pages_unread"], "pages_flagged": self.totals["v2_pages_flagged"],
                "claims": self.totals["v2_claims"], "claims_new": self.totals["v2_new"], "items_v1": self.totals["web_items"],
                "items_new_v1": self.totals["web_new"],
                "per_day": {d.isoformat(): {k: n for k, n in sorted(c.items()) if n} for d, c in sorted(self.by_day.items())}}


def searches(conn: psycopg.Connection[Any], first: date, last: date) -> Searches:
    out = Searches()
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PASSES_SQL, {"first": first, "last": last})
        rows = cur.fetchall()
    for day, _fixture, _kind, counts in rows:
        if not isinstance(counts, dict) or SHADOW_MARK not in counts:
            continue
        out.passes += 1
        failed = bool(counts.get("v2_failed"))
        short = any(k.startswith("v2_skipped_") for k in counts)
        out.failed += int(failed)
        out.cut_short += int(short and not failed)
        if failed or short:
            continue
        out.compared += 1
        mine = out.by_day.setdefault(day, Counter())
        for key in DAILY_KEYS:
            n = int(counts.get(key) or 0)
            out.totals[key] += n
            mine[key] += n
    return out


def fact_of(side: str, kind: str, assertion: str, player: str | None) -> tuple[str, str, str]:
    """(side, who, class) of one piece of evidence. A player named by the item is a fact about who can play only if the item says something
    about it (out, in doubt, available, starts); everything else is a fact about the side."""
    words = normalize_name(player).split() if player else []
    who = words[-1] if words else "team"
    if assertion in PLAYS:
        return side, who, PLAYS[assertion]
    return side, "team", KIND_CLASS.get(kind, "news")


def _facts(rows: Iterable[Mapping[str, Any]]) -> set[Fact]:
    out: set[Fact] = set()
    for r in rows:
        attributes = r["attributes"] if isinstance(r["attributes"], dict) else {}
        team = r["team_id"]
        side = "home" if team == r["home_team_id"] else "away" if team == r["away_team_id"] else "match"
        player = attributes.get("player_name")
        out.add((int(r["fixture_id"]), *fact_of(side, str(r["kind"]), str(attributes.get("assertion") or "info"),
                                                  str(player) if isinstance(player, str) else None)))
    return out


@dataclass(frozen=True)
class Coverage:
    """What v1 found and what research v2 found for the same matches."""

    fixtures: int
    v1: frozenset[Fact]
    v2: frozenset[Fact]

    def _per_match(self, facts: frozenset[Fact]) -> float | None:
        return round(len(facts) / self.fixtures, 2) if self.fixtures else None

    @property
    def found(self) -> frozenset[Fact]:
        return self.v1 & self.v2

    @property
    def missed(self) -> list[Fact]:
        return sorted(self.v1 - self.v2)

    @staticmethod
    def _players(facts: Iterable[Fact]) -> frozenset[Fact]:
        return frozenset(f for f in facts if f[2] != "team")

    @property
    def rate(self) -> Decimal | None:
        return _rate(len(self.found), len(self.v1))

    @property
    def rate_players(self) -> Decimal | None:
        return _rate(len(self._players(self.found)), len(self._players(self.v1)))

    def as_json(self) -> dict[str, Any]:
        per_fixture = Counter(f[0] for f in self.v1)
        return {"fixtures": self.fixtures, "fixtures_with_facts_of_v1": len(per_fixture), "facts_v1": len(self.v1), "facts_v2": len(self.v2),
                "found_by_v2": len(self.found), "only_v2": len(self.v2 - self.v1), "coverage_pct": _pct(self.rate),
                "facts_about_players_v1": len(self._players(self.v1)), "found_about_players": len(self._players(self.found)),
                "coverage_players_pct": _pct(self.rate_players),
                "facts_per_match_v1": self._per_match(self.v1), "facts_per_match_v2": self._per_match(self.v2),
                "missed_examples": [list(f) for f in self.missed[:EXAMPLES]],
                "interval": Proportion(len(self.found), len(self.v1), COVERAGE_MIN, "min").as_json(),
                "interval_players": Proportion(len(self._players(self.found)), len(self._players(self.v1)), COVERAGE_MIN, "min").as_json()}


def coverage(conn: psycopg.Connection[Any], first: date, last: date) -> Coverage:
    """The facts of v1 and of research v2 for the matches that had a pass under shadow on the days, until each one's kick-off."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(PASSES_SQL, {"first": first, "last": last})
        fixtures = sorted({int(r[1]) for r in cur.fetchall() if isinstance(r[3], dict) and SHADOW_MARK in r[3]})
    if not fixtures:
        return Coverage(0, frozenset(), frozenset())
    args = {"fixtures": fixtures, "since": day_start(first), "until": day_start(last + timedelta(days=1)), "stale": STALE_AFTER}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FACTS_V1_SQL, args)
        v1 = _facts(cur.fetchall())
        cur.execute(FACTS_V2_SQL, args)
        v2 = _facts(cur.fetchall())
    return Coverage(len(fixtures), frozenset(v1), frozenset(v2))


def spend(conn: psycopg.Connection[Any], first: date, last: date) -> dict[str, Any]:
    """The Exa searches the ledger recorded on the days, each arm's (research v2's carry ``rk-v2:`` in their input hash)."""
    out: dict[str, dict[str, Any]] = {"v1": {"searches": 0, "usd": "0"}, "v2": {"searches": 0, "usd": "0"}}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(SPEND_SQL, {"prefix": LEDGER_PREFIX[:6], "since": day_start(first), "until": day_start(last + timedelta(days=1))})
        for is_v2, n, usd in cur.fetchall():
            out["v2" if is_v2 else "v1"] = {"searches": int(n), "usd": str(Decimal(usd))}
    return out


def extractor(conn: psycopg.Connection[Any], first: date, last: date) -> dict[str, Any]:
    """How the claim extractor's calls ended on the days. A call whose answer was not ``claim-v1`` is ``invalid_output`` here as it is when the
    provider itself could not read it: the ledger says ``ok`` for the first (the provider answered), the passes counted them (``v2_invalid``)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(EXTRACTOR_SQL, {"agent": AGENT, "since": day_start(first), "until": day_start(last + timedelta(days=1))})
        by = {str(s): int(n) for s, n in cur.fetchall()}
        cur.execute(INVALID_SQL, {"first": first, "last": last})
        row = cur.fetchone()
    total = sum(by.values())
    content = min(int(row[0]) if row is not None else 0, by.get("ok", 0))
    if content:
        by["ok"] -= content
        by["invalid_output"] = by.get("invalid_output", 0) + content
        by = {k: n for k, n in by.items() if n}
    return {"calls": total, "by_status": dict(sorted(by.items())), "invalid_pct": _pct(_rate(by.get("invalid_output", 0), total))}


# ── the checks ──────────────────────────────────────────────────────────────────────────────────────────────────

def check_searches(s: Searches) -> Check:
    ok = None if s.v1 == 0 else s.v2_alone < s.v1
    return Check("fewer_searches", "Research v2 habría pagado menos búsquedas que v1 (en las pasadas en que las dos terminaron)", ok,
                 s.as_json() | {"rule": "searches_v2_alone < searches_v1"}, revert="FBI_AI_RESEARCH_V2")


def check_coverage(c: Coverage) -> Check:
    ok = None if not c.v1 else (c.rate or Decimal(0)) >= COVERAGE_MIN
    return Check("coverage", "Research v2 encontró ≥ 95 % de las evidencias de v1", ok, c.as_json() | {"minimum_pct": _pct(COVERAGE_MIN)},
                 revert="FBI_AI_RESEARCH_V2")


def check_players(c: Coverage) -> Check:
    players = c._players(c.v1)
    ok = None if not players else (c.rate_players or Decimal(0)) >= COVERAGE_MIN
    return Check("coverage_players", "... y ≥ 95 % de las que dicen quién puede jugar", ok,
                 {"facts_about_players_v1": len(players), "found_about_players": len(c._players(c.found)),
                  "coverage_players_pct": _pct(c.rate_players), "minimum_pct": _pct(COVERAGE_MIN),
                  "missed_examples": [list(f) for f in c.missed if f[2] != "team"][:EXAMPLES],
                  "interval": Proportion(len(c._players(c.found)), len(players), COVERAGE_MIN, "min").as_json()}, revert="FBI_AI_RESEARCH_V2")


def check_sample(c: Coverage) -> Check:
    fixtures = len({f[0] for f in c.v1})
    ok = True if fixtures >= MIN_FIXTURES and len(c.v1) >= MIN_FACTS else None
    return Check("sample", f"Se compararon ≥ {MIN_FIXTURES} partidos y ≥ {MIN_FACTS} hechos de v1", ok,
                 {"fixtures_with_facts_of_v1": fixtures, "facts_v1": len(c.v1), "minimum_fixtures": MIN_FIXTURES, "minimum_facts": MIN_FACTS})


def check_invisible(conn: psycopg.Connection[Any], first: date, last: date) -> Check:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CITED_SQL, {"since": day_start(first), "until": day_start(last + timedelta(days=1)), "layer": DECISION_CORE})
        row = cur.fetchone()
    assert row is not None
    reviews, decisions = int(row["reviews"]), int(row["decisions"])
    return Check("shadow_invisible", "Ninguna revisión ni decisión de la ventana cita una afirmación de research v2 (en sombra decide v1)",
                 reviews == 0 and decisions == 0, {"reviews_citing": reviews, "decisions_citing": decisions}, revert="FBI_AI_RESEARCH_V2")


def check_audit(conn: psycopg.Connection[Any], first: date, last: date) -> Check:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(AUDIT_SQL, {"first": first, "last": last})
        rows = {r[0]: (int(r[1]), int(r[2])) for r in cur.fetchall()}
    violations = sum(v for _, v in rows.values())
    needed = WINDOW_DAYS - 1
    ok: bool | None = False if violations else (True if len(rows) >= needed else None)
    return Check("evidence_known", "La auditoría nocturna `evidence_known` sin violaciones en los días de la ventana", ok,
                 {"days_audited": len(rows), "days_needed": needed, "checked": sum(n for n, _ in rows.values()), "violations": violations,
                  "note": "the audit of the latest night may not have run when the window closes"})


# ── the gate ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateReport:
    verdict: str
    at: datetime
    window: Window
    checks: tuple[Check, ...] = ()
    pending: tuple[str, ...] = ()
    consequence: str | None = None
    preview: dict[str, Any] = field(default_factory=dict)

    @property
    def recordable(self) -> bool:
        return self.verdict in (PASS, FAIL)

    def as_json(self) -> dict[str, Any]:
        return {"gate": GATE, "verdict": self.verdict, "at": self.at.isoformat(), "window": self.window.as_json(),
                "checks": [c.as_json() for c in self.checks], "pending": list(self.pending), "consequence": self.consequence,
                "preview": self.preview, "recorded_only_if": "PASA or NO PASA"}

    def lines(self) -> list[str]:
        w = self.window
        out = [f"GATE DE RESEARCH V2 · {self.verdict}", f"Ventana: {w.first} a {w.last} (7 días completos, hora de Bogotá)",
               f"{w.stable_days} día(s) completo(s) de 7 con research v2 en sombra en todas las pasadas"
               + (f" (desde {w.anchor})" if w.anchor else "")]
        for c in self.checks:
            out.append(f"  [{c.mark}] {c.title}")
            i = c.detail.get("interval")
            if i and i.get("cases"):
                ci = i.get("ci95_wilson_pct") or ["-", "-"]
                out.append(f"      {i['counted']}/{i['cases']} · {i['pct']} % · IC95 {ci[0]}-{ci[1]} % · umbral ≥ {i['threshold_pct']} % · "
                           f"resultado del check: {c.mark}")
        out += [f"  Falta: {p}" for p in self.pending]
        if self.consequence:
            out.append(f"Consecuencia: {self.consequence}")
        return out


def evaluate(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, through: date | None = None,
             changes: Sequence[date] = ()) -> GateReport:
    w = window_of(conn, at=at, through=through, changes=changes)
    if not w.complete:
        if w.stable_days:
            need = (f"{w.stable_days} de {WINDOW_DAYS} días completos con research v2 en sombra en todas las pasadas (desde {w.anchor}); "
                    f"el primer día evaluable es {w.eligible_on}")
        else:
            need = (f"ningún día completo con research v2 en sombra en todas las pasadas ({w.anchored_by}); "
                    f"el primer día evaluable sería {w.eligible_on}, si empieza en la próxima pasada")
        if settings.research_v2 == "off":
            need += " (en este entorno FBI_AI_RESEARCH_V2 es off: hay que ponerlo en shadow)"
        preview: dict[str, Any] = {"note": "NOT evidence of the gate: only what the days gone show", "stable_complete_days": w.stable_days}
        if w.stable_days:
            first = w.last - timedelta(days=w.stable_days - 1)
            preview |= {"days": [first.isoformat(), w.last.isoformat()], "searches": searches(conn, first, w.last).as_json(),
                        "coverage": coverage(conn, first, w.last).as_json()}
        return GateReport(PENDING_TIME, at, w, pending=(need,), preview=preview)
    s = searches(conn, w.first, w.last)
    c = coverage(conn, w.first, w.last)
    checks = (Check("window", "7 días completos con research v2 en sombra en todas las pasadas", True, w.as_json()), check_searches(s),
              check_coverage(c), check_players(c), check_invisible(conn, w.first, w.last), check_audit(conn, w.first, w.last), check_sample(c))
    extra = {"exa": spend(conn, w.first, w.last), "extractor": extractor(conn, w.first, w.last)}
    pending = tuple(f"{k.title}: no hay datos para juzgarlo" for k in checks if k.ok is None)
    if pending:
        return GateReport(PENDING_TIME, at, w, checks, pending, preview={
            "failing_now": [k.id for k in checks if k.ok is False], "note": "NOT a verdict: the evidence it needs is missing", **extra})
    failed = [k for k in checks if k.ok is False]
    if failed:
        return GateReport(FAIL, at, w, checks, preview=extra, consequence=consequence(failed))
    return GateReport(PASS, at, w, checks, preview=extra)


def consequence(failed: Sequence[Check]) -> str:
    """What follows a NO PASA: nothing is switched by hand - ``on`` behaves as ``shadow`` while the newest row does not pass - and the plan's
    answer is to correct and compare again (Gate B: «la sombra sigue y se corrige»)."""
    ids = {k.id for k in failed}
    if "shadow_invisible" in ids:
        return ("research v2 salió de la sombra: se pone FBI_AI_RESEARCH_V2=off hasta corregir el lector que cita sus afirmaciones, "
                "y la semana de comparación vuelve a empezar")
    return ("research v2 sigue en sombra (con FBI_AI_RESEARCH_V2=on se comporta como shadow mientras esta evidencia no pase): se corrige lo "
            "que falle - consultas, frescura por tema o extracción, con versión nueva - y la semana de comparación vuelve a empezar")


def record(conn: psycopg.Connection[Any], report: GateReport, *, code_version: str | None = None) -> int | None:
    """Append the gate's row - ``PASA`` or ``NO PASA`` only; a pending report is not evidence and writes nothing. The caller commits.
    Returns the row's id, None when nothing was written."""
    if not report.recordable:
        return None
    return gates.record_gate(conn, gate=GATE, passed=report.verdict == PASS, evidence=report.as_json(), at=report.at, decided_by="script",
                             code_version=code_version)
