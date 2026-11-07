"""The market's signals in shadow (``market-signals-v1``, IA-011), from the command line: what the captured prices of a selection did.

    python -m scripts.ia_market_signals show --fixture 123 --market OU --selection Over --line 2.5
    python -m scripts.ia_market_signals show --fixture 123 --market 1X2 --selection Home --at 2026-11-06T18:00:00Z --json
    python -m scripts.ia_market_signals show --fixture 123 --market 1X2 --selection Home --p-model 0.55 --odds 2.10
    python -m scripts.ia_market_signals day --day 2026-11-06 --json

``show`` prints one selection's signals as of ``--at`` (default: now): opening and current fair probability and price, movement,
velocity, steam, dispersion, books, staleness, the side the market moved relative to the model, the sharp reference and - once the
match has kicked off - the CLV of the taken price. Without ``--p-model`` / ``--odds`` the newest decision of the selection known at
``--at`` gives them (``intel.decisions``, the pipeline's layer). ``day`` does it for every selection the decision layer saw for the
matches of that day (Bogotá time), each as of now (the pre-match series stops at kick-off), and adds the summary: how often the market moved against the model
before kick-off (with its denominator), the median movement and the steam count.

Read-only: the connection refuses writes, nothing is asked of a provider or a model, and nothing here is read by a decision, a pick, a
stake or a page (``fbi.market.signals``). Exit 0 with a report, 2 when it cannot run (an unknown fixture, a bad argument).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg

from fbi.market import signals as sig
from fbi.market.closing_reference import Key

COMMANDS = ("show", "day")
OK, CANNOT = 0, 2


def parse_at(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not an ISO instant") from exc
    if moment.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone: say Z or an offset")
    return moment


def parse_line(text: str) -> Decimal:
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{text!r} is not a line") from exc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_market_signals", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--fixture", type=int, help="show: the fixture id")
    ap.add_argument("--market", help="show: the market key (1X2, OU, BTTS, AH, DC)")
    ap.add_argument("--selection", help="show: the selection (Home, Over, Yes, 1X, ...)")
    ap.add_argument("--line", default="0", help="show: the line (default 0)")
    ap.add_argument("--at", help="show: the moment, ISO with a zone (default: now)")
    ap.add_argument("--p-model", type=float, dest="p_model", help="show: the model probability (default: the newest decision's)")
    ap.add_argument("--odds", type=float, help="show: the taken price for the CLV (default: the newest decision's)")
    ap.add_argument("--day", help="day: the day of the kick-offs, YYYY-MM-DD (Bogotá)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def show(conn: psycopg.Connection[Any], key: Key, *, at: datetime, p_model: float | None = None,
         odds: float | None = None) -> tuple[dict[str, Any], int]:
    decision: dict[str, Any] | None = None
    if p_model is None or odds is None:
        found = sig.decisions(conn, at=at, key=key)
        decision = found[0] if found else None
    if decision is not None:
        p_model = p_model if p_model is not None else decision["p_model"]
        odds = odds if odds is not None else decision["odds"]
    s = sig.read_signals(conn, key, at=at, p_model=p_model, taken_odds=odds)
    if s is None:
        return {"error": f"fixture {key[0]} is unknown"}, CANNOT
    doc = s.as_json()
    doc["decision"] = None if decision is None else {"id": int(decision["id"]), "known_at": decision["known_at"].isoformat(),
                                                     "state": decision["state"], "p_basis": decision["p_basis"]}
    return doc, OK


def day(conn: psycopg.Connection[Any], the_day: date, *, now: datetime) -> tuple[dict[str, Any], int]:
    from fbi.ai.calendar import day_bounds

    start, end = day_bounds(the_day)
    rows = sig.decisions(conn, at=now, start=start, end=end)
    found: list[sig.MarketSignals] = []
    items: list[dict[str, Any]] = []
    for r in rows:
        key: Key = (int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"]))
        # as of now: the pre-match series stops at kick-off by itself (effective_at), and the close is read after it
        s = sig.read_signals(conn, key, at=now, p_model=r["p_model"], taken_odds=r["odds"])
        if s is None:
            continue
        found.append(s)
        items.append(s.as_json() | {"decision": {"id": int(r["id"]), "known_at": r["known_at"].isoformat(), "state": r["state"],
                                                 "p_basis": r["p_basis"]}})
    return {"version": sig.VERSION, "shadow": True, "day": the_day.isoformat(), "at": now.isoformat(),
            "summary": sig.summarise(found).as_json(), "selections": items}, OK


def _pts(x: float | None) -> str:
    return "-" if x is None else f"{x:+.2f} pts"


def render_one(d: dict[str, Any]) -> str:
    lines = [f"{d['fixture_id']} {d['market_key']} {d['selection']} {d['line']}  as of {d['effective_at']}  [{d['status']}]"]
    o, c = d["opening"], d["current"]
    if o is not None and c is not None:
        lines.append(f"  opening  p {o['p_fair']:.4f} @ {o['odds']} (book {o['bookmaker_id']}) at {o['at']}")
        lines.append(f"  current  p {c['p_fair']:.4f} best {c['best_odds']} (book {c['best_bookmaker_id']}), "
                     f"{c['n_bookmakers']} books, dispersion {c['dispersion']}")
        lines.append(f"  movement {_pts(d['movement_points'])}  captures {d['n_captures']}  "
                     f"staleness {d['staleness_minutes']} min{' STALE' if d['stale'] else ''}")
        lines.append("  velocity " + ", ".join(f"{v['window_minutes'] // 60}h {_pts(v['delta_points'])}"
                                               + ("" if v["status"] == sig.OK else f" ({v['status']})") for v in d["velocity"]))
        lines.append(f"  steam    {len(d['steam_events'])} event(s)")
    lines.append(f"  model    p {d['p_model']} -> side {d['side']}")
    lines.append(f"  sharp    {d['sharp']['status']}")
    cl = d["closing"]
    lines.append(f"  closing  {cl['status']}" + ("" if cl["clv"] is None else f": CLV {cl['clv']:+.2%} ({cl['quality']})"))
    return "\n".join(lines)


def render(command: str, doc: dict[str, Any]) -> str:
    if "error" in doc:
        return doc["error"]
    if command == "show":
        return render_one(doc)
    s = doc["summary"]
    head = (f"{doc['version']} (shadow) day {doc['day']}: {s['selections']} selections, {s['priced']} priced; "
            f"market against the model {s['against']}/{s['sided']}"
            + ("" if s["against_share"] is None else f" ({s['against_share']:.0%})")
            + f"; median movement {_pts(s['median_movement_points'])}; steam in {s['with_steam']} ({s['steam_events']} events); "
              f"CLV n={s['clv_n']} median {s['clv_median']}")
    return "\n".join([head, *(render_one(i) for i in doc["selections"])])


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.command == "show":
            if args.fixture is None or not args.market or not args.selection:
                ap.error("show needs --fixture, --market and --selection")
            key: Key = (args.fixture, args.market, args.selection, parse_line(args.line))
            at = parse_at(args.at) if args.at else now
        else:
            if not args.day:
                ap.error("day needs --day")
            the_day = date.fromisoformat(args.day)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        if args.command == "show":
            doc, code = show(conn, key, at=at, p_model=args.p_model, odds=args.odds)
        else:
            doc, code = day(conn, the_day, now=now)
    out = json.dumps(doc, indent=1, default=str, ensure_ascii=False) if args.as_json else render(args.command, doc)
    sys.stdout.write(out + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
