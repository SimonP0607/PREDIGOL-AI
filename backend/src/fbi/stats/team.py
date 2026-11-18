"""The statistics documents of the teams of one competition season (plan EA: EA-003 figures and percentiles, EA-004 pulse, intervals,
survival and game states, EA-006 trends). Pure: a ``SeasonData`` in, contract bodies out (``fbi.api.contracts.intelligence.
stats_profile``); the job writes them as JSON and the API validates them back.

A team's rows are its matches of the competition season from its own side, oldest first. A context (home, away) filters them first,
then a scope keeps the last 5, 10 or 20 (or the whole season). The league's references are the whole season of every team in the same
context, so a scope of 5 is read against what is normal in that league, not against five matches of everybody.

Honesty rules, all of them tested:

* a figure whose matches report it less than ``COVERAGE`` of the time is ``sin_cobertura`` (EA-008), with no data ``sin_datos``;
* a percentile needs ``MIN_TEAMS`` teams with ``MIN_MATCHES`` matches in the same scope and context;
* the pulse, the intervals, the survival and the game states read only the matches whose goal events add up to the result
  (``consistent``): a list that misses a goal would move a curve, so the match is left out of those curves and of their sample;
* the trends count with the settlement rules of IA-070 (``fbi.picks.count_settlement``): one meaning of «more than 9.5 corners».
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Final, cast

import numpy as np

from fbi.market.rules import RULES_BY_MEASURE
from fbi.picks.count_settlement import count_outcome
from fbi.picks.settlement import Status
from fbi.statmath import formulas as fx
from fbi.stats.data import Event, Match, SeasonData
from fbi.stats.doc import (
    Doc,
    GameStates,
    GoalIntervals,
    GoalRef,
    HalfSplit,
    IntervalBin,
    ItemList,
    MatchPoint,
    Pulse,
    PulseBin,
    Quantiles,
    RadarAxis,
    Record,
    Ref,
    StatFigure,
    Survival,
    SurvivalPoint,
    TeamBody,
    TrendColumn,
    TrendRow,
    is_missing,
    missing,
)

CALC_VERSION: Final = "team-agg-v1"
SCOPES: Final = ("u5", "u10", "u20", "season")
SCOPE_SIZE: Final = {"u5": 5, "u10": 10, "u20": 20}
CONTEXTS: Final = ("all", "home", "away")
TREND_CONTEXTS: Final = ("all", "home", "away", "favorite")
COVERAGE: Final = 0.8
MIN_TEAMS: Final = 8
MIN_MATCHES: Final = 3
MIN_CURVE_MATCHES: Final = 3


@dataclass(frozen=True, slots=True)
class Row:
    """One match from one team's side."""

    match: Match
    team_id: int
    home: bool

    @property
    def side(self) -> str:
        return "home" if self.home else "away"

    @property
    def other(self) -> str:
        return "away" if self.home else "home"

    def n(self, stem: str, mine: bool = True) -> int | None:
        return self.match.numbers.get(f"{stem}_{self.side if mine else self.other}")

    def ts(self, key: str, mine: bool = True) -> float | None:
        return self.match.team_stats.get(self.side if mine else self.other, {}).get(key)

    @property
    def gf(self) -> int:
        return int(self.n("goals_ft") or 0)

    @property
    def ga(self) -> int:
        return int(self.n("goals_ft", False) or 0)

    @property
    def points(self) -> int:
        return 3 if self.gf > self.ga else 1 if self.gf == self.ga else 0

    @property
    def favorite(self) -> bool | None:
        """Whether the team was the closing consensus' favourite (its win more likely than its loss); None without a consensus."""
        c = self.match.closing
        if "Home" not in c or "Away" not in c:
            return None
        mine, theirs = (c["Home"], c["Away"]) if self.home else (c["Away"], c["Home"])
        return mine > theirs

    @property
    def opponent(self) -> Doc:
        m = self.match
        return Ref(id=m.away_id, name=m.away_name) if self.home else Ref(id=m.home_id, name=m.home_name)


# ── figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _accuracy(r: Row) -> float | None:
    p, ok = r.ts("passes"), r.ts("passes_accurate")
    return None if not p or ok is None else 100.0 * ok / p


@dataclass(frozen=True, slots=True)
class FigureDef:
    key: str
    unit: str
    better: str
    read: Callable[[Row], float | None]


FIGURES: Final[tuple[FigureDef, ...]] = (
    FigureDef("points", "por_partido", "mas", lambda r: float(r.points)),
    FigureDef("goals_for", "por_partido", "mas", lambda r: float(r.gf)),
    FigureDef("goals_against", "por_partido", "menos", lambda r: float(r.ga)),
    FigureDef("xg_for", "por_partido", "mas", lambda r: r.ts("xg")),
    FigureDef("xg_against", "por_partido", "menos", lambda r: r.ts("xg", False)),
    FigureDef("finishing", "por_partido", "mas", lambda r: _diff(float(r.gf), r.ts("xg"))),
    FigureDef("shots_for", "por_partido", "mas", lambda r: _f(r.n("shots_ft"))),
    FigureDef("shots_against", "por_partido", "menos", lambda r: _f(r.n("shots_ft", False))),
    FigureDef("shots_on_target_for", "por_partido", "mas", lambda r: _f(r.n("shots_on_target_ft"))),
    FigureDef("shots_on_target_against", "por_partido", "menos", lambda r: _f(r.n("shots_on_target_ft", False))),
    FigureDef("corners_for", "por_partido", "mas", lambda r: _f(r.n("corners_ft"))),
    FigureDef("corners_against", "por_partido", "menos", lambda r: _f(r.n("corners_ft", False))),
    FigureDef("corner_balance", "por_partido", "mas", lambda r: _diff(_f(r.n("corners_ft")), _f(r.n("corners_ft", False)))),
    FigureDef("possession", "porcentaje", "neutral", lambda r: r.ts("possession")),
    FigureDef("pass_accuracy", "porcentaje", "mas", _accuracy),
    FigureDef("fouls", "por_partido", "neutral", lambda r: _f(r.n("fouls_ft"))),
    FigureDef("cards", "por_partido", "menos", lambda r: _f(r.n("cards_lines_ft"))),
    FigureDef("saves", "por_partido", "neutral", lambda r: _f(r.n("saves_ft"))),
)
FIGURE_BY_KEY: Final = {f.key: f for f in FIGURES}


def _f(v: int | None) -> float | None:
    return None if v is None else float(v)


@dataclass(frozen=True, slots=True)
class Measured:
    value: float | None
    with_data: int
    covered: bool


def measure(rows: Sequence[Row], fig: FigureDef) -> Measured:
    values = [v for v in (fig.read(r) for r in rows) if v is not None]
    if not values:
        return Measured(None, 0, False)
    return Measured(sum(values) / len(values), len(values), len(values) >= COVERAGE * len(rows))


# ── events ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def regulation_goals(events: Sequence[Event]) -> list[Event]:
    """The goals of the 90 minutes: no missed penalty, no shoot-out, nothing in extra time. An own goal is filed under the team that
    benefits (the provider's convention), so it counts as it is filed."""
    out = []
    for e in events:
        if e.kind != "Goal" or e.detail == "Missed Penalty" or e.comments == "Penalty Shootout":
            continue
        if fx.pulse_bin(e.minute, e.extra) is None:
            continue
        out.append(e)
    return out


def consistent_goals(m: Match) -> list[Event] | None:
    """The match's regulation goals when they add up to its result per side; None otherwise (or with no list)."""
    if m.events is None:
        return None
    goals = regulation_goals(m.events)
    home = sum(1 for g in goals if g.side == "home")
    away = sum(1 for g in goals if g.side == "away")
    if (home, away) != (m.numbers.get("goals_ft_home"), m.numbers.get("goals_ft_away")):
        return None
    return sorted(goals, key=lambda g: fx.clock(g.minute, g.extra))


def regulation_cards(events: Sequence[Event]) -> list[Event]:
    return [e for e in events if e.kind == "Card" and fx.pulse_bin(e.minute, e.extra) is not None]


def _bins(events: Sequence[Event], side: str) -> np.ndarray:
    v = np.zeros(20)
    for e in events:
        if e.side == side:
            b = fx.pulse_bin(e.minute, e.extra)
            if b is not None:
                v[b] += 1
    return v


def _pulse(subject: str, per_match: list[np.ndarray], league: np.ndarray, seed: int) -> Doc | Doc:
    if len(per_match) < MIN_CURVE_MATCHES:
        return missing("muestra_insuficiente", sample=len(per_match), min_sample=MIN_CURVE_MATCHES)
    rate, idx, low, high = fx.pulse(np.vstack(per_match), league, seed=seed)
    def mark(v: float | None) -> float | Doc:
        return v if v is not None else missing("sin_datos")

    bins = [PulseBin(label=fx.PULSE_LABELS[b], start=fx.PULSE_STARTS[b], rate=fx.half_up(float(rate[b]), 4),
                     league_rate=fx.half_up(float(league[b]), 4), index=mark(idx[b]), low=mark(low[b]), high=mark(high[b]))
            for b in range(20)]
    return Pulse(subject=subject, sigma_minutes=fx.SIGMA, bootstrap=fx.BOOTSTRAP, matches=len(per_match), bins=bins)


def game_states(rows: Sequence[Row]) -> Doc | Doc:
    lead = level = trail = 0.0
    led = ceded = trailed = rescued = used = 0
    for r in rows:
        goals = consistent_goals(r.match)
        if goals is None:
            continue
        used += 1
        diff, t0 = 0, 0.0
        ever_led = ever_trailed = False
        for g in goals:
            t = min(90.0, float(g.minute))
            span = max(0.0, t - t0)
            if diff > 0:
                lead += span
            elif diff < 0:
                trail += span
            else:
                level += span
            t0 = max(t0, t)
            diff += 1 if g.side == r.side else -1
            ever_led = ever_led or diff > 0
            ever_trailed = ever_trailed or diff < 0
        span = max(0.0, 90.0 - t0)
        if diff > 0:
            lead += span
        elif diff < 0:
            trail += span
        else:
            level += span
        if ever_led:
            led += 1
            ceded += 3 - r.points
        if ever_trailed:
            trailed += 1
            rescued += r.points
    if used < MIN_CURVE_MATCHES:
        return missing("muestra_insuficiente", sample=used, min_sample=MIN_CURVE_MATCHES)
    return GameStates(minutes_leading=fx.half_up(lead / used, 1), minutes_level=fx.half_up(level / used, 1),
                      minutes_trailing=fx.half_up(trail / used, 1), matches_led=led, points_ceded=ceded, matches_trailed=trailed,
                      points_rescued=rescued, matches_with_data=used)


def _interval_of(e: Event) -> int | None:
    return fx.interval_bin(e.minute, e.extra)


def intervals(rows: Sequence[Row], league_for: list[float], league_against: list[float]) -> Doc | Doc:
    gf: list[list[Doc]] = [[] for _ in fx.INTERVAL_LABELS]
    ga: list[list[Doc]] = [[] for _ in fx.INTERVAL_LABELS]
    used = 0
    for r in rows:
        goals = consistent_goals(r.match)
        if goals is None:
            continue
        used += 1
        for g in goals:
            b = _interval_of(g)
            if b is None:
                continue
            ref = GoalRef(fixture_id=r.match.fixture_id, minute=g.minute, extra_minute=g.extra)
            (gf if g.side == r.side else ga)[b].append(ref)
    if used < MIN_CURVE_MATCHES:
        return missing("muestra_insuficiente", sample=used, min_sample=MIN_CURVE_MATCHES)
    bins = [IntervalBin(label=label, goals_for=len(gf[i]), goals_against=len(ga[i]), league_for=fx.half_up(league_for[i], 3),
                        league_against=fx.half_up(league_against[i], 3), goals_for_list=gf[i], goals_against_list=ga[i])
            for i, label in enumerate(fx.INTERVAL_LABELS)]
    return GoalIntervals(matches=used, bins=bins)


def first_goal(m: Match) -> tuple[bool, float | None]:
    """(usable, clock of the first goal or None for 0-0)."""
    goals = consistent_goals(m)
    if goals is None:
        return False, None
    return True, (fx.clock(goals[0].minute, goals[0].extra) if goals else None)


def _survival_points(firsts: list[float | None]) -> list[Doc]:
    return [SurvivalPoint(label=label, minute=minute, survival=s) for label, minute, s in fx.survival(firsts)]


def survival(rows: Sequence[Row], league: list[Doc]) -> Doc | Doc:
    firsts = []
    for r in rows:
        ok, t = first_goal(r.match)
        if ok:
            firsts.append(t)
    if len(firsts) < MIN_CURVE_MATCHES:
        return missing("muestra_insuficiente", sample=len(firsts), min_sample=MIN_CURVE_MATCHES)
    points = _survival_points(firsts)
    med = fx.median_label([(p["label"], p["minute"], p["survival"]) for p in points])
    halves = [r for r in rows if r.n("goals_1h") is not None and r.n("goals_1h", False) is not None]
    level = (fx.half_up(sum(1 for r in halves if r.n("goals_1h") == 0 and r.n("goals_1h", False) == 0) / len(halves), 4)
             if halves else missing("sin_datos"))
    return Survival(matches=len(firsts), points=points, median_first_goal=med if med is not None else missing("sin_datos"),
                    level_at_half=level, league_points=league)


# ── trends ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TrendDef:
    key: str
    family: str
    measure: str
    kind: str
    subject: str
    """match, mine or theirs"""
    selection: str
    """the provider's words; Mine/Theirs for a 1X2 read from the team's side"""
    line: float | None


TRENDS: Final[tuple[TrendDef, ...]] = (
    TrendDef("win", "resultado", "goals_ft", "one_x_two", "match", "Mine", None),
    TrendDef("draw", "resultado", "goals_ft", "one_x_two", "match", "Draw", None),
    TrendDef("loss", "resultado", "goals_ft", "one_x_two", "match", "Theirs", None),
    TrendDef("over_1_5", "goles", "goals_ft", "over_under", "match", "Over", 1.5),
    TrendDef("over_2_5", "goles", "goals_ft", "over_under", "match", "Over", 2.5),
    TrendDef("over_3_5", "goles", "goals_ft", "over_under", "match", "Over", 3.5),
    TrendDef("btts", "goles", "goals_ft", "both_teams_score", "match", "Yes", None),
    TrendDef("scores", "goles", "goals_ft", "over_under", "mine", "Over", 0.5),
    TrendDef("scores_first", "goles", "events", "first_goal", "mine", "Mine", None),
    TrendDef("clean_sheet", "goles", "goals_ft", "over_under", "theirs", "Under", 0.5),
    TrendDef("ht_over_0_5", "goles_1t", "goals_1h", "over_under", "match", "Over", 0.5),
    TrendDef("ht_over_1_5", "goles_1t", "goals_1h", "over_under", "match", "Over", 1.5),
    TrendDef("corners_over_8_5", "corners", "corners_ft", "over_under", "match", "Over", 8.5),
    TrendDef("corners_over_9_5", "corners", "corners_ft", "over_under", "match", "Over", 9.5),
    TrendDef("corners_over_10_5", "corners", "corners_ft", "over_under", "match", "Over", 10.5),
    TrendDef("cards_over_3_5", "tarjetas", "cards_lines_ft", "over_under", "match", "Over", 3.5),
    TrendDef("cards_over_4_5", "tarjetas", "cards_lines_ft", "over_under", "match", "Over", 4.5),
)


def trend_hit(r: Row, t: TrendDef) -> bool | None:
    """Whether the match settles the selection as won, by the rule's own grader; None when its numbers are missing or it pushes."""
    if t.measure == "events":
        goals = consistent_goals(r.match)
        if goals is None:
            return None
        return bool(goals) and goals[0].side == r.side
    rule = RULES_BY_MEASURE[t.measure]
    home, away = (r.match.numbers.get(c) for c in rule.columns)
    if home is None or away is None:
        return None
    subject = {"match": "match", "mine": r.side, "theirs": r.other}[t.subject]
    selection = t.selection
    if selection == "Mine":
        selection = "Home" if r.home else "Away"
    elif selection == "Theirs":
        selection = "Away" if r.home else "Home"
    status = count_outcome(t.kind, subject, selection, Decimal(str(t.line or 0)), int(home), int(away))
    if status == Status.WIN:
        return True
    if status == Status.LOSS:
        return False
    return None


def trend_counts(rows: Sequence[Row], t: TrendDef) -> tuple[int, int, list[int]]:
    hits = n = 0
    fids: list[int] = []
    for r in rows:
        h = trend_hit(r, t)
        if h is None:
            continue
        n += 1
        if h:
            hits += 1
            fids.append(r.match.fixture_id)
    return hits, n, fids


def trends(rows: Sequence[Row], league: dict[str, tuple[int, int]]) -> Doc:
    out = []
    for t in TRENDS:
        hits, n, fids = trend_counts(rows, t)
        if n == 0:
            continue
        pct, lo, hi = fx.wilson_pct(hits, n)
        lh, ln = league.get(t.key, (0, 0))
        league_pct: int | Doc = fx.pct_int(lh / ln) if ln else missing("sin_datos")
        dev: int | Doc = pct - league_pct if isinstance(league_pct, int) else missing("sin_datos")
        rule_key: str | Doc = RULES_BY_MEASURE[t.measure].key if t.measure in RULES_BY_MEASURE else missing("sin_datos")
        out.append(TrendRow(key=t.key, family=t.family, rule_key=rule_key, line=t.line, hits=hits, n=n,
                            pct=pct, wilson_low=lo, wilson_high=hi, league_pct=league_pct, deviation_pts=dev, fixture_ids=fids))
    if not out:
        return ItemList(items=[], missing_reason="sin_datos")
    return ItemList(items=out)


def in_trend_context(rows: Sequence[Row], context: str) -> list[Row]:
    if context == "favorite":
        return [r for r in rows if r.favorite]
    return in_context(rows, context)


def matrix(rows: Sequence[Row], league: dict[str, dict[str, tuple[int, int]]]) -> list[Doc]:
    """V2·7: the trends of the same rows, over each context (the league's reference of that context)."""
    out = []
    for context in TREND_CONTEXTS:
        chosen = in_trend_context(rows, context)
        column = trends(chosen, league.get(context, {})) if chosen else None
        out.append(TrendColumn(context=context, matches=len(chosen),
                               rows=column["items"] if column is not None else []))
    return out


# ── one team's body ──────────────────────────────────────────────────────────────────────────────────────────────────

def record(rows: Sequence[Row]) -> Doc:
    w = sum(1 for r in rows if r.gf > r.ga)
    d = sum(1 for r in rows if r.gf == r.ga)
    lo = len(rows) - w - d
    return Record(matches=len(rows), wins=w, draws=d, losses=lo, goals_for=sum(r.gf for r in rows),
                  goals_against=sum(r.ga for r in rows), points=3 * w + d)


def series(rows: Sequence[Row]) -> list[Doc]:
    out = []
    xf: list[float] = []
    xa: list[float] = []
    for r in rows:
        f, a = r.ts("xg"), r.ts("xg", False)
        if f is not None:
            xf.append(f)
        if a is not None:
            xa.append(a)
        out.append(MatchPoint(
            fixture_id=r.match.fixture_id, kickoff_at=r.match.kickoff_at, opponent=r.opponent, home=r.home, goals_for=r.gf,
            goals_against=r.ga, xg_for=f if f is not None else missing("sin_datos"),
            xg_against=a if a is not None else missing("sin_datos"),
            xg_for_avg5=fx.half_up(sum(xf[-5:]) / len(xf[-5:]), 3) if f is not None else missing("sin_datos"),
            xg_against_avg5=fx.half_up(sum(xa[-5:]) / len(xa[-5:]), 3) if a is not None else missing("sin_datos")))
    return out


def halves(rows: Sequence[Row]) -> Doc | Doc:
    ok = [r for r in rows if None not in (r.n("goals_1h"), r.n("goals_1h", False), r.n("goals_2h"), r.n("goals_2h", False))]
    if not ok:
        return missing("sin_datos")
    k = len(ok)
    return HalfSplit(goals_for_1h=fx.half_up(sum(int(r.n("goals_1h") or 0) for r in ok) / k, 3),
                     goals_against_1h=fx.half_up(sum(int(r.n("goals_1h", False) or 0) for r in ok) / k, 3),
                     goals_for_2h=fx.half_up(sum(int(r.n("goals_2h") or 0) for r in ok) / k, 3),
                     goals_against_2h=fx.half_up(sum(int(r.n("goals_2h", False) or 0) for r in ok) / k, 3),
                     matches_with_data=k)


RADAR: Final[tuple[tuple[str, str, bool], ...]] = (
    ("ataque", "xg_for", False), ("pegada", "finishing", False), ("volumen", "shots_for", False),
    ("presencia", "corner_balance", False), ("defensa", "xg_against", True), ("disciplina", "cards", True),
)
"""(axis, figure, inverted): an inverted axis is 100 - the figure's percentile, so that more is better on every axis."""


@dataclass(slots=True)
class LeagueRef:
    """The references of one context over the whole season of every team."""

    means: dict[str, float]
    pulse_for: np.ndarray
    pulse_against: np.ndarray
    pulse_cards: np.ndarray
    interval_for: list[float]
    interval_against: list[float]
    trends: dict[str, tuple[int, int]]


def team_rows(data: SeasonData) -> dict[int, list[Row]]:
    rows: dict[int, list[Row]] = {}
    for m in data.matches:
        rows.setdefault(m.home_id, []).append(Row(m, m.home_id, True))
        rows.setdefault(m.away_id, []).append(Row(m, m.away_id, False))
    for v in rows.values():
        v.sort(key=lambda r: (r.match.kickoff_at, r.match.fixture_id))
    return rows


def in_context(rows: Sequence[Row], context: str) -> list[Row]:
    if context == "home":
        return [r for r in rows if r.home]
    if context == "away":
        return [r for r in rows if not r.home]
    return list(rows)


def in_scope(rows: Sequence[Row], scope: str) -> list[Row]:
    return list(rows) if scope == "season" else list(rows)[-SCOPE_SIZE[scope]:]


def available(rows: Sequence[Row], scope: str) -> bool:
    return scope == "season" or len(rows) >= SCOPE_SIZE[scope]


def _per_team_match(rows: Sequence[Row], fn: Callable[[Row], np.ndarray]) -> np.ndarray:
    mats = [fn(r) for r in rows]
    return fx.smoothed_rate(np.vstack(mats)) if mats else np.zeros(20)


def league_ref(all_rows: Sequence[Row]) -> LeagueRef:
    means = {}
    for fig in FIGURES:
        m = measure(all_rows, fig)
        if m.value is not None:
            means[fig.key] = m.value
    goal_rows = [(r, g) for r in all_rows if (g := consistent_goals(r.match)) is not None]
    card_rows = [(r, regulation_cards(r.match.events)) for r in all_rows if r.match.events is not None]
    pf = fx.smoothed_rate(np.vstack([_bins(g, r.side) for r, g in goal_rows])) if goal_rows else np.zeros(20)
    pa = fx.smoothed_rate(np.vstack([_bins(g, r.other) for r, g in goal_rows])) if goal_rows else np.zeros(20)
    pc = fx.smoothed_rate(np.vstack([_bins(c, r.side) for r, c in card_rows])) if card_rows else np.zeros(20)
    k = max(1, len(goal_rows))
    i_for = [0.0] * len(fx.INTERVAL_LABELS)
    i_against = [0.0] * len(fx.INTERVAL_LABELS)
    for r, goals in goal_rows:
        for goal in goals:
            b = _interval_of(goal)
            if b is not None:
                if goal.side == r.side:
                    i_for[b] += 1
                else:
                    i_against[b] += 1
    tr = {}
    for t in TRENDS:
        hits, n, _ = trend_counts(all_rows, t)
        tr[t.key] = (hits, n)
    return LeagueRef(means, pf, pa, pc, [x / k for x in i_for], [x / k for x in i_against], tr)


def league_survival(data: SeasonData) -> list[Doc]:
    firsts = []
    for m in data.matches:
        ok, t = first_goal(m)
        if ok:
            firsts.append(t)
    return _survival_points(firsts) if firsts else []


@dataclass(slots=True)
class TeamDoc:
    team_id: int
    scope: str
    context: str
    body: Doc
    sample: int


def _seed(team_id: int, scope: str, context: str, subject: str) -> int:
    return (team_id * 1_000_003 + SCOPES.index(scope) * 101 + CONTEXTS.index(context) * 11 + len(subject)) % (2**32)


def _figures(rows: Sequence[Row], population: dict[str, list[float]], ref: LeagueRef) -> tuple[list[Doc], dict[str, int]]:
    out, pcts = [], {}
    for fig in FIGURES:
        m = measure(rows, fig)
        value: float | Doc
        if m.with_data == 0:
            value = missing("sin_datos")
        elif not m.covered:
            value = missing("sin_cobertura")
        else:
            value = fx.half_up(cast(float, m.value), 3)
        pop = population.get(fig.key, [])
        pct: int | Doc
        if is_missing(value):
            pct = missing("sin_datos")
        elif len(pop) < MIN_TEAMS:
            pct = missing("muestra_insuficiente", sample=len(pop), min_sample=MIN_TEAMS)
        else:
            pct = fx.percentile(cast(float, m.value), pop)
            pcts[fig.key] = pct
        lv = ref.means.get(fig.key)
        out.append(StatFigure(key=fig.key, unit=fig.unit, better=fig.better, value=value, matches_with_data=m.with_data,
                              percentile=pct, league_value=fx.half_up(lv, 3) if lv is not None else missing("sin_datos"),
                              distribution=_quantiles(pop)))
    return out, pcts


def _quantiles(pop: Sequence[float]) -> Doc | Doc:
    if len(pop) < MIN_TEAMS:
        return missing("muestra_insuficiente", sample=len(pop), min_sample=MIN_TEAMS)
    q = fx.quantiles(pop)
    return Quantiles(p10=q[0], p25=q[1], p50=q[2], p75=q[3], p90=q[4], entities=len(pop))


def _radar(figures: list[Doc], pcts: dict[str, int]) -> list[Doc]:
    by = {f["key"]: f for f in figures}
    out = []
    for axis, key, inverted in RADAR:
        p = pcts.get(key)
        f = by[key]
        out.append(RadarAxis(key=axis, percentile=(100 - p if inverted else p) if p is not None else missing("sin_datos"),
                             value=f["value"]))
    return out


def season_documents(data: SeasonData) -> tuple[list[TeamDoc], dict[str, LeagueRef], list[Doc]]:
    """Every team's body for every available scope and context, and the league's references."""
    by_team = team_rows(data)
    refs = {c: league_ref([r for rows in by_team.values() for r in in_context(rows, c)]) for c in CONTEXTS}
    surv = league_survival(data)
    every = [r for rows in by_team.values() for r in rows]
    trend_refs = {c: {t.key: trend_counts(in_trend_context(every, c), t)[:2] for t in TRENDS} for c in TREND_CONTEXTS}
    docs: list[TeamDoc] = []
    for context in CONTEXTS:
        ref = refs[context]
        for scope in SCOPES:
            chosen = {t: in_scope(in_context(rows, context), scope) for t, rows in by_team.items()
                      if available(in_context(rows, context), scope)}
            population: dict[str, list[float]] = {}
            for rows in chosen.values():
                if len(rows) < MIN_MATCHES:
                    continue
                for fig in FIGURES:
                    m = measure(rows, fig)
                    if m.value is not None and m.covered:
                        population.setdefault(fig.key, []).append(m.value)
            for team_id, rows in chosen.items():
                if not rows:
                    continue
                docs.append(TeamDoc(team_id, scope, context, team_body(team_id, rows, population, ref, surv, scope, context,
                                                                       trend_refs), len(rows)))
    return docs, refs, surv


def team_body(team_id: int, rows: list[Row], population: dict[str, list[float]], ref: LeagueRef, surv: list[Doc],
              scope: str, context: str, trend_refs: dict[str, dict[str, tuple[int, int]]] | None = None) -> Doc:
    first = rows[0]
    name = first.match.home_name if first.home else first.match.away_name
    figures, pcts = _figures(rows, population, ref)
    goal_rows = [(r, g) for r in rows if (g := consistent_goals(r.match)) is not None]
    card_rows = [(r, regulation_cards(r.match.events)) for r in rows if r.match.events is not None]
    return TeamBody(
        team=Ref(id=team_id, name=name), record=record(rows), figures=figures, radar=_radar(figures, pcts), series=series(rows),
        halves=halves(rows), states=game_states(rows),
        pulse_for=_pulse("goles_a_favor", [_bins(g, r.side) for r, g in goal_rows], ref.pulse_for,
                         _seed(team_id, scope, context, "for")),
        pulse_against=_pulse("goles_en_contra", [_bins(g, r.other) for r, g in goal_rows], ref.pulse_against,
                             _seed(team_id, scope, context, "against")),
        pulse_cards=_pulse("tarjetas", [_bins(c, r.side) for r, c in card_rows], ref.pulse_cards,
                           _seed(team_id, scope, context, "cards")),
        intervals=intervals(rows, ref.interval_for, ref.interval_against), survival=survival(rows, surv),
        trends=trends(rows, ref.trends),
        matrix=matrix(rows, trend_refs or {}) if context == "all" else missing("sin_datos"))


def coverage(data: SeasonData) -> dict[str, float]:
    """EA-008: the share of team-matches that report each figure, over the whole competition season."""
    rows = [r for rs in team_rows(data).values() for r in rs]
    if not rows:
        return {}
    return {fig.key: fx.half_up(measure(rows, fig).with_data / len(rows), 4) for fig in FIGURES}


def latest_kickoff(data: SeasonData) -> datetime | None:
    return data.matches[-1].kickoff_at if data.matches else None
