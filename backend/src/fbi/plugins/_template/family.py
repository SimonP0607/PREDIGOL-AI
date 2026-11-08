"""TEAM_TOTALS: the goals of ONE side over / under a line (provider bets 16 "Total - Home" and 17 "Total - Away", catalogue keys
``OU_HOME`` / ``OU_AWAY``), derived from the ``sim-v1`` joint distribution of the match. The worked example of a plug-in family:
SHADOW, never ACTIVE (``activatable=False``), not installed.

DATA. The taxonomy extracts bets 16 and 17 (status CANDIDATE: priced, not studied); the catalogue derives ``OU_HOME`` / ``OU_AWAY``
from them, graded by ``goals_ft@v1`` (the goals of the side after 90 minutes) with ``fbi.picks.count_settlement.settle_numbers``.

MODEL. No new fit. The Dixon-Coles model in force for the match (its newest real-time forecast by the moment, never after kick-off) is
read as sim-v1 reads it (``fbi.simulator.consistency.in_force`` / ``invert``: its seven fixed rows give its expected goals and rho), the
joint is built (``fbi.simulator.joint.build``), and P(side's goals > line) is a sum over it (``fbi.simulator.markets``, ``TT_HOME`` /
``TT_AWAY``). The same joint gives the dependence of a team total with any goals market of the match the joint settles (1X2, OU, BTTS,
AH): the portfolio's correlation provider. Model name: ``MODEL``; the calibrator slots are (``OU_HOME`` | ``OU_AWAY``, ``MODEL``) -
none exists, so decision-v2 abstains at the calibration stage before the SHADOW cap even applies.

DECISION. The candidates are decision-fam-v1's rule (``fbi.familydecisions.decide.candidates``) applied to the derived probabilities:
a half line, at least ``versus.MIN_BOOKS`` complete books, ``MIN_EV`` at the best price, the best line of each market of each match.
The prices are the quotes in force (``read_prices``) and the age is when the match's odds were last read (``observed``), as for the
families of F10.

Read-only: SELECTs only, nothing written, nothing committed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Protocol

import psycopg
from psycopg.rows import dict_row

from fbi.decision.families import Candidate, FamilyParams, GateStatus, SettlementRule, gate_of
from fbi.familydecisions import decide as fd
from fbi.intel import decision
from fbi.plugins.family import SHADOW, FamilyPlugin, SelectionLike
from fbi.simulator import VERSION as SIM_VERSION
from fbi.simulator import consistency
from fbi.simulator import joint as jt
from fbi.simulator.markets import TEAM_LINES, Correlations
from fbi.simulator.markets import Selection as SimSelection

NAME: Final = "TEAM_TOTALS"
LABEL: Final = "Goles de un equipo (más / menos)"
BETS: Final = (16, 17)
MARKET_KEYS: Final = ("OU_AWAY", "OU_HOME")
RULE: Final = "goals_ft@v1"
SOURCE_MODEL: Final = "dixon_coles"
"""The model in force whose joint the family sums over (``fbi.simulator.consistency.GOAL_MODELS``)."""
MODEL: Final = f"{SIM_VERSION}:{SOURCE_MODEL}"
MODEL_VERSION: Final = SIM_VERSION
DECISION_VERSION: Final = "decision-v2-plugin-team-totals"
"""The version its rows WOULD be written under. In SHADOW nothing is written; the replay reads rows of it only when given them."""
OUTCOME_VERSION: Final = "none (shadow: no outcome is written)"
SETTLEMENT: Final = SettlementRule("fbi.picks.count_settlement", "settle_numbers", OUTCOME_VERSION)
SPEC: Final = fd.FamilySpec(NAME)
SIM_MARKET: Final = {"OU_HOME": "TT_HOME", "OU_AWAY": "TT_AWAY", "1X2": "1X2", "OU": "OU", "BTTS": "BTTS", "AH": "AH"}
"""The catalogue keys the joint settles, as sim-v1 names them: the family's two, and the core's goals markets (for the dependence)."""
DERIVED_ID: Final = 0
"""The forecast id of a derived probability: it is computed at the moment, never stored."""


@dataclass(frozen=True)
class Match:
    """One match as of the moment: its fixture fields (``fd.FIXTURE_FIELDS``) and the joint of the Dixon-Coles in force."""

    fixture_id: int
    fixture: Mapping[str, Any] = field(compare=False)
    joint: jt.JointScore = field(compare=False)
    model_version_id: int
    data_cutoff_ts: datetime


@dataclass(frozen=True)
class Inputs:
    """What the family reads at a moment: the matches with a joint, the books' prices of its markets, when the odds were last read."""

    matches: Mapping[int, Match]
    priced: Mapping[fd.PriceKey, fd.Priced]
    observed: Mapping[int, datetime]


class Source(Protocol):
    def __call__(self, conn: psycopg.Connection[Any] | None, *, at: datetime, fixtures: Sequence[int] | None,
                 horizon: timedelta) -> Inputs: ...


def to_sim(market_key: str, selection: str, line: Decimal) -> SimSelection | None:
    """The sim-v1 selection of a catalogue selection, or None when the joint does not settle it."""
    market = SIM_MARKET.get(market_key)
    if market is None:
        return None
    try:
        return SimSelection(market, selection, float(line))
    except ValueError:
        return None


@dataclass(frozen=True)
class TeamTotalsModel:
    """The distribution provider: the probabilities of the family's selections and the dependence of two selections of one match
    (the portfolio's ``JointProvider`` shape), from each match's joint."""

    matches: Mapping[int, Match]

    def _corr(self, fixture_id: int) -> Correlations | None:
        m = self.matches.get(fixture_id)
        return None if m is None else Correlations(m.joint)

    def price(self, fixture_id: int, market_key: str, selection: str, line: Decimal) -> tuple[float, float] | None:
        c = self._corr(fixture_id)
        sel = to_sim(market_key, selection, line) if market_key in MARKET_KEYS else None
        if c is None or sel is None:
            return None
        lo = c.price(sel)
        return lo.win, lo.push

    def correlation(self, a: SelectionLike, b: SelectionLike) -> float | None:
        """The phi coefficient of the two win indicators under the match's joint, for a pair of one match of which at least one
        selection is the family's; None otherwise (the portfolio's other sources then decide)."""
        if a.fixture_id != b.fixture_id or not (a.market_key in MARKET_KEYS or b.market_key in MARKET_KEYS):
            return None
        c = self._corr(a.fixture_id)
        sa, sb = to_sim(a.market_key, a.selection, a.line), to_sim(b.market_key, b.selection, b.line)
        if c is None or sa is None or sb is None:
            return None
        return c.pair(sa, sb).correlation

    def forecasts(self) -> list[fd.Forecast]:
        """Every selection of the family at the menu's team lines, as the forecast decision-fam-v1's candidate rule reads."""
        out: list[fd.Forecast] = []
        for fid, m in sorted(self.matches.items()):
            c = Correlations(m.joint)
            for key in MARKET_KEYS:
                for line in TEAM_LINES:
                    for pick in ("Over", "Under"):
                        p = c.price(SimSelection(SIM_MARKET[key], pick, line)).win
                        out.append(fd.Forecast(DERIVED_ID, fid, NAME, MODEL, m.model_version_id, key, Decimal(str(line)), pick, p, p,
                                               None, None, "UNCALIBRATED", m.data_cutoff_ts, m.data_cutoff_ts, m.fixture))
        return out


# -- reading, as of a moment ------------------------------------------------------------------------------------------------------

FIXTURES_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, f.status_short, f.status_group, f.home_team_id, f.away_team_id, f.competition_season_id,
       cs.competition_id, c.name AS competition_name, th.name AS home_name, ta.name AS away_name
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.kickoff_at > %(at)s
   AND (%(only)s::bigint[] IS NOT NULL OR f.kickoff_at < %(until)s)
   AND (%(only)s::bigint[] IS NULL OR f.id = ANY(%(only)s))
 ORDER BY f.kickoff_at, f.id
"""
"""The matches still to play at ``at``: the ones asked for, or every one that kicks off within the horizon."""


def read_matches(conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                 horizon: timedelta = decision.HORIZON) -> dict[int, Match]:
    """Each match with the joint of the Dixon-Coles in force at ``at``; a match whose model is missing, not invertible or refused
    (an invalid rho) is left out."""
    if fixtures is not None and not fixtures:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FIXTURES_SQL, {"at": at, "until": at + horizon, "only": None if fixtures is None else list(fixtures)})
        rows = cur.fetchall()
    out: dict[int, Match] = {}
    for r in rows:
        fid = int(r["fixture_id"])
        mf = next((m for m in consistency.in_force(conn, fid, at) if m.model == SOURCE_MODEL), None)
        if mf is None:
            continue
        inv = consistency.invert(mf.rows, SOURCE_MODEL)
        if inv is None or inv.residual > consistency.INVERSION_TOLERANCE:
            continue
        try:
            joint = jt.build(jt.split_full_time(inv.lam_home, inv.lam_away), rho=inv.rho, source=f"{SOURCE_MODEL} (recovered, documented split)")
        except ValueError:  # InvalidCorrectionError included
            continue
        out[fid] = Match(fid, {k: r[k] for k in fd.FIXTURE_FIELDS}, joint, mf.version_id, mf.data_cutoff_ts)
    return out


def read_inputs(conn: psycopg.Connection[Any] | None, *, at: datetime, fixtures: Sequence[int] | None = None,
                horizon: timedelta = decision.HORIZON) -> Inputs:
    """The matches, their prices and when their odds were last read, as of ``at``."""
    if conn is None:
        raise ValueError("reading the family needs a connection")
    matches = read_matches(conn, at=at, fixtures=fixtures, horizon=horizon)
    forecasts = TeamTotalsModel(matches).forecasts()
    return Inputs(matches, fd.read_prices(conn, forecasts, at=at), fd.observed(conn, sorted(matches), at=at))


# -- the decision-v2 adapter --------------------------------------------------------------------------------------------------------

PARAMS: Final = FamilyParams(
    decision_version=DECISION_VERSION, forecast_max_age=None, interval_required=False, correlate=True, promoted=False,
    candidate_rule="decision-fam-v1's rule (fd.candidates) on the sim-v1 probability of each team line: a half line, at least "
                   "versus.MIN_BOOKS complete books, fd.MIN_EV at the best price, the best line of each market of each match",
    price_source="the quotes in force (market.odds_quotes) of bets 16 and 17, de-vigged by each book's margin; the age is when the "
                 "match's odds were last read")
"""``correlate``: the goals of a side are goals of the match, so the day it is judged for real it competes with the match's other
selections. ``promoted`` is the author's default; the plug-in's status overrides it (``fbi.plugins.family.PluginFamily``)."""


@dataclass(frozen=True)
class TeamTotalsFamily:
    """The adapter: a ``fbi.decision.families.MarketFamily`` reading ``source`` (the database by default)."""

    source: Source = read_inputs
    name: str = NAME
    params: FamilyParams = PARAMS
    settlement: SettlementRule = SETTLEMENT

    def markets(self) -> tuple[str, ...]:
        return MARKET_KEYS

    def owns(self, market_key: str) -> bool:
        return market_key in MARKET_KEYS

    def candidates(self, conn: psycopg.Connection[Any], *, at: datetime, fixtures: Sequence[int] | None = None,
                   horizon: timedelta = decision.HORIZON) -> list[Candidate]:
        found = self.source(conn, at=at, fixtures=fixtures, horizon=horizon)
        return self.from_inputs(found)

    def from_inputs(self, found: Inputs) -> list[Candidate]:
        """The candidates of what was read (pure)."""
        chosen = fd.candidates(TeamTotalsModel(found.matches).forecasts(), found.priced, found.observed, specs={NAME: SPEC})
        return [Candidate(self, c.key, {MODEL: c.row()}, model_hint=MODEL) for c in chosen]

    def gate(self, world: decision.World, market: str, model: str) -> GateStatus:
        return gate_of(world, market, model)

    def claims(self, row: Mapping[str, Any]) -> bool:
        return row.get("decision_version") == DECISION_VERSION and self.owns(str(row.get("market_key")))


def make_plugin(source: Source = read_inputs) -> FamilyPlugin:
    """The entry of the family, reading ``source`` (a test gives one in memory)."""

    def distribution(conn: psycopg.Connection[Any] | None, *, at: datetime, fixtures: Sequence[int]) -> TeamTotalsModel:
        return TeamTotalsModel(source(conn, at=at, fixtures=fixtures, horizon=decision.HORIZON).matches)

    return FamilyPlugin(name=NAME, label=LABEL, status=SHADOW, bets=BETS, market_keys=MARKET_KEYS, rule=RULE, model=MODEL,
                        model_version=MODEL_VERSION, decision_version=DECISION_VERSION, settlement=SETTLEMENT,
                        adapter=TeamTotalsFamily(source), distribution=distribution, activatable=False)


PLUGIN: Final = make_plugin()
"""The example's entry: SHADOW, never ACTIVE, not installed."""
