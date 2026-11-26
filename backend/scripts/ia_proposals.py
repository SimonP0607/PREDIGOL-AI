"""Controlled learning (IA-139, AD-K07): the register of proposals and the owner's signatures, from the command line.

    python -m scripts.ia_proposals list                                   # every proposal and its state (writes nothing)
    python -m scripts.ia_proposals show --id 4                            # one proposal, its evidence and the hash to sign
    python -m scripts.ia_proposals board --from 2026-11-01 --to 2026-12-01 # the promotions board-v1 supports (writes nothing)
    python -m scripts.ia_proposals board ... --write                      # append them (proposed_by = system; nothing is applied)
    python -m scripts.ia_proposals drafts [--write]                       # the retirements of AD-K06, parity pending
    python -m scripts.ia_proposals verdicts [--write]                     # the proposals the experiments' verdicts of success support (RP-8.4)
    python -m scripts.ia_proposals sign --id 4 --hash <sha256> --signature "Firmo..." --confirm-owner      # THE OWNER'S ACTION
    python -m scripts.ia_proposals reject --id 4 --hash <sha256> --signature "Rechazo..." --confirm-owner  # THE OWNER'S ACTION
    python -m scripts.ia_proposals record --id 4 --as aplicada --note "..." --confirm-owner                # after the owner applied it
    python -m scripts.ia_proposals record --id 4 --as revertida --note "..." --confirm-owner               # after taking it back

Nothing here changes a switch, a threshold, a weight or a model: a signed change takes effect only when the owner turns on its new version,
and ``record`` says that it did. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 done, 1 refused by the rules (nothing written), 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from typing import Any

import psycopg

from fbi.core.version import code_version
from fbi.proposals import REJECTED, SIGNED, Row, from_board, from_verdicts, problems
from fbi.proposals import store as register
from fbi.proposals.drafts import RETIREMENTS

COMMANDS = ("list", "show", "board", "drafts", "verdicts", "sign", "reject", "record")
OWNER = ("sign", "reject", "record")
WRITES = ("board", "drafts", "verdicts", *OWNER)
OK, REFUSED, USAGE = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_proposals", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--id", type=int, dest="proposal_id")
    ap.add_argument("--hash", dest="seen_hash", help="sign/reject: the evidence hash shown by `show`")
    ap.add_argument("--signature", help="sign/reject: the owner's words")
    ap.add_argument("--as", dest="record_as", choices=("aplicada", "revertida"))
    ap.add_argument("--note", help="record: what was done (10 to 600 characters)")
    ap.add_argument("--from", dest="start", type=date.fromisoformat)
    ap.add_argument("--to", dest="end", type=date.fromisoformat)
    ap.add_argument("--confirm-owner", action="store_true", help="sign/reject/record: I am the owner")
    ap.add_argument("--write", action="store_true", help="board/drafts: append (without it, only the plan is printed)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _row(r: Row) -> dict[str, Any]:
    p = r.proposal
    return {"id": r.id, "kind": p.kind, "target": p.target, "from": p.current_version, "to": p.proposed_version, "rollback_to": p.rollback_to,
            "status": r.status, "proposed_by": p.proposed_by, "reason": p.reason, "evidence_hash": p.hash}


VERDICTS_SQL = """
SELECT id, experiment, protocol_version, protocol_fingerprint, verdict, n, mean, low, high, adjusted_p, thresholds, population, computed_at
  FROM analytics.experiment_verdicts_latest ORDER BY id
"""


def _verdict_rows(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(VERDICTS_SQL)
        return list(cur.fetchall())


def _verdicts_with_a_proposal(conn: psycopg.Connection[Any]) -> set[int]:
    """The ids of the verdicts that already carry a proposal, wherever it stands (the plan's indicator: successes without a proposal = 0)."""
    return {int(ref["id"]) for r in register.rows(conn, limit=10_000) for ref in r.proposal.evidence_refs
            if ref.get("table") == "analytics.experiment_verdicts" and isinstance(ref.get("id"), int)}


def run(conn: psycopg.Connection[Any], args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "list":
        return {"proposals": [_row(r) for r in register.rows(conn)], **register.summary(conn)}, OK
    if args.command == "show":
        found = register.rows(conn, proposal_id=args.proposal_id, limit=1)
        if not found:
            return {"error": f"no proposal {args.proposal_id}"}, REFUSED
        return {**_row(found[0]), "change": found[0].proposal.change, "evidence": found[0].proposal.evidence,
                "evidence_refs": list(found[0].proposal.evidence_refs)}, OK
    if args.command in ("board", "drafts", "verdicts"):
        without: list[int] = []
        if args.command == "verdicts":
            drafted = from_verdicts(_verdict_rows(conn))
            have = _verdicts_with_a_proposal(conn)
            without = [p.evidence["verdict_id"] for p in drafted if p.evidence["verdict_id"] not in have]
        elif args.command == "board":
            from fbi.evaluation import views

            start = datetime.combine(args.start, time(), UTC)
            end = datetime.combine(args.end, time(), UTC)
            board = views.board(conn, start=start, end=end)
            drafted = from_board(board or {}, period={"from": args.start.isoformat(), "to": args.end.isoformat()})
        else:
            drafted = list(RETIREMENTS)
        plan = [{"kind": p.kind, "target": p.target, "to": p.proposed_version, "problems": problems(p), "evidence_hash": p.hash}
                for p in drafted]
        extra = {"successes_without_a_proposal": len(without)} if args.command == "verdicts" else {}
        if not args.write:
            return {"plan": plan, "written": [], **extra}, OK
        written = [register.register(conn, p, code_version=code_version()) for p in drafted if not problems(p)]
        conn.commit()
        return {"plan": plan, "written": written, **extra}, OK
    try:
        if args.command in ("sign", "reject"):
            sid = register.sign(conn, args.proposal_id, decision=SIGNED if args.command == "sign" else REJECTED,
                                signature=args.signature or "", seen_hash=args.seen_hash or "")
            conn.commit()
            return {"signature_id": sid}, OK
        aid = register.record(conn, args.proposal_id, kind=args.record_as, note=args.note or "")
        conn.commit()
        return {"application_id": aid}, OK
    except (ValueError, psycopg.Error) as exc:
        conn.rollback()
        return {"error": str(exc)}, REFUSED


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.command in OWNER and not args.confirm_owner:
        ap.error(f"{args.command} is the owner's action: --confirm-owner")
    if args.command in OWNER and args.proposal_id is None:
        ap.error(f"{args.command} needs --id")
    if args.command == "record" and args.record_as is None:
        ap.error("record needs --as aplicada|revertida")
    if args.command == "board" and (args.start is None or args.end is None):
        ap.error("board needs --from and --to")
    from fbi.core.config import settings as platform

    writes = args.command in OWNER or (args.write and args.command in WRITES)
    options = "-c TimeZone=UTC" if writes else "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=60000"
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=options) as conn:
        doc, code = run(conn, args)
        conn.rollback()
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
