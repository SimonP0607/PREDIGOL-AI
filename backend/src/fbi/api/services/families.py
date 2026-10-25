"""THE FAMILIES IN SHADOW for the Admin Console (plan F10.17 and F11.11): what corners, cards and the goals of the halves decided, the rule that
grades each bet, what became of it, the post-mortem the families made of it and what they remember. Reading only.

The families decide in SHADOW (``FBI_FAMILY_DECISIONS``, off by default) under versions of their own - ``decision-fam-v1`` for the decision,
``outcome-fam-v1`` for its settlement, ``pm-fam-v1`` for the post-mortem and ``memory-fam-v1`` for the memory - in rows that are never a pick: a
decision of a family has no pick, its state is capped at INVESTIGACION (a selection being measured) or RECHAZADO (the filters refused it) and its
stake is zero. This page is where they are read: the LAST word of each family's model on each market of each match (the revisions of the hourly
pass are the same bet seen again, and the post-mortem studies only that last word), with the rule that settles it, the outcome, the verdict of luck
against decision and the causes the post-mortem found.

It reads the tables by SQL and imports nothing of ``fbi.families`` or ``fbi.familydecisions``: a package that serves the console does not pull the
research into its import cycle (``tests/unit/test_architecture.py`` holds the cycle at eight packages), so the few facts of the families it needs
- which they are, how a market key maps to the rule that grades it (those two live in ``fbi.api.services.family_rules``, which the readers of what is
said before a kick-off share), which steps they run in - are written here and held equal to the code by ``tests/unit/test_api_families.py``.
Nothing it reads is an input of anything said before a kick-off (``tests/unit/test_postmortem_isolation.py``), and for that reason no reader of what
is said before one imports this module."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services.family_rules import FAMILIES, MEASURES, measure_of, rule_of
from fbi.api.services.intelligence import j
from fbi.core.clock import now
from fbi.core.decision_versions import (
    DECISION_FAMILIES,
    MEMORY_FAMILIES,
    OUTCOME_FAMILIES,
    POSTMORTEM_FAMILIES,
)
from fbi.market.rules import RULES_BY_MEASURE, Rule

FORECAST_VERSION: Final = "family-v1"
"""The version of the forecasts the families state (``fbi.families.forecast.VERSION``): held equal by a test."""
STEPS: Final = ("families", "family_outcomes", "family_postmortems", "family_memory")
"""The steps the worker hands to its jobs while the switch is not off, in the order they run (``apps.worker.scheduler``): the decision, in the
job that decides every quarter of an hour, and the three that learn, in the nightly one. Held equal by a test."""
STEP_JOBS: Final = ("decide", "nightly")
STEPS_LOOKBACK: Final = timedelta(days=7)
"""How far back the runs are looked at for the last time of each step."""
STEP_RUNS: Final = 8
"""The latest runs of a step that are read: the decision is a step of a job that comes every quarter of an hour and works once an hour, so the
last pass that did something is among the latest four."""
LEAD: Final = timedelta(days=3)
"""How long before a kick-off a decision can have been taken (the horizon of the decisions is 36 hours, ``fbi.familydecisions.decide.HORIZON``: held
by a test); it only lets the query use the index on the moment of the decision."""
DEFAULT_DAYS: Final = 14
MAX_DAYS: Final = 120
MEMORY_TOP: Final = 25
"""The competitions and the referees whose memory is listed (the ones with the most post-mortems): there are hundreds, and the page is for the
families and the markets first."""

STATES: Final = ("INVESTIGACION", "RECHAZADO")
UNKNOWN: Final = "UNKNOWN"


# ── what the families are ────────────────────────────────────────────────────────────────────────────────────────────────

def rule_view(rule: Rule) -> dict[str, Any]:
    """A rule as the console shows it: what is measured, in which convention (the registry's own words, in English), from which columns of the
    finished match and whether it can grade at all."""
    return {"key": rule.key, "measure": rule.measure, "version": rule.version, "period": rule.period, "convention": rule.convention,
            "columns": list(rule.columns), "liquidable": rule.liquidable, "note": rule.note}


def rules_of_families() -> dict[str, dict[str, Any]]:
    """The rules that grade the bets of the families, by key: the ones every card says it settles with."""
    found = (RULES_BY_MEASURE[m] for measures in MEASURES.values() for m in measures if m in RULES_BY_MEASURE)
    return {r.key: rule_view(r) for r in sorted(found, key=lambda r: r.key)}


def rules_for(family: str) -> list[str]:
    """The keys of the rules that grade the bets of a family."""
    return [RULES_BY_MEASURE[m].key for m in MEASURES.get(family, ()) if m in RULES_BY_MEASURE]


# ── what is read ─────────────────────────────────────────────────────────────────────────────────────────────────────────

LAST_SQL: Final = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.model_name, d.market_key)
           d.id, d.fixture_id, d.model_name, d.market_key, d.selection, d.line, d.known_at, d.checkpoint, d.kickoff_at, d.state, d.odds,
           d.n_bookmakers, d.p_model, d.p_market, d.ev_raw, d.stake_units, d.reasons,
           jsonb_path_query_first(d.filters, '$[*] ? (@.key == "model").data') AS forecast,
           count(*) OVER (PARTITION BY d.fixture_id, d.model_name, d.market_key) AS revisions
      FROM intel.decisions d
     WHERE d.decision_version = %(decision_version)s AND d.pick_id IS NULL AND d.odds IS NOT NULL
       AND d.known_at >= %(since)s - %(lead)s::interval AND d.kickoff_at >= %(since)s
     ORDER BY d.fixture_id, d.model_name, d.market_key, d.known_at DESC, d.id DESC
), seen AS (
    SELECT l.*, coalesce(l.forecast ->> 'family', 'UNKNOWN') AS family,
           o.result_status, o.profit_flat, o.close_odds, o.close_p_fair, o.close_minutes_to_ko, o.clv,
           p.verdict, p.quality, p.causes, p.actual, p.margin
      FROM last l
      LEFT JOIN intel.decision_outcomes o ON o.decision_id = l.id AND o.version = %(outcome_version)s
      LEFT JOIN intel.family_postmortems p ON p.decision_id = l.id AND p.version = %(postmortem_version)s
)
"""
"""The last word of every model on every market of every match that kicks off in the window: the revisions of a selection are the same bet seen
again, so the last one is the family's word (the post-mortem studies that one: ``fbi.familydecisions.postmortem.STOOD_SQL``), with what became of
it. The rows are those of the versions of the families and never a pick's."""

TOTALS_SQL: Final = LAST_SQL + """
SELECT family, state, result_status, verdict, count(*) AS n
  FROM seen GROUP BY 1, 2, 3, 4
"""
"""How many last words there are of each family, state, result and verdict: the cards and the total are made of it."""

ITEMS_SQL: Final = LAST_SQL + """
SELECT s.*, th.name AS home, ta.name AS away, c.name AS competition, c.country
  FROM seen s
  JOIN core.fixtures f ON f.id = s.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (%(family)s::text IS NULL OR s.family = %(family)s) AND (%(state)s::text IS NULL OR s.state = %(state)s)
 ORDER BY s.kickoff_at DESC, s.id DESC
 LIMIT %(limit)s
"""
"""The last words matching the filters, the newest match first, with the names the console shows."""

MEMORY_SQL: Final = """
WITH newest AS (
    SELECT DISTINCT ON (m.entity_type, m.entity_key) m.*
      FROM intel.family_memory m
     WHERE m.version = %(version)s
     ORDER BY m.entity_type, m.entity_key, m.as_of_day DESC, m.id DESC
), ranked AS (
    SELECT n.*, row_number() OVER (PARTITION BY n.entity_type ORDER BY (n.stats #>> '{all,n}')::int DESC NULLS LAST, n.entity_key) AS rn
      FROM newest n
)
SELECT entity_type, entity_key, entity_name, version, as_of_day, built_at, confidence::float8 AS confidence, stats, delta, evidence_ref
  FROM ranked
 WHERE entity_type IN ('family', 'market') OR rn <= %(top)s
 ORDER BY CASE entity_type WHEN 'family' THEN 0 WHEN 'market' THEN 1 WHEN 'competition' THEN 2 ELSE 3 END,
          (stats #>> '{all,n}')::int DESC NULLS LAST, entity_key
"""
"""What the families remember: the newest snapshot of ``memory-fam-v1`` of each family, market, competition and referee - every family and market, and
the competitions and referees with the most post-mortems behind them."""

STEPS_SQL: Final = """
SELECT s.step, r.id AS run_id, r.job, r.started_at, r.finished_at, r.status, r.counts -> s.step AS result,
       r.counts -> (s.step || '_ms') AS ms, r.errors
  FROM unnest(%(steps)s::text[]) AS s(step)
 CROSS JOIN LATERAL (
       SELECT x.* FROM intel.runs x
        WHERE x.job = ANY(%(jobs)s::text[]) AND x.started_at >= %(since)s AND x.counts ? (s.step || '_ms')
        ORDER BY x.started_at DESC, x.id DESC LIMIT %(per)s) r
 ORDER BY s.step, r.started_at DESC, r.id DESC
"""
"""The latest runs of the jobs that carry a step of the families, for each step: a run that ran the step has its milliseconds in the counts (a
step that raised has them too, and no result)."""


# ── what is made of it ───────────────────────────────────────────────────────────────────────────────────────────────────

def _number(x: Any) -> float | None:
    return None if x is None else float(x)


def item_of(row: Mapping[str, Any]) -> dict[str, Any]:
    """One last word as the console shows it. ``rule`` is the key of the rule that grades the bet (its words are in ``rules``)."""
    forecast = row["forecast"] if isinstance(row["forecast"], dict) else None
    rule = rule_of(str(row["market_key"]))
    causes = row["causes"] if isinstance(row["causes"], list) else []
    return {
        "id": int(row["id"]), "fixture_id": int(row["fixture_id"]), "kickoff_at": row["kickoff_at"], "known_at": row["known_at"],
        "checkpoint": row["checkpoint"], "match": f"{row['home']} - {row['away']}", "home": row["home"], "away": row["away"],
        "competition": row["competition"], "country": row["country"], "family": row["family"], "model_name": row["model_name"],
        "market_key": row["market_key"], "selection": row["selection"], "line": _number(row["line"]), "odds": _number(row["odds"]),
        "n_bookmakers": row["n_bookmakers"], "p_model": _number(row["p_model"]), "p_market": _number(row["p_market"]),
        "ev_raw": _number(row["ev_raw"]), "state": row["state"], "stake_units": _number(row["stake_units"]),
        "reasons": list(row["reasons"] or []), "revisions": int(row["revisions"]),
        "forecast": None if forecast is None else {"forecast_id": forecast.get("forecast_id"), "known_at": forecast.get("forecast_known_at"),
                                                    "calibration": forecast.get("calibration")},
        "rule": None if rule is None else rule.key,
        "outcome": None if row["result_status"] is None else {
            "result": row["result_status"], "profit_flat": _number(row["profit_flat"]), "close_odds": _number(row["close_odds"]),
            "close_p_fair": _number(row["close_p_fair"]), "close_minutes_to_ko": row["close_minutes_to_ko"], "clv": _number(row["clv"])},
        "postmortem": None if row["verdict"] is None else {
            "verdict": row["verdict"], "quality": row["quality"],
            "causes": [str(c["text"]) for c in causes if isinstance(c, dict) and c.get("text")],
            "actual": _number(row["actual"]), "margin": _number(row["margin"])},
    }


def card_of(family: str, totals: Iterable[Mapping[str, Any]], memory: Mapping[str, Any] | None) -> dict[str, Any]:
    """The card of a family from the counts of its last words: the selections (INVESTIGACION) and those the filters refused, how many of the
    selections are settled and how many wait, the results and the verdicts, and the newest snapshot of what the family remembers."""
    selections = rejected = settled = 0
    results: dict[str, int] = defaultdict(int)
    verdicts: dict[str, int] = defaultdict(int)
    for t in totals:
        if t["family"] != family:
            continue
        n = int(t["n"])
        if t["state"] == "RECHAZADO":
            rejected += n
            continue
        selections += n
        if t["result_status"] is not None:
            settled += n
            results[str(t["result_status"])] += n
        if t["verdict"] is not None:
            verdicts[str(t["verdict"])] += n
    return {"family": family, "selections": selections, "rejected": rejected, "settled": settled, "open": selections - settled,
            "results": dict(results), "verdicts": dict(verdicts), "rules": rules_for(family), "memory": memory}


def families_seen(totals: Iterable[Mapping[str, Any]]) -> list[str]:
    """The families of the cards: the four there are, and any other a decision names (a family added to the code before the console learns it)."""
    named = {str(t["family"]) for t in totals}
    return [*FAMILIES, *sorted(named - set(FAMILIES))]


def last_pass(runs: Sequence[Mapping[str, Any]], step: str) -> dict[str, Any] | None:
    """The latest run of a step that WORKED, from its runs newest first. The decision is a step of a job that comes every quarter of an hour and
    returns ``waiting`` three times out of four: those say nothing of the families and are passed over. A run that raised is a run: it is shown with its
    error and no result."""
    for r in runs:
        result = r["result"] if isinstance(r["result"], dict) else None
        if step == "families" and result is not None and "forecasts" not in result:
            continue  # the pass of the hour had not come, or the switch was off: nothing was looked at
        error = next((e for e in (r["errors"] or []) if isinstance(e, str) and e.startswith(f"{step}:")), None)
        return {"step": step, "job": r["job"], "run_id": int(r["run_id"]), "started_at": r["started_at"], "finished_at": r["finished_at"],
                "status": r["status"], "ms": None if r["ms"] is None else int(r["ms"]), "result": result or {}, "error": error}
    return None


def steps_of(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The last time each step of the cycle ran, in the order the cycle runs them; a step that has not run in the lookback is not listed."""
    by_step: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_step[str(r["step"])].append(r)
    return [found for step in STEPS if (found := last_pass(by_step.get(step, ()), step)) is not None]


def mode_of(steps: Sequence[Mapping[str, Any]]) -> str | None:
    """What the worker did in its latest run of a step of the families (``shadow``, or ``off``), or None when none ran in the lookback: the page
    does not read the worker's environment, it says what the runs recorded."""
    stamped = [s for s in steps if isinstance(s["result"].get("mode"), str)]
    if not stamped:
        return None
    return str(max(stamped, key=lambda s: (s["started_at"], s["run_id"]))["result"]["mode"])


def total_of(totals: Iterable[Mapping[str, Any]], *, family: str | None, state: str | None) -> int:
    """How many last words there are that match the filters of the list."""
    return sum(int(t["n"]) for t in totals if (family is None or t["family"] == family) and (state is None or t["state"] == state))


def belongs(memory: Mapping[str, Any], family: str) -> bool:
    """Whether a snapshot of a family or of a market is the family's: a family by its key, a market by the family its key belongs to."""
    if memory["entity_type"] == "family":
        return bool(memory["entity_key"] == family)
    measure = measure_of(str(memory["entity_key"]))
    return measure is not None and measure in MEASURES.get(family, ())


def overview(conn: Conn, *, family: str | None = None, state: str | None = None, days: int = DEFAULT_DAYS, limit: int = 200,
             at: datetime | None = None) -> Envelope[dict[str, Any]]:
    """THE FAMILIES IN SHADOW: the cycle's steps and when they last ran, a card per family, the last words matching the filters with the rule that
    grades each, what became of it and its post-mortem, the rules, and what the families remember. Every block may be empty: the switch is off
    until the owner asks, and a young database has nothing to show."""
    moment = at or now()
    since = moment - timedelta(days=days)
    params = {"decision_version": DECISION_FAMILIES, "outcome_version": OUTCOME_FAMILIES, "postmortem_version": POSTMORTEM_FAMILIES,
              "since": since, "lead": LEAD}
    totals = fetch_all(conn, TOTALS_SQL, params)
    items = fetch_all(conn, ITEMS_SQL, {**params, "family": family, "state": state, "limit": limit})
    memory = fetch_all(conn, MEMORY_SQL, {"version": MEMORY_FAMILIES, "top": MEMORY_TOP})
    steps = steps_of(fetch_all(conn, STEPS_SQL, {"steps": list(STEPS), "jobs": list(STEP_JOBS), "since": moment - STEPS_LOOKBACK,
                                                 "per": STEP_RUNS}))
    own = {str(m["entity_key"]): m for m in memory if m["entity_type"] == "family"}
    cards = [card_of(f, totals, own.get(f)) for f in families_seen(totals)]
    shown = [m for m in memory if family is None or m["entity_type"] in ("competition", "referee") or belongs(m, family)]
    return ok(j({
        "versions": {"forecast": FORECAST_VERSION, "decision": DECISION_FAMILIES, "outcome": OUTCOME_FAMILIES,
                     "postmortem": POSTMORTEM_FAMILIES, "memory": MEMORY_FAMILIES},
        "window": {"days": days, "from": since, "to": moment}, "mode": mode_of(steps), "steps": steps, "families": cards,
        "items": [item_of(r) for r in items], "total": total_of(totals, family=family, state=state),
        "rules": rules_of_families(), "memory": shown,
    }))
