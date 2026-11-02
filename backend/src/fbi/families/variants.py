"""A variant of a family's means set against the market (plan F12.5): the reading that decides whether an idea about a family is worth a hypothesis.

The comparison of the families with the books (``fbi.families.versus``) is made on the forecasts that were STORED, and those are the family as it is.
An idea about how to improve one - correct its level with what was seen lately, blend it with the market - cannot wait for weeks of stored
forecasts of the idea: it needs a way to stand it next to the family as it is, on the same matches, the same prices and the same outcomes, and to
repeat that reading whenever there is more data. This is that way. The first one, in ``FAMILIAS_VS_MERCADO_F11.md``, was a script thrown away after
use; this one is in the repository, with tests, and anyone can run it again.

What it does. For one family (``corners_ft``, ``cards_lines_ft``, ``yellow_ft``) it replays, week by week, the forecast the family would have stated
with what was known at the START of the week - the walk-forward of ``fbi.families.evaluate``, with the time decay, the penalty and the referee
multiplier the production job uses - and from those means it states every market that the books also quote, once as the family does (``as-is``) and
once for each VARIANT. Each is graded with what happened, set against the consensus of the books at the last price and a day before the kick-off (the
one ``fbi.families.versus`` and the scoreboard use: not a second definition of the market), and its simulated bets are counted against the plan's
criterion (``fbi.families.bets``).

Nothing it uses is a future of the week it states. The dispersion of each block is measured on the matches that kicked off in the ``dispersion_days``
before it and were already known (as the production job does), with the means of that variant; the variant ``recent-level:N`` scales the means of each
side by what was observed over what the family predicted in the ``N`` days before the block, again only over matches already known. Both are
ratios of matches that finished before the block started, and a test changes the outcomes from a block on and checks that no number of that block or of an
earlier one moves.

What it is not. It does not change the family, a forecast, a price, a pick or a model version: it reads, computes and prints. A variant that beats the
family here is a hypothesis with a measurement behind it (``fbi.research.hypotheses``), not a promotion: promoting is the owner's, through the loop
of Evolución. And a reading of four weeks of prices is short: what it leaves in doubt is said beside every number (the standard error is clustered by
match).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import numpy as np
import psycopg

from fbi.families import bets, evaluate, forecast, history, score, versus
from fbi.families.evaluate import Row
from fbi.families.fit import OUTCOME_KNOWN_AFTER, Dispersion, estimate_dispersion, prediction

VERSION: Final = "variants-v1"
AS_IS: Final = "as-is"
"""The family as it is today: the means of the walk-forward, untouched."""
RECENT_LEVEL: Final = "recent-level"
"""``recent-level:N``: the means of each side scaled by observed over predicted in the ``N`` days before the block."""
LEVEL_DAYS: Final = 28
"""The memory the correction uses when none is asked for: four weeks, the one the hypothesis of the guide proposes."""
MIN_LEVEL_DAYS: Final = 7
MAX_LEVEL_DAYS: Final = 365
MIN_PAST: Final = 200
"""Fewer matches than this (all the competitions together) in the window of a correction and the block is left as the family states it."""
STEP_DAYS: Final = 7
"""The length of a block: the family is refitted, and the forecast stated, at the start of each."""
DISPERSION_DAYS: Final = forecast.DISPERSION_DAYS
"""How far back the dispersion of a block is measured (the production job measures it on the same 120 days)."""
MAIN_BAND: Final = (0.08, 0.92)
"""The main line of a match is the line whose Over the market gives closest to one in two, among those the market gives between these two."""
MIN_SIGNAL: Final = 30
"""Fewer rows than this and the extra signal is not fitted."""
PROB_FLOOR: Final = 1e-4

OVER: Final = "Over"
TOTAL, HOME, AWAY, RESULT = "total", "home", "away", "result"
SUBJECTS: Final = (TOTAL, HOME, AWAY, RESULT)
"""What a comparison is about: the total of the match, one side's own count, and who had more (the 1X2 of the count)."""
MAIN, ALL = "main", "all"
SCOPES: Final = (MAIN, ALL)
"""The main line of each match (one row per match: the rows of one match depend on each other) or every line the market quotes."""
_SUBJECT_OF: Final = {"match": TOTAL, "home": HOME, "away": AWAY}


class NotAFamilyError(ValueError):
    """The family is not one this reading can be made for."""


def specs() -> dict[str, forecast.Spec]:
    """The families that can be read: those fitted on ONE count, which states the markets the books also quote."""
    return {s.key: s for s in forecast.SPECS if len(s.measures) == 1 and s.over_dispersed}


def spec_of(family: str) -> forecast.Spec:
    found = specs().get(family)
    if found is None:
        raise NotAFamilyError(f"{family!r} cannot be read here: {', '.join(sorted(specs()))}")
    return found


# ── the variants ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    level_days: int = 0
    """With a value, the means are scaled by observed over predicted of this many days before the block."""


def parse(text: str) -> Variant:
    """``as-is`` or ``recent-level:N`` (N days, ``MIN_LEVEL_DAYS`` to ``MAX_LEVEL_DAYS``)."""
    name = text.strip().lower()
    if name == AS_IS:
        return Variant(AS_IS)
    kind, _, days = name.partition(":")
    if kind == RECENT_LEVEL and days.isascii() and days.isdigit() and MIN_LEVEL_DAYS <= int(days) <= MAX_LEVEL_DAYS:
        return Variant(f"{RECENT_LEVEL}:{int(days)}", int(days))
    raise ValueError(f"{text!r} is not a variant: {AS_IS!r} or {RECENT_LEVEL}:DAYS with DAYS from {MIN_LEVEL_DAYS} to {MAX_LEVEL_DAYS}")


def variants_of(texts: Iterable[str]) -> list[Variant]:
    """The family as it is, always first, and the variants asked for, each once."""
    out = [Variant(AS_IS)]
    for text in texts:
        variant = parse(text)
        if variant not in out:
            out.append(variant)
    return out


# ── the weeks ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Window:
    """``[start, end)`` are the kick-offs compared; the walk-forward begins at ``first``, earlier by the history that the corrections and the dispersion
    of the first block need (they are not compared). Blocks are ``step_days`` long from ``first``, so ``start`` is the start of one."""

    first: datetime
    start: datetime
    end: datetime
    step_days: int


def plan(start: datetime, end: datetime, *, step_days: int, burn_in_days: int) -> Window:
    """The walk-forward window for kick-offs in ``[start, end)`` whose first block still has ``burn_in_days`` of forecasts behind it."""
    if end <= start:
        raise ValueError(f"the window is empty: {start.isoformat()} to {end.isoformat()}")
    if step_days < 1:
        raise ValueError("a block is at least a day long")
    blocks = -(-max(burn_in_days, 0) // step_days) + 1
    return Window(start - timedelta(days=blocks * step_days), start, end, step_days)


def block_start(kickoff: datetime, window: Window) -> datetime:
    """The start of the block a match is stated in: the moment the family was last refitted before it."""
    step = timedelta(days=window.step_days)
    return window.first + ((kickoff - window.first) // step) * step


def known(row: Row) -> datetime:
    """From when the outcome of a match can be used."""
    return row.kickoff_at + OUTCOME_KNOWN_AFTER


@dataclass(frozen=True, slots=True)
class Level:
    """Observed over predicted of the matches already known at ``at``, in the days before it."""

    at: datetime
    home: float
    away: float
    matches: int


def level_at(rows: Sequence[Row], *, at: datetime, days: int) -> Level | None:
    """What the family did over the ``days`` before ``at`` with the matches whose outcome was known by then, or None when there are fewer than
    ``MIN_PAST``. Nothing from ``at`` on enters: a match counts only once ``OUTCOME_KNOWN_AFTER`` has passed since its kick-off."""
    since = at - timedelta(days=days)
    past = [r for r in rows if since <= r.kickoff_at and known(r) <= at]
    if len(past) < MIN_PAST:
        return None
    predicted_home, predicted_away = sum(r.mu_home for r in past), sum(r.mu_away for r in past)
    if predicted_home <= 0.0 or predicted_away <= 0.0:
        return None
    return Level(at, sum(r.y_home for r in past) / predicted_home, sum(r.y_away for r in past) / predicted_away, len(past))


def corrected(rows: Sequence[Row], variant: Variant, window: Window) -> tuple[list[Row], dict[datetime, Level | None]]:
    """The rows as the variant states them, and the correction of each block (None: the block is left as the family states it). The ratio is that
    of the FAMILY's own predictions (``rows``), not of the corrected ones."""
    if not variant.level_days:
        return list(rows), {}
    levels: dict[datetime, Level | None] = {}
    out: list[Row] = []
    for r in rows:
        at = block_start(r.kickoff_at, window)
        if at not in levels:
            levels[at] = level_at(rows, at=at, days=variant.level_days)
        level = levels[at]
        out.append(r if level is None else replace(r, mu_home=r.mu_home * level.home, mu_away=r.mu_away * level.away))
    return out, levels


@dataclass(frozen=True, slots=True)
class Spread:
    """The dispersion that a block states with, and the matches it was measured on."""

    at: datetime
    dispersion: Dispersion
    matches: int


def spread_at(rows: Sequence[Row], *, at: datetime, days: int, minimum: int) -> Spread | None:
    """The dispersion of the three counts measured on the matches that kicked off in the ``days`` before ``at`` and were known by then (the means
    are those the variant stated them with), or None when they are fewer than ``minimum``: a family states nothing it cannot measure."""
    since = at - timedelta(days=days)
    past = [r for r in rows if since <= r.kickoff_at and known(r) <= at]
    if len(past) < minimum:
        return None
    return Spread(at, estimate_dispersion([r.y_home for r in past], [r.mu_home for r in past], [r.y_away for r in past], [r.mu_away for r in past]),
                  len(past))


# ── what each variant states ─────────────────────────────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Forecasts:
    """Everything one variant states for the matches of the window: a row per selection of every market the books also quote."""

    variant: Variant
    rows: list[score.Row] = field(default_factory=list)
    levels: dict[datetime, Level | None] = field(default_factory=dict)
    spreads: dict[datetime, Spread | None] = field(default_factory=dict)
    matches: int = 0
    corrected_matches: int = 0
    without_spread: int = 0


def forecasts(base: Sequence[Row], variant: Variant, spec: forecast.Spec, *, available: frozenset[str], window: Window,
              dispersion_days: int = DISPERSION_DAYS, min_dispersion: int = forecast.MIN_DISPERSION_MATCHES) -> Forecasts:
    """What ``variant`` states for every match of the window, from the means of the walk-forward ``base`` (the family's own) and what was known at
    the start of the block of each. The markets are those the family states (``spec.build``) that the books quote (the kinds of ``versus.OUTCOMES``)."""
    rows, levels = corrected(base, variant, window)
    out = Forecasts(variant, levels=levels)
    for r in rows:
        if not window.start <= r.kickoff_at < window.end:
            continue
        out.matches += 1
        at = block_start(r.kickoff_at, window)
        if at not in out.spreads:
            out.spreads[at] = spread_at(rows, at=at, days=dispersion_days, minimum=min_dispersion)
        spread = out.spreads[at]
        if spread is None:
            out.without_spread += 1
            continue
        if levels.get(at) is not None:
            out.corrected_matches += 1
        pred = prediction(r.mu_home, r.mu_away, spread.dispersion)
        for probs in spec.build([pred], available):
            if score.key_shape(probs.market_key)[0] not in versus.OUTCOMES:
                continue
            for selection, p in probs.outcomes:
                out.rows.append(score.Row(r.fixture_id, variant.name, probs.market_key, Decimal(str(probs.line)), selection, p, at))
    return out


# ── the reading ──────────────────────────────────────────────────────────────────────────────────────────────────

def groups_of(pairs: Iterable[versus.Pair]) -> dict[tuple[str, str, str], list[versus.Pair]]:
    """The pairs by (moment, subject, scope), the Over of each line only (the Under is its complement and says nothing more). The main line of a
    match at a moment is chosen by the MARKET alone - the line whose Over it gives closest to one in two, within ``MAIN_BAND`` - so it is the same
    line for every variant."""
    out: dict[tuple[str, str, str], list[versus.Pair]] = defaultdict(list)
    main: dict[tuple[str, int, str], versus.Pair] = {}
    for p in pairs:
        kind, subject = score.key_shape(p.key)
        if kind == "one_x_two":
            out[(p.ref, RESULT, ALL)].append(p)
        elif kind == "over_under" and p.selection == OVER:
            out[(p.ref, _SUBJECT_OF[subject], ALL)].append(p)
            if MAIN_BAND[0] <= p.p_market <= MAIN_BAND[1]:
                slot = (p.ref, p.fixture_id, p.key)
                held = main.get(slot)
                if held is None or (abs(p.p_market - 0.5), p.line) < (abs(held.p_market - 0.5), held.line):
                    main[slot] = p
    for (ref, _, key), p in main.items():
        out[(ref, _SUBJECT_OF[score.key_shape(key)[1]], MAIN)].append(p)
    return dict(out)


def _logit(p: Any) -> Any:
    q = np.clip(p, PROB_FLOOR, 1.0 - PROB_FLOOR)
    return np.log(q / (1.0 - q))


def extra_signal(pairs: Sequence[versus.Pair]) -> dict[str, float] | None:
    """Does the model say anything the market did not? A logistic regression of what happened on ``1``, the market's logit and the model's logit
    MINUS the market's: the coefficient of the last term is 0 when the model adds nothing to the market and 1 when it deserves full weight on top
    of it. Its standard error is clustered by match (a match with several lines is one observation of how right the model was). None when there
    are fewer than ``MIN_SIGNAL`` rows or only one outcome happened."""
    n = len(pairs)
    y = np.array([p.won for p in pairs], dtype=float)
    if n < MIN_SIGNAL or float(y.min()) == float(y.max()):
        return None
    z_model = _logit(np.array([p.p_model for p in pairs]))
    z_market = _logit(np.array([p.p_market for p in pairs]))
    x = np.column_stack([np.ones(n), z_market, z_model - z_market])
    beta = np.zeros(3)
    try:
        for _ in range(60):
            mu = 1.0 / (1.0 + np.exp(-(x @ beta)))
            hessian = x.T @ (x * (mu * (1.0 - mu))[:, None]) + 1e-9 * np.eye(3)
            step = np.linalg.solve(hessian, x.T @ (y - mu))
            beta = beta + step
            if float(np.abs(step).max()) < 1e-9:
                break
        mu = 1.0 / (1.0 + np.exp(-(x @ beta)))
        hessian = x.T @ (x * (mu * (1.0 - mu))[:, None]) + 1e-9 * np.eye(3)
        _, cluster = np.unique(np.array([p.fixture_id for p in pairs]), return_inverse=True)
        sums = np.zeros((int(cluster.max()) + 1, 3))
        np.add.at(sums, cluster, x * (y - mu)[:, None])
        inverse = np.linalg.inv(hessian)
        se = np.sqrt(np.diag(inverse @ (sums.T @ sums) @ inverse))
    except np.linalg.LinAlgError:
        return None
    if not np.isfinite(beta).all() or not np.isfinite(se).all():
        return None
    return {"coef": float(beta[2]), "se": float(se[2]), "market_slope": float(beta[1]), "market_slope_se": float(se[1])}


def summarise(pairs: Sequence[versus.Pair]) -> dict[str, Any]:
    """One group of pairs: what each said, what happened, the log losses, their difference (market minus model: positive, the model was better) and
    the extra signal."""
    return {**versus.block(pairs), "signal": extra_signal(pairs)}


def _key(p: versus.Pair) -> tuple[str, int, str, Decimal, str]:
    return p.ref, p.fixture_id, p.key, p.line, p.selection


def paired(reference: Sequence[versus.Pair], other: Sequence[versus.Pair]) -> dict[str, Any]:
    """``other`` against ``reference`` on the very same rows (the market and the outcome are the same, only the model's probability differs): the
    log loss ``other`` saves per row (positive: ``other`` was better) and its standard error, clustered by match."""
    index = {_key(p): p for p in reference}
    diffs: list[tuple[int, float]] = []
    for q in other:
        p = index.get(_key(q))
        if p is not None:
            diffs.append((q.fixture_id, versus.loss(p.p_model, p.won) - versus.loss(q.p_model, q.won)))
    n = len(diffs)
    if n == 0:
        return {"n": 0, "fixtures": 0, "gain": None, "se": None}
    mean = sum(d for _, d in diffs) / n
    by_match: dict[int, float] = defaultdict(float)
    for fixture_id, d in diffs:
        by_match[fixture_id] += d - mean
    return {"n": n, "fixtures": len(by_match), "gain": mean, "se": math.sqrt(sum(v * v for v in by_match.values())) / n}


def early(graded: Iterable[score.Graded], kickoffs: Mapping[int, datetime]) -> list[score.Graded]:
    """The graded rows stated at least ``bets.PICK_LEAD`` before the kick-off: what a bet taken that long before it could have used. The forecast of a
    block is stated at the start of the block, so a match in the last day of its block has none."""
    return [g for g in graded if g.row.known_at + bets.PICK_LEAD <= kickoffs[g.row.fixture_id]]


def assess(stated: Sequence[Forecasts], base: Sequence[Row], *, measure: str, kickoffs: Mapping[int, datetime],
           fair: Mapping[versus.FairKey, tuple[float, int]], best: Mapping[versus.FairKey, tuple[float, int]], min_books: int = versus.MIN_BOOKS,
           min_ev: float = bets.MIN_EV) -> dict[str, Any]:
    """Grade what each variant stated and set it against the books: for each variant, each moment and each subject, the main line and every line
    (``summarise``); each variant against the family as it is on the same rows (``paired``); and the bets each would have simulated, against the
    criterion of the plan."""
    home_column, away_column = history.columns_of(measure)
    counts = {r.fixture_id: {home_column: r.y_home, away_column: r.y_away} for r in base}
    groups: dict[str, dict[tuple[str, str, str], list[versus.Pair]]] = {}
    on_the_day_before: list[score.Graded] = []
    left = {"pushed": 0, "ungradable": 0}
    report_variants: dict[str, Any] = {}
    for f in stated:
        graded, not_graded = score.grade(f.rows, counts)
        for k, v in not_graded.items():
            left[k] += v
        groups[f.variant.name] = groups_of(versus.pairs(graded, fair, min_books=min_books))
        on_the_day_before += early(graded, kickoffs)
        tree: dict[str, Any] = {}
        for (ref, subject, scope), members in sorted(groups[f.variant.name].items()):
            tree.setdefault(ref, {}).setdefault(subject, {})[scope] = summarise(members)
        report_variants[f.variant.name] = {
            "level_days": f.variant.level_days, "matches": f.matches, "corrected_matches": f.corrected_matches, "without_dispersion": f.without_spread,
            "levels": [{"at": at.isoformat(), "home": lv.home, "away": lv.away, "matches": lv.matches}
                       for at, lv in sorted(f.levels.items()) if lv is not None and f.spreads.get(at) is not None],
            "dispersion": [{"at": at.isoformat(), "home": s.dispersion.home, "away": s.dispersion.away, "total": s.dispersion.total, "matches": s.matches}
                           for at, s in sorted(f.spreads.items()) if s is not None],
            "versus": tree,
        }
    reference = stated[0].variant.name
    against: dict[str, Any] = {}
    for f in stated[1:]:
        tree = {}
        for key, members in sorted(groups[f.variant.name].items()):
            ref, subject, scope = key
            tree.setdefault(ref, {}).setdefault(subject, {})[scope] = paired(groups[reference].get(key, []), members)
        against[f.variant.name] = tree
    return {"variants": report_variants, "paired": against, "reference": reference, "bets": bets.report(on_the_day_before, fair, best, min_ev=min_ev, min_books=min_books),
            "left_out": left}


def run(conn: psycopg.Connection[Any], *, family: str, variants: Sequence[Variant], start: datetime, end: datetime, step_days: int = STEP_DAYS,
        dispersion_days: int = DISPERSION_DAYS, min_dispersion: int = forecast.MIN_DISPERSION_MATCHES, min_books: int = versus.MIN_BOOKS,
        min_ev: float = bets.MIN_EV) -> dict[str, Any]:
    """The reading for the kick-offs in ``[start, end)``: replay the family week by week, state each variant, read the prices of the books and
    compare. Reads only (the caller opens the connection read-only). ``variants[0]`` is the reference the others are compared with."""
    spec = spec_of(family)
    measure = spec.measures[0]
    window = plan(start, end, step_days=step_days, burn_in_days=dispersion_days + max((v.level_days for v in variants), default=0))
    data = history.load(conn, measure, since=window.first - timedelta(days=forecast.HISTORY_DAYS), cutoff=window.end + OUTCOME_KNOWN_AFTER,
                        with_referee=bool(spec.referee_kappa))
    usable = {competition: matches for competition, matches in data.items() if forecast.teams(matches) <= forecast.MAX_TEAMS}
    evaluation = evaluate.walk_forward(usable, measure=measure, start=window.first, end=window.end, step_days=step_days, xi=spec.xi,
                                       penalty=spec.penalty, referee_kappa=spec.referee_kappa or None)
    base = sorted(evaluation.rows, key=lambda r: (r.kickoff_at, r.fixture_id))
    available = forecast.available_keys(conn)
    stated = [forecasts(base, v, spec, available=available, window=window, dispersion_days=dispersion_days, min_dispersion=min_dispersion)
              for v in variants]
    kickoffs = {r.fixture_id: r.kickoff_at for r in base}
    keys = sorted({row.key for f in stated for row in f.rows})
    inside = [r for r in base if window.start <= r.kickoff_at < window.end]
    fixtures = {r.fixture_id for r in inside}
    fair, best = versus.read_prices(conn, fixtures=fixtures, keys=keys, since=window.start)
    report = assess(stated, base, measure=measure, kickoffs=kickoffs, fair=fair, best=best, min_books=min_books, min_ev=min_ev)
    report.update({
        "version": VERSION, "family": family, "measure": measure,
        "params": {"xi": spec.xi, "penalty": spec.penalty, "referee_kappa": spec.referee_kappa},
        "window": {"start": window.start.isoformat(), "end": window.end.isoformat(), "first_block": window.first.isoformat(), "step_days": step_days},
        "criterion": {"min_books": min_books, "min_ev": min_ev, "min_bets": bets.MIN_BETS, "dispersion_days": dispersion_days,
                      "min_dispersion": min_dispersion, "min_past": MIN_PAST, "main_band": list(MAIN_BAND), "pick_lead_hours": bets.PICK_LEAD.total_seconds() / 3600,
                      "references": [r for r, _ in versus.REFERENCES]},
        "history": {"competitions": len(usable), "competitions_dropped": len(data) - len(usable), "walk_forward_rows": len(base),
                    "window_with_referee": sum(1 for r in inside if r.with_referee), "blocks_without_history": evaluation.skipped_blocks,
                    "priced_fixtures": len({k[1] for k in fair}), "prices": len(fair)},
    })
    return report


# ── to read ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _signal(x: Mapping[str, float] | None) -> str:
    return "  n/a" if x is None else f"{x['coef']:+.2f} ± {x['se']:.2f}"


def render(report: Mapping[str, Any]) -> str:
    """The reading as text: per moment and subject, the family as it is and each variant on the main line of each match; then every line, the
    variants against the family on the same rows and the simulated bets."""
    w, c = report["window"], report["criterion"]
    lines = [f"{report['family']} ({report['version']}): the family and its variants set against the books, kick-offs {w['start'][:16]} to {w['end'][:16]} UTC, "
             f"a forecast per {w['step_days']} days with what was known at the start of each; the books' own probability, margin removed, {c['min_books']}+ books"]
    reference = report["reference"]
    if report["params"]["referee_kappa"]:
        lines.append(f"  the referee's multiplier (kappa {report['params']['referee_kappa']:g}) is part of the family's means: it was applied to "
                     f"{report['history']['window_with_referee']} of {report['variants'][reference]['matches']} matches")
    for name, v in report["variants"].items():
        extra = f", corrected in {v['corrected_matches']} of them" if v["level_days"] else ""
        lines.append(f"  {name}: {v['matches']} matches{extra}; without a dispersion to state with: {v['without_dispersion']}")
        for lv in v["levels"]:
            lines.append(f"      level of the block of {lv['at'][:10]}: home x{lv['home']:.3f}, away x{lv['away']:.3f} ({lv['matches']} matches)")
    for scope, title in ((MAIN, "main line of each match (the Over the market gives closest to one in two)"), (ALL, "every line, the Over of each")):
        body: list[str] = []
        for ref in c["references"]:
            for subject in SUBJECTS:
                for name, v in report["variants"].items():
                    b = v["versus"].get(ref, {}).get(subject, {}).get(scope)
                    if b is None:
                        continue
                    body.append(f"  {ref:<5} {subject:<6} {name:<16} n {b['n']:>5}  model said {b['mean_p_model'] * 100:5.1f} %  market {b['mean_p_market'] * 100:5.1f} %  "
                                f"happened {b['observed'] * 100:5.1f} %  log loss {b['log_loss_model']:.4f} / {b['log_loss_market']:.4f}  "
                                f"market minus model {b['market_minus_model']:+.4f} ± {b['se']:.4f}  signal {_signal(b['signal'])}")
        if body:
            lines.append(f"{title}; market minus model: positive means the model was better; extra signal: 0 = adds nothing to the market, 1 = full weight on top")
            lines += body
    for name, tree in report["paired"].items():
        body = []
        for ref in c["references"]:
            for subject in SUBJECTS:
                for scope in SCOPES:
                    p = tree.get(ref, {}).get(subject, {}).get(scope)
                    if p is not None and p["n"]:
                        body.append(f"  {ref:<5} {subject:<6} {scope:<5} n {p['n']:>5}  saves {p['gain']:+.4f} ± {p['se']:.4f}")
        if body:
            lines.append(f"{name} against {reference} on the same rows (log loss it saves per row, positive: better than {reference}):")
            lines += body
    lines.append(bets.render(report["bets"]))
    if any(report["left_out"].values()):
        lines.append(f"left out: {report['left_out']}")
    return "\n".join(lines)
