"""The deterministic protocol of the Council v2 in shadow (``council-protocol-v1``, IA-012). Read-only.

    python -m scripts.ia_council_v2 show --fixture 1234                         # as of now (or the kick-off, if it is earlier)
    python -m scripts.ia_council_v2 show --fixture 1234 --at 2026-11-06T18:00:00+00:00 --json
    python -m scripts.ia_council_v2 day --day 2026-11-06 [--at ...] [--json]     # every match of a Bogotá day with a shadow pass

``show`` deliberates one match: the positions of the specialists on each selection with their weights, the contradictions (agent against
agent, against the model, against the market, and what the model or the market already knew), whether ONE research round is warranted and
on which topics, the ``ctx-adj-v1`` adjustment the deterministic layer would propose without the judge, and the judge's actual verdict and
the agreement when the shadow has one. ``day`` counts, over a day, the contradictions by kind, the rounds that would be requested and the
agreement of the baseline with each judge. Nothing is written and no model is called. Exit status: 0 a report, 2 it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from fbi.council import protocol

COMMANDS = ("show", "day")
OK, CANNOT = 0, 2


def parse_at(text: str | None) -> datetime:
    if text is None:
        return datetime.now(UTC)
    try:
        at = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a moment (ISO 8601 with its zone)") from exc
    if at.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone")
    return at


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_council_v2", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--fixture", type=int, help="the match (show)")
    ap.add_argument("--day", help="the Bogotá day, YYYY-MM-DD (day)")
    ap.add_argument("--at", help="the moment of knowledge (default: now); a match is never read past its kick-off")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def show(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime) -> tuple[dict[str, Any], int]:
    d = protocol.deliberate(conn, fixture_id, at=at)
    if d.status == "unknown_fixture":
        return {"error": f"fixture {fixture_id} is unknown"}, CANNOT
    if d.kickoff_at is not None and at >= d.kickoff_at:
        d = protocol.deliberate(conn, fixture_id, at=d.kickoff_at - timedelta(microseconds=1))
    return d.as_json(), OK


def day(conn: psycopg.Connection[Any], which: date, *, at: datetime) -> tuple[dict[str, Any], int]:
    return protocol.day_report(conn, which, at=at), OK


def render_show(doc: dict[str, Any]) -> str:
    lines = [f"{doc['version']} (shadow) · fixture {doc['fixture_id']} · as of {doc['at']} · {doc['status']}"]
    if doc["pass"]:
        p = doc["pass"]
        lines.append(f"pass #{p['match_run_id']} {p['pass_kind']} known {p['known_at']} · kick-off {doc['kickoff_at']}")
    for x in doc["weights"]:
        lines.append(f"  weight {x['agent']}@{x['agent_version']} {x['family']}: {x['weight']} (promoted {x['promoted']}, "
                     f"{x['hits']}/{x['hits'] + x['misses']} hits, shrunk {x['shrunk_precision']})")
    for s in doc["selections"]:
        b = s["baseline"]
        lines.append(f"\n{s['candidate']} {s['market_key']} {s['selection']} {s['line']} ({s['family']}) · edge {s['model']['edge']} · "
                     f"ev {s['model']['ev']} · contra-v1 {','.join(s['contra_v1']) or '-'} · market {s['market']['status']} "
                     f"{s['market']['movement_points']}")
        for p in s["positions"]:
            lines.append(f"  {p['agent']}@{p['agent_version']} {p['stance']} ({','.join(p['drivers']) or '-'}) w={p['weight']} "
                         f"novelty={p['novelty']} run #{p['run_id']}")
        for f in s["findings"]:
            lines.append(f"  {f['code']} {f['kind']}{' MATERIAL' if f['material'] else ''} {'+'.join(f['agents'])} runs {f['run_ids']}")
        lines.append(f"  research: {'warranted' if s['research']['warranted'] else 'no'} ({','.join(s['research']['reasons'])})")
        lines.append(f"  baseline: {b['adjustment']['verdict']} ({b['word']}, score {b['score']}, heard {b['weight_heard']}; "
                     f"{','.join(b['reasons'])})")
        for a in s["agreement"]:
            judge = s["judges"].get(a["engine"])
            lines.append(f"  judge {a['engine']}: {judge['verdict'] if judge else '-'} · {a['status']}"
                         + (f" · verdict {a['verdict_agrees']} · effect {a['effect_agrees']}" if a["status"] == "compared" else ""))
    r = doc["research_round"]
    if r:
        lines.append(f"\nresearch round: {'REQUESTED ' + ','.join(r['topics']) + ' for ' + ','.join(r['candidates']) if r['requested'] else 'no'}"
                     f" ({','.join(r['reasons'])}; {r['minutes_to_kickoff']} min to kick-off)")
    for problem in doc["problems"]:
        lines.append(f"problem: {problem}")
    return "\n".join(lines) + "\n"


def render_day(doc: dict[str, Any]) -> str:
    c = doc["contradictions"]
    lines = [f"{doc['version']} (shadow) · day {doc['day']} · as of {doc['at']}",
             f"fixtures {doc['fixtures']} · deliberated {doc['deliberated']} · selections {doc['selections']} · {doc['statuses']}",
             "contradictions by kind: " + ", ".join(f"{k} {v} ({c['material_by_kind'][k]} material)" for k, v in c["by_kind"].items()),
             "by code: " + ", ".join(f"{k} {v}" for k, v in c["by_code"].items()),
             f"research rounds requested: {doc['research_rounds']['requested']} · topics {doc['research_rounds']['topics']}",
             "baseline: " + ", ".join(f"{k} {v}" for k, v in doc["baseline"].items())]
    for engine, a in doc["agreement"].items():
        lines.append(f"agreement with {engine}: compared {a['compared']} of {a['selections']} · verdict {a['verdict_agrees']} "
                     f"({a['verdict_rate']}) · effect {a['effect_agrees']} ({a['effect_rate']}) · no judge {a['no_judge']} · "
                     f"judge SIN_COUNCIL {a['judge_sin_council']} · baseline SIN_COUNCIL {a['baseline_sin_council']}")
    if doc["problems"]:
        lines.append(f"problems: {doc['problems']}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        at = parse_at(args.at)
        which = date.fromisoformat(args.day) if args.command == "day" and args.day else None
    except ValueError as exc:
        ap.error(str(exc))
    if args.command == "show" and args.fixture is None:
        ap.error("show needs --fixture")
    if args.command == "day" and which is None:
        ap.error("day needs --day YYYY-MM-DD")
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        if args.command == "show":
            doc, code = show(conn, int(args.fixture), at=at)
        else:
            assert which is not None
            doc, code = day(conn, which, at=at)
    if code == CANNOT:
        sys.stderr.write(f"{doc['error']}\n")
        return code
    if args.as_json:
        sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(render_show(doc) if args.command == "show" else render_day(doc))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
