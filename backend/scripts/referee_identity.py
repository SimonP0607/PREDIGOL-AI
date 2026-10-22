"""Who is who among the referees (plan F3): place the spellings, audit the result, look at the queue, decide a pair. 0 provider requests.

    python -m scripts.referee_identity status                        # the counts, the queue by reason, the last runs
    python -m scripts.referee_identity build                         # dry run: what a pass would write
    python -m scripts.referee_identity build --apply                 # a pass (the first one places the whole history)
    python -m scripts.referee_identity audit                         # the invariants and the criteria of the plan
    python -m scripts.referee_identity queue --limit 30              # the pairs waiting for a person, the biggest first
    python -m scripts.referee_identity find oliver                   # referees by (part of) a name or of any spelling
    python -m scripts.referee_identity show 123                      # one referee: spellings, doubts, changes, last matches
    python -m scripts.referee_identity merge 123 456 --note "..." --apply   # 456 is the same person as 123
    python -m scripts.referee_identity undo 17 --apply               # take back merge event 17
    python -m scripts.referee_identity split 123 --alias 88 --alias 91 --apply   # those spellings are another person
    python -m scripts.referee_identity reject 123 456 --apply        # two people: never suggest the pair again
    python -m scripts.referee_identity reopen 123 456 --apply        # take a rejection back
    python -m scripts.referee_identity rename 123 --name "Michael Oliver" --apply    # or --release: the rules name him again

``build`` reads ``core.fixture_facts`` (the referee string of every match, with its history), decides which spellings are
one person (``fbi.people.referee_identity``, ``refid-v1``) and writes the difference: referees, their spellings, who
officiated each match, and the queue of doubts. A pass is idempotent; a second one writes nothing. The worker runs it every
hour (``FBI_REFEREE_IDENTITY``) and audits once a day; this is the same pass by hand.

Everything that changes something is a DRY RUN unless ``--apply`` is given: the action is done inside a transaction that is
rolled back, so what it would refuse (two referees with matches at the same time are two people) is refused in the dry run
too. ``merge`` and ``split`` only move spellings between referees, so ``undo`` puts them back. The actor recorded is
``script:referee_identity``.

``audit`` only reads (a pass is simulated, not written). It exits 1 when a criterion fails: under 95 % of the matches that
name a referee with a referee id, a spelling on a merged referee, a referee with no spelling, a pass that would still write.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.errors import LockNotAvailable

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.ingestion import referee_identity as job
from fbi.people import referees
from fbi.people.countries import country_name

ACTOR = "script:referee_identity"

LAST_RUNS_SQL = """
SELECT id, started_at, finished_at, status, rows_written, rows_updated, rows_normalized, errors, params
  FROM raw.ingestion_runs WHERE job_type = %s ORDER BY started_at DESC LIMIT %s
"""
BASIS_ORDER = ("identity", "extension", "initial", "foreign", "unscoped", "manual")


def _n(value: int) -> str:
    return f"{value:,}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _country(key: str | None) -> str:
    return country_name(key) or "?"


def _when(value: Any) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value is not None else "-"


def _line(label: str, value: Any, width: int = 34) -> None:
    print(f"  {label:<{width}} {value}")


# ── looking ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def print_report(report: referees.BuildReport) -> None:
    _line("matches that name a referee", _n(report.fixtures))
    _line("observations read", _n(report.observations))
    _line("spellings (name + scope)", _n(report.forms))
    _line("people (groups)", f"{_n(report.groups)}   settled: {_pct(report.settled_share)} of their matches")
    _line("vetoes (same-time collisions)", _n(report.vetoes))
    _line("basis of the spellings", ", ".join(f"{k} {_n(v)}" for k, v in sorted(report.basis.items())) or "-")
    verb = "written" if report.applied else "to write"
    _line(f"referees {verb}", _n(report.new_referees))
    _line(f"spellings {verb}", _n(report.new_aliases))
    _line(f"officials rows {verb}", _n(report.officials_to_write))
    _line("names changed", _n(report.renamed))
    _line("doubts in the queue now", f"{_n(report.candidates)} (new {_n(report.candidates_added)}, changed "
          f"{_n(report.candidates_changed)}, gone {_n(report.candidates_removed)})")
    _line("seconds", f"{report.seconds:.1f}")


def build_command(conn: psycopg.Connection[Any], args: argparse.Namespace, *, commit: bool = True) -> int:
    """``commit=False`` leaves the transaction to the caller (a test)."""
    if not args.apply:
        report = referees.build(conn, apply=False, wait=True)
        print("referee_identity build - DRY RUN (nothing is written; add --apply)")
        print_report(report)
        return 0
    report = job.run_job(conn, commit=commit, wait=True)
    if report.skipped_locked:
        print("another pass is writing; try again in a minute")
        return 1
    print("referee_identity build - APPLIED" + ("" if report.changed else " (there was nothing to write)"))
    print_report(report)
    return 0


def status_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    counts = referees.audit(conn)
    print(f"referees {referees.VERSION}")
    _line("referees (active / merged)", f"{_n(counts['referees_active'])} / {_n(counts['referees_merged'])}")
    by_basis = referees.counts_by_basis(conn)
    _line("spellings", f"{_n(counts['aliases'])}   (" + ", ".join(f"{b} {_n(by_basis[b])}" for b in BASIS_ORDER if b in by_basis) + ")")
    _line("officials rows (history)", _n(counts["officials_rows"]))
    _line("matches with a referee now", f"{_n(counts['fixtures_with_referee'])} of {_n(counts['with_a_referee_in_the_facts'])} "
          f"({_pct(counts['placed_share'])})")
    _line("matches with a doubt waiting", f"{_n(counts['matches_with_a_doubt'])}   settled: {_pct(counts['settled_share'])}")
    _line("queue (open / rejected / merged)", f"{_n(counts['candidates_open'])} / {_n(counts['candidates_rejected'])} / {_n(counts['candidates_merged'])}")
    with conn.cursor() as cur:
        cur.execute("SELECT reason, count(*), coalesce(sum(impact), 0) FROM core.referee_candidates WHERE status = 'open' GROUP BY 1 ORDER BY 3 DESC")
        for reason, n, impact in cur.fetchall():
            _line(f"   {reason}", f"{_n(int(n))} pairs, {_n(int(impact))} matches on the smaller sides")
    problems = job.problems_of(counts)
    _line("problems", ", ".join(problems) if problems else "none")
    with conn.cursor() as cur:
        cur.execute(LAST_RUNS_SQL, (job.JOB, args.runs))
        rows = cur.fetchall()
    print(f"last {len(rows)} runs of the job (a pass that writes nothing leaves no row):")
    for run_id, started, finished, status, written, updated, normalized, errors, params in rows:
        took = f"{(finished - started).total_seconds():.0f}s" if finished and started else "-"
        print(f"  #{run_id} {_when(started)} {status:<11} {took:>5}  written {_n(written or 0)}, updated {_n(updated or 0)}, "
              f"matches {_n(normalized or 0)}, errors {errors or 0}  {json.dumps(params, sort_keys=True)}")
    return 0


def audit_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    result = referees.audit(conn)
    problems = job.problems_of(result)
    print(f"referee_identity audit ({referees.VERSION})")
    for key in ("referees_active", "referees_merged", "aliases", "officials_rows", "fixtures_with_referee", "with_a_referee_in_the_facts",
                "candidates_open", "candidates_rejected", "candidates_merged"):
        _line(key, _n(result[key]))
    for key in ("aliases_on_merged_referee", "active_without_alias", "candidates_on_merged_referee"):
        _line(key + "  (must be 0)", _n(result[key]))
    _line("placed_share  (>= 95%)", _pct(result["placed_share"]))
    _line("settled_share", f"{_pct(result['settled_share'])}  ({_n(result['matches_with_a_doubt'])} matches wait for a person)")
    _line("a pass would write  (must be 0)", result["pass_would_write"])
    print("FAILED: " + ", ".join(problems) if problems else "OK")
    return 1 if problems else 0


def queue_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    total = referees.queue_size(conn, status=args.status, reason=args.reason)
    rows = referees.queue(conn, status=args.status, reason=args.reason, limit=args.limit, offset=args.offset)
    print(f"{args.status} pairs: {_n(total)}" + (f" ({args.reason})" if args.reason else "") + f" - showing {len(rows)} from {args.offset}")
    for r in rows:
        ev = r["evidence"] or {}
        shown = ", ".join(f"{k}={v}" for k, v in ev.items()) if isinstance(ev, dict) else str(ev)
        print(f"  #{r['id']:<6} {r['reason']:<22} impact {r['impact']:>4} score {r['score']:.2f}  "
              f"{r['referee_a']}:{r['name_a']} ({_country(r['country_a'])}, {r['matches_a']})  <->  "
              f"{r['referee_b']}:{r['name_b']} ({_country(r['country_b'])}, {r['matches_b']})")
        if shown:
            print(f"           {shown[:200]}")
        if r["status"] != "open":
            print(f"           decided by {r['decided_by']} at {_when(r['decided_at'])}")
    return 0


def find_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    rows = referees.find(conn, args.text, limit=args.limit)
    if not rows:
        print("no referee")
        return 1
    for r in rows:
        print(f"  {r['id']:<7} {r['name']:<34} {_country(r['country_key']):<16} {_n(r['matches']):>6} matches  "
              f"{_when(r['first_match'])[:10]} .. {_when(r['last_match'])[:10]}" + ("  (name set by a person)" if r["name_locked"] else ""))
    return 0


def show_command(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    row = referees.referee_row(conn, args.referee)
    if row is None:
        print(f"no referee {args.referee}")
        return 1
    print(f"referee {row['id']}: {row['name']}   country {_country(row['country_key'])}   status {row['status']}"
          + (f" (merged into {row['merged_into']})" if row["merged_into"] else "")
          + f"   origin {row['origin']}   {_n(row['matches'])} matches, {_when(row['first_match'])[:10]} .. {_when(row['last_match'])[:10]}"
          + ("   name set by a person" if row["name_locked"] else ""))
    print("spellings:")
    for a in referees.aliases_of(conn, args.referee):
        print(f"  alias {a['id']:<7} {a['display']:<36} scope {_country(a['scope']):<14} {a['basis']:<9} by {a['placed_by']:<6} "
              f"{_n(a['matches']):>5} matches  {_when(a['first'])[:10]} .. {_when(a['last'])[:10]}")
    pairs = referees.candidates_of(conn, args.referee)
    if pairs:
        print("doubts waiting:")
        for p in pairs:
            print(f"  #{p['id']:<6} {p['reason']:<22} impact {p['impact']:>4}  with {p['other_id']}:{p['other_name']} "
                  f"({_country(p['other_country'])}, {p['other_matches']} matches)")
    events = referees.events_of(conn, args.referee, limit=args.events)
    if events:
        print("changes:")
        for e in events:
            print(f"  event {e['id']:<6} {_when(e['at'])} {e['actor']:<24} {e['action']:<7} {e['referee_id']} <- {e['other_id']} "
                  f"aliases {list(e['alias_ids'])}" + (f"  undone by {e['undone_by']}" if e["undone_by"] else "")
                  + (f"  {json.dumps(e['detail'], sort_keys=True, default=str)[:120]}" if e["detail"] else ""))
    if args.matches:
        print("last matches:")
        for m in referees.recent_matches(conn, args.referee, limit=args.matches):
            print(f"  {_when(m['kickoff_at'])}  {m['home']} - {m['away']}  ({m['competition']} {m['season']})  as '{m['spelling']}'")
    return 0


# ── deciding ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def act(conn: psycopg.Connection[Any], args: argparse.Namespace) -> int:
    """Do one action of a person. Without ``--apply`` it is done inside a transaction block that is rolled back, so the dry run
    refuses what the real one would. The block is the outermost transaction at the console (it commits on leaving) and a
    savepoint under a caller that has one (a test)."""
    try:
        with conn.transaction() as tx:
            message = _do(conn, args)
            if not args.apply:
                raise psycopg.Rollback(tx)
    except referees.ActionError as err:
        print(f"refused ({err.code}): {err.message}")
        return 1
    except LockNotAvailable:
        print("another pass is writing; try again in a minute")
        return 1
    print(f"done: {message}" if args.apply else f"DRY RUN, nothing was written (add --apply): {message}")
    return 0


def _do(conn: psycopg.Connection[Any], args: argparse.Namespace) -> str:
    if args.command == "merge":
        event = referees.merge(conn, args.keep, args.merge, actor=ACTOR, note=args.note, force=args.force)
        return f"{args.merge} merged into {args.keep}: event {event} (undo with 'undo {event}')"
    if args.command == "undo":
        undo_id = referees.undo(conn, args.event, actor=ACTOR)
        return f"merge event {args.event} taken back: event {undo_id}"
    if args.command == "split":
        new_id = referees.split(conn, args.referee, args.alias, actor=ACTOR, name=args.name, note=args.note)
        return f"spellings {sorted(set(args.alias))} of {args.referee} are now referee {new_id}"
    if args.command == "reject":
        referees.reject(conn, args.a, args.b, actor=ACTOR, note=args.note)
        return f"{args.a} and {args.b} are two people: the pair will not be suggested again"
    if args.command == "reopen":
        referees.reopen(conn, args.a, args.b, actor=ACTOR)
        return f"the pair {args.a} / {args.b} is a question again"
    if args.command == "rename":
        if args.release:
            referees.rename(conn, args.referee, None, actor=ACTOR)
            return f"referee {args.referee} is named by the rules again"
        referees.rename(conn, args.referee, args.name, actor=ACTOR)
        return f"referee {args.referee} is now shown as '{args.name}'"
    raise AssertionError(args.command)


# ── the command line ─────────────────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="referee_identity", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="a pass: place the spellings, the officials and the queue (dry run unless --apply)")
    b.add_argument("--apply", action="store_true", help="write (the default is a dry run)")

    st = sub.add_parser("status", help="the counts, the queue by reason and the last runs (read only)")
    st.add_argument("--runs", type=int, default=8, help="how many runs of the job to list")

    sub.add_parser("audit", help="the invariants and the criteria of the plan; exit 1 if one fails (read only)")

    q = sub.add_parser("queue", help="the pairs of referees waiting for a person")
    q.add_argument("--status", choices=("open", "rejected", "merged"), default="open")
    q.add_argument("--reason", choices=("same_name_other_scope", "longer_name", "initial_and_full", "spelling_variant", "manual"))
    q.add_argument("--limit", type=int, default=25)
    q.add_argument("--offset", type=int, default=0)

    f = sub.add_parser("find", help="referees by (part of) a name or of any of their spellings")
    f.add_argument("text")
    f.add_argument("--limit", type=int, default=20)

    s = sub.add_parser("show", help="one referee: spellings, doubts, changes and last matches")
    s.add_argument("referee", type=int)
    s.add_argument("--events", type=int, default=10, help="changes to list")
    s.add_argument("--matches", type=int, default=5, help="last matches to list (0 = none)")

    def acting(name: str, help_text: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--apply", action="store_true", help="do it (the default is a dry run)")
        return p

    m = acting("merge", "referee MERGE is the same person as KEEP: his spellings move to KEEP")
    m.add_argument("keep", type=int)
    m.add_argument("merge", type=int)
    m.add_argument("--note")
    m.add_argument("--force", action="store_true", help="even if they have matches at the same time (almost never right)")

    u = acting("undo", "take back a merge by the id of its event")
    u.add_argument("event", type=int)

    sp = acting("split", "move spellings of a referee to a new one (two people were taken for one)")
    sp.add_argument("referee", type=int)
    sp.add_argument("--alias", type=int, action="append", required=True, help="spelling id (repeatable); at least one stays")
    sp.add_argument("--name", help="the name of the new referee (else the best of the spellings)")
    sp.add_argument("--note")

    r = acting("reject", "two referees are two people: never suggest the pair again")
    r.add_argument("a", type=int)
    r.add_argument("b", type=int)
    r.add_argument("--note")

    ro = acting("reopen", "take back a rejection: the pair is a question again")
    ro.add_argument("a", type=int)
    ro.add_argument("b", type=int)

    rn = acting("rename", "set the name a referee is shown with, or give the naming back to the rules")
    rn.add_argument("referee", type=int)
    which = rn.add_mutually_exclusive_group(required=True)
    which.add_argument("--name")
    which.add_argument("--release", action="store_true", help="the rules name him again")
    return ap


READ_ONLY = {"status": status_command, "audit": audit_command, "queue": queue_command, "find": find_command, "show": show_command}


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
            if args.command in READ_ONLY:
                code = READ_ONLY[args.command](conn, args)
                conn.rollback()  # read only (the audit simulates a pass: nothing of it is kept)
                return code
            return act(conn, args)
        except LockNotAvailable:
            conn.rollback()
            print("another pass is writing; try again in a minute")
            return 1


if __name__ == "__main__":
    sys.exit(main())
