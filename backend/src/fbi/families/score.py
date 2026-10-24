"""The scoreboard of the stored family forecasts (plan F11): how the research forecasts of ``family-v1`` did once the matches were over.

The forecasts of the families are stored before the kick-off, UNCALIBRATED, and nobody prices or shows them. What can be measured about them with
no price at all is whether the probabilities they state were right: of the times a model said 60 %, did it happen 60 % of the time? This module
grades the stored rows of the finished matches of a window - the LAST forecast of each match, stored before it started - against what the match
turned out to be. The outcomes come through the one door the families read them through (``fbi.families.history``: a result counts only once it is
known and, for the cards, once the statistics have settled), and the arithmetic of a bet is the one that will settle a pick on a family
(``fbi.picks.count_settlement``).

Each stored row is a yes/no question - "will this selection win?" - with a probability, so every measure is per row:

    calibration    the probabilities said against the frequency that happened, by tenths (and the mean gap between them, weighted by rows)
    log loss       the mean of -log(probability given to what happened), per row
    constant       the log loss of the best constant probability for the same selection, fitted on the very same matches. It has seen the
                   answers, so it is a hard bar: a model that beats it knows more than how often the thing happens; one that does not may
                   still be well calibrated
    brier          the mean squared gap between the probability and what happened

A row whose bet does not settle as a win or a loss (a push) is left out and counted; a row whose count is unknown is counted as ungradable and
never read as a loss. It reads only: 0 provider requests, 0 AI, and nothing it prints goes into a model, a price or a pick.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.families import bets, forecast, history, versus
from fbi.families.fit import OUTCOME_KNOWN_AFTER
from fbi.market.catalogue import KINDS
from fbi.market.rules import RULES_BY_MEASURE
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status

BINS: Final = 10
"""The tenths of probability the calibration is read in."""
PREFIXES: Final = frozenset({"CORNERS", "CARDS", "YELLOW", "RED", "POINTS", "SOT", "SHOTS", "FOULS", "OFFSIDES", "SAVES"})
HALVES_KEYS: Final = frozenset({"HTFT", "HSH", "HSH_HOME", "HSH_AWAY"})
_KIND_OF: Final = {abbreviation: kind for kind, (abbreviation, _) in KINDS.items()}


@dataclass(frozen=True, slots=True)
class Row:
    """One stored forecast: the probability of one selection of one market, as it stood just before the kick-off."""

    fixture_id: int
    model: str
    key: str
    line: Decimal
    selection: str
    p: float
    known_at: datetime


@dataclass(frozen=True, slots=True)
class Graded:
    """A forecast row and what happened: ``won`` is 1 when the selection won and 0 when it lost."""

    row: Row
    won: int


def key_shape(key: str) -> tuple[str, str]:
    """The kind of bet and the subject (``match``, ``home``, ``away``) of a market key of the catalogue: ``CORNERS_OU_HOME`` is an over/under on the
    corners of the home side, ``OU_1H`` one on the goals of the first half, ``HTFT`` half time / full time. Raises for a key it cannot read."""
    parts = key.split("_")
    if parts[0] in PREFIXES:
        parts = parts[1:]
    if parts and parts[-1] in ("1H", "2H"):
        parts = parts[:-1]
    subject = "match"
    if parts and parts[-1] in ("HOME", "AWAY"):
        subject = parts.pop().lower()
    kind = _KIND_OF.get("_".join(parts))
    if kind is None:
        raise ValueError(f"the key {key!r} is not one the scoreboard can read")
    return kind, subject


def measure_of(key: str) -> str:
    """The measure of the settlement rules (``fbi.market.rules``) that grades a market key."""
    if key.startswith("CORNERS_"):
        return "corners_ft"
    if key.startswith("CARDS_"):
        return "cards_lines_ft"
    if key.startswith("YELLOW_"):
        return "yellow_ft"
    if key in HALVES_KEYS:
        return "goals_halves"
    if key.endswith("_1H"):
        return "goals_1h"
    if key.endswith("_2H"):
        return "goals_2h"
    raise ValueError(f"the key {key!r} is not graded on a measure the scoreboard can read")


def measures_to_read(keys: Iterable[str]) -> list[str]:
    """The measures whose counts grade these keys (HT/FT and the highest scoring half read both halves)."""
    out: set[str] = set()
    for key in keys:
        measure = measure_of(key)
        out.update(("goals_1h", "goals_2h") if measure == "goals_halves" else (measure,))
    return sorted(out)


def grade(rows: Iterable[Row], counts: Mapping[int, Mapping[str, int | None]]) -> tuple[list[Graded], dict[str, int]]:
    """Grade the rows against the counts of the finished matches (``counts``: for each match, the columns of the rules). Returns the rows that
    settled as a win or a loss and, apart, how many did not: ``pushed`` (the stake would come back), ``ungradable`` (a count is unknown, or the
    match has none yet)."""
    graded: list[Graded] = []
    left = {"pushed": 0, "ungradable": 0}
    for row in rows:
        kind, subject = key_shape(row.key)
        values = counts.get(row.fixture_id)
        status = None if values is None else settle_numbers(RULES_BY_MEASURE[measure_of(row.key)], kind, subject, row.selection, row.line, values)
        if status is None:
            left["ungradable"] += 1
        elif status is Status.WIN or status is Status.LOSS:
            graded.append(Graded(row, 1 if status is Status.WIN else 0))
        else:
            left["pushed"] += 1
    return graded, left


def _log_loss(p: float, won: int) -> float:
    return -math.log(p if won else 1.0 - p)


def _entropy(frequency: float) -> float:
    """The log loss of the constant probability ``frequency`` on the very rows it is the frequency of."""
    if frequency <= 0.0 or frequency >= 1.0:
        return 0.0
    return -(frequency * math.log(frequency) + (1.0 - frequency) * math.log(1.0 - frequency))


def _reliability(graded: Sequence[Graded]) -> list[dict[str, float]]:
    bins: list[list[Graded]] = [[] for _ in range(BINS)]
    for g in graded:
        bins[min(int(g.row.p * BINS), BINS - 1)].append(g)
    return [{"lo": i / BINS, "hi": (i + 1) / BINS, "n": len(b), "mean_p": sum(g.row.p for g in b) / len(b),
             "observed": sum(g.won for g in b) / len(b)} for i, b in enumerate(bins) if b]


def summarise(graded: Sequence[Graded], left: Mapping[str, int] | None = None) -> dict[str, Any]:
    """The scoreboard of the graded rows, model by model: calibration, log loss against the constant, Brier, and each selection of each market."""
    by_model: dict[str, list[Graded]] = defaultdict(list)
    for g in graded:
        by_model[g.row.model].append(g)
    models: dict[str, Any] = {}
    for model, rows in sorted(by_model.items()):
        groups: dict[tuple[str, Decimal, str], list[Graded]] = defaultdict(list)
        for g in rows:
            groups[(g.row.key, g.row.line, g.row.selection)].append(g)
        markets = []
        constant_loss = 0.0
        for (key, line, selection), members in sorted(groups.items()):
            n = len(members)
            observed = sum(g.won for g in members) / n
            model_loss = sum(_log_loss(g.row.p, g.won) for g in members) / n
            reference = _entropy(observed)
            constant_loss += reference * n
            markets.append({"key": key, "line": float(line), "selection": selection, "n": n,
                            "mean_p": sum(g.row.p for g in members) / n, "observed": observed,
                            "log_loss": model_loss, "log_loss_constant": reference, "gain": reference - model_loss})
        n = len(rows)
        reliability = _reliability(rows)
        loss = sum(_log_loss(g.row.p, g.won) for g in rows) / n
        models[model] = {
            "fixtures": len({g.row.fixture_id for g in rows}), "rows": n, "log_loss": loss, "log_loss_constant": constant_loss / n,
            "gain": constant_loss / n - loss, "brier": sum((g.row.p - g.won) ** 2 for g in rows) / n,
            "ece": sum(b["n"] * abs(b["mean_p"] - b["observed"]) for b in reliability) / n, "reliability": reliability, "markets": markets,
        }
    return {"models": models, "left_out": dict(left or {})}


FORECASTS_SQL: Final = """
SELECT DISTINCT ON (f.fixture_id, f.model_name, f.market_key, f.line, f.selection)
       f.fixture_id, f.model_name, f.market_key, f.line, f.selection, f.p, f.known_at
  FROM models.match_forecasts f JOIN core.fixtures x ON x.id = f.fixture_id
 WHERE f.version = %(version)s AND x.kickoff_at >= %(since)s AND x.kickoff_at < %(until)s AND f.known_at < x.kickoff_at
   AND f.known_at <= x.kickoff_at - %(lead)s::interval AND (%(model)s::text IS NULL OR f.model_name = %(model)s)
 ORDER BY f.fixture_id, f.model_name, f.market_key, f.line, f.selection, f.known_at DESC
"""
"""The last forecast of each selection of each market of each match that was stored before the kick-off - and at least ``lead`` before it - for
the kick-offs of the window."""


def load_forecasts(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, model: str | None = None,
                   version: str = forecast.VERSION, lead: timedelta = timedelta(0)) -> list[Row]:
    """The stored forecasts the matches of the window are graded with: the last one stored before the kick-off or, with ``lead``, the last one
    stored at least that long before it (what a bet taken ``lead`` before the kick-off could have used)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FORECASTS_SQL, {"version": version, "since": since, "until": until, "model": model, "lead": lead})
        return [Row(int(r["fixture_id"]), str(r["model_name"]), str(r["market_key"]), Decimal(r["line"]), str(r["selection"]), float(r["p"]),
                    r["known_at"]) for r in cur.fetchall()]


def load_counts(conn: psycopg.Connection[Any], measures: Sequence[str], *, since: datetime, until: datetime) -> dict[int, dict[str, int]]:
    """The counts of the finished matches, by match, under the names of the columns the rules read. ``until`` is the latest kick-off: the
    door waits ``OUTCOME_KNOWN_AFTER`` after it by itself, so the cut-off it is given is that much later."""
    out: dict[int, dict[str, int]] = defaultdict(dict)
    for measure in measures:
        home_column, away_column = history.columns_of(measure)
        for matches in history.load(conn, measure, since=since, cutoff=until + OUTCOME_KNOWN_AFTER).values():
            for m in matches:
                out[m.fixture_id][home_column] = m.home
                out[m.fixture_id][away_column] = m.away
    return dict(out)


def score(conn: psycopg.Connection[Any], *, now: datetime, days: int = 14, wait_hours: float = 30.0, model: str | None = None,
          market: bool = True, min_books: int = versus.MIN_BOOKS, min_ev: float = bets.MIN_EV) -> dict[str, Any]:
    """Grade the family forecasts of the matches that kicked off in the last ``days`` days, leaving out the last ``wait_hours`` hours: the
    statistics of the cards settle some 26 hours after the match, and a count read before that is short.

    With ``market`` the graded rows are also set against the consensus of the books (``fbi.families.versus``): the test of whether the model
    knew anything the prices did not. And the bets that the forecasts of a day before the kick-off would have placed at the best price of that
    day are simulated and set against the plan's criterion for a family to decide in shadow (``fbi.families.bets``): at least 300 bets and a
    closing-line value that is not negative."""
    until = now - timedelta(hours=wait_hours)
    since = now - timedelta(days=days)
    rows = load_forecasts(conn, since=since, until=until, model=model)
    early = load_forecasts(conn, since=since, until=until, model=model, lead=bets.PICK_LEAD) if market else []
    counts = load_counts(conn, measures_to_read(r.key for r in [*rows, *early]), since=since, until=until)
    graded, left = grade(rows, counts)
    report = summarise(graded, left)
    report["window"] = {"since": since.isoformat(), "until": until.isoformat(), "wait_hours": wait_hours, "forecast_rows": len(rows)}
    if market:
        graded_early, _ = grade(early, counts)
        priced = [*graded, *graded_early]
        keys = sorted({g.row.key for g in priced if key_shape(g.row.key)[0] in versus.OUTCOMES})
        fair, best = versus.read_prices(conn, fixtures={g.row.fixture_id for g in priced}, keys=keys, since=since)
        report["versus"] = versus.versus(graded, fair, min_books=min_books)
        report["bets"] = bets.report(graded_early, fair, best, min_ev=min_ev, min_books=min_books)
    return report


def render(report: Mapping[str, Any], *, top: int = 12, min_rows: int = 50) -> str:
    """The scoreboard as text: for each model its sums and the selections that stray most from what happened."""
    w = report["window"]
    lines = [f"family forecasts of the matches kicking off {w['since'][:16]} to {w['until'][:16]} UTC (results waited {w['wait_hours']:g} h), "
             f"{w['forecast_rows']} stored rows read; left out: {report['left_out']}"]
    if not report["models"]:
        lines.append("  nothing to grade yet: no finished match of the window has a stored forecast with its count known")
    for model, m in report["models"].items():
        lines.append(f"{model}: {m['fixtures']} matches, {m['rows']} rows - log loss {m['log_loss']:.4f} against {m['log_loss_constant']:.4f} for "
                     f"the best constant (gain {m['gain']:+.4f} a row), Brier {m['brier']:.4f}, calibration gap {m['ece'] * 100:.1f} points")
        stray = sorted((x for x in m["markets"] if x["n"] >= min_rows), key=lambda x: -abs(x["mean_p"] - x["observed"]) * math.sqrt(x["n"]))
        for x in stray[:top]:
            lines.append(f"    {x['key']:<16} {x['line']:>5g} {x['selection']:<10} n {x['n']:>5}  said {x['mean_p'] * 100:5.1f} %  "
                         f"happened {x['observed'] * 100:5.1f} %  gain {x['gain']:+.4f}")
    if "versus" in report and report["models"]:
        lines.append(versus.render(report["versus"], min_rows=min_rows))
    if "bets" in report and report["models"]:
        lines.append(bets.render(report["bets"], min_rows=min_rows))
    return "\n".join(lines)
