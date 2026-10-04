"""Research V2 (GATE F-G): every model family against the market, on the validated history.

    python -m scripts.research_v2              # dry run: the report printed and saved, nothing stored
    python -m scripts.research_v2 --apply      # store the session, one experiment per model with its role,
                                               # the market baselines, the prospective evaluation and the
                                               # pick audit (refuses on uncommitted code)
    python -m scripts.research_v2 --audit-only # E0 and the prospective evaluation only (seconds, read only)

Competitions: the domestic leagues whose validation AND test seasons are MODEL_READY (results,
integrity, Elo and market prices; ``analytics.competition_data_scores``) - the only seasons
with prices to judge a model against. Zero provider requests. See ``fbi.research.v2``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import psycopg

from fbi.backtesting.walkforward import WalkForwardConfig
from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.research.evolution import learn_from_v2
from fbi.research.loop import frozen, model_ready
from fbi.research.v2 import run_v2
from fbi.research.v2_record import record_v2
from fbi.research.v2_report import report_json, report_markdown

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "data" / "reports"


def dirty() -> list[str]:
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", "src", "scripts", "migrations"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line for line in out.splitlines() if line.strip()]


def audit_only() -> int:
    from fbi.research.pick_audit import audit_picks
    from fbi.research.prospective import evaluate_prospective

    at = now()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        audit = audit_picks(conn, at=at)
        prospective = evaluate_prospective(conn, until=at)
    print(json.dumps({"audit": audit.as_json(), "prospective": prospective.as_json()}, indent=2, default=str))
    return 0


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="research_v2", description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validation-season", type=int, default=2023)
    parser.add_argument("--test-season", type=int, default=2024)
    parser.add_argument("--refit-days", type=int, default=1)
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.audit_only:
        return audit_only()
    if args.apply and dirty():
        print("refusing --apply: uncommitted changes under src/, scripts/ or migrations/", file=sys.stderr)
        return 2
    if args.apply and (why := frozen()):
        print(f"refusing --apply: research is frozen ({why})", file=sys.stderr)
        return 3
    version = code_version()
    at = now()
    stamp = at.strftime("%Y%m%dT%H%M%SZ")
    name = f"research-v2-{args.test_season}-{stamp}"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        comps = model_ready(conn, args.validation_season, args.test_season)
        if not comps:
            print("no competition has MODEL_READY validation and test seasons", file=sys.stderr)
            return 1
        print(f"competitions: {', '.join(n for _, n in comps)}", flush=True)
        cfg = WalkForwardConfig(competition_ids=tuple(i for i, _ in comps), test_season=args.test_season,
                                validation_season=args.validation_season, refit_days=args.refit_days)
        ledger = RunLedger(conn) if args.apply else None
        run_id = ledger.open("research_v2", params={"name": name}) if ledger else None
        counters = RunCounters()
        try:
            result = run_v2(conn, cfg, comps, at=at, progress=lambda m: print(m, flush=True))
            body = report_json(result)
            json_path = REPORT_DIR / f"{name}.json"
            md_path = REPORT_DIR / f"{name}.md"
            json_path.write_text(json.dumps(body, indent=2, default=str))
            md_path.write_text(report_markdown(result, title=f"Research V2 - {at:%d %b %Y}"))
            print(f"report: {md_path}", flush=True)
            if args.apply:
                written = record_v2(conn, result, name=name, code_version=version, report_path=json_path)
                learned = learn_from_v2(conn, run=name, champion=result.champion.key,
                                        roles={m: (r.role, r.reason) for m, r in result.roles.items()}, at=at)
                conn.commit()
                written["proposals"] = learned.proposals
                counters.rows_inserted = len(written.get("models", {}))
                print(json.dumps(written, indent=2, default=str), flush=True)
            else:
                print("dry run - nothing stored (use --apply)", flush=True)
        finally:
            if ledger is not None and run_id is not None:
                ledger.close(run_id, counters, notes=f"{name}, 0 requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
