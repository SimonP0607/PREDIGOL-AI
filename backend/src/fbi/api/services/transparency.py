"""«Cómo le va a PrediGol» (plan UX, A12; section 31 of the plan): the answer to «¿funciona?» with data, always with its sample.
Reading only - nothing here computes a probability, prices a selection, chooses a pick or changes a rule - and one calculation:
the page, its contrast script (``scripts/transparency_check.py``) and the tests all read this module's numbers.

WHAT IS COUNTED. A published pick is an item of the day's ``qualified`` set (``picks.daily_set_items``): the only set a reader
is ever shown. The ``evaluation`` set (the owner's preview, shadow picks too) is never read here - no query names it - and
nothing of evaluation is shown but counts.

    published picks  won, lost, half won and half lost, pushed and voided, in 7 days, 30 days and the whole history (fixed
                     periods, cut in the reader's time zone exactly as Mis picks cuts them: ``fbi.userdata.records``), with
                     the units and the ROI of a flat stake of one unit only from MIN_SAMPLE settled picks, always beside
                     their margin (one standard error, 1 / sqrt(n)), and below CONCLUSIVE the sample is said to be too
                     small to conclude. The formula is Mis picks' - a test feeds the same rows to both.
    days without     a product day (America/Bogota, as the sets) whose qualified set had no item, over the 30 days before
    picks            today (never before the daily rule started, 4 Oct 2026): no match of the followed competitions; no
                     forecast of a model that beat the market in its own test (``picks.picks.qualification``) - so
                     nothing could be published -; or such candidates and none chosen. What PrediGol Intelligence measured
                     those days is reconstructed from its decisions saved (``intel.decisions``, the last one of each
                     selection before kick-off): how many selections and the commonest first filter that stopped them -
                     labelled as a reconstruction, counts only.
    by kind of bet   the whole history per market; a kind with fewer than MIN_SAMPLE settled picks goes to «other».
    line value       ``clv-v1`` (``fbi.market.closing_value``): the published price against the de-vigged (Shin) consensus of
                     the last capture before kick-off - computed by that module's own function, the definition labelled
                     with its date; the median of how long before kick-off the reference was taken is shown with it.
    the forecast     per market (1X2, total goals at 2.5, both teams to score), the last forecast before kick-off of each
                     finished match of the last CALIBRATION_DAYS days against its result (regular time): CALIBRATED or
                     «sin calibrar» as most of its recent forecasts were, and - only for a calibrated market with
                     MIN_CALIBRATION matches - what PrediGol said against what happened, in ranges of ten points.
    in evaluation    how many kinds of bet and kind x model combinations PrediGol Intelligence measures against the market
                     (``edge-gate-v1``, ``intel.promotions``) and how many beat it out of sample; how many forecasts of
                     a qualified model there were - never a selection, a price or a result of evaluation.

Kept ten minutes (``shared``): the published picks per time zone - the periods are cut in the reader's days - and the
rest, the costly part, once for every reader.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, get_args

from fbi.api.cache import shared
from fbi.api.contracts.transparency import (
    CalibrationBin,
    Definition,
    Evaluation,
    ForecastCalibration,
    LineValue,
    MarketTally,
    NoPickDay,
    NoPickDays,
    NoPickReason,
    Period,
    PeriodTally,
    StopKey,
    Transparency,
)
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services.forecast import VERSION as FORECAST_VERSION
from fbi.api.switches import transparency_open
from fbi.core.clock import now
from fbi.market import closing_value
from fbi.picks.daily import DAY_TZ, product_day
from fbi.userdata.records import period_bounds

PUBLISHING_SINCE: Final = date(2026, 10, 4)
"""The first product day of the daily rule (``fbi.picks.daily``, daily-set-v1): there were no sets before it."""
DAYS: Final = 30
MIN_SAMPLE: Final = 25
"""Settled picks from which units, ROI and margin are shown (plan section 31: ±20 points with 25)."""
CONCLUSIVE: Final = 100
"""Below it the page says the sample does not allow a conclusion yet (plan section 31: ±10 points with 100)."""
MIN_CALIBRATION: Final = 300
"""Calibrated forecasts of finished matches from which «said against happened» is shown."""
MIN_BIN: Final = 30
"""A range of probabilities with fewer cases is left out of the calibration (and counted as omitted)."""
CALIBRATION_DAYS: Final = 90
STATE_DAYS: Final = 14
"""A market's state is what most of its forecasts of the last 14 days of the window were."""
PERIODS: Final[tuple[Period, ...]] = ("7d", "30d", "all")
FORECAST_MARKETS: Final[tuple[tuple[Literal["1X2", "OU", "BTTS"], Decimal, str | None], ...]] = (
    ("1X2", Decimal("0"), None), ("OU", Decimal("2.5"), "Over"), ("BTTS", Decimal("0"), "Yes"))
"""The forecast's markets and the outcome whose calibration is shown (1X2: every outcome)."""
STOPS: Final[tuple[StopKey, ...]] = get_args(StopKey)
"""The decision layer's filters in their order (``fbi.intel.decision``, decision-v1): a tie of commonest stops goes to the
earlier filter."""
OTHER: Final = "other"
LINE_VALUE_SINCE: Final = date(2026, 10, 22)
"""``clv-v1`` is in force since 22 Oct 2026 (``fbi.market.closing_value``)."""
DEFINITIONS: Final = (
    Definition(key="roi", version="flat-1u", since=date(2026, 10, 4)),
    Definition(key="sample", version="se-v1", since=date(2026, 10, 26)),
    Definition(key="no_pick_day", version="daily-set-v5", since=date(2026, 10, 11)),
    Definition(key="line_value", version=closing_value.VERSION, since=LINE_VALUE_SINCE),
    Definition(key="calibration", version=FORECAST_VERSION, since=date(2026, 10, 23)),
)
"""What each figure means and since when (plan section 31: «las definiciones llevan fecha»). The evaluation's comes from its own
first verdict. A changed definition gets a new version and date here, and the page recomputes the history with it."""

PUBLISHED_SQL = """
SELECT i.status, i.profit_units AS profit, i.market_key, i.settled_at, f.kickoff_at
  FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id
  JOIN core.fixtures f ON f.id = i.fixture_id
 WHERE s.source = 'qualified' AND f.kickoff_at < %(until)s
"""

DAYS_SQL = """
WITH d AS (SELECT generate_series(%(first)s::date, %(last)s::date, interval '1 day')::date AS day),
b AS (SELECT day, (day::timestamp AT TIME ZONE %(tz)s) AS start, ((day + 1)::timestamp AT TIME ZONE %(tz)s) AS stop FROM d)
SELECT b.day,
       (SELECT count(i.rank) FROM picks.daily_sets s JOIN picks.daily_set_items i ON i.set_id = s.id
         WHERE s.day = b.day AND s.source = 'qualified')::int AS published,
       (SELECT count(*) FROM core.fixtures f
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
         WHERE c.is_tracked AND f.kickoff_at >= b.start AND f.kickoff_at < b.stop)::int AS matches,
       (SELECT count(*) FROM picks.picks p JOIN core.fixtures f ON f.id = p.fixture_id
         WHERE f.kickoff_at >= b.start AND f.kickoff_at < b.stop AND p.created_at < f.kickoff_at
           AND (p.qualification ->> 'qualified')::boolean)::int AS qualified
  FROM b ORDER BY b.day
"""

STOPS_SQL = """
WITH last AS (
    SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line)
           (d.kickoff_at AT TIME ZONE %(tz)s)::date AS day, d.filters, d.pick_id
      FROM intel.decisions d
     WHERE d.known_at >= %(known_from)s AND d.known_at < %(stop)s
       AND d.kickoff_at >= %(start)s AND d.kickoff_at < %(stop)s AND d.known_at < d.kickoff_at
     ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.known_at DESC, d.id DESC
)
SELECT l.day,
       (SELECT x ->> 'key' FROM jsonb_array_elements(l.filters) x
         WHERE x ->> 'ok' = 'false' ORDER BY (x ->> 'n')::int LIMIT 1) AS stop,
       COALESCE((p.qualification ->> 'qualified')::boolean, false) AS qualified,
       count(*)::int AS n
  FROM last l LEFT JOIN picks.picks p ON p.id = l.pick_id
 GROUP BY 1, 2, 3
"""

LINE_VALUE_SQL = """
SELECT i.odds, f.kickoff_at, cp.p_fair AS p_close, cp.as_of AS close_at
  FROM picks.daily_set_items i
  JOIN picks.daily_sets s ON s.id = i.set_id
  JOIN core.fixtures f ON f.id = i.fixture_id
  LEFT JOIN LATERAL (
      SELECT m.p_fair, m.as_of FROM market.market_consensus m
       WHERE m.fixture_id = i.fixture_id AND m.market_key = i.market_key AND m.selection = i.selection
         AND m.line = i.line AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
       ORDER BY m.as_of DESC LIMIT 1) cp ON true
 WHERE s.source = 'qualified' AND f.kickoff_at <= %(at)s
"""

FORECASTS_SQL = """
WITH last AS (
    SELECT x.fixture_id, x.market_key, x.line, max(x.known_at) AS k
      FROM models.match_forecasts x JOIN core.fixtures f ON f.id = x.fixture_id
     WHERE x.version = %(version)s AND x.known_at >= %(known_from)s AND x.known_at < f.kickoff_at
       AND f.status_group = 'finished' AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(at)s
       AND ((x.market_key = '1X2' AND x.line = 0) OR (x.market_key = 'OU' AND x.line = 2.5)
            OR (x.market_key = 'BTTS' AND x.line = 0))
     GROUP BY 1, 2, 3
)
SELECT x.fixture_id, x.market_key, x.line, x.selection, x.p, x.calibration, f.kickoff_at,
       r.reg_goals_home AS home, r.reg_goals_away AS away
  FROM last l
  JOIN models.match_forecasts x ON x.fixture_id = l.fixture_id AND x.version = %(version)s
                               AND x.market_key = l.market_key AND x.line = l.line AND x.known_at = l.k
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.fixture_results r ON r.fixture_id = l.fixture_id
 WHERE r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
"""

EDGE_SQL = """
SELECT DISTINCT ON (market_key, model_name) market_key, model_name, to_role, gate_version, min(at) OVER () AS first_at
  FROM intel.promotions WHERE entity = 'market_edge'
 ORDER BY market_key, model_name, at DESC, id DESC
"""


def shown() -> bool:
    """Whether readers see the page (``FBI_TRANSPARENCY``, off until the owner's review: P9)."""
    return transparency_open()


# ── the published picks ─────────────────────────────────────────────────────────

@dataclass
class Count:
    """A tally of published picks, with Mis picks' rules (``fbi.userdata.records.history``)."""

    published: int = 0
    pending: int = 0
    won: int = 0
    lost: int = 0
    half_won: int = 0
    half_lost: int = 0
    push: int = 0
    void: int = 0
    staked: int = 0
    """Settled with a price and not voided: the stakes the profit is counted over - and the n of the sample."""
    profit: Decimal = Decimal(0)

    def add(self, status: str, profit: Decimal | None) -> None:
        self.published += 1
        if status == "PENDING":
            self.pending += 1
            return
        if status == "WIN":
            self.won += 1
        elif status == "HALF_WIN":
            self.half_won += 1
        elif status == "LOSS":
            self.lost += 1
        elif status == "HALF_LOSS":
            self.half_lost += 1
        elif status == "PUSH":
            self.push += 1
        else:
            self.void += 1
        if profit is not None:
            self.profit += Decimal(profit)
            if status != "VOID":
                self.staked += 1

    @property
    def roi(self) -> Decimal | None:
        return self.profit / self.staked if self.staked else None


def count(rows: Iterable[Mapping[str, Any]]) -> Count:
    out = Count()
    for r in rows:
        out.add(str(r["status"]), r["profit"])
    return out


def margin(n: int) -> Decimal | None:
    """One standard error of a flat-stake ROI over n settled picks, as the plan states it (1 / sqrt(n): ±0.20 with 25)."""
    return Decimal(1 / math.sqrt(n)).quantize(Decimal("0.0001")) if n > 0 else None


def tally_fields(c: Count) -> dict[str, Any]:
    """The contract's fields of a tally: counts always; units, ROI and margin only from MIN_SAMPLE settled picks."""
    enough = c.staked >= MIN_SAMPLE
    roi = c.roi
    return {"published": c.published, "pending": c.pending, "won": c.won, "lost": c.lost, "half_won": c.half_won,
            "half_lost": c.half_lost, "push": c.push, "void": c.void, "settled": c.staked,
            "units": c.profit.quantize(Decimal("0.01")) if enough else None,
            "roi": roi.quantize(Decimal("0.0001")) if enough and roi is not None else None,
            "margin": margin(c.staked) if enough else None,
            "conclusive": c.staked >= CONCLUSIVE}


def periods(rows: list[dict[str, Any]], *, at: datetime, tz: str) -> list[PeriodTally]:
    out: list[PeriodTally] = []
    for period in PERIODS:
        since, until = period_bounds(period, at=at, tz=tz)
        inside = [r for r in rows if since <= r["kickoff_at"] < until]
        out.append(PeriodTally(period=period, since=None if period == "all" else since.date(),
                               until=(until - timedelta(days=1)).date(), **tally_fields(count(inside))))
    return out


def markets(rows: list[dict[str, Any]]) -> list[MarketTally]:
    """The whole history per kind of bet, most settled first; the kinds with fewer than MIN_SAMPLE settled picks together as
    «other», last."""
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[str(r["market_key"])].append(r)
    big: list[tuple[str, Count]] = []
    small: list[dict[str, Any]] = []
    for key, group in by.items():
        c = count(group)
        if c.staked >= MIN_SAMPLE:
            big.append((key, c))
        else:
            small.extend(group)
    big.sort(key=lambda kc: (-kc[1].staked, kc[0]))
    out = [MarketTally(market=key, **tally_fields(c)) for key, c in big]
    if small:
        out.append(MarketTally(market=OTHER, **tally_fields(count(small))))
    return out


# ── the days without picks ──────────────────────────────────────────────────────

def window(at: datetime) -> tuple[date, date]:
    """The product days counted: the DAYS before today, never before the daily rule started (today is Home's)."""
    today = product_day(at)
    return max(today - timedelta(days=DAYS), PUBLISHING_SINCE), today - timedelta(days=1)


def commonest(stops: Mapping[str, int]) -> StopKey | None:
    """The stop with the most selections; a tie goes to the earlier filter. None when nothing was stopped."""
    best: StopKey | None = None
    most = 0
    for key in STOPS:
        n = stops.get(key, 0)
        if n > most:
            best, most = key, n
    return best


def no_pick_days(conn: Conn, *, at: datetime) -> tuple[NoPickDays, int]:
    """The days without picks and why - and, for the evaluation block, the qualified forecasts of the window."""
    first, last = window(at)
    tz = str(DAY_TZ)
    rows = fetch_all(conn, DAYS_SQL, {"first": first, "last": last, "tz": tz}) if first <= last else []
    start = datetime.combine(first, datetime.min.time(), tzinfo=DAY_TZ)
    stop = datetime.combine(last + timedelta(days=1), datetime.min.time(), tzinfo=DAY_TZ)
    measured: dict[date, int] = defaultdict(int)
    stops_all: dict[date, Counter[str]] = defaultdict(Counter)
    stops_qualified: dict[date, Counter[str]] = defaultdict(Counter)
    if first <= last:
        for r in fetch_all(conn, STOPS_SQL, {"tz": tz, "start": start, "stop": stop,
                                             "known_from": start - timedelta(days=2)}):
            day = r["day"]
            measured[day] += int(r["n"])
            if r["stop"] is not None:
                stops_all[day][str(r["stop"])] += int(r["n"])
                if r["qualified"]:
                    stops_qualified[day][str(r["stop"])] += int(r["n"])
    items: list[NoPickDay] = []
    for r in rows:
        if int(r["published"]) > 0:
            continue
        day = r["day"]
        reason: NoPickReason = ("no_matches" if int(r["matches"]) == 0 else
                                "no_qualified_candidates" if int(r["qualified"]) == 0 else "not_chosen")
        stop_key = commonest(stops_qualified[day] if reason == "not_chosen" else stops_all[day])
        items.append(NoPickDay(day=day, reason=reason, matches=int(r["matches"]), measured=measured[day], stop=stop_key))
    items.sort(key=lambda d: d.day, reverse=True)
    reasons = Counter(d.reason for d in items)
    stops = Counter(d.stop for d in items if d.stop is not None)
    qualified = sum(int(r["qualified"]) for r in rows)
    block = NoPickDays(since=first, until=last, days=len(rows), with_picks=len(rows) - len(items), without=len(items),
                       reasons=dict(sorted(reasons.items())), measured=sum(d.measured for d in items),
                       stops={k: stops[k] for k in STOPS if stops[k]}, items=items)
    return block, qualified


# ── the line value ──────────────────────────────────────────────────────────────

def line_value(conn: Conn, *, at: datetime) -> LineValue:
    rows = [r for r in fetch_all(conn, LINE_VALUE_SQL, {"at": at}) if r["p_close"] is not None]
    values = [closing_value.clv(Decimal(r["odds"]), Decimal(r["p_close"])) for r in rows]
    minutes = [(r["kickoff_at"] - r["close_at"]).total_seconds() / 60 for r in rows]
    enough = len(values) >= MIN_SAMPLE
    return LineValue(
        version=closing_value.VERSION, since=LINE_VALUE_SINCE, n=len(values),
        mean=(sum(values, Decimal(0)) / len(values)).quantize(Decimal("0.0001")) if enough else None,
        positive=(Decimal(sum(1 for v in values if v > 0)) / len(values)).quantize(Decimal("0.0001")) if enough else None,
        minutes=round(statistics.median(minutes)) if minutes else None)


# ── the forecast's calibration ──────────────────────────────────────────────────

def happened(market: str, selection: str, home: int, away: int) -> bool:
    """Whether the outcome happened, in regular time - the basis the forecast is made on."""
    if market == "1X2":
        return selection == ("Home" if home > away else "Away" if away > home else "Draw")
    if market == "OU":
        return (home + away > 2.5) == (selection == "Over")
    if market == "BTTS":
        return (home > 0 and away > 0) == (selection == "Yes")
    raise ValueError(f"no outcome rule for {market}")


def bins_of(points: list[tuple[Decimal, bool]]) -> tuple[list[CalibrationBin], int]:
    """Ten-point ranges of what was said, each with its mean said, its share happened and its n; the small ones left out."""
    by: dict[int, list[tuple[Decimal, bool]]] = defaultdict(list)
    for p, hit in points:
        by[min(int(p * 10), 9)].append((p, hit))
    out: list[CalibrationBin] = []
    omitted = 0
    for k in sorted(by):
        group = by[k]
        if len(group) < MIN_BIN:
            omitted += len(group)
            continue
        out.append(CalibrationBin(low=Decimal(k) / 10, high=Decimal(k + 1) / 10,
                                  predicted=(sum((p for p, _ in group), Decimal(0)) / len(group)).quantize(Decimal("0.001")),
                                  observed=(Decimal(sum(1 for _, h in group if h)) / len(group)).quantize(Decimal("0.001")),
                                  n=len(group)))
    return out, omitted


def forecasts(conn: Conn, *, at: datetime) -> list[ForecastCalibration]:
    since = at - timedelta(days=CALIBRATION_DAYS)
    rows = fetch_all(conn, FORECASTS_SQL, {"version": FORECAST_VERSION, "since": since, "at": at,
                                           "known_from": since - timedelta(days=7)})
    out: list[ForecastCalibration] = []
    for market, line, side in FORECAST_MARKETS:
        mine = [r for r in rows if r["market_key"] == market and Decimal(r["line"]) == line]
        per_match: dict[int, tuple[datetime, str]] = {int(r["fixture_id"]): (r["kickoff_at"], str(r["calibration"]))
                                                      for r in mine}
        matches = len(per_match)
        calibrated = sum(1 for _, c in per_match.values() if c == "CALIBRATED")
        newest = max((k for k, _ in per_match.values()), default=None)
        recent = [c for k, c in per_match.values() if newest is not None and k >= newest - timedelta(days=STATE_DAYS)]
        state: Literal["CALIBRATED", "UNCALIBRATED"] = (
            "CALIBRATED" if recent and 2 * sum(1 for c in recent if c == "CALIBRATED") > len(recent) else "UNCALIBRATED")
        bins: list[CalibrationBin] = []
        omitted = 0
        if state == "CALIBRATED" and calibrated >= MIN_CALIBRATION:
            points = [(Decimal(r["p"]), happened(market, str(r["selection"]), int(r["home"]), int(r["away"])))
                      for r in mine if r["calibration"] == "CALIBRATED" and (side is None or r["selection"] == side)]
            bins, omitted = bins_of(points)
        out.append(ForecastCalibration(market=market, line=line, state=state, matches=matches, calibrated=calibrated,
                                       selection=side, bins=bins, omitted=omitted))
    return out


# ── what is in evaluation ───────────────────────────────────────────────────────

def evaluation(conn: Conn, *, qualified: int) -> tuple[Evaluation, str | None]:
    """The evaluation block, and the version of the test its verdicts are of (the newest stored)."""
    rows = fetch_all(conn, EDGE_SQL)
    passed = [r for r in rows if r["to_role"] == "VALIDATED"]
    first = min((r["first_at"] for r in rows), default=None)
    versions = sorted({str(r["gate_version"]) for r in rows})
    block = Evaluation(markets=len({r["market_key"] for r in rows}), pairs=len(rows),
                       passed_markets=len({r["market_key"] for r in passed}), passed_pairs=len(passed),
                       since=None if first is None else first.astimezone(DAY_TZ).date(), qualified=qualified)
    return block, ", ".join(versions) or None


# ── the page ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Common:
    """The blocks that are the same for every reader (the product days are Bogota's, the rest has no day to cut): the
    costly ones - about three seconds on the production data of 26 Oct 2026 - computed once for every time zone."""

    days: NoPickDays
    line_value: LineValue
    forecasts: list[ForecastCalibration]
    evaluation: Evaluation
    definitions: list[Definition]


def common(conn: Conn, *, at: datetime) -> Common:
    days, qualified = no_pick_days(conn, at=at)
    ev, gate = evaluation(conn, qualified=qualified)
    definitions = [*DEFINITIONS]
    if ev.since is not None and gate is not None:
        definitions.append(Definition(key="evaluation", version=gate, since=ev.since))
    return Common(days=days, line_value=line_value(conn, at=at), forecasts=forecasts(conn, at=at), evaluation=ev,
                  definitions=definitions)


def assemble(conn: Conn, *, tz: str, at: datetime, base: Common) -> Transparency:
    """The page for a reader in ``tz``: the published picks cut in their days, with the common blocks."""
    _, until = period_bounds("all", at=at, tz=tz)
    published = fetch_all(conn, PUBLISHED_SQL, {"until": until})
    settled = [r["settled_at"] for r in published if r["settled_at"] is not None]
    return Transparency(
        timezone=tz, min_sample=MIN_SAMPLE, conclusive=CONCLUSIVE, min_calibration=MIN_CALIBRATION, min_bin=MIN_BIN,
        calibration_days=CALIBRATION_DAYS, periods=periods(published, at=at, tz=tz), days=base.days,
        markets=markets(published), line_value=base.line_value, forecasts=base.forecasts, evaluation=base.evaluation,
        definitions=base.definitions, data_as_of=max(settled, default=None))


def build(conn: Conn, *, tz: str, at: datetime) -> Transparency:
    """Every block of the page at ``at``, for a reader in ``tz`` (no cache: the contrast script and the tests call it)."""
    return assemble(conn, tz=tz, at=at, base=common(conn, at=at))


@shared(600)
def common_now(conn: Conn) -> Common:
    """The common blocks now, kept ten minutes for every reader."""
    return common(conn, at=now())


@shared(600)
def transparency(conn: Conn, *, tz: str) -> Transparency:
    """The page for a reader in ``tz``, kept ten minutes per time zone (the common blocks, ten minutes for all)."""
    return assemble(conn, tz=tz, at=now(), base=common_now(conn))
