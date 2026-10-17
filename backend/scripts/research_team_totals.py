"""REVIEW P5 (B3), research: team totals - the provider's bets 16 ("Total - Home") and 17 ("Total - Away").

    python -m scripts.research_team_totals [--days 30] [--refit-days 7] [--families dixon_coles,poisson]

Would the goal models find value in one team's own goals, and would that value be real? Read-only: nothing is
normalised, nothing activated. It is step 3 of the market-expansion plan (docs/owner/P5_SELECCION_RIESGO_CONTEXTO.md):
the backtest against the market before any shadow period.

PRICES. The RAW /odds payloads behind each match's stored pre-match prices (``market.odds_snapshots.payload_hash``;
the same /odds answer carries every bet type): EARLY, the last one at least ``--early-hours`` before kick-off (when a
pick is chosen), and CLOSE, the last one before kick-off. Half lines only (no push). Each book's Over/Under pair is de-vigged with Shin (production's method,
``fbi.domain.market_probability.devig``) and the consensus is the mean over the books - production's consensus.
MODEL. Each family with production's hyper-parameters (``fbi.predictions.forecast.current_spec``), refitted
walk-forward per competition every ``--refit-days`` on the 730 days before the cut-off (an hour before the block's
first kick-off), as ``fbi.backtesting.walkforward.run_goal_model``; a competition with more teams than production
forecasts (``MAX_GOAL_TEAMS``, club friendlies) is left out, as production leaves it out. P(team goals > line) is read off the fitted score matrix; the
prudent end is the 5 % quantile over the Laplace parameter draws (the 90 % interval production uses).
OUTCOME. The 90-minute score.
REPORT. (1) Accuracy on every priced selection, Over side: log loss and Brier of the model against the close
consensus, paired, with a 95 % bootstrap over matches; calibration by band. (2) Production's gate at the EARLY
price - EV > 0 at the best price, two books or more, the best price at most 25 % above fair, prudent growth of a
1 % stake > 0, odds <= 3.00 (risk-v1) - its return (bootstrap over matches), hit rate and closing-line value
(early price x close consensus - 1); one per match (the best prudent growth) as the daily set would; and the same
choice made with the market's own early probability, as the placebo the model has to beat.
"""

from __future__ import annotations

import argparse
import gc
import gzip
import json
import math
import random
import re
import statistics
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

BETS = {16: "home", 17: "away"}
VALUE = re.compile(r"^\s*(Over|Under)\s+(\d+(?:\.\d+)?)\s*$", re.I)
MAX_ODDS = 3.00  # risk-v1
MAX_PRICE_EDGE = 0.25  # the gate's outlier guard
MIN_BOOKS = 2
STAKE = 0.01
QUANTILE = 0.05  # the prudent end of a 90 % interval


# ── pure pieces (unit-tested) ────────────────────────────────────────────────────────────────────────────────────


def parse_value(text: str) -> tuple[str, float] | None:
    """'Over 1.5' -> ('Over', 1.5); only half lines (a whole line can push)."""
    m = VALUE.match(text or "")
    if not m:
        return None
    line = float(m.group(2))
    if abs(line - math.floor(line) - 0.5) > 1e-9:
        return None
    return m.group(1).capitalize(), line


def p_team_over(matrix: NDArray[np.float64], side: str, line: float) -> float:
    """P(the team scores more than ``line``) off a (home goals x away goals) score matrix."""
    m = matrix / matrix.sum()
    k = math.floor(line) + 1
    return float(m[k:, :].sum() if side == "home" else m[:, k:].sum())


def tails(mats: NDArray[np.float64], side: str, line: float) -> NDArray[np.float64]:
    """P(the team scores more than ``line``) for each of a stack of normalised score matrices (n x goals x goals)."""
    k = math.floor(line) + 1
    return np.asarray(mats[:, k:, :].sum(axis=(1, 2)) if side == "home" else mats[:, :, k:].sum(axis=(1, 2)))


def p_team_over_draws(lh: NDArray[np.float64], la: NDArray[np.float64], rho: NDArray[np.float64] | None,
                      side: str, line: float) -> NDArray[np.float64]:
    from fbi.models.scoring import matrices_batch

    return tails(matrices_batch(lh, la, rho), side, line)


def shin_pair(over: float, under: float) -> float | None:
    """A book's de-vigged P(Over), or None when the pair has no margin (not a real two-way price)."""
    from fbi.core.errors import InvalidDistributionError, InvalidOddsError
    from fbi.domain.market_probability import DevigMethod, devig
    from fbi.domain.odds import DecimalOdds

    try:
        fair = devig({"Over": DecimalOdds.parse(over), "Under": DecimalOdds.parse(under)}, DevigMethod.SHIN)
    except (InvalidOddsError, InvalidDistributionError, ValueError):
        return None
    return float(fair["Over"])


def growth(p_win: float, odds: float, f: float = STAKE) -> float:
    """Expected log growth of a fraction ``f`` staked at ``odds`` with win probability ``p_win`` (no push)."""
    return p_win * math.log(1 + f * (odds - 1)) + (1 - p_win) * math.log(1 - f)


def roi_ci(profits_by_match: dict[int, list[float]], rng: random.Random, b: int = 400) -> tuple[float, float, float]:
    groups = [g for g in profits_by_match.values() if g]
    n = sum(len(g) for g in groups)
    if not n:
        return float("nan"), float("nan"), float("nan")
    point = sum(sum(g) for g in groups) / n
    stats = []
    for _ in range(b):
        pick = [groups[rng.randrange(len(groups))] for _ in range(len(groups))]
        stats.append(sum(sum(g) for g in pick) / sum(len(g) for g in pick))
    stats.sort()
    return point, stats[int(0.025 * b)], stats[int(0.975 * b) - 1]


def paired_ci(diffs_by_match: dict[int, list[float]], rng: random.Random, b: int = 400) -> tuple[float, float, float]:
    """Mean per selection of a paired difference, 95 % bootstrap over matches."""
    return roi_ci(diffs_by_match, rng, b)


# ── data ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Snapshot:
    """One side-line of one match at one moment: each book's (over, under) and the consensus."""

    books: dict[int, tuple[float, float]] = field(default_factory=dict)

    def fair_over(self) -> float | None:
        ps = [p for o, u in self.books.values() if (p := shin_pair(o, u)) is not None]
        return statistics.fmean(ps) if len(ps) >= MIN_BOOKS else None

    def best(self, sel: str) -> float | None:
        prices = [o if sel == "Over" else u for o, u in self.books.values()]
        return max(prices) if prices else None


@dataclass
class Quote:
    fixture_id: int
    side: str
    line: float
    early: Snapshot
    close: Snapshot


PAYLOADS_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at,
       (SELECT s.payload_hash FROM market.odds_snapshots s
         WHERE s.fixture_id = f.id AND s.market_key = '1X2' AND s.selection = 'Home' AND s.source = 'prematch'
           AND s.captured_at < f.kickoff_at ORDER BY s.captured_at DESC LIMIT 1) AS close_hash,
       (SELECT s.payload_hash FROM market.odds_snapshots s
         WHERE s.fixture_id = f.id AND s.market_key = '1X2' AND s.selection = 'Home' AND s.source = 'prematch'
           AND s.captured_at <= f.kickoff_at - %(early)s ORDER BY s.captured_at DESC LIMIT 1) AS early_hash
  FROM core.fixtures f
 WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < now() AND f.status_group = 'finished'
   AND f.provider_fixture_id IS NOT NULL
"""


def team_totals(item: dict[str, Any]) -> dict[tuple[str, float, int], tuple[float, float]]:
    """(side, line, book) -> (over, under) from one fixture's entry of an /odds response."""
    out: dict[tuple[str, float, int], tuple[float, float]] = {}
    for bm in item.get("bookmakers") or []:
        book = bm.get("id")
        for bet in bm.get("bets") or []:
            side = BETS.get(int(bet.get("id") or 0))
            if side is None or book is None:
                continue
            pairs: dict[float, dict[str, float]] = defaultdict(dict)
            for v in bet.get("values") or []:
                parsed = parse_value(str(v.get("value")))
                try:
                    odd = float(v.get("odd"))
                except (TypeError, ValueError):
                    continue
                if parsed and odd > 1.0:
                    pairs[parsed[1]][parsed[0]] = odd
            for line, pr in pairs.items():
                if "Over" in pr and "Under" in pr:
                    out[(side, line, int(book))] = (pr["Over"], pr["Under"])
    return out


def load_quotes(conn: Any, root: Path, *, since: datetime, early: timedelta) -> tuple[list[Quote], dict[str, int]]:
    """Team-total quotes of every finished match kicked off since ``since``. The payloads read are the ones behind
    each match's last stored pre-match price before kick-off (CLOSE) and at least ``early`` before it (EARLY):
    ``market.odds_snapshots.payload_hash`` names them, and the same /odds answer carries every bet type."""
    stats: dict[str, int] = defaultdict(int)
    rows = conn.execute(PAYLOADS_SQL, {"since": since, "early": early}).fetchall()
    stats["finished_matches"] = len(rows)
    wanted: dict[str, list[tuple[int, int, datetime, str]]] = defaultdict(list)  # hash -> (fixture, pid, ko, which)
    for fid, pid, ko, close_hash, early_hash in rows:
        if close_hash:
            wanted[close_hash].append((int(fid), int(pid), ko, "close"))
        if early_hash:
            wanted[early_hash].append((int(fid), int(pid), ko, "early"))
    files = {h: (fp, at) for h, fp, at in conn.execute(
        "SELECT hash, file_path, fetched_at FROM raw.ingestion_payloads WHERE hash = ANY(%s)",
        (list(wanted),)).fetchall()}
    stats["payloads"] = len(wanted)
    out: dict[tuple[int, str, float], Quote] = {}
    for n, (h, uses) in enumerate(wanted.items(), 1):
        if n % 500 == 0:
            print(f"  read {n}/{len(wanted)} payloads", flush=True)
        if h not in files:
            stats["payload_row_missing"] += 1
            continue
        file_path, fetched_at = files[h]
        try:
            with gzip.open(root / file_path, "rt", encoding="utf-8") as fh:
                env = json.load(fh)
        except (OSError, ValueError):
            stats["files_missing"] += 1
            continue
        stats["files_read"] += 1
        body = env.get("body") or env.get("response") or env
        items = {int((it.get("fixture") or {}).get("id") or 0): it
                 for it in (body.get("response", []) if isinstance(body, dict) else [])}
        for fid, pid, ko, which in uses:
            if fetched_at >= ko or pid not in items:
                stats["not_in_payload"] += 1
                continue
            for (side, line, book), pair in team_totals(items[pid]).items():
                q = out.setdefault((fid, side, line), Quote(fid, side, line, Snapshot(), Snapshot()))
                (q.close if which == "close" else q.early).books[book] = pair
    stats["selections"] = len(out)
    stats["matches"] = len({k[0] for k in out})
    return list(out.values()), stats


def production_hyper(conn: Any, family: str) -> dict[str, Any] | None:
    """The hyper-parameters production forecasts with (``fbi.predictions.forecast.current_spec``: the latest completed
    backtest session's choice on its validation season), else the newest stored version's."""
    from fbi.predictions.forecast import current_spec

    spec = current_spec(conn)
    if spec is not None and family in spec.goal:
        g = spec.goal[family]
        return {"xi": g.xi, "penalty": g.penalty, "history_days": spec.cfg.history_days, "source": "current_spec"}
    row = conn.execute(
        "SELECT v.hyperparameters FROM models.model_versions v JOIN models.model_registry r ON r.id = v.model_id "
        "WHERE r.name = %s AND v.hyperparameters ? 'xi' ORDER BY v.created_at DESC, v.id DESC LIMIT 1",
        (family,)).fetchone()
    return None if row is None else dict(row[0]) | {"source": "newest_version"}


# ── the walk-forward ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Pred:
    p: float
    p_low_over: float | None
    p_low_under: float | None


def walk_forward(matches: Sequence[Any], targets: Iterable[int], *, family: str, hyper: dict[str, Any],
                 refit_days: int, lines: dict[int, set[tuple[str, float]]]) -> tuple[dict[tuple[int, str, float], Pred],
                                                                                    dict[str, int]]:
    from fbi.backtesting.walkforward import MIN_GOAL_TRAIN, blocks, known_before
    from fbi.models.goals import GoalObs, InvalidCorrectionError, fit_goal_model
    from fbi.models.scoring import matrices_batch
    from fbi.predictions.forecast import MAX_GOAL_TEAMS

    xi, penalty, history = float(hyper["xi"]), float(hyper["penalty"]), int(hyper.get("history_days", 730))
    by_comp: dict[int, list[Any]] = defaultdict(list)
    by_id = {}
    for m in matches:
        by_comp[m.competition_id].append(m)
        by_id[m.fixture_id] = m
    comp_targets: dict[int, list[Any]] = defaultdict(list)
    for fid in targets:
        if fid in by_id:
            comp_targets[by_id[fid].competition_id].append(by_id[fid])
    out: dict[tuple[int, str, float], Pred] = {}
    note: dict[str, int] = defaultdict(int)
    for comp, ts in sorted(comp_targets.items()):
        for cutoff, group in blocks(ts, refit_days, timedelta(minutes=60)):
            horizon = cutoff - timedelta(days=history)
            train = [m for m in by_comp[comp] if known_before(m, cutoff) and m.kickoff_at >= horizon]
            if len(train) < MIN_GOAL_TRAIN:
                note["few_training_matches"] += len(group)
                continue
            n_teams = len({m.home_team_id for m in train} | {m.away_team_id for m in train})
            if n_teams > MAX_GOAL_TEAMS:
                # Production does not forecast these either (club friendlies: thousands of sides, a few matches
                # each), and the fit's covariance alone is gigabytes: the first run was killed for memory (11 Oct).
                note["too_many_teams"] += len(group)
                continue
            obs = [GoalObs(m.home_team_id, m.away_team_id, m.settle_home or 0, m.settle_away or 0,
                           weight=math.exp(-xi * (cutoff - m.kickoff_at).total_seconds() / 86400),
                           neutral=m.is_neutral) for m in train]
            note["fits"] += 1
            try:
                model = fit_goal_model(obs, kind=family, xi=xi, penalty=penalty, with_covariance=True)
            except (ValueError, np.linalg.LinAlgError):
                note["failed_fits"] += 1
                continue
            if not model.converged:
                note["failed_fits"] += 1
                continue
            for m in group:
                if not (model.knows(m.home_team_id) and model.knows(m.away_team_id)):
                    note["unknown_team"] += 1
                    continue
                try:
                    matrix, _, _ = model.score_matrix(m.home_team_id, m.away_team_id, neutral=m.is_neutral)
                except InvalidCorrectionError:
                    note["dc_invalid"] += 1
                    continue
                draws = model.lambda_draws(m.home_team_id, m.away_team_id, neutral=m.is_neutral)
                mats = None if draws is None else matrices_batch(draws[0], draws[1], draws[2])
                for side, line in lines.get(m.fixture_id, ()):
                    p = p_team_over(matrix, side, line)
                    lo_over = lo_under = None
                    if mats is not None:
                        d = tails(mats, side, line)
                        lo_over, lo_under = float(np.quantile(d, QUANTILE)), float(np.quantile(1 - d, QUANTILE))
                    out[(m.fixture_id, side, line)] = Pred(p, lo_over, lo_under)
                note["predicted_matches"] += 1
            del model, obs
            gc.collect()
    return out, note


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────


def logloss(p: float, y: int) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def report(label: str, quotes: Sequence[Quote], preds: dict[tuple[int, str, float], Pred],
           goals: dict[int, tuple[int, int]], rng: random.Random) -> None:
    print(f"\n== {label}")
    ll: dict[int, list[float]] = defaultdict(list)
    br: dict[int, list[float]] = defaultdict(list)
    bands: dict[int, list[tuple[float, int]]] = defaultdict(list)
    n = 0
    for q in quotes:
        pr = preds.get((q.fixture_id, q.side, q.line))
        fair = q.close.fair_over()
        if pr is None or fair is None or q.fixture_id not in goals:
            continue
        h, a = goals[q.fixture_id]
        y = int((h if q.side == "home" else a) > q.line)
        ll[q.fixture_id].append(logloss(pr.p, y) - logloss(fair, y))
        br[q.fixture_id].append((pr.p - y) ** 2 - (fair - y) ** 2)
        bands[min(9, int(pr.p * 10))].append((pr.p, y))
        n += 1
    if not n:
        print("  nothing to compare")
        return
    d_ll, lo_ll, hi_ll = paired_ci(ll, rng)
    d_br, lo_br, hi_br = paired_ci(br, rng)
    print(f"  accuracy, Over side, model - close consensus (negative = the model is better): n={n} "
          f"matches={len(ll)}")
    print(f"    log loss {d_ll:+.4f} [{lo_ll:+.4f}, {hi_ll:+.4f}]   Brier {d_br:+.4f} [{lo_br:+.4f}, {hi_br:+.4f}]")
    print("  calibration (model p band: n, mean p, observed)")
    for k in sorted(bands):
        xs = bands[k]
        print(f"    {k / 10:.1f}-{(k + 1) / 10:.1f}: {len(xs):5d}  {statistics.fmean(p for p, _ in xs):5.1%}  "
              f"{statistics.fmean(y for _, y in xs):5.1%}")

    def choose(prob: str) -> list[tuple[float, int, float, float, float]]:
        """(growth, fixture, odds, profit, clv) for every selection through the gate at the EARLY price."""
        chosen = []
        for q in quotes:
            pr = preds.get((q.fixture_id, q.side, q.line))
            fe, fc = q.early.fair_over(), q.close.fair_over()
            if pr is None or fe is None or fc is None or q.fixture_id not in goals:
                continue
            h, a = goals[q.fixture_id]
            scored = h if q.side == "home" else a
            for sel in ("Over", "Under"):
                odds = q.early.best(sel)
                if odds is None or len(q.early.books) < MIN_BOOKS:
                    continue
                p_fair_e = fe if sel == "Over" else 1 - fe
                p_fair_c = fc if sel == "Over" else 1 - fc
                if prob == "model":
                    p = pr.p if sel == "Over" else 1 - pr.p
                    p_low = pr.p_low_over if sel == "Over" else pr.p_low_under
                else:  # placebo: the market's own early probability
                    p, p_low = p_fair_e, p_fair_e
                if p_low is None:
                    continue
                g = growth(p_low, odds)
                if p * odds - 1 <= 0 or odds * p_fair_e - 1 > MAX_PRICE_EDGE or g <= 0 or odds > MAX_ODDS:
                    continue
                won = scored > q.line if sel == "Over" else scored < q.line
                chosen.append((g, q.fixture_id, odds, odds - 1 if won else -1.0, odds * p_fair_c - 1))
        return chosen

    for prob in ("model", "placebo"):
        chosen = choose(prob)
        for scope in ("every selection", "one per match"):
            rows = chosen
            if scope == "one per match":
                best: dict[int, tuple[float, int, float, float, float]] = {}
                for r in chosen:
                    if r[1] not in best or r[0] > best[r[1]][0]:
                        best[r[1]] = r
                rows = list(best.values())
            if not rows:
                print(f"  {prob:7} {scope:15} n=0")
                continue
            by_match: dict[int, list[float]] = defaultdict(list)
            clv: dict[int, list[float]] = defaultdict(list)
            for _, fid, _, profit, c in rows:
                by_match[fid].append(profit)
                clv[fid].append(c)
            roi, lo, hi = roi_ci(by_match, rng)
            c, clo, chi = roi_ci(clv, rng)
            hit = sum(1 for r in rows if r[3] > 0) / len(rows)
            print(f"  {prob:7} {scope:15} n={len(rows):5d} matches={len(by_match):4d} odds={statistics.fmean(r[2] for r in rows):4.2f} "
                  f"hit={hit:5.1%} ROI={roi:+6.1%} [{lo:+6.1%},{hi:+6.1%}] CLV={c:+5.1%} [{clo:+5.1%},{chi:+5.1%}]")


def main() -> int:
    import psycopg

    from fbi.core.config import settings
    from fbi.features.data import load_matches

    parser = argparse.ArgumentParser(prog="research_team_totals", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="matches kicked off in the last N days")
    parser.add_argument("--refit-days", type=int, default=7)
    parser.add_argument("--early-hours", type=float, default=3.0)
    parser.add_argument("--families", default="dixon_coles,poisson")
    args = parser.parse_args()
    rng = random.Random(7)
    t0 = time.monotonic()
    since = datetime.now(UTC) - timedelta(days=args.days)
    with psycopg.connect(settings.database.psycopg_url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        conn.read_only = True
        quotes, stats = load_quotes(conn, Path(settings.runtime.raw_store_dir), since=since,
                                    early=timedelta(hours=args.early_hours))
        print(f"RAW: {dict(stats)} ({time.monotonic() - t0:.0f}s)", flush=True)
        comps = [int(r[0]) for r in conn.execute(
            "SELECT DISTINCT cs.competition_id FROM core.fixtures f JOIN core.competition_seasons cs "
            "ON cs.id = f.competition_season_id WHERE f.id = ANY(%s)", ([q.fixture_id for q in quotes],)).fetchall()]
        matches = load_matches(conn, competition_ids=comps)  # their whole history, not every stored fixture
        print(f"competitions: {len(comps)}; their matches loaded: {len(matches)}", flush=True)
        goals = {m.fixture_id: (m.settle_home, m.settle_away) for m in matches
                 if m.status_group == "finished" and m.settle_home is not None and m.settle_away is not None}
        lines: dict[int, set[tuple[str, float]]] = defaultdict(set)
        for q in quotes:
            lines[q.fixture_id].add((q.side, q.line))
        settled = [q for q in quotes if q.fixture_id in goals]
        print(f"selections with a 90-minute score: {len(settled)} in {len({q.fixture_id for q in settled})} matches; "
              f"lines {sorted({q.line for q in settled})}", flush=True)
        families = [f.strip() for f in args.families.split(",") if f.strip()]
        hypers = {family: production_hyper(conn, family) for family in families}
    # Everything is read: the connection is closed before the fits, which take minutes - an open transaction that
    # long is ended by the server (idle_in_transaction_session_timeout; the second family's read failed so, 12 Oct).
    for family in families:
        hyper = hypers[family]
        if hyper is None:
            print(f"\n== {family}: no stored version with hyper-parameters; skipped")
            continue
        t1 = time.monotonic()
        preds, note = walk_forward(matches, {q.fixture_id for q in settled}, family=family, hyper=hyper,
                                   refit_days=args.refit_days, lines=lines)
        print(f"\n{family}: xi={hyper['xi']} penalty={hyper['penalty']} ({hyper.get('source')}) {dict(note)} "
              f"({time.monotonic() - t1:.0f}s)", flush=True)
        report(f"{family} - team totals, last {args.days} days", settled, preds, goals, rng)
    print(f"\ndone in {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
