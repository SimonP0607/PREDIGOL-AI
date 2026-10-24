"""THE DECISION LAYER FOR A FAMILY (plan F11): corners, cards and the goals of the halves go through the same filters as a market of the pipeline -
in SHADOW, under a version of their own, and switched OFF until the owner asks for it.

WHAT IT DOES. The pipeline's decision layer (``fbi.intel.decision``, ``decision-v1``) judges the selections that a shadow rule flagged in
``picks.picks``. The families of F10 state their probabilities in the forecast table of F5 (``models.match_forecasts``, ``family-v1``) and no
pick is ever born from them, so this module is the other door into the same judge: it reads the last forecast of each selection and the prices
the books quoted by the moment of the decision, takes the selections the model sees value in (the rule of the simulated bets of the plan's
criterion, ``fbi.families.bets``: at least 3 % at the best price, a line that cannot push, three or more complete books behind the consensus,
the best line of each market of each match), and gives each one to ``fbi.intel.decision.evaluate`` - the ten filters, the score, the stake -
exactly as it gives it a pick. What is written is a row of ``intel.decisions``, append-only like every other, under ``decision-fam-v1``.

WHAT IT CANNOT DO, ON PURPOSE.

* Nothing a family decides reaches a user. The rows carry a version the picks of the day, the parlays and every page a user can open do not read
  (``tests/unit/test_decision_version_guard.py`` holds every reader of ``intel.decisions`` to say which version it reads). A family's state is
  capped at INVESTIGACION: with no calibrator it cannot go higher (filter 4), and if one ever did, the cap would keep it measured and unstaked
  until the owner lifts it. The stake is zero.
* It does not write a probability, a price or a pick: it reads the forecast and the prices. Rollback is the switch: ``FBI_FAMILY_DECISIONS=off``
  (the default) and the family is back to research - the rows stay as the record of what it said.
* A family states no interval yet (``fbi.families.forecast.market_forecast``), so the filter of the width of the interval cannot judge it: the
  candidate says so (``interval_optional``) and the width is judged the day an interval exists (``FamilySpec.max_width``).

WHAT IS READ AS OF THE MOMENT. The forecast: the last one stored by then. The prices: the last quote in force of every book (``market.odds_quotes``
stores a price once, the first time it is seen, and it stays in force until the next row, so "the last row at or before the moment" is the price),
of the markets the forecasts are about. The age of the price is the age of the last time the fixture's odds were read (the newest consensus of the
fixture): a price that did not change is not an old price.

The cost of a pass is one read of the forecasts of the next 36 hours and one of the quotes of those matches, so the worker runs it once an hour
(``EVERY``), not every quarter of an hour, and a failure of it never fails the pass of the core layer (``run_step``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.core.env import environment
from fbi.families import bets, forecast, versus
from fbi.families.score import key_shape
from fbi.intel import decision
from fbi.intel import stake as staking
from fbi.intel.decision import Evaluated, Key

log = structlog.get_logger(__name__)

VERSION: Final = "decision-fam-v1"
"""The decision version the families decide under: the ``decision_version`` of their rows."""
CORE_VERSION: Final = decision.VERSION
"""The version of the pipeline's decision layer: what every reader that is not about the families reads."""
FORECAST_VERSION: Final = forecast.VERSION
SWITCH: Final = "FBI_FAMILY_DECISIONS"
MODES: Final = ("off", "shadow")
EVERY: Final = timedelta(minutes=60)
"""How often the worker runs the pass: the decide job runs every quarter of an hour, and a pass of the families runs on the first of each hour."""
HORIZON: Final = decision.HORIZON
MIN_EV: Final = bets.MIN_EV
"""The value the model must see at the best price to make a selection a candidate: the floor of the simulated bets of the plan's criterion."""
QUOTE_WINDOW: Final = versus.PRICE_WINDOW
"""How far back a quote can have been first seen and still be in force (the provider keeps the pre-match prices seven days)."""
CHUNK: Final = 100
"""Matches whose quotes are read at a time."""
REASON_RESEARCH: Final = "family_research"
REASON_CAPPED: Final = "family_shadow_only"


def mode() -> str:
    """What the worker does with the families' decisions, by ``FBI_FAMILY_DECISIONS``: ``off`` (the default, and what anything unknown means: no
    pass is run) or ``shadow`` (a pass an hour; the rows are the record of a family that decides without being believed). Read at each run."""
    value = environment().get(SWITCH, "off").strip().lower()
    return value if value in MODES else "off"


@dataclass(frozen=True, slots=True)
class FamilySpec:
    """What a family's selections must show to be candidates, beside what every selection must (``decision.evaluate``)."""

    family: str
    min_books: int = versus.MIN_BOOKS
    """Complete books behind the consensus and the best price."""
    max_width: float | None = None
    """The widest interval (points of probability) a candidate may have. None: no limit. No family stores an interval today, so the width is
    judged only if one appears."""
    min_ev: float = MIN_EV


SPECS: Final[Mapping[str, FamilySpec]] = {s.family: s for s in (
    FamilySpec("GOALS_HALF"), FamilySpec("CORNERS"), FamilySpec("CARDS"), FamilySpec("YELLOW"))}
"""One spec per family of ``fbi.families.forecast.SPECS``. A forecast of a family that is not here is not a candidate."""


# ── what the books quoted ────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AsOfQuote(versus.Quote):
    """A quote of ``versus`` that remembers when it was first seen."""

    captured_at: datetime


@dataclass(frozen=True, slots=True)
class Priced:
    """What the books said of one selection at the moment: the fair probability (the mean over the complete books of their own de-vigged
    probabilities), the best price and who quoted it, and how many complete books stand behind them."""

    p_fair: float
    best_odds: float
    best_bookmaker_id: int
    books: int
    overround: float
    newest_quote: datetime


PriceKey = tuple[int, str, Decimal, str]
"""(match, market key, line, selection)"""

QUOTES_SQL: Final = """
SELECT DISTINCT ON (q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line)
       q.fixture_id, q.bookmaker_id, d.market_key, d.kind, q.selection, q.line, q.odds_decimal, q.captured_at
  FROM market.odds_quotes q JOIN market.market_definitions d ON d.id = q.definition_id
 WHERE q.fixture_id = ANY(%(fixtures)s::bigint[]) AND d.scope = 'prematch' AND d.market_key = ANY(%(keys)s::text[])
   AND d.kind = ANY(%(kinds)s::text[]) AND q.captured_at >= %(since)s AND q.captured_at <= %(at)s
 ORDER BY q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line, q.captured_at DESC
"""
"""The last quote in force of every selection at every book, as of ``at`` (never "the latest": nothing captured after ``at`` is read)."""

OBSERVED_SQL: Final = """
SELECT m.fixture_id, max(m.as_of) AS observed_at
  FROM market.market_consensus m
 WHERE m.fixture_id = ANY(%(fixtures)s::bigint[]) AND m.as_of <= %(at)s AND m.as_of >= %(since)s
 GROUP BY m.fixture_id
"""
"""The last time the odds of each match were read (the newest consensus of any of its markets), by ``at``."""


def load_quotes(conn: psycopg.Connection[Any], *, fixtures: Sequence[int], keys: Sequence[str], at: datetime) -> list[AsOfQuote]:
    """The quotes in force at ``at`` of the markets ``keys`` of the matches ``fixtures``."""
    if not fixtures or not keys:
        return []
    params = {"fixtures": list(fixtures), "keys": list(keys), "kinds": list(versus.OUTCOMES), "since": at - QUOTE_WINDOW, "at": at}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(QUOTES_SQL, params)
        return [AsOfQuote("now", int(r["fixture_id"]), int(r["bookmaker_id"]), str(r["market_key"]), str(r["kind"]), str(r["selection"]),
                          Decimal(r["line"]), float(r["odds_decimal"]), r["captured_at"]) for r in cur.fetchall()]


def price(quotes: Iterable[AsOfQuote]) -> dict[PriceKey, Priced]:
    """The consensus and the best price of every selection that complete books quoted (``versus.complete_books``: every outcome of the market
    once, a believable margin). The best price on a tie is the lowest bookmaker id, so the same quotes always give the same decision."""
    shares: dict[PriceKey, list[float]] = defaultdict(list)
    overrounds: dict[PriceKey, list[float]] = defaultdict(list)
    best: dict[PriceKey, tuple[float, int]] = {}
    newest: dict[PriceKey, datetime] = {}
    for book in versus.complete_books(quotes):
        for m in book.quotes:
            if not isinstance(m, AsOfQuote):  # pragma: no cover - the quotes of this module are all dated
                continue
            k = (book.fixture_id, book.key, book.line, m.selection)
            shares[k].append((1.0 / m.odds) / book.overround)
            overrounds[k].append(book.overround)
            held = best.get(k)
            if held is None or m.odds > held[0] or (m.odds == held[0] and m.bookmaker_id < held[1]):
                best[k] = (m.odds, m.bookmaker_id)
            if k not in newest or m.captured_at > newest[k]:
                newest[k] = m.captured_at
    return {k: Priced(sum(v) / len(v), best[k][0], best[k][1], len(v), sum(overrounds[k]) / len(v), newest[k]) for k, v in shares.items()}


def observed(conn: psycopg.Connection[Any], fixtures: Sequence[int], *, at: datetime) -> dict[int, datetime]:
    """When the odds of each match were last read by ``at`` (absent when they never were in the window)."""
    if not fixtures:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OBSERVED_SQL, {"fixtures": list(fixtures), "at": at, "since": at - QUOTE_WINDOW})
        return {int(r["fixture_id"]): r["observed_at"] for r in cur.fetchall()}


# ── what the families said ───────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Forecast:
    """The last stored forecast of one selection by the moment, and the match it is about."""

    id: int
    fixture_id: int
    family: str
    model: str
    model_version_id: int
    key: str
    line: Decimal
    selection: str
    p: float
    p_model: float
    lo: float | None
    hi: float | None
    calibration: str
    known_at: datetime
    data_cutoff_ts: datetime
    fixture: Mapping[str, Any] = field(compare=False, hash=False)
    """The fixture-level fields ``decision.evaluate`` reads (kick-off, status, teams, competition)."""


FORECASTS_SQL: Final = """
SELECT DISTINCT ON (mf.fixture_id, mf.model_name, mf.market_key, mf.line, mf.selection)
       mf.id, mf.fixture_id, mf.family, mf.model_name, mf.model_version_id, mf.market_key, mf.line, mf.selection, mf.p::float8 AS p,
       mf.p_model::float8 AS p_model, mf.p_lo::float8 AS p_lo, mf.p_hi::float8 AS p_hi, mf.calibration, mf.known_at, mf.data_cutoff_ts,
       f.kickoff_at, f.status_short, f.status_group, f.home_team_id, f.away_team_id, f.competition_season_id, cs.competition_id,
       c.name AS competition_name, th.name AS home_name, ta.name AS away_name
  FROM models.match_forecasts mf
  JOIN core.fixtures f ON f.id = mf.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE mf.version = %(version)s AND mf.known_at <= %(at)s AND f.kickoff_at > %(at)s AND f.kickoff_at < %(until)s
   AND (%(only)s::bigint[] IS NULL OR f.id = ANY(%(only)s))
 ORDER BY mf.fixture_id, mf.model_name, mf.market_key, mf.line, mf.selection, mf.known_at DESC, mf.id DESC
"""
"""The last forecast of each selection of each match that kicks off in the horizon, as stored by ``at``."""

FIXTURE_FIELDS: Final = ("kickoff_at", "status_short", "status_group", "home_team_id", "away_team_id", "competition_season_id",
                         "competition_id", "competition_name", "home_name", "away_name")


def load_forecasts(conn: psycopg.Connection[Any], *, at: datetime, horizon: timedelta = HORIZON, only: Sequence[int] | None = None) -> list[Forecast]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FORECASTS_SQL, {"version": FORECAST_VERSION, "at": at, "until": at + horizon, "only": None if only is None else list(only)})
        return [Forecast(int(r["id"]), int(r["fixture_id"]), str(r["family"]), str(r["model_name"]), int(r["model_version_id"]), str(r["market_key"]),
                         Decimal(r["line"]), str(r["selection"]), float(r["p"]), float(r["p_model"]),
                         None if r["p_lo"] is None else float(r["p_lo"]), None if r["p_hi"] is None else float(r["p_hi"]), str(r["calibration"]),
                         r["known_at"], r["data_cutoff_ts"], {k: r[k] for k in FIXTURE_FIELDS}) for r in cur.fetchall()]


# ── candidates ───────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Candidate:
    """A selection a family sees value in, with the price it would be taken at."""

    forecast: Forecast
    priced: Priced
    price_at: datetime
    believed: float
    """The value the model sees at the best price: ``p x odds - 1``."""

    @property
    def key(self) -> Key:
        f = self.forecast
        return f.fixture_id, f.key, f.selection, f.line.quantize(decision.LINE_Q)

    def row(self) -> dict[str, Any]:
        """The candidate as ``decision.evaluate`` reads a pick: the same names, no pick.

        ``p_model`` is the model's own number (the judge applies the calibrator it knows of to it, as it does to a pick's). ``data_cutoff_ts`` is
        left out on purpose: the forecast table stores a forecast again only when an outcome moves by half a point (``says_something_new``), so
        the age of the row is the time since the last MOVE, not since the model last looked - an old row is a forecast that held, and it is never
        more than half a point from what the model would say now. The judge's rule "a forecast older than 72 h is not a basis" is for a pipeline
        that writes a pick at every run."""
        f, p = self.forecast, self.priced
        return {**f.fixture, "pick_id": None, "forecast_id": f.id, "fixture_id": f.fixture_id, "market_key": f.key, "selection": f.selection,
                "line": f.line, "model_name": f.model, "model_status": "RESEARCH", "model_version_id": f.model_version_id, "p_model": f.p_model,
                "p_push": 0.0, "p_low": f.lo, "p_high": f.hi, "pick_created_at": f.known_at, "data_cutoff_ts": None,
                "p_fair": p.p_fair, "best_odds": p.best_odds, "best_bookmaker_id": p.best_bookmaker_id, "n_bookmakers": p.books,
                "overround": p.overround, "dispersion": None, "price_at": self.price_at, "interval_optional": True}


def candidates(forecasts: Iterable[Forecast], priced: Mapping[PriceKey, Priced], observed_at: Mapping[int, datetime], *,
               specs: Mapping[str, FamilySpec] = SPECS) -> list[Candidate]:
    """The selections the families see value in: the rule of the simulated bets of ``fbi.families.bets`` read at the moment of the decision - a
    line that cannot push, a kind of bet the books' consensus can be built for, ``min_books`` or more complete books, at least ``min_ev`` at the
    best price, and only the best line of each market of each match (the lines of a market are one view of one question)."""
    chosen: dict[tuple[int, str, str], tuple[tuple[float, str, Decimal], Candidate]] = {}
    for f in forecasts:
        spec = specs.get(f.family)
        if spec is None or not versus.comparable(f.line):
            continue
        try:
            kind, _ = key_shape(f.key)
        except ValueError:
            continue
        if kind not in versus.OUTCOMES:
            continue
        found = priced.get((f.fixture_id, f.key, f.line, f.selection))
        if found is None or found.books < spec.min_books:
            continue
        if spec.max_width is not None and f.lo is not None and f.hi is not None and f.hi - f.lo > spec.max_width:
            continue
        believed = found.best_odds * f.p - 1.0
        if believed < spec.min_ev:
            continue
        slot = (f.fixture_id, f.model, f.key)
        rank = (believed, f.selection, f.line)  # the same tie-break as the simulated bets: whatever the order of the rows, the same line
        if slot not in chosen or rank > chosen[slot][0]:
            chosen[slot] = (rank, Candidate(f, found, observed_at.get(f.fixture_id) or found.newest_quote, believed))
    return [c for _, c in sorted(chosen.values(), key=lambda x: (x[1].forecast.fixture_id, x[1].forecast.model, x[1].forecast.key))]


def finalise(e: Evaluated, c: Candidate, spec: FamilySpec) -> Evaluated:
    """What a family adds to a decision: where its forecast came from, why it is only being measured, and the cap. A family is capped at
    INVESTIGACION whatever the filters said, and its stake is zero: a state above that is the owner's to give."""
    f = c.forecast
    for flt in e.filters:
        if flt["key"] == "model":
            flt.setdefault("data", {}).update({"forecast_id": f.id, "forecast_known_at": f.known_at.isoformat(),
                                               "forecast_cutoff": f.data_cutoff_ts.isoformat(), "family": f.family, "calibration": f.calibration})
    e.filters.append(decision._f(  # the filter record is the layer's own shape
        "family", True, f"{f.family} en investigación: pronóstico {f.calibration.lower()}, al menos {spec.min_books} casas completas, valor visto "
        f"{c.believed:+.1%} al mejor precio" + ("" if spec.max_width is None else f", intervalo de {spec.max_width * 100:.0f} puntos como mucho"),
        n=0, family=f.family, min_books=spec.min_books, min_ev=spec.min_ev, max_width=spec.max_width, believed=round(c.believed, 6)))
    e.filters.append(decision._f("correlation", None, "no se aplica: una familia no pasa de investigación, no compite por el partido", n=8))
    e.filters.sort(key=lambda x: x["n"])
    if REASON_RESEARCH not in e.reasons:
        e.reasons.append(REASON_RESEARCH)
    if e.state not in ("RECHAZADO", "INVESTIGACION"):
        e.state = "INVESTIGACION"
        e.premium = e.parlay_eligible = False
        e.reasons.append(REASON_CAPPED)
    if e.state == "INVESTIGACION":
        odds = e.row.get("best_odds")
        e.stake = staking.stake_for("INVESTIGACION", e.p_cal, None if odds is None else float(odds), float(e.row.get("p_push") or 0))
    return e


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class FamilyReport:
    forecasts: int = 0
    fixtures: int = 0
    priced_selections: int = 0
    candidates: int = 0
    evaluated: int = 0
    written: int = 0
    by_family: dict[str, int] = field(default_factory=dict)
    by_state: dict[str, int] = field(default_factory=dict)
    by_reason: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"forecasts": self.forecasts, "fixtures": self.fixtures, "priced": self.priced_selections, "candidates": self.candidates,
                "evaluated": self.evaluated, "written": self.written, "by_family": self.by_family, "by_state": self.by_state,
                "by_reason": self.by_reason}


def read_prices(conn: psycopg.Connection[Any], forecasts: Sequence[Forecast], *, at: datetime) -> dict[PriceKey, Priced]:
    """The consensus and the best price of every selection the forecasts are about, as of ``at``, a few matches at a time."""
    wanted: dict[int, set[str]] = defaultdict(set)
    for f in forecasts:
        try:
            kind, _ = key_shape(f.key)
        except ValueError:
            continue
        if kind in versus.OUTCOMES and versus.comparable(f.line):
            wanted[f.fixture_id].add(f.key)
    out: dict[PriceKey, Priced] = {}
    ordered = sorted(wanted)
    for start in range(0, len(ordered), CHUNK):
        chunk = ordered[start:start + CHUNK]
        out.update(price(load_quotes(conn, fixtures=chunk, keys=sorted(set().union(*(wanted[i] for i in chunk))), at=at)))
    return out


def decide_families(conn: psycopg.Connection[Any], *, at: datetime, horizon: timedelta = HORIZON, only: Sequence[int] | None = None,
                    write: bool = True, specs: Mapping[str, FamilySpec] = SPECS) -> tuple[FamilyReport, list[Evaluated]]:
    """One pass of the families' decisions over the next ``horizon``. Idempotent (the same input twice writes nothing); commits nothing itself.
    With ``write=False`` it reads and judges and writes nothing: the way to see what a pass would do."""
    report = FamilyReport()
    forecasts = load_forecasts(conn, at=at, horizon=horizon, only=only)
    report.forecasts = len(forecasts)
    report.fixtures = len({f.fixture_id for f in forecasts})
    if not forecasts:
        return report, []
    priced = read_prices(conn, forecasts, at=at)
    report.priced_selections = len(priced)
    seen = observed(conn, sorted({f.fixture_id for f in forecasts}), at=at)
    found = candidates(forecasts, priced, seen, specs=specs)
    report.candidates = len(found)
    if not found:
        return report, []
    world = decision.read_world(conn, sorted({c.forecast.fixture_id for c in found}), at=at, version=VERSION)
    out: list[Evaluated] = []
    for c in found:
        e = finalise(decision.evaluate(world, c.key, {c.forecast.model: c.row()}), c, specs[c.forecast.family])
        out.append(e)
        report.evaluated += 1
        report.by_family[c.forecast.family] = report.by_family.get(c.forecast.family, 0) + 1
        report.by_state[e.state] = report.by_state.get(e.state, 0) + 1
        for reason in e.reasons:
            report.by_reason[reason] = report.by_reason.get(reason, 0) + 1
        if write and decision.should_write(e, world.previous.get(e.key)) and decision.store(conn, e, at=at, version=VERSION) is not None:
            report.written += 1
    return report, out


def due(at: datetime) -> bool:
    """Whether the pass of the families runs at ``at``: the decide job comes every quarter of an hour and this one is the first of each hour."""
    return at.minute < EVERY.total_seconds() / 60 / 4


def run_step(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The step of the decide job: nothing while the switch is ``off``; in ``shadow`` the pass of the hour. A failure here is logged and written
    in the record of the run as the step's result - it does not fail the job, whose first duty is the core layer."""
    chosen = mode()
    if chosen == "off":
        return {"mode": chosen}
    if not due(at):
        return {"mode": chosen, "waiting": 1}
    try:
        report, _ = decide_families(conn, at=at)
    except Exception as exc:  # the families are research: a read that fails costs this hour's rows, never the pass of the core layer
        conn.rollback()
        log.error("family_decisions.failed", error=type(exc).__name__, detail=str(exc)[:300])
        return {"mode": chosen, "failed": 1, "error": f"{type(exc).__name__}: {exc}"[:200]}
    return {"mode": chosen, **report.as_dict()}
