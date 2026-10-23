"""The specialised model families (plan F10): the goals of each half, the corners and the cards - research, in SHADOW, nothing is priced.

    python -m scripts.families measures                              # what a family can be trained on, and the columns that grade it
    python -m scripts.families export --measure corners_ft --out corners.csv.gz     # the training history, read-only, to analyse elsewhere
    python -m scripts.families evaluate --measure corners_ft         # walk-forward against the baseline of "nothing known about the teams"
    python -m scripts.families evaluate --measure corners_ft --csv corners.csv.gz --tune --json

``evaluate`` fits each competition on the matches already known at the start of every block of ``--step-days`` and predicts the block; it reports
whether that beats the competition's average, the calibration of the totals lines, and competition by competition where it does. It does not
compare with the market (the price history of F1 is still short): a family stays in RESEARCH until the gate of the plan can be run.
It only reads; 0 provider requests; 0 AI.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.families import evaluate, history
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
HISTORY_DAYS = 3 * 365
FIELDS = ("competition_id", "fixture_id", "kickoff_at", "home_id", "away_id", "home", "away", "neutral")


def write_csv(path: Path, by_competition: dict[int, list[Match]]) -> int:
    n = 0
    with gzip.open(path, "wt", newline="", encoding="utf-8") if path.suffix == ".gz" else path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for competition, matches in sorted(by_competition.items()):
            for m in matches:
                w.writerow([competition, m.fixture_id, m.kickoff_at.isoformat(), m.home_id, m.away_id, m.home, m.away, int(m.neutral)])
                n += 1
    return n


def read_csv(path: Path) -> dict[int, list[Match]]:
    out: dict[int, list[Match]] = {}
    with gzip.open(path, "rt", newline="", encoding="utf-8") if path.suffix == ".gz" else path.open("r", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(int(r["competition_id"]), []).append(
                Match(int(r["fixture_id"]), datetime.fromisoformat(r["kickoff_at"]), int(r["home_id"]), int(r["away_id"]), int(r["home"]),
                      int(r["away"]), bool(int(r["neutral"]))))
    return out


def load(args: argparse.Namespace, now: datetime) -> dict[int, list[Match]]:
    if getattr(args, "csv", None):
        return read_csv(Path(args.csv))
    with psycopg.connect(settings.database.psycopg_url, options="-c default_transaction_read_only=on") as conn:
        data = history.load(conn, args.measure, since=now - timedelta(days=HISTORY_DAYS + args.months * 31), cutoff=now)
        conn.rollback()
    return data


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
    # only the competitions that had enough history BEFORE the first block can be predicted
    usable = {c: ms for c, ms in data.items() if sum(1 for m in ms if m.kickoff_at + OUTCOME_KNOWN_AFTER <= start) >= MIN_TRAIN}
    print(f"{args.measure}: {sum(len(v) for v in data.values())} matches in {len(data)} competitions; {len(usable)} with enough history before "
          f"{start:%Y-%m-%d}", file=sys.stderr)
    xi, penalty = float(args.xi), float(args.penalty)
    grid: dict[str, float] = {}
    if args.tune:
        xi, penalty, grid = evaluate.tune(usable, measure=args.measure, start=start, step_days=args.step_days)
    ev = evaluate.walk_forward(usable, measure=args.measure, start=start, end=end, step_days=args.step_days, xi=xi, penalty=penalty)
    lines = tuple(float(x) for x in args.lines.split(",")) if args.lines else DEFAULT_LINES.get(args.measure, ())
    summary = evaluate.summarise(ev, lines)
    summary["tuning_grid"] = grid
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
    if s["lines"]:
        first = next(iter(s["lines"]))
        print(f"  reliability of over {first} (predicted -> observed): " + " ".join(
            f"{b['mean_p']:.2f}->{b['observed']:.2f}({b['n']})" for b in s["lines"][first]["reliability"]))
    print("  by competition (most predictions first): " + "; ".join(
        f"{c['competition_id']}: {c['gain']:+.3f} ({c['n']})" for c in s["by_competition"][:12]))


def export_command(args: argparse.Namespace) -> int:
    now = clock_now()
    data = load(args, now)
    n = write_csv(Path(args.out), data)
    print(f"{n} matches of {len(data)} competitions written to {args.out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="families", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("measures", help="what a family can be trained on")
    for name, helptext in (("evaluate", "walk-forward evaluation against the baseline"), ("export", "write the training history to a CSV")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--measure", required=True, help="a measure of the settlement rules (see 'measures')")
        p.add_argument("--months", type=int, default=12, help="months of test window (default %(default)s)")
        p.add_argument("--csv", help="read the matches from this CSV instead of the database")
        if name == "evaluate":
            p.add_argument("--step-days", type=int, default=28, help="days per block (default %(default)s)")
            p.add_argument("--xi", type=float, default=evaluate.DEFAULT_XI, help="time decay per day (default %(default)s)")
            p.add_argument("--penalty", type=float, default=evaluate.DEFAULT_PENALTY, help="shrinkage of the strengths (default %(default)s)")
            p.add_argument("--tune", action="store_true", help="choose xi and penalty on the window before the test window")
            p.add_argument("--lines", help="comma-separated lines of the total to calibrate (default: the usual ones of the measure)")
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--out", required=True)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    if args.command == "measures":
        return measures_command()
    history.columns_of(args.measure)  # refuses a measure a family cannot be trained on, before anything is read
    return evaluate_command(args) if args.command == "evaluate" else export_command(args)


if __name__ == "__main__":
    sys.exit(main())
