"""Where a player played and which matches were his national team's (plan F3), and the careers of the coaches. 0 provider requests.

    python -m scripts.player_history status                         # the counts of the tables and the last runs of the job
    python -m scripts.player_history build                          # dry run: what a pass over everyone would write
    python -m scripts.player_history build --apply                  # a pass over everyone (the first one builds the whole history)
    python -m scripts.player_history build --recent --apply         # what the worker's pass does: the players of the last days
    python -m scripts.player_history build --player 123 --apply     # only these players' streaks (repeatable; no caps, no coaches)
    python -m scripts.player_history audit                          # the invariants, the crossed sheets and a simulated pass over all
    python -m scripts.player_history show 123                       # one player: his streaks, his caps
    python -m scripts.player_history show 123 --at 2026-03-20       # ... and where he was that day, his record before it
    python -m scripts.player_history coach 456                      # one coach: the person, his career with the links

``build`` reads what the provider already gave us - the transfers (``core.player_transfers``), the squad sheets and the statistics of the
matches, the squad lists - and folds it (``fbi.people.spells`` / ``fbi.people.caps``) into ``core.player_spells`` (one row per streak at a
club) and ``core.player_national_caps`` (one row per match of a senior national side whose squad sheet carries him), then ties the
careers of the coaches to the person and the club (``fbi.people.coach_links``). A pass is idempotent; a second one writes nothing. The
worker runs it every few hours (``FBI_PLAYER_HISTORY``) and sweeps once a day; this is the same pass by hand. Which side of a match a
man was on is read with ``fbi.people.sides``: the statistics win over the squad sheet, and a sheet the provider crossed (each team given
the other's) is read the other way round; ``build`` reports the sheets it turned and ``audit`` counts them, and the matches whose sheet
has no statistics to check it.

Everything that changes something is a DRY RUN unless ``--apply`` is given. ``status`` only counts; ``audit`` also simulates a pass over
everyone (it reads all the facts: minutes on the production database) and exits 1 when an invariant fails: streaks out of order, a cap of
a match not played or of a team that is not a senior national side, a career tied to the wrong person or club, a pass that would write.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.errors import LockNotAvailable

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion import player_history as job
from fbi.people import caps as cp
from fbi.people import coach_links, player_history
from fbi.people import spells as sp

LAST_RUNS_SQL = """
SELECT id, started_at, finished_at, status, rows_written, rows_updated, rows_normalized, errors, params
  FROM raw.ingestion_runs WHERE job_type = %s ORDER BY started_at DESC LIMIT %s
"""


def _n(value: int) -> str:
    return f"{value:,}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _when(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "-"


def _day(value: Any) -> str:
    return value.isoformat() if value is not None else "?"


def _line(label: str, value: Any, width: int = 36) -> None:
    print(f"  {label:<{width}} {value}")


# ── looking ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def print_history(report: player_history.BuildReport) -> None:
    verb = "written" if report.applied else "to write"
    _line("players looked at", _n(report.players))
    _line("streaks the facts give", _n(report.spells))
    _line(f"players whose streaks change ({verb})", _n(report.players_changed))
    _line(f"streak rows {verb} / removed", f"{_n(report.spells_written)} / {_n(report.spells_deleted)}")
    _line("streaks of no days (left out)", _n(report.phantoms))
    _line("squad sheets turned round (crossed)", f"{_n(report.sheets_crossed)}   (doubtful, left as they are: {_n(report.sheets_doubtful)}; "
          f"men put nowhere: {_n(report.men_nowhere)})")
    _line("matches looked at for caps", _n(report.fixtures))
    _line("caps the facts give", f"{_n(report.caps)}   (waiting for the statistics: {_n(report.caps_open)})")
    _line(f"caps {verb} / removed", f"{_n(report.caps_written)} / {_n(report.caps_deleted)}")
    _line("seconds", f"{report.seconds:.1f}")


def print_coaches(report: coach_links.BuildReport) -> None:
    verb = "created" if report.applied else "to create"
    _line(f"persons {verb} (from a profile)", _n(report.persons_created))
    _line("career rows to tie to a person" if not report.applied else "career rows tied to a person", _n(report.careers_coach_linked))
    _line("career rows to tie to a club" if not report.applied else "career rows tied to a club", _n(report.careers_team_linked))


def build_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, commit: bool = True) -> int:
    """``commit=False`` leaves the transaction to the caller (a test)."""
    if args.player:
        report = player_history.build(conn, apply=args.apply, wait=True, players=args.player)
        print(f"player_history build - {'APPLIED' if args.apply else 'DRY RUN (nothing is written; add --apply)'} - {len(set(args.player))} players")
        print_history(report)
        return 0
    if not args.apply:
        history = player_history.build(conn, apply=False, sweep=not args.recent)
        coaches = coach_links.build(conn, apply=False)
        print("player_history build - DRY RUN (nothing is written; add --apply)" + (" - the last days only" if args.recent else " - everyone"))
        print_history(history)
        print_coaches(coaches)
        return 0
    result = job.run_job(conn, sweep=not args.recent, commit=commit, wait=True)
    if result.skipped_locked:
        print("another pass is writing; try again in a minute")
        return 1
    print("player_history build - APPLIED" + ("" if result.changed else " (there was nothing to write)")
          + (" - the last days only" if args.recent else " - everyone"))
    print_history(result.history)
    print_coaches(result.coaches)
    return 0


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    figures = player_history.counts(conn)
    coaches = coach_links.counts(conn)
    print(f"player_history {player_history.VERSION}")
    _line("players with streaks", _n(figures["players_with_spells"]))
    _line("streaks (open / total)", f"{_n(figures['spells_open'])} / {_n(figures['spells'])}   (" + ", ".join(
        f"{k} {_n(v)}" for k, v in sorted(figures["spells_by_source"].items())) + ")")
    _line("caps (players / matches)", f"{_n(figures['caps'])}   ({_n(figures['caps_players'])} / {_n(figures['caps_fixtures'])})")
    _line("caps waiting for the statistics", _n(figures["caps_open"]))
    _line("caps of the last year with a club known", f"{_n(figures['recent_caps_with_a_club'])} of {_n(figures['recent_caps'])} "
          f"({_pct(figures['recent_club_known_share'])})")
    for key in (*player_history.INVARIANTS, "spells_of_another_version", "caps_of_another_version"):
        _line(key + ("  (must be 0)" if key in player_history.INVARIANTS else ""), _n(figures[key]))
    _line("lone stints (A, B for one match, A)", _n(figures["lone_stints"]))
    print(f"coaches ({coach_links.JOB})")
    _line("persons / careers (rows)", f"{_n(coaches['coaches'])} / {_n(coaches['careers'])}")
    _line("careers without a person", _n(coaches["careers_without_coach"]))
    _line("careers of a club we do not hold", _n(coaches["careers_of_clubs_not_held"]))
    _line("profiles without a person", _n(coaches["profiles_without_person"]))
    _line("newest careers (with person and club)", f"{_n(coaches['spells'])}  ({_n(coaches['spells_with_person_and_club'])})")
    for key in coach_links.INVARIANTS:
        _line(key + "  (must be 0)", _n(coaches[key]))
    with conn.cursor() as cur:
        cur.execute(LAST_RUNS_SQL, (job.JOB, args.runs))
        rows = cur.fetchall()
    print(f"last {len(rows)} runs of the job (a pass that writes nothing leaves no row):")
    for run_id, started, finished, status, written, updated, normalized, errors, params in rows:
        took = f"{(finished - started).total_seconds():.0f}s" if finished and started else "-"
        print(f"  #{run_id} {_when(started)} {status:<11} {took:>5}  written {_n(written or 0)}, updated {_n(updated or 0)}, "
              f"looked at {_n(normalized or 0)}, errors {errors or 0}  {json.dumps(params, sort_keys=True)}")
    return 0


def audit_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    print("player_history audit: simulating a pass over everyone (it reads all the facts; this takes a while)...", flush=True)
    result = {"history": player_history.audit(conn), "coaches": coach_links.audit(conn)}
    problems = job.problems_of(result)
    history, coaches = result["history"], result["coaches"]
    print(f"player_history audit ({player_history.VERSION})")
    for key in ("players_with_spells", "spells", "spells_open", "caps", "caps_players", "caps_fixtures", "caps_open", "recent_caps"):
        _line(key, _n(history[key]))
    for key in (*player_history.INVARIANTS, "spells_of_another_version", "caps_of_another_version"):
        _line(key + "  (must be 0)", _n(history[key]))
    _line("recent_club_known_share", _pct(history["recent_club_known_share"]))
    _line("a pass would write  (must be 0)", history["pass_would_write"])
    _line("streaks of no days the facts leave out", _n(history["phantoms"]))
    _line("squad sheets turned round (crossed)", _n(history["sheets_crossed"]))
    _line("squad sheets in doubt, left as they are", _n(history["sheets_doubtful"]))
    _line("men put nowhere (in both sheets)", _n(history["men_nowhere"]))
    _line("finished matches with sheets and no statistics", _n(history["fixtures_with_sheets_only"]))
    _line("lone stints (A, B for one match, A)", _n(history["lone_stints"]))
    for key in ("coaches", "careers", "careers_without_coach", "careers_of_clubs_not_held", "profiles_without_person"):
        _line("coaches: " + key, _n(coaches[key]))
    for key in coach_links.INVARIANTS:
        _line("coaches: " + key + "  (must be 0)", _n(coaches[key]))
    _line("coaches: a pass would write  (must be 0)", coaches["pass_would_write"])
    print("FAILED: " + ", ".join(problems) if problems else "OK")
    return 1 if problems else 0


def show_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    streaks = player_history.spells_of(conn, [args.player]).get(args.player, [])
    names = player_history.spell_names(conn, [args.player])
    caps = player_history.caps_of(conn, [args.player]).get(args.player, [])
    if not streaks and not caps:
        print(f"nothing about player {args.player}")
        return 1
    print(f"player {args.player}: {len(streaks)} streaks at clubs, {len(caps)} national-team squad entries")
    for n, s in enumerate(streaks):
        print(f"  {n:>2}  {names.get(s.club, '?'):<28} (club {s.club})  {_day(s.valid_from)} .. {_day(s.valid_to)}  from a {s.source:<8} "
              f"{s.matches:>3} matches  last evidence {_day(s.last_evidence)}" + (f"  via '{s.via}'" if s.via else ""))
    if args.at:
        day = date.fromisoformat(args.at)
        there = sp.club_at(streaks, day)
        print(f"on {day}: " + (f"{names.get(there.club, '?')} (club {there.club}), last evidence {_day(there.last_evidence)}" if there else "no club is known"))
        before = datetime(day.year, day.month, day.day, tzinfo=UTC)
        record = cp.profile(caps, before=before)
        print(f"before {day}: {record.squads} squad entries, {record.caps} played ({record.starts} starts, {record.minutes} minutes), "
              f"{record.unknown} waiting for the statistics; last in a squad {_day(record.last_squad.date() if record.last_squad else None)}, "
              f"last cap {_day(record.last_cap.date() if record.last_cap else None)}")
    if caps:
        print("squad entries (newest first):")
        for c in caps[: args.caps]:
            played = {True: "played", False: "bench", None: "?"}[c.appeared]
            print(f"  {c.kickoff:%Y-%m-%d}  match {c.fixture_id:<9} team {c.team_id:<7} {'started' if c.is_starter else 'sub':<8} {played:<7}"
                  + (f" {c.minutes}'" if c.minutes is not None else ""))
    return 0


def coach_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, firstname, lastname, birth_date, nationality FROM core.coaches WHERE provider_coach_id = %s", (args.coach,))
        person = cur.fetchone()
        cur.execute("SELECT s.provider_team_id, s.team_id, s.team_name, t.name, s.start_date, s.end_date "
                    "FROM core.coach_spells s LEFT JOIN core.teams t ON t.id = s.team_id "
                    "WHERE s.provider_coach_id = %s ORDER BY s.start_date NULLS FIRST, s.provider_team_id", (args.coach,))
        rows = cur.fetchall()
    if person is None and not rows:
        print(f"nothing about coach {args.coach}")
        return 1
    if person is None:
        print(f"coach {args.coach}: no person yet (a pass makes it when a profile with a name exists)")
    else:
        print(f"coach {args.coach}: person {person[0]}  {person[1]}  {person[2] or ''} {person[3] or ''}  born {_day(person[4])}  {person[5] or ''}")
    print(f"career as the provider last listed it ({len(rows)} rows):")
    for provider_team, team, listed, ours, start, end in rows:
        tied = f"-> team {team} ({ours})" if team is not None else "-> not a club we hold"
        print(f"  {_day(start)} .. {_day(end) if end else 'now':<10}  {listed or '?':<30} (club {provider_team})  {tied}")
    return 0


# ── the command line ─────────────────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="player_history", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="a pass: the streaks, the caps and the careers of the coaches (dry run unless --apply)")
    b.add_argument("--apply", action="store_true", help="write (the default is a dry run)")
    b.add_argument("--recent", action="store_true", help="only the players and matches of the last days (what the worker's pass does)")
    b.add_argument("--player", type=int, action="append", help="only this provider player id (repeatable): streaks only, no caps, no coaches")

    st = sub.add_parser("status", help="the counts of the tables and the last runs (read only)")
    st.add_argument("--runs", type=int, default=8, help="how many runs of the job to list")

    sub.add_parser("audit", help="the invariants and a simulated pass over everything; exit 1 if one fails (read only, slow)")

    s = sub.add_parser("show", help="one player: his streaks at clubs and his national-team squad entries")
    s.add_argument("player", type=int, help="provider player id")
    s.add_argument("--at", help="a day (YYYY-MM-DD): where he was, and his record before it")
    s.add_argument("--caps", type=int, default=10, help="national-team squad entries to list")

    c = sub.add_parser("coach", help="one coach: the person and his career with the links")
    c.add_argument("coach", type=int, help="provider coach id")
    return ap


READ_ONLY = {"status": status_command, "audit": audit_command, "show": show_command, "coach": coach_command}


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging("WARNING")
    args = build_parser().parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        try:
            if args.command == "build":
                code = build_command(conn, args)
                if not args.apply:
                    conn.rollback()
                return code
            code = READ_ONLY[args.command](conn, args)
            conn.rollback()  # read only (the audit simulates a pass: nothing of it is kept)
            return code
        except LockNotAvailable:
            conn.rollback()
            print("another pass is writing; try again in a minute")
            return 1


if __name__ == "__main__":
    sys.exit(main())
