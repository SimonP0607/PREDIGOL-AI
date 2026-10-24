"""The specialised model families (plan F10): the goals of each half, the corners and the cards - research, in SHADOW, nothing is priced.

    python -m scripts.families measures                              # what a family can be trained on, and the columns that grade it
    python -m scripts.families export --measure corners_ft --out corners.csv.gz     # the training history, read-only, to analyse elsewhere
    python -m scripts.families evaluate --measure corners_ft         # walk-forward against the baseline of "nothing known about the teams"
    python -m scripts.families evaluate --measure corners_ft --csv corners.csv.gz --tune --json
    python -m scripts.families sql --measure corners_ft              # the same history as one COPY statement, to run with psql where Python is not at hand
    python -m scripts.families halves                                # the bets of the halves (HT/FT, highest half, BTTS by half...) derived from two fits
    python -m scripts.families score --days 14                       # how the stored forecasts of the families did on the matches that have finished

``evaluate`` fits each competition on the matches already known at the start of every block of ``--step-days`` and predicts the block; it reports
whether that beats the competition's average, the calibration of the totals lines, and competition by competition where it does. It does not
compare with the market (the price history of F1 is still short): a family stays in RESEARCH until the gate of the plan can be run.
It only reads; 0 provider requests; 0 AI.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.families import evaluate, evaluate_halves, history
from fbi.families import score as scoreboard
from fbi.families.fit import MIN_TRAIN, OUTCOME_KNOWN_AFTER, Match
from fbi.market.rules import RULES

DEFAULT_LINES: dict[str, tuple[float, ...]] = {
    "corners_ft": (8.5, 9.5, 10.5, 11.5),
    "cards_lines_ft": (3.5, 4.5, 5.5),
    "yellow_ft": (2.5, 3.5, 4.5),
    "goals_1h": (0.5, 1.5),
    "goals_2h": (1.5, 2.5),
    "shots_on_target_ft": (7.5, 8.5, 9.5),
}
DEFAULT_SIDE_LINES: dict[str, tuple[float, ...]] = {
    "corners_ft": (3.5, 4.5, 5.5, 6.5),
    "cards_lines_ft": (1.5, 2.5),
    "yellow_ft": (1.5, 2.5),
    "goals_1h": (0.5,),
    "goals_2h": (0.5, 1.5),
    "shots_on_target_ft": (3.5, 4.5, 5.5),
}
HISTORY_DAYS = 3 * 365
FIELDS = ("competition_id", "fixture_id", "kickoff_at", "home_id", "away_id", "home", "away", "neutral", "referee_id")


def _write_rows(fh: TextIO, by_competition: dict[int, list[Match]]) -> int:
    n = 0
    w = csv.writer(fh)
    w.writerow(FIELDS)
    for competition, matches in sorted(by_competition.items()):
        for m in matches:
            w.writerow([competition, m.fixture_id, m.kickoff_at.isoformat(), m.home_id, m.away_id, m.home, m.away, int(m.neutral),
                        "" if m.referee_id is None else m.referee_id])
            n += 1
    return n


def write_csv(path: Path, by_competition: dict[int, list[Match]]) -> int:
    """Write the history to ``path`` (gzip when it ends in .gz) or, for ``-``, to the standard output as gzip: the way to bring it out of a
    one-off container without mounting a folder."""
    if str(path) == "-":
        with gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb") as raw, io.TextIOWrapper(raw, encoding="utf-8", newline="") as fh:
            return _write_rows(fh, by_competition)
    with gzip.open(path, "wt", newline="", encoding="utf-8") if path.suffix == ".gz" else path.open("w", newline="", encoding="utf-8") as fh:
        return _write_rows(fh, by_competition)


def read_csv(path: Path) -> dict[int, list[Match]]:
    out: dict[int, list[Match]] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") if path.suffix == ".gz" else path.open("r", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(int(r["competition_id"]), []).append(
                Match(int(r["fixture_id"]), datetime.fromisoformat(r["kickoff_at"]), int(r["home_id"]), int(r["away_id"]), int(r["home"]),
                      int(r["away"]), bool(int(r["neutral"])), int(r["referee_id"]) if r.get("referee_id") else None))
    return out


def load_measure(measure: str, csv_path: str | None, months: int, now: datetime, *, with_referee: bool = False) -> dict[int, list[Match]]:
    """The finished matches of a measure, from a CSV written by ``export`` or, read-only, from the database."""
    if csv_path:
        return read_csv(Path(csv_path))
    with psycopg.connect(settings.database.psycopg_url, options="-c default_transaction_read_only=on") as conn:
        data = history.load(conn, measure, since=now - timedelta(days=HISTORY_DAYS + months * 31), cutoff=now, with_referee=with_referee)
        conn.rollback()
    return data


def load(args: argparse.Namespace, now: datetime) -> dict[int, list[Match]]:
    wanted = bool(getattr(args, "referee", False) or getattr(args, "referee_kappa", None))
    return load_measure(args.measure, getattr(args, "csv", None), args.months, now, with_referee=wanted)


def grid_of(args: argparse.Namespace) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """The (time decays, penalties) of ``--tune``: the ones the command line names, else the grid of ``evaluate.tune``."""
    xis = tuple(float(x) for x in args.xis.split(",")) if getattr(args, "xis", None) else tuple(evaluate.DEFAULT_XIS)
    penalties = tuple(float(x) for x in args.penalties.split(",")) if getattr(args, "penalties", None) else tuple(evaluate.DEFAULT_PENALTIES)
    return xis, penalties


def measures_command() -> int:
    print("measure                 columns                                       (rule)")
    for r in RULES:
        if r.liquidable and len(r.columns) == 2:
            print(f"{r.measure:<23} {', '.join(r.columns):<45} {r.key}")
    return 0


def evaluate_command(args: argparse.Namespace) -> int:
    now = clock_now()
    end = now - OUTCOME_KNOWN_AFTER
    start = end - timedelta(days=31 * args.months)
    data = load(args, now)
    usable = usable_competitions(data, start)
    print(f"{args.measure}: {sum(len(v) for v in data.values())} matches in {len(data)} competitions; {len(usable)} with enough history before "
          f"{start:%Y-%m-%d}", file=sys.stderr)
    xi, penalty = float(args.xi), float(args.penalty)
    grid: dict[str, float] = {}
    if args.tune:
        xi, penalty, grid = evaluate.tune(usable, measure=args.measure, start=start, step_days=args.step_days, xis=grid_of(args)[0], penalties=grid_of(args)[1])
    ev = evaluate.walk_forward(usable, measure=args.measure, start=start, end=end, step_days=args.step_days, xi=xi, penalty=penalty)
    with_referee = None
    if args.referee_kappa:
        with_referee = evaluate.walk_forward(usable, measure=args.measure, start=start, end=end, step_days=args.step_days, xi=xi, penalty=penalty,
                                             referee_kappa=args.referee_kappa)
    lines = tuple(float(x) for x in args.lines.split(",")) if args.lines else DEFAULT_LINES.get(args.measure, ())
    side_lines = tuple(float(x) for x in args.side_lines.split(",")) if args.side_lines else DEFAULT_SIDE_LINES.get(args.measure, ())
    summary = evaluate.summarise(ev, lines, side_lines)
    summary["tuning_grid"] = grid
    if with_referee is not None:
        summary["referee"] = {"kappa": args.referee_kappa, **evaluate.compare_referee(ev, with_referee)}
    if getattr(args, "calibration", False):
        summary["calibration"] = evaluate.calibration_check(ev, lines, side_lines)
    summary["window"] = {"start": start.isoformat(), "end": end.isoformat()}
    comps = evaluate.by_competition(ev)
    summary["by_competition"] = comps[:40]
    if args.json:
        print(json.dumps(summary, indent=1, default=str))
        return 0
    print_summary(summary)
    return 0


def print_summary(s: dict[str, Any]) -> None:
    if not s["n"]:
        print("no predictions: no competition had enough history")
        return
    g = s["log_score_gain_per_match"]
    print(f"{s['measure']}: {s['n']} predictions ({s['skipped_blocks']} blocks without enough history) · xi {s['params']['xi']} penalty {s['params']['penalty']}")
    print(f"  mean per match: home {s['mean_observed']['home']:.2f}, away {s['mean_observed']['away']:.2f} · dispersion model "
          f"{s['dispersion_model']['total']:.3f}, baseline {s['dispersion_baseline']['total']:.3f} (total)")
    for side in ("home", "away", "total"):
        x = g[side]
        print(f"  log-score gain over the baseline, {side:<5}: {x['mean']:+.4f} nats/match  (se {x['se']:.4f})")
    for line, d in s["lines"].items():
        print(f"  over {line}: rate {d['over_rate']:.3f} · log loss {d['log_loss_model']:.4f} vs {d['log_loss_baseline']:.4f} "
              f"(gain {d['log_loss_gain']:+.4f}, se {d['log_loss_gain_se']:.4f}) · brier {d['brier_model']:.4f} vs {d['brier_baseline']:.4f}")
    for line, d in s["side_lines"].items():
        print(f"  {line}: rate {d['over_rate']:.3f} · log loss {d['log_loss_model']:.4f} vs {d['log_loss_baseline']:.4f} "
              f"(gain {d['log_loss_gain']:+.4f}, se {d['log_loss_gain_se']:.4f})")
    r = s["result"]
    print(f"  who has more (1X2 of the count): log-score gain over the baseline {r['log_score_gain']:+.4f} nats/match (se {r['se']:.4f})")
    if s["lines"]:
        first = next(iter(s["lines"]))
        print(f"  reliability of over {first} (predicted -> observed): " + " ".join(
            f"{b['mean_p']:.2f}->{b['observed']:.2f}({b['n']})" for b in s["lines"][first]["reliability"]))
    print("  by competition (most predictions first): " + "; ".join(
        f"{c['competition_id']}: {c['gain']:+.3f} ({c['n']})" for c in s["by_competition"][:12]))
    cal = s.get("calibration")
    if cal and cal["bets"]:
        print(f"  recalibration fitted on the first half of the predictions (until {cal['fit_until'][:10]}) and graded on the second: "
              "ECE as said -> shifted -> with slope · log loss saved per prediction (shift, slope)")
        for name, b in cal["bets"].items():
            print(f"    over {name:<11} p {b['mean_p']:.3f} observed {b['observed']:.3f} · ece {b['ece']['raw']:.3f} -> {b['ece']['shift']:.3f} -> "
                  f"{b['ece']['slope']:.3f} · saved {b['gain']['shift']['mean']:+.4f}±{b['gain']['shift']['se']:.4f}, "
                  f"{b['gain']['slope']['mean']:+.4f}±{b['gain']['slope']['se']:.4f} (slope {b['slope']:.2f})")
    ref = s.get("referee")
    if ref and ref["n"]:
        print(f"  the referee (prior {ref['kappa']:g} cards; {ref['coverage']:.0%} of the matches had a multiplier), log score added per match: " + ", ".join(
            f"{side} {ref[side]['mean']:+.4f} (se {ref[side]['se']:.4f})" for side in ("home", "away", "total")))


def usable_competitions(data: dict[int, list[Match]], start: datetime) -> dict[int, list[Match]]:
    """Only the competitions that had enough history BEFORE the first block can be predicted."""
    return {c: ms for c, ms in data.items() if sum(1 for m in ms if m.kickoff_at + OUTCOME_KNOWN_AFTER <= start) >= MIN_TRAIN}


def halves_command(args: argparse.Namespace) -> int:
    """Fit the first and the second half, derive the bets of the halves from the two, and grade them against the competition's average."""
    now = clock_now()
    end = now - OUTCOME_KNOWN_AFTER
    start = end - timedelta(days=31 * args.months)
    evaluations = {}
    params: dict[str, dict[str, float]] = {}
    for measure, csv_path in (("goals_1h", args.csv_1h), ("goals_2h", args.csv_2h)):
        usable = usable_competitions(load_measure(measure, csv_path, args.months, now), start)
        xi, penalty = float(args.xi), float(args.penalty)
        if args.tune:
            xi, penalty, _ = evaluate.tune(usable, measure=measure, start=start, step_days=args.step_days, xis=grid_of(args)[0], penalties=grid_of(args)[1])
        params[measure] = {"xi": xi, "penalty": penalty}
        evaluations[measure] = evaluate.walk_forward(usable, measure=measure, start=start, end=end, step_days=args.step_days, xi=xi, penalty=penalty)
        print(f"{measure}: {len(evaluations[measure].rows)} predictions in {len(usable)} competitions (xi {xi}, penalty {penalty})", file=sys.stderr)
    report = evaluate_halves.evaluate(evaluations["goals_1h"], evaluations["goals_2h"])
    report["window"] = {"start": start.isoformat(), "end": end.isoformat()}
    report["params"] = params  # what each half was fitted with (the chosen ones when tuned): a guide can then check them against the code
    if args.json:
        print(json.dumps(report, indent=1, default=str))
        return 0
    print_halves(report)
    return 0


def print_halves(r: dict[str, Any]) -> None:
    if not r["n"]:
        print("no match was predicted in both halves: no competition had enough history")
        return
    print(f"{r['n']} matches predicted in both halves · goals per match: first half {r['mean_goals']['first_half']:.2f}, "
          f"second half {r['mean_goals']['second_half']:.2f}")
    c = r["halves_residual_correlation"]
    shown = "n/a" if c["r"] is None else f"{c['r']:+.3f}"
    print(f"  the halves, beyond their predictions: correlation {shown} (se {c['se']:.3f}) - near 0 means the independence assumed holds")
    print("  log-loss gain over the competition's average, nats/match (positive: the model knows something; > 2 se: it is not luck):")
    for name, m in sorted(r["markets"].items()):
        se = "n/a" if m["gain_se"] is None else f"{m['gain_se']:.4f}"
        print(f"    {name:<14} {m['gain']:+.4f} (se {se})   model {m['log_loss_model']:.4f} vs {m['log_loss_baseline']:.4f}")
    print("  HT/FT cells, predicted -> observed: " + " ".join(f"{x['cell']} {x['mean_predicted']:.3f}->{x['observed']:.3f}" for x in r["htft_calibration"]))


def sql_command(args: argparse.Namespace) -> int:
    """Print the statement that reads the history of ``--measure`` (no database is touched)."""
    now = clock_now()
    print(history.export_statement(args.measure, since=now - timedelta(days=HISTORY_DAYS + args.months * 31), cutoff=now,
                                   with_referee=bool(getattr(args, "referee", False))))
    return 0


def export_command(args: argparse.Namespace) -> int:
    now = clock_now()
    data = load(args, now)
    n = write_csv(Path(args.out), data)
    print(f"{n} matches of {len(data)} competitions written to {args.out}", file=sys.stderr if args.out == "-" else sys.stdout)
    return 0


def score_command(args: argparse.Namespace) -> int:
    """Grade the stored forecasts of the families on the finished matches of the last ``--days`` days (read-only)."""
    now = clock_now()
    with psycopg.connect(settings.database.psycopg_url, options="-c default_transaction_read_only=on") as conn:
        report = scoreboard.score(conn, now=now, days=args.days, wait_hours=args.wait_hours, model=args.model, market=not args.no_market,
                                  min_books=args.min_books, min_ev=args.min_ev)
        conn.rollback()
    print(json.dumps(report, indent=1, default=str) if args.json else scoreboard.render(report, top=args.top))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="families", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("measures", help="what a family can be trained on")
    ps = sub.add_parser("score", help="how the stored forecasts of the families did on the matches that have finished")
    ps.add_argument("--days", type=int, default=14, help="kick-offs of the last N days (default %(default)s)")
    ps.add_argument("--wait-hours", type=float, default=30.0, help="leave out the last N hours, until the statistics of the cards have settled (default %(default)s)")
    ps.add_argument("--model", help="only this model (e.g. family-corners_ft)")
    ps.add_argument("--top", type=int, default=12, help="selections that stray most, per model, in the text (default %(default)s)")
    ps.add_argument("--no-market", action="store_true", help="do not set the forecasts against the consensus of the books")
    ps.add_argument("--min-books", type=int, default=3, help="books a consensus needs to be compared with (default %(default)s)")
    ps.add_argument("--min-ev", type=float, default=0.03, help="the value the model has to see at the price for a simulated bet (default %(default)s)")
    ps.add_argument("--json", action="store_true")
    ph = sub.add_parser("halves", help="the bets of the halves derived from the fits of the first and of the second half")
    ph.add_argument("--months", type=int, default=12, help="months of test window (default %(default)s)")
    ph.add_argument("--csv-1h", help="read the first-half goals from this CSV (an 'export' of goals_1h) instead of the database")
    ph.add_argument("--csv-2h", help="read the second-half goals from this CSV (an 'export' of goals_2h) instead of the database")
    ph.add_argument("--step-days", type=int, default=28, help="days per block (default %(default)s)")
    ph.add_argument("--xi", type=float, default=evaluate.DEFAULT_XI, help="time decay per day (default %(default)s)")
    ph.add_argument("--penalty", type=float, default=evaluate.DEFAULT_PENALTY, help="shrinkage of the strengths (default %(default)s)")
    ph.add_argument("--tune", action="store_true", help="choose xi and penalty, per half, on the window before the test window")
    ph.add_argument("--xis", help="with --tune: comma-separated time decays of the grid (default: the grid of evaluate.tune)")
    ph.add_argument("--penalties", help="with --tune: comma-separated penalties of the grid (default: the grid of evaluate.tune)")
    ph.add_argument("--json", action="store_true")
    for name, helptext in (("evaluate", "walk-forward evaluation against the baseline"), ("export", "write the training history to a CSV"),
                           ("sql", "print the COPY statement that reads the training history (for psql)")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--measure", required=True, help="a measure of the settlement rules (see 'measures')")
        p.add_argument("--months", type=int, default=12, help="months of test window (default %(default)s)")
        p.add_argument("--csv", help="read the matches from this CSV instead of the database")
        if name in {"export", "sql"}:
            p.add_argument("--referee", action="store_true", help="also read the referee of each match (the identity F3 settled on)")
        if name == "evaluate":
            p.add_argument("--referee-kappa", type=float, help="also evaluate with the referee's multiplier on the means, shrunk with this prior "
                                                               "strength in cards (the history needs the referees: export --referee)")
            p.add_argument("--step-days", type=int, default=28, help="days per block (default %(default)s)")
            p.add_argument("--xi", type=float, default=evaluate.DEFAULT_XI, help="time decay per day (default %(default)s)")
            p.add_argument("--penalty", type=float, default=evaluate.DEFAULT_PENALTY, help="shrinkage of the strengths (default %(default)s)")
            p.add_argument("--tune", action="store_true", help="choose xi and penalty on the window before the test window")
            p.add_argument("--xis", help="with --tune: comma-separated time decays of the grid (default: the grid of evaluate.tune)")
            p.add_argument("--penalties", help="with --tune: comma-separated penalties of the grid (default: the grid of evaluate.tune)")
            p.add_argument("--lines", help="comma-separated lines of the total to calibrate (default: the usual ones of the measure)")
            p.add_argument("--side-lines", help="comma-separated lines of ONE side (home and away each) to grade (default: the usual ones)")
            p.add_argument("--calibration", action="store_true", help="also grade a recalibration (a shift, and a shift with a slope) fitted on the "
                                                                      "first half of the predictions on the second half")
            p.add_argument("--json", action="store_true")
        elif name == "export":
            p.add_argument("--out", required=True, help="a file (.csv or .csv.gz) or '-' for the standard output as gzip")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    if args.command == "measures":
        return measures_command()
    if args.command == "halves":
        return halves_command(args)
    if args.command == "score":
        return score_command(args)
    history.columns_of(args.measure)  # refuses a measure a family cannot be trained on, before anything is read
    if args.command == "sql":
        return sql_command(args)
    return evaluate_command(args) if args.command == "evaluate" else export_command(args)


if __name__ == "__main__":
    sys.exit(main())
