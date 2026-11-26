"""The triage of the hypotheses waiting for the owner's decision (RP-8.2, ``triage-v1``).

    python -m scripts.hypothesis_triage propose                 # reading only: groups by variable and direction, a destination and a reason for each
    python -m scripts.hypothesis_triage propose --all           # also one line per hypothesis
    python -m scripts.hypothesis_triage propose --out plan.json # keep the proposal (with its fingerprint) for the owner to look at
    python -m scripts.hypothesis_triage status                  # how many proposed hypotheses carry no triage (the plan's limit is 20)
    python -m scripts.hypothesis_triage apply --plan plan.json --fingerprint <hex> --user-id <owner id> --confirm-owner

``propose`` and ``status`` read through a connection that cannot write. ``apply`` is the OWNER's decision in block (D5): it writes only the proposal he was shown
(the fingerprint must be the one printed with it), only while every hypothesis in it is still waiting, approves the experiments, archives with the reason and
notes the ones kept. 0 requests to the provider, 0 AI; nothing here reaches a model, a forecast, a pick or a threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import psycopg

from fbi.core.clock import now as clock_now
from fbi.core.config import settings
from fbi.research import triage

READ_ONLY = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=60000"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="hypothesis_triage", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("command", choices=("propose", "status", "apply"))
    ap.add_argument("--all", action="store_true", dest="every_one", help="one line per hypothesis (propose)")
    ap.add_argument("--out", help="write the proposal, with its fingerprint, to this file (propose)")
    ap.add_argument("--plan", help="the proposal file (apply)")
    ap.add_argument("--fingerprint", help="the fingerprint printed with the proposal the owner was shown (apply)")
    ap.add_argument("--user-id", type=int, help="the owner's user id (apply)")
    ap.add_argument("--confirm-owner", action="store_true", help="the owner's confirmation (apply)")
    ap.add_argument("--max-experiments", type=int, default=triage.MAX_EXPERIMENTS)
    return ap


def _load(path: str) -> list[triage.Decision]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [triage.Decision(**d) for d in raw["decisions"]]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in ("propose", "status"):
        with psycopg.connect(settings.database.psycopg_url, options=READ_ONLY) as conn:
            if args.command == "status":
                n = triage.untriaged(conn)
                sys.stdout.write(f"Hipótesis en espera sin triage: {n} (límite permanente: {triage.UNTRIAGED_LIMIT}){' — SUPERADO' if n > triage.UNTRIAGED_LIMIT else ''}\n")
                return 0
            items = triage.read(conn)
        decisions = triage.propose(items, max_experiments=args.max_experiments)
        sys.stdout.write("\n".join(triage.lines(decisions, {i.id: i for i in items} if args.every_one else None)) + "\n")
        if args.out:
            from dataclasses import asdict

            Path(args.out).write_text(json.dumps({"version": triage.VERSION, "fingerprint": triage.plan_fingerprint(decisions),
                                                  "decisions": [asdict(d) for d in decisions]}, ensure_ascii=False, indent=1), encoding="utf-8")
        return 0
    if not (args.plan and args.fingerprint and args.user_id):
        sys.stderr.write("apply needs --plan, --fingerprint and --user-id\n")
        return 2
    decisions = _load(args.plan)
    with psycopg.connect(settings.database.psycopg_url) as conn:
        try:
            done = triage.apply(conn, decisions, claimed_fingerprint=args.fingerprint, user_id=args.user_id, at=clock_now(), confirmed_by_owner=args.confirm_owner)
        except triage.PlanRefusedError as exc:
            conn.rollback()
            sys.stderr.write(f"refused: {exc}\n")
            return 3
        conn.commit()
    sys.stdout.write("Aplicado: " + ", ".join(f"{k} {v}" for k, v in done.items()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
