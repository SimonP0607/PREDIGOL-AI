"""The Evidence Engine in shadow (``evidence-engine-v1``, IA-012), from the command line: what is known about a match, claim by claim.

    python -m scripts.ia_evidence show --fixture 123
    python -m scripts.ia_evidence show --fixture 123 --at 2026-11-06T18:00:00Z --json
    python -m scripts.ia_evidence day --day 2026-11-06 [--at ...] [--json]

``show`` prints the claims of one match as of ``--at`` (default: now), strictly: each with its subject, topic and assertion, its status on
the ladder RUMOR -> REPORTADO -> CONFIRMADO -> OFICIAL, its computed confidence (and the net of its contradictions), its window of validity
(expired or not) and its sources with their tier (A-D) and credibility (learned or the tier's prior); then the contradictions (claim vs
claim, claim vs provider, contra-v1's C07). ``day`` does it for every match that kicks off that day (Bogotá time) and prints the counts by
tier, status and topic, the contradictions, the expired claims, and how many items are v1's evidences and how many research v2's claims.

Read-only: the connection refuses writes, nothing is asked of a provider or a model, and nothing here is read by a decision, a pick, a page
or a user (``fbi.evidence``). Exit 0 with a report, 2 when it cannot run (an unknown fixture, a bad argument).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

import psycopg

from fbi.evidence import engine

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


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_evidence", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--fixture", type=int, help="show: the fixture id")
    ap.add_argument("--day", help="day: the day of the kick-offs, YYYY-MM-DD (Bogotá)")
    ap.add_argument("--at", help="the moment, ISO with a zone (default: now)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def show(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> tuple[dict[str, Any], int]:
    report = engine.evidence_for(conn, fixture_id, at=at)
    if report is None:
        return {"error": f"fixture {fixture_id} is unknown"}, CANNOT
    return report.as_json(), OK


def day(conn: psycopg.Connection[Any], the_day: date, *, at: datetime) -> tuple[dict[str, Any], int]:
    return engine.day_summary(conn, the_day, at=at), OK


def render_counts(c: dict[str, Any]) -> list[str]:
    def row(d: dict[str, int]) -> str:
        return ", ".join(f"{k} {v}" for k, v in d.items()) or "-"

    g = c["generations"]
    return [f"  items {c['items']} (v1 evidences {g['v1_evidences']}, v2 claims {g['v2_claims']}); claims {c['claims']}, "
            f"expired {c['expired']}",
            f"  by tier    {row(c['by_tier'])}",
            f"  by status  {row(c['by_status'])} (live claims)",
            f"  by topic   {row(c['by_topic'])}",
            f"  contradictions {row(c['contradictions'])}"]


def render_show(d: dict[str, Any]) -> str:
    lines = [f"{d['version']} (shadow, rules {d['rules']}) fixture {d['fixture_id']} {d['home']['name']} - {d['away']['name']}  "
             f"kick-off {d['kickoff_at']}  as of {d['at']}", *render_counts(d["counts"])]
    for c in d["claims"]:
        v = c["validity"]
        flag = " EXPIRED" if v["expired"] else ""
        lines.append(f"  [{c['status']}{flag}] {c['subject']} {c['topic']}={c['assertion']} ({c['side']})  confidence {c['confidence']:.3f}"
                     f" net {c['confidence_net']:.3f}  valid until {v['until']}"
                     + (f"  contradicts {','.join(c['contradictions'])}" if c["contradictions"] else ""))
        for s in c["sources"]:
            cred = s["credibility"]
            lines.append(f"      E:{s['evidence_id']} {s['generation']} {s['tier']} {s['outlet']} ({s['tier_reason']}) cred {cred['value']:.2f}"
                         f" {cred['basis']}" + (f" {cred['corroborated']}/{cred['resolved']}" if cred["basis"] == "learned" else "")
                         + ("" if s["live"] else " expired"))
    for x in d["contradictions"]:
        lines.append(f"  ! {x['rule']} {x['subject']} {' vs '.join(x['claims'])} E:{','.join(str(i) for i in x['evidence_ids'])}")
    return "\n".join(lines)


def render_day(d: dict[str, Any]) -> str:
    lines = [f"{d['version']} (shadow, rules {d['rules']}) day {d['day']} as of {d['at']}: {d['fixtures']} matches, "
             f"{d['with_evidence']} with evidence", *render_counts(d["counts"])]
    for m in d["matches"]:
        g = m["generations"]
        lines.append(f"  {m['fixture_id']} {m['home']} - {m['away']}: claims {m['claims']} (expired {m['expired']}), "
                     f"v1 {g['v1_evidences']} / v2 {g['v2_claims']}, contradictions {sum(m['contradictions'].values())}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        at = parse_at(args.at) if args.at else datetime.now(UTC)
        if args.command == "show" and args.fixture is None:
            ap.error("show needs --fixture")
        if args.command == "day":
            if not args.day:
                ap.error("day needs --day")
            the_day = date.fromisoformat(args.day)
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        doc, code = show(conn, args.fixture, at=at) if args.command == "show" else day(conn, the_day, at=at)
    if "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
        return code
    out = json.dumps(doc, indent=1, default=str, ensure_ascii=False) if args.as_json else \
        (render_show(doc) if args.command == "show" else render_day(doc))
    sys.stdout.write(out + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
