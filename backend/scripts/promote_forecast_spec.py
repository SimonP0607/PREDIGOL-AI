"""The forecast spec in force - which backtest session production forecasts with (fbi.predictions.spec).

    python -m scripts.promote_forecast_spec show                  # the spec in force, its history, the newest sessions
    python -m scripts.promote_forecast_spec promote --session ID --reason "why"
                                                                  # dry run: what putting that session in force changes
    python -m scripts.promote_forecast_spec promote --session ID --reason "why" --by NAME --confirm
                                                                  # a person's decision: put it in force

A backtest session - the weekly research-V2 run included - is research until promoted: it changes nothing the forecast
does. Promoting writes one row of ``analytics.promoted_forecast_spec`` (append-only); rolling back is promoting an
earlier session again. The next forecast run (every 30 minutes) uses the new spec; the forecasts already stored keep the
model version that made them.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.config import settings
from fbi.predictions import spec as forecast_spec

NEWEST = 8


def show(conn: psycopg.Connection[Any]) -> list[str]:
    """The spec in force, the promotions before it, and the newest completed sessions (the ones a person may promote)."""
    out: list[str] = []
    current = forecast_spec.promoted(conn)
    if current is None:
        out.append("No forecast spec is in force: the forecast writes nothing until one is promoted.")
    else:
        spec = current.spec
        out.append(f"IN FORCE since {current.promoted_at:%Y-%m-%d %H:%M} UTC: session {current.session_id} "
                   f"({current.evidence.get('session', '?')}), promoted by {current.promoted_by}")
        out.append(f"  why: {current.reason}")
        for kind, g in sorted(spec.goal.items()):
            out.append(f"  {kind}: xi={g.xi:g} penalty={g.penalty:g}")
        out.append(f"  training window {spec.cfg.history_days} days; feature models on "
                   f"{len(spec.competition_ids)} competitions")
    older = forecast_spec.history(conn)[1:]
    if older:
        out.append("")
        out.append("EARLIER:")
        for p in older:
            out.append(f"  #{p.id} {p.promoted_at:%Y-%m-%d %H:%M} session {p.session_id} by {p.promoted_by}: {p.reason}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, name, finished_at, n_targets FROM analytics.backtest_sessions WHERE status = 'completed' "
                    "AND protocol = 'walk_forward' ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT %s", (NEWEST,))
        sessions = cur.fetchall()
    out.append("")
    out.append(f"NEWEST COMPLETED SESSIONS (research until promoted; the {NEWEST} newest):")
    for s in sessions:
        mark = "*" if current is not None and current.session_id == s["id"] else " "
        out.append(f" {mark} {s['id']:>5}  {s['finished_at']:%Y-%m-%d %H:%M}  {s['name']}  ({s['n_targets']} matches)")
    return out


def promote_command(conn: psycopg.Connection[Any], *, session: int, reason: str, by: str | None,
                    confirm: bool) -> tuple[int, list[str]]:
    """(exit code, lines). Without ``confirm`` nothing is written: the lines say what would change. The caller owns the
    transaction (``main`` commits when the code is 0 and rolls back otherwise): nothing here commits, so a refusal cannot
    undo what the caller had done before asking."""
    try:
        forecast_spec.check_reason("owner", reason)
        if not confirm:
            p = forecast_spec.plan(conn, session)
            changed = not p.already_in_force
            lines = [f"DRY RUN - session {session} ({p.evidence['session']}) would "
                     f"{'change' if changed else 'not change'} the spec in force:"]
            lines += [f"  {c}" for c in (p.changes or ["nothing: it is already in force"])]
            lines.append("Nothing was written. Add --by NAME --confirm to put it in force.")
            return 0, lines
        if not by:
            return 2, ["--confirm needs --by NAME: a promotion is a person's decision"]
        result = forecast_spec.promote(conn, session, by="owner", reason=reason, who=by)
    except (LookupError, PermissionError, ValueError) as exc:
        return 3, [f"refused: {exc}"]
    if not result.changed:
        return 0, [f"Session {session} is already in force: nothing written."]
    lines = [f"Session {session} is in force (promotion #{result.promotion.id}, by {by}):"]
    lines += [f"  {c}" for c in result.changes]
    lines.append("The next forecast run uses it.")
    return 0, lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "promote"))
    ap.add_argument("--session", type=int, help="the backtest session to put in force (promote)")
    ap.add_argument("--reason", help="why, in a sentence a person can look back on (promote)")
    ap.add_argument("--by", help="who decides (promote --confirm)")
    ap.add_argument("--confirm", action="store_true", help="write the promotion; without it, a dry run")
    args = ap.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "show":
            print("\n".join(show(conn)))
            return 0
        if args.session is None or not args.reason:
            print("promote needs --session ID and --reason TEXT", file=sys.stderr)
            return 2
        code, lines = promote_command(conn, session=args.session, reason=args.reason, by=args.by, confirm=args.confirm)
        if code == 0:
            conn.commit()  # the promotion, when there was one (a dry run wrote nothing)
        else:
            conn.rollback()  # a refusal leaves no trace, and the advisory lock goes with the transaction
    print("\n".join(lines), file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
