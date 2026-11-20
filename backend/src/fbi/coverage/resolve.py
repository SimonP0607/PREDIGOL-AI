"""The seven states of availability of a match, by one function (plan PM, section 4; PM-02-04): the body of C-16's
``GET /matches/{id}/availability``.

For each block of data and each market of a match the matrix answers seven different questions that each module answers today on its
own. Nothing is decided here that a module does not already decide: every state COMPOSES the piece that already answers it.

====  ========================  ==============================================================================================
 n.   state                     the piece it reads
====  ========================  ==============================================================================================
 1    ``exists``                the match's facts (``analytics.coverage_fixture_facts``) or the season's cell: the datum or price arrived
 2    ``coverage_ok``           the season's cell (``analytics.coverage_cells`` / ``analytics.market_availability``) is B or more
 3    ``price_in_force``        the prices in force (``fbi.market.in_force.book``, the Mercados tab's and Mi parlay's reading): at
                                least ``MIN_BOOKS`` houses price one selection now
 4    ``prob_computed``         a forecast of the model is stored for the match and market (``models.predictions``,
                                ``models.match_forecasts``)
 5    ``prob_authorised``       the catalogue holds the market ``evaluable`` (a validated calibrator) and readers may see the forecast
                                (``FBI_FORECAST_USERS``): what C-14 shows a reader
 6    ``settleable``            a settlement rule grades it (``fbi.market.rules.rule_for``) and the season records what it reads
                                (``fbi.market.settle_coverage``, Mi parlay's own test)
 7    ``modules``               Mi parlay: the verdict of every selection exactly as ``fbi.userdata.records.validate_parlay`` gives
                                it for one leg (``fbi.market.eligibility.verdict`` is CALLED, never rewritten); Picks: only an
                                ``evaluable`` market with a forecast; Cuotas: a price in force
====  ========================  ==============================================================================================

The states of a match are never stored: ``load`` reads what they rest on (one read of each table per match) and ``resolve`` is pure. The
API caches the answer 60 seconds (PM-02-05). The reasons use the code's vocabulary: ``sin_cobertura``, ``muestra_insuficiente``,
``no_entregado``, ``sin_regla``, ``menos_de_3_casas``, ``no_ofrecer``, ``interruptor_apagado``, ``linea_de_cuarto``, ``empezado``.

This module reads; it writes nothing and decides no pick. The catalogue's state of a bet and the switches are the API's
(``fbi.coverage`` may not import ``fbi.api``), and Mi parlay's own checks (``fbi.userdata.records``: what a valid selection, a quarter
line and an outlier price are, how a catalogue leg is graded) come in as ``ParlayRules`` - imported here they would tie the domain into
the loop of the API (``tests/unit/test_architecture.py``). The API builds them from Mi parlay's module (``fbi.api.services.availability``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.coverage import levels
from fbi.coverage.job import PHASE_ALL
from fbi.market.eligibility import MIN_BOOKS, spec_for_key, verdict
from fbi.market.in_force import book, implied, key_of, unify
from fbi.market.rules import Rule, rule_for
from fbi.market.settle_coverage import SCORE_FAMILIES, SeasonCoverage
from fbi.odds.quote_current import CurrentQuote
from fbi.odds.quote_taxonomy import BetSpec

CRASH: Final = "error_interno"
"""What Mi parlay does today with a leg its rules take but no house prices (see ``_catalogue_leg``): the request fails."""
COVERED: Final = ("A", "B")
"""A cell is enough (state 2) at B or more."""
FAMILY_OF: Final[dict[str, str]] = {"goals_half": "goals_half", "corners": "corners", "cards": "cards", "shots": "shots",
                                    "players": "players"}
"""The market of the matrix (``levels.MARKETS``) a bet's family is graded in; the four core keys are their own."""
BLOCKS: Final[dict[str, tuple[str, ...]]] = {
    "events": ("events",), "lineups": ("lineups",), "team_stats": ("corners", "yellow_cards", "shots"),
    "shots_on_target": ("shots_on_target",), "fouls": ("fouls",), "xg": ("xg",), "player_stats": ("player_stats",),
    "referee": ("referee",),
}
"""The blocks of a page and the data each rests on: a block is the worst of its data (``levels.worst``)."""


# ── what one match rests on ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ParlayRules:
    """Mi parlay's own checks of one leg (``fbi.userdata.records``), passed in rather than imported."""

    core_markets: frozenset[str]
    """The five settled on the score (``records.CORE_MARKETS``)."""
    lookback: timedelta
    """How old a consensus price may be (``records.SNAPSHOT_LOOKBACK``)."""
    valid_selection: Callable[[str, str, Decimal], bool]
    quarter_line: Callable[[Decimal], bool]
    outlier_price: Callable[[dict[str, Any]], bool]
    grade: Callable[[Rule, str, str, str, Decimal, dict[str, int | None]], object]
    """``fbi.picks.count_settlement.settle_numbers``: raises ``ValueError`` for a selection the rule cannot grade."""


@dataclass(frozen=True, slots=True)
class Cell:
    level: levels.Level
    n: int
    k: int
    provisional: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class Consensus:
    """A row of ``market.market_consensus`` (Mi parlay's price of a core leg: ``fbi.userdata.records.PRICE_SQL``)."""

    market_key: str
    selection: str
    line: Decimal
    as_of: datetime
    best_odds: Decimal | None
    p_fair: Decimal | None
    bookmaker: str | None
    n_bookmakers: int | None


@dataclass(frozen=True, slots=True)
class MatchInputs:
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    competition_season_id: int | None
    at: datetime
    cells: Mapping[str, Cell]
    markets: Mapping[str, Cell]
    present: frozenset[str] | None
    """The data the finished match carries (its facts), None before the match or before the batch measured it."""
    quotes: tuple[CurrentQuote, ...]
    consensus: tuple[Consensus, ...]
    forecasts: frozenset[str]
    covered: Callable[[Rule], bool]
    """The season records what the rule reads: ``SeasonCoverage.covered`` (Mi parlay's own test, read once per rule)."""
    state_of: Callable[[int], str] | None
    parlay_on: bool
    forecast_users: bool
    rules: ParlayRules


# ── the answer ────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModuleVerdict:
    ok: bool
    reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"ok": self.ok} if self.reason is None else {"ok": self.ok, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class SelectionState:
    selection: str
    line: Decimal
    books: int
    mi_parlay: tuple[str, ...]
    """The refusals of Mi parlay for this selection as one leg, in its order (``validate_parlay``); empty: taken."""


@dataclass(frozen=True, slots=True)
class MarketState:
    key: str
    matrix_market: str | None
    catalogue_state: str | None
    exists: bool
    coverage_ok: bool | None
    level: levels.Level | None
    price_in_force: bool
    prob_computed: bool
    prob_authorised: bool
    settleable: bool
    modules: Mapping[str, ModuleVerdict]
    selections: tuple[SelectionState, ...]
    reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"key": self.key, "matrix_market": self.matrix_market, "catalogue_state": self.catalogue_state, "exists": self.exists,
                "coverage_ok": self.coverage_ok, "level": self.level, "price_in_force": self.price_in_force,
                "prob_computed": self.prob_computed, "prob_authorised": self.prob_authorised, "settleable": self.settleable,
                "modules": {k: v.as_json() for k, v in self.modules.items()}, "reason": self.reason,
                "selections": [{"selection": s.selection, "line": str(s.line), "books": s.books,
                                "mi_parlay": {"ok": not s.mi_parlay, **({"reasons": list(s.mi_parlay)} if s.mi_parlay else {})}}
                               for s in self.selections]}


@dataclass(frozen=True, slots=True)
class BlockState:
    exists: bool
    level: levels.Level | None
    n: int
    provisional: bool = False
    reason: str | None = None

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"exists": self.exists, "level": self.level, "n": self.n}
        if self.provisional:
            out["provisional"] = True
        if self.reason:
            out["reason"] = self.reason
        return out


@dataclass(frozen=True, slots=True)
class Availability:
    fixture_id: int
    rules_version: str
    at: datetime
    blocks: Mapping[str, BlockState]
    markets: tuple[MarketState, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "rules_version": self.rules_version, "at": self.at.isoformat(),
                "blocks": {k: v.as_json() for k, v in self.blocks.items()},
                "markets": [m.as_json() for m in self.markets], "notes": list(self.notes)}


# ── Mi parlay, one leg: validate_parlay's own steps, on what was read once ────────────────────────────────────────────


def _price_of_core(inputs: MatchInputs, market_key: str, selection: str, line: Decimal) -> Consensus | None:
    """``fbi.userdata.records._snapshot``: the newest consensus (Shin) of the selection at most ``SNAPSHOT_LOOKBACK`` old."""
    since = inputs.at - inputs.rules.lookback
    found = [c for c in inputs.consensus if c.market_key == market_key and c.selection == selection and c.line == line
             and since <= c.as_of <= inputs.at]
    return max(found, key=lambda c: c.as_of) if found else None


def _catalogue_leg(inputs: MatchInputs, market_key: str, selection: str, line: Decimal) -> tuple[str | None, dict[str, Any] | None]:
    """``fbi.userdata.records._catalogue_leg`` on the prices read once: the refusal (or None) and the price kept."""
    spec = spec_for_key(market_key)
    if spec is None or rule_for(spec) is None:
        return "invalid_selection", None
    rule = rule_for(spec)
    assert rule is not None
    try:
        inputs.rules.grade(rule, spec.kind, spec.subject, selection, line, dict.fromkeys(rule.columns, 0))
    except ValueError:
        return "invalid_selection", None
    quotes = [q for q in unify(inputs.quotes) if key_of(q) == market_key]
    mine = [q for q in quotes if q.selection == selection and q.line == line]
    state = inputs.state_of(spec.bet_id) if inputs.state_of else "en_calibracion"
    v = verdict(spec, line=line, books=len({q.bookmaker_id for q in mine}), state=state,
                started=inputs.kickoff_at <= inputs.at, switch_on=inputs.parlay_on,
                covered=lambda r: _covered(inputs, r))
    if not v.allowed:
        return ("invalid_selection" if v.reason in ("interruptor_apagado", "sin_regla", "no_ofrecer", "sin_cobertura")
                else "quarter_line" if v.reason == "linea_de_cuarto" else "market_not_priced"), None
    if not mine:
        # ``verdict`` takes a core market read through its catalogue key (``match_winner.FT.match``) without counting houses, and
        # ``validate_parlay`` then fails on ``max()`` of no price (a 500, measured on 20-nov-2026): said as it is, never as a refusal.
        return CRASH, None
    top = max(mine, key=lambda q: (q.odds, -q.bookmaker_id))
    fair = implied(quotes).get((selection, line))
    return None, {"best_odds": top.odds, "p_fair": None if fair is None else Decimal(str(round(fair[0], 6)))}


def _covered(inputs: MatchInputs, rule: Rule) -> bool:
    return True if rule.family in SCORE_FAMILIES else inputs.covered(rule)


def parlay_leg(inputs: MatchInputs, market_key: str, selection: str, line: Decimal) -> tuple[str, ...]:
    """The refusals of Mi parlay for one leg, in the order ``validate_parlay`` records them (``leg_count`` and ``same_fixture`` are
    of a parlay, not of a selection). Empty: the leg is taken."""
    errors: list[str] = []
    r = inputs.rules
    core = market_key in r.core_markets
    if core and not r.valid_selection(market_key, selection, line):
        errors.append("invalid_selection")
    if r.quarter_line(line):
        errors.append("quarter_line")
    if inputs.kickoff_at <= inputs.at or inputs.status_group != "scheduled":
        errors.append("started")
        return tuple(errors)
    price: dict[str, Any] | None
    if core:
        found = _price_of_core(inputs, market_key, selection, line)
        price = None if found is None else {"best_odds": found.best_odds, "p_fair": found.p_fair}
    else:
        refused, price = _catalogue_leg(inputs, market_key, selection, line)
        if refused is not None and refused != "quarter_line":
            errors.append(refused)
    if price is not None and r.outlier_price(price):
        errors.append("outlier_price")
    return tuple(errors)


# ── the seven states ──────────────────────────────────────────────────────────────────────────────────────────────────


def matrix_market(spec: BetSpec | None, key: str) -> str | None:
    """The market of the matrix a market key is graded in."""
    if key in levels.MARKETS:
        return key
    if spec is None:
        return None
    if spec.market_key in levels.MARKETS and spec.period == "FT" and spec.subject == "match":
        return spec.market_key
    return FAMILY_OF.get(spec.family)


def _block(inputs: MatchInputs, data: Sequence[str]) -> BlockState:
    cells = [inputs.cells[d] for d in data if d in inputs.cells]
    if inputs.present is not None:
        exists = all(d in inputs.present for d in data)
    else:
        exists = bool(cells) and all(c.k > 0 for c in cells)
    if len(cells) < len(data):
        return BlockState(exists, None, 0, reason="sin_medir")
    level = levels.worst(c.level for c in cells)
    worst = next(c for c in cells if c.level == level)
    reason = worst.reason or ("no_entregado" if not exists and level == "D" else None)
    return BlockState(exists, level, min(c.n for c in cells), any(c.provisional for c in cells), reason)


def _market(inputs: MatchInputs, key: str, quotes: Sequence[CurrentQuote], selections: Sequence[tuple[str, Decimal]]) -> MarketState:
    spec = spec_for_key(key)
    mm = matrix_market(spec, key)
    cell = inputs.markets.get(mm) if mm else None
    books_of: dict[tuple[str, Decimal], set[int]] = defaultdict(set)
    for q in quotes:
        books_of[(q.selection, q.line)].add(q.bookmaker_id)
    most = max((len(b) for b in books_of.values()), default=0)
    in_force = most >= MIN_BOOKS
    state = inputs.state_of(spec.bet_id) if (spec is not None and inputs.state_of) else None
    rule = rule_for(spec) if spec is not None else None
    settleable = rule is not None and _covered(inputs, rule)
    computed = key in inputs.forecasts or (spec is not None and spec.market_key is not None and spec.market_key in inputs.forecasts)
    authorised = computed and state == "evaluable" and inputs.forecast_users
    picked = [SelectionState(s, line, len(books_of.get((s, line), ())), parlay_leg(inputs, key, s, line)) for s, line in selections]
    refusals = Counter(r for s in picked for r in s.mi_parlay[:1])
    parlay = ModuleVerdict(True) if any(not s.mi_parlay for s in picked) else ModuleVerdict(
        False, refusals.most_common(1)[0][0] if refusals else "market_not_priced")
    picks = (ModuleVerdict(True) if state == "evaluable" and computed
             else ModuleVerdict(False, "MERCADO_NO_EVALUABLE" if state != "evaluable" else "SIN_PROBABILIDAD"))
    cuotas = ModuleVerdict(True) if in_force else ModuleVerdict(False, "menos_de_3_casas" if quotes else "sin_precio")
    exists = bool(quotes) or bool(cell and cell.k > 0)
    reason = None
    if rule is None:
        reason = "sin_regla"
    elif not settleable:
        reason = "sin_cobertura"
    elif cell is not None and cell.level not in COVERED:
        reason = cell.reason or ("muestra_insuficiente" if cell.level == "MI" else "sin_cobertura")
    return MarketState(key=key, matrix_market=mm, catalogue_state=state, exists=exists,
                       coverage_ok=None if cell is None else cell.level in COVERED, level=None if cell is None else cell.level,
                       price_in_force=in_force, prob_computed=computed, prob_authorised=authorised, settleable=settleable,
                       modules={"mi_parlay": parlay, "picks": picks, "cuotas": cuotas}, selections=tuple(picked), reason=reason)


def resolve(inputs: MatchInputs) -> Availability:
    """The seven states of every block and market of the match. Pure."""
    blocks = {name: _block(inputs, data) for name, data in BLOCKS.items()}
    by_key: dict[str, list[CurrentQuote]] = defaultdict(list)
    for q in unify(inputs.quotes):
        by_key[key_of(q)].append(q)
    selections: dict[str, set[tuple[str, Decimal]]] = defaultdict(set)
    for key, qs in by_key.items():
        selections[key].update((q.selection, q.line) for q in qs)
    for c in inputs.consensus:
        if c.market_key in inputs.rules.core_markets:
            selections[c.market_key].add((c.selection, c.line))
    for key in sorted(inputs.rules.core_markets):
        selections.setdefault(key, set())
    markets = tuple(_market(inputs, key, by_key.get(key, []), sorted(sel, key=lambda s: (s[1], s[0])))
                    for key, sel in sorted(selections.items()))
    notes: list[str] = []
    if any(b.level == "MI" for b in blocks.values()):
        notes.append("muestra_insuficiente")
    return Availability(inputs.fixture_id, levels.RULES_VERSION, inputs.at, blocks, markets, tuple(notes))


# ── reading ───────────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL: Final = "SELECT id, kickoff_at, status_group, competition_season_id FROM core.fixtures WHERE id = %s"
CELLS_SQL: Final = ("SELECT datum, level, n_finished, n_with_data, provisional, reason FROM analytics.coverage_cells "
                    "WHERE competition_season_id = %s AND phase_key = %s")
MARKETS_SQL: Final = ("SELECT market_key, level, n_window, n_priced, provisional, reason FROM analytics.market_availability "
                      "WHERE competition_season_id = %s")
FACTS_SQL: Final = "SELECT present FROM analytics.coverage_fixture_facts WHERE fixture_id = %s"
CONSENSUS_SQL: Final = """
SELECT m.market_key, m.selection, m.line, m.as_of, m.best_odds, m.p_fair, b.name AS bookmaker, m.n_bookmakers
  FROM market.market_consensus m LEFT JOIN market.bookmakers b ON b.id = m.best_bookmaker_id
 WHERE m.fixture_id = %(fixture)s AND m.devig_method = 'shin' AND m.as_of <= %(at)s AND m.as_of >= %(since)s
"""
"""Mi parlay's price of a core leg (``fbi.userdata.records.PRICE_SQL``), every selection of the match at once."""
FORECASTS_SQL: Final = """
SELECT DISTINCT market_key FROM models.predictions
 WHERE fixture_id = %(fixture)s AND backtest_session_id IS NULL AND data_cutoff_ts <= %(at)s
UNION
SELECT DISTINCT market_key FROM models.match_forecasts WHERE fixture_id = %(fixture)s AND known_at <= %(at)s
"""


def load(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, rules: ParlayRules, parlay_on: bool = False,
         state_of: Callable[[int], str] | None = None, forecast_users: bool = False) -> MatchInputs | None:
    """Everything the states of a match rest on, one read of each table. None for a match that does not exist."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURE_SQL, (fixture_id,))
        f = cur.fetchone()
        if f is None:
            return None
        cs = f["competition_season_id"]
        cells: dict[str, Cell] = {}
        markets: dict[str, Cell] = {}
        if cs is not None:
            cur.execute(CELLS_SQL, (cs, PHASE_ALL))
            cells = {r["datum"]: Cell(r["level"], r["n_finished"], r["n_with_data"], r["provisional"], r["reason"])
                     for r in cur.fetchall()}
            cur.execute(MARKETS_SQL, (cs,))
            markets = {r["market_key"]: Cell(r["level"], r["n_window"], r["n_priced"], r["provisional"], r["reason"])
                       for r in cur.fetchall()}
        cur.execute(FACTS_SQL, (fixture_id,))
        facts = cur.fetchone()
        cur.execute(CONSENSUS_SQL, {"fixture": fixture_id, "at": at, "since": at - rules.lookback})
        consensus = tuple(Consensus(r["market_key"], r["selection"], r["line"], r["as_of"], r["best_odds"], r["p_fair"],
                                    r["bookmaker"], r["n_bookmakers"]) for r in cur.fetchall())
        cur.execute(FORECASTS_SQL, {"fixture": fixture_id, "at": at})
        forecasts = frozenset(str(r["market_key"]) for r in cur.fetchall() if r["market_key"] is not None)
    current = book(conn, fixture_id)
    quotes = tuple(current.quotes) if current else ()
    season = SeasonCoverage(conn, cs)
    return MatchInputs(
        fixture_id=fixture_id, kickoff_at=f["kickoff_at"], status_group=f["status_group"], competition_season_id=cs, at=at,
        cells=cells, markets=markets, present=None if facts is None else frozenset(facts["present"] or ()), quotes=quotes,
        consensus=consensus, forecasts=forecasts, covered=season.covered, state_of=state_of,
        parlay_on=parlay_on, forecast_users=forecast_users, rules=rules)


def availability(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, rules: ParlayRules, parlay_on: bool = False,
                 state_of: Callable[[int], str] | None = None, forecast_users: bool = False) -> Availability | None:
    inputs = load(conn, fixture_id, at=at, rules=rules, parlay_on=parlay_on, state_of=state_of, forecast_users=forecast_users)
    return None if inputs is None else resolve(inputs)

