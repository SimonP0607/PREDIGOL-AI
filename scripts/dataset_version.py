"""Dataset versions - what a model may learn from (fbi.datasets.versions).

    python -m scripts.dataset_version show                       # every version, its status and gates
    python -m scripts.dataset_version build [--name DATASET_V2]  # counts + gates -> CANDIDATE or VALIDATED
    python -m scripts.dataset_version promote --name DATASET_V2 --by OWNER --confirm
                                                                 # a person: VALIDATED -> MODEL_READY

``build`` never promotes. ``promote`` refuses while research is frozen or when the version is not VALIDATED.
A build is also a run (audit.truth_v2_runs, kind datasets) with its report in data/truth/<stamp>-datasets/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.datasets.versions import CURRENT, build, promote
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")


def markdown(b: dict[str, object]) -> str:
    gates = b["gates"]
    assert isinstance(gates, list)
    lines = [f"# Dataset version {b['name']} - {b['status']}", "", "| Gate | Status | Detail |", "|---|---|---|"]
    lines += [f"| {g['key']} | **{g['status']}** | {g['detail']} |" for g in gates]
    lines += ["", "| Count | Rows |", "|---|---:|"]
    counts = b["counts"]
    assert isinstance(counts, dict)
    lines += [f"| {k} | {v:,} |" for k, v in counts.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "build", "promote"))
    ap.add_argument("--name", default=CURRENT)
    ap.add_argument("--by", help="who promotes (promote)")
    ap.add_argument("--confirm", action="store_true", help="required by promote")
    args = ap.parse_args(argv)
    at = now()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "show":
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT name, status, model_ready, created_at, promoted_at, counts, gates->'gates' AS gates, "
                            "notes FROM audit.dataset_versions ORDER BY created_at")
                print(json.dumps(cur.fetchall(), indent=1, default=str))
            return 0
        if args.command == "promote":
            if not (args.confirm and args.by):
                print("promote needs --by NAME and --confirm: it is a person's decision", file=sys.stderr)
                return 2
            try:
                promote(conn, args.name, by=args.by, at=at)
            except ValueError as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 3
            conn.commit()
            print(f"{args.name} is MODEL_READY")
            return 0
        conn.autocommit = True
        run = V2Run(conn, None, "datasets", at, params={"name": args.name})
        try:
            result = build(conn, name=args.name, at=at).as_dict()
        except ValueError as exc:
            run.finish({"error": str(exc)}, failed=True)
            print(f"refused: {exc}", file=sys.stderr)
            return 3
        folder = write_report(REPORTS, "datasets", at, result, markdown(result))
        run.finish({"name": result["name"], "status": result["status"],
                    "gates": {g["key"]: g["status"] for g in result["gates"]}}, report_dir=folder)
    print(markdown(result))
    print(f"report: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
