"""The LAB of the protocol ``AD-B07`` (IA-095): ``family-v1`` refitted block by block, its out-of-sample dispersion, the calibrator
``count-cal-v1``, the league mean and the market without margin - one verdict per family. Pure: no database, no clock.

THE WALK, as the protocol fixes it. Blocks of ``STEP_DAYS`` from ``warmup`` to ``end``. In each block, for each competition:

* family-v1 as it runs (``fbi.families.fit.fit_family`` with the hyper-parameters of ``fbi.families.forecast.SPECS``) is fitted on the
  matches KNOWN at the start of the block (kick-off + 6 h) and predicts the matches of the block;
* the league mean of the same training window is the baseline (``fbi.families.evaluate._baseline``'s rule, written here again);
* for the cards, the referee's multiplier (``fbi.families.referee.factors``, KAPPA 150, 5 matches) learned from that training, applied
  to a match only when its referee was designated ``REFEREE_LEAD`` or more before the kick-off (``referee_known``).

Then, block by block in the order of time, from the predictions of the EARLIER blocks whose result was known at the start of the
block (and of the last ``CAL_WINDOW``): the NB2 dispersion of the model, of the model with the referee and of the baseline, and one
calibrator per family (``fbi.countcal.calibrator.fit``) on the probabilities as they were stated then. A block with fewer than
``MIN_FIT`` such matches is not scored in any arm. Only blocks that start at ``start`` or later are scored.

Nothing is ever predicted, dispersed or calibrated with a match whose result was not known by then.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from fbi.countcal import calibrator as cc
from fbi.families import referee as fref
from fbi.families.counts import MAX_COUNT, fit_dispersion, nb_pmf, normalised
from fbi.families.fit import (
    DAY,
    Dispersion,
    Fitted,
    Match,
    NotEnoughHistoryError,
    fit_family,
    known_at,
)

STEP_DAYS: Final = 28
CAL_WINDOW: Final = timedelta(days=365)
REFEREE_LEAD: Final = timedelta(hours=3)
XI: Final = 0.0019
PENALTY: Final = 32.0
REFEREE_KAPPA: Final = fref.KAPPA
MAX_TEAMS: Final = 250
BOGOTA: Final = timedelta(hours=-5)
BOOTSTRAP: Final = 2000
NON_INFERIORITY: Final = 0.001
MAX_ECE: Final = 0.03
ECE_MIN_N: Final = 200
MIN_MATCHES: Final = 1500
MIN_DAYS: Final = 60
MIN_MARKET: Final = 300
FEW_REFEREE_MATCHES: Final = 10
REFEREE_BAND: Final = 0.25

VALIDATED: Final = "VALIDADO"
NOT_VALIDATED: Final = "NO VALIDADO"
INSUFFICIENT: Final = "INSUFICIENTE"
VERDICTS: Final = (VALIDATED, NOT_VALIDATED, INSUFFICIENT)


@dataclass(frozen=True, slots=True)
class Pred:
    """One out-of-sample prediction of one match: the means of each arm and what happened."""

    fixture_id: int
    competition_id: int
    kickoff_at: datetime
    block: int
    y_home: int
    y_away: int
    mu_home: float
    mu_away: float
    base_home: float
    base_away: float
    factor: float | None = None
    """The referee's multiplier when his designation was known in time and he had enough known matches."""


@dataclass
class BlockFit:
    """What the block knew: the dispersions and the calibrators, all from earlier predictions."""

    start: datetime
    n_prior: int
    model: Dispersion
    referee: Dispersion
    baseline: Dispersion
    calibrators: dict[str, cc.Params]

    @property
    def dispersed(self) -> bool:
        return self.n_prior >= cc.MIN_FIT

    @property
    def scored(self) -> bool:
        return self.dispersed and bool(self.calibrators) and all(c.n_matches >= cc.MIN_FIT for c in self.calibrators.values())


@dataclass
class Walk:
    measure: str
    preds: list[Pred]
    blocks: list[BlockFit]
    starts: list[datetime] = field(default_factory=list)
    """The instant each block was fitted at (its index is ``Pred.block``)."""
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    referee_checks: list[tuple[int, float]] = field(default_factory=list)
    """(known matches, multiplier) of every referee multiplier learned in a block (cards only)."""


def blocks_of(warmup: datetime, end: datetime, step_days: int = STEP_DAYS) -> list[datetime]:
    out, t = [], warmup
    while t < end:
        out.append(t)
        t = t + timedelta(days=step_days)
    return out


def _baseline(train: Sequence[Match], at: datetime, xi: float) -> tuple[float, float]:
    w = np.array([math.exp(-xi * max(0.0, (at - m.kickoff_at).total_seconds() / DAY)) for m in train])
    h = np.array([m.home for m in train], dtype=float)
    a = np.array([m.away for m in train], dtype=float)
    return float((w * h).sum() / w.sum()), float((w * a).sum() / w.sum())


def _referee_counts(train: Sequence[Match], fitted: Fitted) -> dict[int, int]:
    """How many known matches each referee had in the training of ``fitted`` (the same filter as ``fbi.families.referee.factors``)."""
    out: dict[int, int] = defaultdict(int)
    for m in train:
        if m.referee_id is not None and fitted.knows(m.home_id, m.away_id):
            out[m.referee_id] += 1
    return out


def predict(by_competition: Mapping[int, Sequence[Match]], *, measure: str, warmup: datetime, end: datetime,
            referee_known: Mapping[int, int] | None = None, xi: float = XI, penalty: float = PENALTY,
            step_days: int = STEP_DAYS) -> Walk:
    """Every match with a kick-off in ``[warmup, end)`` predicted by family-v1 fitted on what was known at the start of its block.

    ``referee_known`` (cards): fixture -> the referee designated ``REFEREE_LEAD`` or more before its kick-off. ``Match.referee_id`` of the
    training matches is the referee of a finished match (whenever he was observed): it only teaches the multipliers."""
    starts = blocks_of(warmup, end, step_days)
    preds: list[Pred] = []
    walk = Walk(measure, preds, [], starts)
    for competition, matches in sorted(by_competition.items()):
        ordered = sorted(matches, key=lambda m: (m.kickoff_at, m.fixture_id))
        teams = {m.home_id for m in ordered} | {m.away_id for m in ordered}
        if len(teams) > MAX_TEAMS:
            walk.skipped["too many sides"] += 1
            continue
        for b, t in enumerate(starts):
            block_end = min(t + timedelta(days=step_days), end)
            block = [m for m in ordered if t <= m.kickoff_at < block_end]
            if not block:
                continue
            train = [m for m in ordered if known_at(m) <= t]
            try:
                fitted = fit_family(train, measure=measure, at=t, xi=xi, penalty=penalty, dispersion=Dispersion(0.0, 0.0, 0.0))
            except NotEnoughHistoryError:
                walk.skipped["short history"] += 1
                continue
            base_h, base_a = _baseline(train, t, xi)
            multipliers: dict[int, float] = {}
            if referee_known is not None:
                multipliers = fref.factors(train, fitted, kappa=REFEREE_KAPPA)
                counts = _referee_counts(train, fitted)
                walk.referee_checks.extend((counts[r], f) for r, f in multipliers.items())
            for m in block:
                if not fitted.knows(m.home_id, m.away_id):
                    walk.skipped["team not known"] += 1
                    continue
                mu_h, mu_a = fitted.means(m.home_id, m.away_id)
                rid = None if referee_known is None else referee_known.get(m.fixture_id)
                factor = None if rid is None else multipliers.get(rid)
                preds.append(Pred(m.fixture_id, competition, m.kickoff_at, b, m.home, m.away, mu_h, mu_a, base_h, base_a, factor))
    preds.sort(key=lambda p: (p.kickoff_at, p.fixture_id))
    return walk


# ── the arms of a prediction ─────────────────────────────────────────────────────────────────────────────────────────

def _pmfs(mu_h: float, mu_a: float, d: Dispersion) -> dict[str, NDArray[np.float64]]:
    ph, pa = normalised(nb_pmf(mu_h, d.home)), normalised(nb_pmf(mu_a, d.away))
    pt = normalised(nb_pmf(mu_h + mu_a, d.total, 2 * MAX_COUNT))
    return {"home": ph, "away": pa, "total": pt}


def arm_pmfs(p: Pred, fit_: BlockFit, arm: str) -> dict[str, NDArray[np.float64]]:
    """The distributions of the total and of each side under ``arm``: ``raw`` (family-v1 as stated: with the referee when it had one),
    ``plain`` (without the referee), ``base`` (the league mean)."""
    if arm == "base":
        return _pmfs(p.base_home, p.base_away, fit_.baseline)
    if arm == "raw" and p.factor is not None:
        return _pmfs(p.mu_home * p.factor, p.mu_away * p.factor, fit_.referee)
    return _pmfs(p.mu_home, p.mu_away, fit_.model)


def _observed(p: Pred, scope: str) -> int:
    return p.y_home + p.y_away if scope == "total" else (p.y_home if scope == "home" else p.y_away)


def units(family: str) -> tuple[str, ...]:
    return ("total",) if family.endswith("_total") else ("home", "away")


def calibrate(walk: Walk, *, start: datetime) -> list[BlockFit]:
    """The dispersions and the calibrators of every block, each from the predictions of earlier blocks known at its start.

    A block is DISPERSED when ``MIN_FIT`` earlier predictions were known at its start: its probabilities can be stated, and they feed the
    calibrators of the blocks after it. It is SCORED when, besides, every calibrator of the measure was fitted on ``MIN_FIT`` matches
    of probabilities stated that way. ``walk.blocks[i]`` is the block that starts at ``walk.starts[i]``."""
    by_block: dict[int, list[Pred]] = defaultdict(list)
    for p in walk.preds:
        by_block[p.block].append(p)
    stated: dict[int, dict[str, tuple[NDArray[np.float64], NDArray[np.float64], list[Pred]]]] = {}
    # block -> family -> (P(over) of the ladder as stated, the outcomes, the prediction of each row): one row per unit
    families = [f for f in cc.FAMILIES if cc.MEASURE_OF[f] == walk.measure]
    fits: list[BlockFit] = []
    for b, t in enumerate(walk.starts):
        prior = [p for bb in range(b) for p in by_block.get(bb, ()) if known_at_pred(p) <= t and p.kickoff_at >= t - CAL_WINDOW]
        n = len(prior)
        zero = Dispersion(0.0, 0.0, 0.0)
        model = referee = baseline = zero
        if n >= cc.MIN_FIT:
            yh, ya = np.array([p.y_home for p in prior], float), np.array([p.y_away for p in prior], float)
            model = _dispersion(yh, ya, np.array([p.mu_home for p in prior]), np.array([p.mu_away for p in prior]))
            with_ref = [p for p in prior if p.factor is not None]
            referee = (_dispersion(np.array([p.y_home for p in with_ref], float), np.array([p.y_away for p in with_ref], float),
                                   np.array([p.mu_home * (p.factor or 1.0) for p in with_ref]),
                                   np.array([p.mu_away * (p.factor or 1.0) for p in with_ref]))
                       if len(with_ref) >= cc.MIN_FIT else model)
            baseline = _dispersion(yh, ya, np.array([p.base_home for p in prior]), np.array([p.base_away for p in prior]))
        prior_ids = {id(p) for p in prior}
        cals: dict[str, cc.Params] = {}
        for fam in families:
            ps, ys = [], []
            matches: set[int] = set()
            for bb in range(b):
                if bb not in stated:
                    continue
                pp, yy, members = stated[bb][fam]
                keep = np.array([id(m) in prior_ids for m in members], dtype=bool)
                ps.append(pp[keep])
                ys.append(yy[keep])
                matches.update(id(m) for m, k in zip(members, keep, strict=True) if k)
            p_all = np.concatenate(ps) if ps else np.zeros(0)
            y_all = np.concatenate(ys) if ys else np.zeros(0)
            cals[fam] = cc.fit(p_all, y_all, n_matches=len(matches))
        fit_ = BlockFit(t, n, model, referee, baseline, cals)
        fits.append(fit_)
        if fit_.dispersed and by_block.get(b):
            stated[b] = {fam: _stated(by_block[b], fit_, fam) for fam in families}
    walk.blocks = fits
    return fits


def known_at_pred(p: Pred) -> datetime:
    return known_at(Match(p.fixture_id, p.kickoff_at, 0, 0, p.y_home, p.y_away))


def _dispersion(yh: NDArray[np.float64], ya: NDArray[np.float64], mh: NDArray[np.float64], ma: NDArray[np.float64]) -> Dispersion:
    return Dispersion(fit_dispersion(yh, mh), fit_dispersion(ya, ma), fit_dispersion(yh + ya, mh + ma))


def _stated(block: Sequence[Pred], fit_: BlockFit, family: str) -> tuple[NDArray[np.float64], NDArray[np.float64], list[Pred]]:
    """The ladder probabilities family-v1 stated for the units of ``family`` in a block, the outcomes, and the predictions behind them."""
    lines = cc.LADDERS[family]
    ps, ys, members = [], [], []
    for p in block:
        pm = arm_pmfs(p, fit_, "raw")
        for scope in units(family):
            ps.append(cc.ladder(pm[scope], lines))
            k = _observed(p, scope)
            ys.append(np.array([1.0 if k > ln else 0.0 for ln in lines]))
            members.append(p)
    width = len(lines)
    return (np.asarray(np.array(ps).reshape(-1, width), dtype=np.float64),
            np.asarray(np.array(ys).reshape(-1, width), dtype=np.float64), members)


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def bogota_day(t: datetime) -> date:
    return (t.astimezone(UTC) + BOGOTA).date()


def daily_ci(diffs: Sequence[float], days: Sequence[date], *, seed: int, resamples: int = BOOTSTRAP) -> dict[str, Any]:
    """The mean of the daily means of ``diffs`` and its 95 % interval by bootstrap of days."""
    by_day: dict[date, list[float]] = defaultdict(list)
    for d, x in zip(days, diffs, strict=True):
        by_day[d].append(x)
    if not by_day:
        return {"n": 0, "days": 0}
    daily = np.array([float(np.mean(v)) for _, v in sorted(by_day.items())])
    rng = np.random.default_rng(seed)
    boots = daily[rng.integers(0, daily.size, size=(resamples, daily.size))].mean(axis=1)
    sd = float(daily.std(ddof=1)) if daily.size > 1 else float("nan")
    return {"n": len(diffs), "days": int(daily.size), "mean": float(daily.mean()), "low": float(np.quantile(boots, 0.025)),
            "high": float(np.quantile(boots, 0.975)), "sd_daily": sd,
            "mde": float(2.8016 * sd / math.sqrt(daily.size)) if daily.size > 1 else None}


@dataclass(frozen=True, slots=True)
class MarketPrice:
    """The books' probability of «over» at one line of one market of one match, margin removed, and how many books it is the mean of."""

    fixture_id: int
    market_key: str
    line: float
    p_over: float
    books: int


def score(walk: Walk, family: str, *, start: datetime, seed: int, market: Sequence[MarketPrice] = (),
          yellow: Mapping[int, tuple[int, int]] | None = None) -> dict[str, Any]:
    """The numbers of the protocol for one family over the scored blocks starting at ``start`` or later, and its verdict."""
    lines = cc.LADDERS[family]
    fits = walk.blocks
    starts = walk.starts
    scored_blocks = {i for i, f in enumerate(fits) if f.scored and starts[i] >= start}
    rows = [p for p in walk.preds if p.block in scored_blocks and p.kickoff_at >= start]
    days, d_raw, d_base, d_plain, ll = [], [], [], [], defaultdict(list)
    per_line: dict[str, dict[float, tuple[list[float], list[float]]]] = {
        arm: {ln: ([], []) for ln in lines} for arm in ("raw", "cal", "base")}
    rps_sum: dict[str, float] = defaultdict(float)
    params = []
    for b in sorted(scored_blocks):
        pr = fits[b].calibrators[family]
        params.append({"block_start": starts[b].date().isoformat(), "a": pr.a, "b": pr.b, "n_matches": pr.n_matches})
    by_fixture: dict[int, Pred] = {}
    for p in rows:
        f = fits[p.block]
        cal = f.calibrators[family]
        arms = {"raw": arm_pmfs(p, f, "raw"), "base": arm_pmfs(p, f, "base"), "plain": arm_pmfs(p, f, "plain")}
        by_fixture[p.fixture_id] = p
        for scope in units(family):
            k = _observed(p, scope)
            y = np.array([1.0 if k > ln else 0.0 for ln in lines])
            raw = cc.ladder(arms["raw"][scope], lines)
            cal_p = cc.transform(raw, cal)
            base = cc.ladder(arms["base"][scope], lines)
            plain = cc.ladder(arms["plain"][scope], lines)
            l_raw, l_cal, l_base, l_plain = (float(cc.log_loss(x, y).mean()) for x in (raw, cal_p, base, plain))
            days.append(bogota_day(p.kickoff_at))
            d_raw.append(l_cal - l_raw)
            d_base.append(l_cal - l_base)
            d_plain.append(l_raw - l_plain)
            for arm, v in (("raw", l_raw), ("cal", l_cal), ("base", l_base), ("plain", l_plain)):
                ll[arm].append(v)
            for arm, probs in (("raw", raw), ("cal", cal_p), ("base", base)):
                for i, ln in enumerate(lines):
                    per_line[arm][ln][0].append(float(probs[i]))
                    per_line[arm][ln][1].append(float(y[i]))
            rps_sum["raw"] += cc.rps(arms["raw"][scope], k)
            rps_sum["cal"] += cc.rps(cc.calibrated_pmf(arms["raw"][scope], cal), k)
            rps_sum["base"] += cc.rps(arms["base"][scope], k)
    n_units = len(days)
    matches = len({p.fixture_id for p in rows})
    out: dict[str, Any] = {"family": family, "measure": walk.measure, "lines": list(lines), "matches": matches, "units": n_units,
                           "days": len(set(days)), "blocks_scored": len(scored_blocks),
                           "blocks_not_scored": sum(1 for i, f in enumerate(fits) if starts[i] >= start and not f.scored),
                           "calibrators": params}
    if n_units == 0:
        out["verdict"], out["reasons"] = INSUFFICIENT, ["sin partidos puntuados"]
        return out
    out["log_loss"] = {arm: float(np.mean(v)) for arm, v in ll.items()}
    out["cal_minus_raw"] = daily_ci(d_raw, days, seed=seed)
    out["cal_minus_base"] = daily_ci(d_base, days, seed=seed + 1)
    out["rps"] = {arm: v / n_units for arm, v in rps_sum.items()}
    out["ece"] = {arm: {str(ln): {"n": len(v[0]), "ece": cc.ece(np.array(v[0]), np.array(v[1])),
                                  "said": float(np.mean(v[0])), "happened": float(np.mean(v[1]))}
                        for ln, v in per_line[arm].items()} for arm in per_line}
    if walk.measure == "cards_lines_ft":
        covered = [p.factor is not None for p in rows]
        out["referee"] = {"coverage": float(np.mean(covered)) if covered else 0.0,
                          "raw_minus_plain": daily_ci(d_plain, days, seed=seed + 2),
                          **referee_check(walk.referee_checks)}
    out["market"] = versus_market(rows, fits, family, market, start=start, seed=seed + 3)
    if yellow is not None and family == "cards_total":
        out["convention"] = convention_gap(rows, market, yellow)
    out["verdict"], out["reasons"] = verdict(out)
    return out


def referee_check(checks: Sequence[tuple[int, float]]) -> dict[str, Any]:
    """The protocol's referee test: with ``FEW_REFEREE_MATCHES`` known matches or fewer, |multiplier - 1| <= ``REFEREE_BAND``."""
    few = [abs(f - 1.0) for n, f in checks if n <= FEW_REFEREE_MATCHES]
    return {"multipliers": len(checks), "few_matches": len(few), "few_max_deviation": max(few) if few else None,
            "few_within_band": (sum(1 for x in few if x <= REFEREE_BAND) / len(few)) if few else None,
            "all_max_deviation": max((abs(f - 1.0) for _, f in checks), default=None)}


def versus_market(rows: Sequence[Pred], fits: Sequence[BlockFit], family: str, market: Sequence[MarketPrice], *, start: datetime,
                  seed: int) -> dict[str, Any]:
    """The calibrated probability against the books' (3 books or more, half lines), at the market's own lines."""
    by_fixture = {p.fixture_id: p for p in rows}
    diffs, days, n_books = [], [], []
    ll_cal, ll_mkt, ll_raw = [], [], []
    for mp in market:
        fam_scope = cc.FAMILY_OF_KEY.get(mp.market_key)
        if fam_scope is None or fam_scope[0] != family or mp.books < 3 or not float(mp.line - 0.5).is_integer():
            continue
        p = by_fixture.get(mp.fixture_id)
        if p is None:
            continue
        scope = fam_scope[1]
        f = fits[p.block]
        pm = arm_pmfs(p, f, "raw")[scope]
        if mp.line + 0.5 >= pm.size:
            continue
        raw = cc.over(pm, mp.line)
        cal = float(cc.transform(np.array([raw]), f.calibrators[family])[0])
        y = 1.0 if _observed(p, scope) > mp.line else 0.0
        lc = float(cc.log_loss(np.array([cal]), np.array([y]))[0])
        lm = float(cc.log_loss(np.array([mp.p_over]), np.array([y]))[0])
        lr = float(cc.log_loss(np.array([raw]), np.array([y]))[0])
        diffs.append(lc - lm)
        days.append(bogota_day(p.kickoff_at))
        n_books.append(mp.books)
        ll_cal.append(lc)
        ll_mkt.append(lm)
        ll_raw.append(lr)
    out: dict[str, Any] = {"rows": len(diffs), "matches": len({mp.fixture_id for mp in market if mp.fixture_id in by_fixture
                                                                and cc.FAMILY_OF_KEY.get(mp.market_key, ("",))[0] == family})}
    if not diffs:
        return out
    out.update({"log_loss_cal": float(np.mean(ll_cal)), "log_loss_market": float(np.mean(ll_mkt)),
                "log_loss_raw": float(np.mean(ll_raw)), "mean_books": float(np.mean(n_books)),
                "cal_minus_market": daily_ci(diffs, days, seed=seed),
                "interpretable": len(diffs) >= MIN_MARKET})
    return out


def convention_gap(rows: Sequence[Pred], market: Sequence[MarketPrice], yellow: Mapping[int, tuple[int, int]]) -> dict[str, Any]:
    """How often the two card conventions (every card one, yellow cards only) settle a priced «over L» of the total differently."""
    by_fixture = {p.fixture_id: p for p in rows}
    seen, differ = 0, 0
    for mp in market:
        if mp.market_key != "CARDS_OU" or mp.books < 3 or mp.fixture_id not in by_fixture or mp.fixture_id not in yellow:
            continue
        p = by_fixture[mp.fixture_id]
        lines_total = p.y_home + p.y_away
        yel = sum(yellow[mp.fixture_id])
        seen += 1
        differ += int((lines_total > mp.line) != (yel > mp.line))
    return {"priced_lines": seen, "settle_differently": differ, "share": differ / seen if seen else None}


def verdict(s: Mapping[str, Any]) -> tuple[str, list[str]]:
    """VALIDADO / NO VALIDADO / INSUFICIENTE as the protocol AD-B07 says, with the reasons in the owner's words."""
    reasons: list[str] = []
    if s["matches"] < MIN_MATCHES or s["days"] < MIN_DAYS:
        return INSUFFICIENT, [f"{s['matches']} partidos en {s['days']} días (mínimo {MIN_MATCHES} en {MIN_DAYS})"]
    high = s["cal_minus_raw"]["high"]
    if high > NON_INFERIORITY:
        reasons.append(f"el calibrador empeora a family-v1: límite superior {high:+.4f} > {NON_INFERIORITY}")
    bad = [f"{ln} (ECE {v['ece']:.3f})" for ln, v in s["ece"]["cal"].items() if v["n"] >= ECE_MIN_N and v["ece"] > MAX_ECE]
    if bad:
        reasons.append("líneas con ECE > 0,03: " + ", ".join(bad))
    base_high = s["cal_minus_base"]["high"]
    if base_high >= 0.0:
        reasons.append(f"no supera a la media de la liga: límite superior {base_high:+.4f} ≥ 0")
    return (NOT_VALIDATED, reasons) if reasons else (VALIDATED, ["cumple las tres condiciones del protocolo"])


FIT_BLOCKS: Final = 14
"""How many blocks of ``STEP_DAYS`` before the moment a current fit walks: 13 to state probabilities out of sample (the calibrator's
year, ``CAL_WINDOW``) and the block that starts at the moment, whose calibrator is the fit."""


def fit_current(by_competition: Mapping[int, Sequence[Match]], *, measure: str, at: datetime,
                referee_known: Mapping[int, int] | None = None) -> tuple[dict[str, cc.Params], int]:
    """The calibrators of the measure's families as they would be fitted at ``at``: the same walk as the LAB, ending with a block that
    starts at ``at`` (its calibrators are fitted on the out-of-sample predictions known by then). Returns them and the number of
    out-of-sample predictions behind them."""
    warmup = at - timedelta(days=STEP_DAYS * FIT_BLOCKS)
    walk = predict(by_competition, measure=measure, warmup=warmup, end=at + timedelta(seconds=1), referee_known=referee_known)
    if walk.starts[-1] != at:
        raise RuntimeError("the last block of a current fit must start at the moment of the fit")
    calibrate(walk, start=at)
    last = walk.blocks[-1]
    return dict(last.calibrators), last.n_prior


def run(by_competition: Mapping[int, Sequence[Match]], *, measure: str, warmup: datetime, start: datetime, end: datetime, seed: int,
        referee_known: Mapping[int, int] | None = None, market: Sequence[MarketPrice] = (),
        yellow: Mapping[int, tuple[int, int]] | None = None) -> dict[str, Any]:
    """The whole LAB of one measure: predict, calibrate block by block, score each family of the measure."""
    walk = predict(by_competition, measure=measure, warmup=warmup, end=end, referee_known=referee_known)
    calibrate(walk, start=start)
    families = [f for f in cc.FAMILIES if cc.MEASURE_OF[f] == measure]
    return {"measure": measure, "predictions": len(walk.preds), "skipped": dict(walk.skipped),
            "families": {f: score(walk, f, start=start, seed=seed, market=market, yellow=yellow) for f in families}}
