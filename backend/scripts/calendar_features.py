"""Rest and congestion from the whole calendar: how much of it is there, what it changes, and the pre-registered test (plan F4.4;
definitions ``rest-v1``, protocol ``rest-ab-v1``).

    python -m scripts.calendar_features coverage [--days 7] [--since D] [--until D]
                                                 # the next week's matches with a whole calendar on both sides; the played ones
                                                 # with one, and what the calendar changes in the rest production counted
    python -m scripts.calendar_features export --since D [--until D] [--out FILE.csv]
                                                 # one row per finished match with a whole calendar on both sides
    python -m scripts.calendar_features compare --since D [--until D] [--out FILE.json]
                                                 # the test: does the model that reads the real rest score better? The verdict
                                                 # is arithmetic fixed before the run: promising / harmful / inconclusive

It reads and nothing else: the connection is read-only, no model is trained that production reads, no pick, price or page changes.
``promising`` does not promote anything - it says the full gate (F10 / F14) is worth running. See ``fbi.research.rest_ab``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import psycopg
from psycopg.rows import tuple_row

from fbi.competitions import team_calendar as tc
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.features.data import load_matches
from fbi.features.engine import FEATURE_VERSION
from fbi.features.store import load_feature_matrix
from fbi.research import rest_ab
from fbi.research.rest_ab import Observation, SideRest
from fbi.research.rest_features import VERSION, side_rest

DEFAULT_SPAN = timedelta(days=60)
Say = Callable[[str], None]

UPCOMING_SQL = """
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id
  FROM core.fixtures f
 WHERE f.status_group = 'scheduled' AND f.kickoff_at > %(lo)s AND f.kickoff_at <= %(hi)s
 ORDER BY f.kickoff_at, f.id
"""


def _day(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text).replace(tzinfo=UTC)


def _pct(part: int, whole: int) -> str:
    return "-" if whole == 0 else f"{100 * part / whole:.1f}%"


# --------------------------------------------------------------------------------------------------------- the sample


@dataclass(slots=True)
class Sample:
    since: datetime
    until: datetime
    finished: int = 0
    """Finished matches of the window in the dataset production reads."""
    with_features: int = 0
    """Of them, those with a stored feature set (the inputs production read)."""
    observations: list[Observation] = field(default_factory=list)
    """Of those, the ones with a whole calendar on both sides - the sample the test runs on."""
    all_sides: list[SideRest] = field(default_factory=list)
    reasons: Counter[str] = field(default_factory=Counter)
    """Why a side was not whole, over every side of every match with a stored feature set."""


def calendars(conn: psycopg.Connection[Any], team_ids: Iterable[int], *, at: datetime, since: datetime,
              until: datetime) -> dict[int, tc.TeamCalendar]:
    """One calendar per team that spans the window, so that any kick-off in it can be asked of it."""
    back = (until - since) + tc.BACK + timedelta(days=1)
    return {team: tc.load(conn, team_id=team, at=at, kickoff=until, back=back) for team in sorted(set(team_ids))}


def build_sample(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, at: datetime,
                 say: Say | None = None) -> Sample:
    """The finished matches of ``[since, until)`` with the inputs production read for them and the calendar of each side as it
    stands at ``at`` (a list read after a match shows how that stretch of the season ended)."""
    out = Sample(since, until)
    finished = [m for m in load_matches(conn) if m.has_result and since <= m.kickoff_at < until]
    out.finished = len(finished)
    features = load_feature_matrix(conn, version=FEATURE_VERSION, fixture_ids=[m.fixture_id for m in finished])
    held = [m for m in finished if m.fixture_id in features]
    out.with_features = len(held)
    if say:
        say(f"{len(finished)} finished matches, {len(held)} with a stored feature set; reading the calendar of their teams")
    teams = calendars(conn, (t for m in held for t in (m.home_team_id, m.away_team_id)), at=at, since=since, until=until)
    for m in held:
        assert m.settle_home is not None and m.settle_away is not None
        home = side_rest(teams[m.home_team_id], m.kickoff_at)
        away = side_rest(teams[m.away_team_id], m.kickoff_at)
        for side in (home, away):
            out.all_sides.append(side)
            if side.reason is not None:
                out.reasons[side.reason] += 1
        if home.whole and away.whole:
            outcome = 0 if m.settle_home > m.settle_away else 1 if m.settle_home == m.settle_away else 2
            out.observations.append(Observation(m.fixture_id, m.kickoff_at, outcome, features[m.fixture_id][1], home, away))
    return out


# ---------------------------------------------------------------------------------------------------------- coverage


def upcoming_lines(conn: psycopg.Connection[Any], *, days: int, at: datetime) -> list[str]:
    """The matches of the next ``days`` days: how many have a calendar that is whole now on both sides (the packet's and the page's rule)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(UPCOMING_SQL, {"lo": at, "hi": at + timedelta(days=days)})
        coming = cur.fetchall()
    both = one = none = 0
    why: Counter[str] = Counter()
    for _fid, kickoff, home_id, away_id in coming:
        states = [tc.load(conn, team_id=int(team), at=at, kickoff=kickoff).state(kickoff) for team in (home_id, away_id)]
        whole = sum(1 for s in states if s.complete)
        both, one, none = both + (whole == 2), one + (whole == 1), none + (whole == 0)
        for s in states:
            if s.reason is not None:
                why[s.reason] += 1
    n = len(coming)
    lines = [f"Matches in the next {days} days: {n}",
             f"  both calendars whole  {both:>6}  ({_pct(both, n)})",
             f"  one side whole        {one:>6}  ({_pct(one, n)})",
             f"  neither whole         {none:>6}  ({_pct(none, n)})"]
    if why:
        lines.append("  why a side is not whole: " + ", ".join(f"{k} {v}" for k, v in sorted(why.items())))
    return lines


def sample_lines(sample: Sample) -> list[str]:
    n_sides = len(sample.all_sides)
    whole = len(sample.observations)
    lines = [f"Finished matches {sample.since:%Y-%m-%d} to {sample.until:%Y-%m-%d}: {sample.finished} "
             f"({sample.with_features} with the feature set production read)",
             f"  both calendars whole (the sample of the test)  {whole:>6}  ({_pct(whole, sample.with_features)})"]
    if sample.reasons:
        lines.append(f"  why a side is not whole ({n_sides} sides): "
                     + ", ".join(f"{k} {v}" for k, v in sorted(sample.reasons.items())))
    d = rest_ab.describe(sample.observations)
    if d.get("with_rest"):
        lines += [f"What the calendar changes in the rest of the sample ({d['with_rest']} sides with a rest known):",
                  f"  a match outside the followed competitions in the last 14 days  {100 * d['share_with_an_outside_match_in_14d']:.1f}% of sides",
                  f"  rest shorter than production counted: by 1 day or more {100 * d['share_rest_shorter_by_1d_or_more']:.1f}%, "
                  f"by 2 days or more {100 * d['share_rest_shorter_by_2d_or_more']:.1f}%",
                  f"  days shorter: mean {d['mean_days_shorter']}, median {d['p50_days_shorter']}, p90 {d['p90_days_shorter']}, "
                  f"max {d['max_days_shorter']}"]
    else:
        lines.append("Nothing to describe yet: no match has a whole calendar on both sides.")
    return lines


def coverage_command(conn: psycopg.Connection[Any], *, days: int, since: datetime, until: datetime, at: datetime,
                     say: Say | None = None) -> list[str]:
    return [*upcoming_lines(conn, days=days, at=at), "", *sample_lines(build_sample(conn, since=since, until=until, at=at, say=say)),
            "", f"definitions {VERSION}, protocol {rest_ab.PROTOCOL}"]


# ------------------------------------------------------------------------------------------------------------ export

COLUMNS = ("fixture_id", "kickoff_at", "outcome", "production_home_rest", "production_away_rest",
           "home_rest_days", "away_rest_days", "home_rest_tracked", "away_rest_tracked", "home_rest_outside", "away_rest_outside",
           "home_played_7d", "away_played_7d", "home_played_14d", "away_played_14d", "home_played_30d", "away_played_30d",
           "home_outside_14d", "away_outside_14d", "home_next_gap_days", "away_next_gap_days", "home_next_type", "away_next_type",
           "true_rest_diff")


def _cell(value: object) -> object:
    return "" if value is None else round(value, 4) if isinstance(value, float) else value


def export_rows(observations: Sequence[Observation]) -> list[list[object]]:
    rows: list[list[object]] = []
    for o in observations:
        h, a = o.home, o.away
        rows.append([_cell(x) for x in (
            o.fixture_id, o.kickoff_at.isoformat(), o.outcome, o.values.get("home_rest_days"), o.values.get("away_rest_days"),
            h.rest_days, a.rest_days, h.rest_days_tracked, a.rest_days_tracked, h.rest_days_outside, a.rest_days_outside,
            h.played_7d, a.played_7d, h.played_14d, a.played_14d, h.played_30d, a.played_30d, h.outside_14d, a.outside_14d,
            h.next_gap_days, a.next_gap_days, h.next_competition_type, a.next_competition_type, rest_ab.true_rest_diff(o))])
    return rows


def write_csv(observations: Sequence[Observation], out: TextIO) -> int:
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    rows = export_rows(observations)
    writer.writerows(rows)
    return len(rows)


# ----------------------------------------------------------------------------------------------------------- compare


def result_lines(result: rest_ab.Result) -> list[str]:
    p = result.primary
    lines = [f"protocol {rest_ab.PROTOCOL}, definitions {VERSION}",
             f"sample: {result.n_sample} matches with a whole calendar on both sides; {result.n_tested} predicted in {result.blocks} "
             f"walk-forward blocks"]
    if p is not None:
        lines += [f"{p.arm} vs {p.reference} (primary): log loss {p.loss_arm:.5f} vs {p.loss_reference:.5f}, change {p.diff:+.5f} "
                  f"[{p.lo:+.5f}, {p.hi:+.5f}] over {p.n} matches on {p.days} days; the sample would show a gain of "
                  f"{p.minimum_detectable:.5f} with 80% power"]
    for s in result.secondary:
        lines.append(f"  {s.arm} vs {s.reference}: change {s.diff:+.5f} [{s.lo:+.5f}, {s.hi:+.5f}] (not decisive)")
    lines.append(f"VERDICT: {result.verdict.upper()} - {result.why}")
    return lines


def compare_command(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, at: datetime, out: Path | None,
                    say: Say | None = None) -> tuple[int, list[str]]:
    sample = build_sample(conn, since=since, until=until, at=at, say=say)
    result = rest_ab.run(sample.observations)
    if out is not None:
        payload = {**result.as_dict(), "window": {"since": since.isoformat(), "until": until.isoformat(), "at": at.isoformat()},
                   "coverage": {"finished": sample.finished, "with_features": sample.with_features,
                                "why_a_side_is_not_whole": dict(sample.reasons)}}
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return 0, [*sample_lines(sample), "", *result_lines(result)]


# -------------------------------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("coverage", "export", "compare"))
    ap.add_argument("--days", type=int, default=7, help="coverage: how far ahead to look at the matches still to be played")
    ap.add_argument("--since", help="first kick-off of the finished matches (YYYY-MM-DD, UTC); coverage: 60 days before --until")
    ap.add_argument("--until", help="kick-offs before this date (YYYY-MM-DD, UTC); default: now")
    ap.add_argument("--out", type=Path, help="export: the CSV file (default: standard output); compare: also write the result as JSON")
    args = ap.parse_args(argv)

    def say(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    at = now()
    until = _day(args.until) or at
    since = _day(args.since) or (until - DEFAULT_SPAN if args.command == "coverage" else None)
    if since is None:
        print(f"{args.command} needs --since YYYY-MM-DD", file=sys.stderr)
        return 2
    with psycopg.connect(settings.database.psycopg_url) as conn:
        conn.read_only = True
        if args.command == "coverage":
            print("\n".join(coverage_command(conn, days=args.days, since=since, until=until, at=at, say=say)))
            return 0
        if args.command == "export":
            sample = build_sample(conn, since=since, until=until, at=at, say=say)
            if args.out is None:
                write_csv(sample.observations, sys.stdout)
            else:
                with args.out.open("w", encoding="utf-8", newline="") as handle:
                    n = write_csv(sample.observations, handle)
                say(f"{n} matches written to {args.out}")
            return 0
        code, lines = compare_command(conn, since=since, until=until, at=at, out=args.out, say=say)
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
