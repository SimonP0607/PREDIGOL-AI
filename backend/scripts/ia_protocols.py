"""The owner's signatures of the preregistered protocols (IA-143, AD-K07), from the command line: ``ai.protocol_signatures``.

    python -m scripts.ia_protocols list                         # every protocol, its fingerprint of now and whether it is signed (writes nothing)
    python -m scripts.ia_protocols show --key AD-K02            # one protocol, whole, with the fingerprint to sign and the exact command
    python -m scripts.ia_protocols sign --key AD-K02 --fingerprint <sha256> --reason "..."                   # preview (writes nothing)
    python -m scripts.ia_protocols sign --key AD-K02 --fingerprint <sha256> --reason "..." --confirm-owner   # THE OWNER'S ACTION

The catalog is ``fbi.protosign.catalog``: the LAB protocols of ``fbi.research.protocol`` and the own records (the chronicle's AD-F04,
AD-F05, AD-F06 and the retirement of ``review-v2``, AD-D11). ``sign`` writes ONE row (``decided_by = 'owner'``) for the fingerprint the code has NOW: a fingerprint that is not the one in force
is refused (the protocol changed, or it was copied wrong - look again with ``show``), and a fingerprint already signed writes nothing twice
and says which row signs it. Without ``--confirm-owner`` (or with ``--dry-run``) it is a preview on a read-only connection.

A SIGNATURE TURNS NOTHING ON: no verdict switches on, promotes or changes a threshold because a protocol is signed. AD-A03 (battery-v4) and
AD-C09 (the extraction protocol) also keep their own signature in ``ai.feature_gates`` (``scripts/ia_battery_v4.py sign``,
``scripts/ia_page_bank.py sign``), the one their measurement asks for; ``list`` and ``show`` say which command signs it and which shows it,
and this register does not replace it. ``--dsn`` overrides the database (the worker's own by default).

Exit status: 0 done (``sign``: written now, or already on file for that fingerprint), 1 refused by the rules (nothing written), 2 usage error,
3 preview (nothing written, waiting for ``--confirm-owner``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any, Final

import psycopg

from fbi.core.version import code_version
from fbi.protosign import NOTICE, VERSION, catalog, current, sign_problems
from fbi.protosign import store as register

COMMANDS: Final = ("list", "show", "sign")
OK, REFUSED, USAGE, PREVIEW = 0, 1, 2, 3
READ_ONLY: Final = "-c TimeZone=UTC -c default_transaction_read_only=on -c statement_timeout=60000"
WRITE: Final = "-c TimeZone=UTC -c statement_timeout=60000"
OWN_GATE: Final[dict[str, dict[str, str]]] = {
    "AD-A03": {"sign": 'python -m scripts.ia_battery_v4 sign --invalid-max 0 --reason "..." --confirm-owner',
               "status": "python -m scripts.ia_battery_v4 status"},
    "AD-C09": {"sign": 'python -m scripts.ia_page_bank sign --reason "..." --confirm-owner', "status": "python -m scripts.ia_page_bank status"},
}
"""The protocols that also keep a signature of their own in ``ai.feature_gates`` (the one their measurement asks for). This command does not
read it (its readers are held by their own tests); it says where it is."""


def sign_command(key: str, fingerprint: str) -> str:
    return f'python -m scripts.ia_protocols sign --key {key} --fingerprint {fingerprint} --reason "..." --confirm-owner'


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {"id": int(r["id"]), "fingerprint": r["fingerprint"], "version": r["protocol_version"], "signed_at": r["signed_at"],
            "reason": r["reason"], "code_version": r["code_version"]}


def run(conn: psycopg.Connection[Any], args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.command == "list":
        items = []
        for i in register.overview(conn):
            item = {**i, "signature": _row(i["signature"])}
            if not i["signed_by_owner"]:
                item["sign"] = sign_command(str(i["key"]), str(i["fingerprint"]))
            if i["key"] in OWN_GATE:
                item["own_gate_signature"] = dict(OWN_GATE[str(i["key"])])
            items.append(item)
        signed = sum(1 for i in items if i["signed_by_owner"])
        return {"register": VERSION, "table_exists": register.exists(conn), "signed": signed, "pending": len(items) - signed,
                "protocols": items, "notice": NOTICE}, OK
    try:
        s = current(args.key)
    except LookupError as exc:
        return {"error": f"{exc} (claves: {', '.join(catalog())})"}, REFUSED
    if args.command == "show":
        rows = register.signatures(conn, [s.key])
        found = register.in_force_of(s, rows)
        doc = {**s.head(), "protocol": dict(s.body), "signed_by_owner": found is not None, "signature": _row(found),
               "history": [_row(r) for r in rows], "sign": None if found is not None else sign_command(s.key, s.fingerprint),
               "notice": NOTICE}
        if s.key in OWN_GATE:
            doc["own_gate_signature"] = dict(OWN_GATE[s.key])
        return doc, OK
    problems = sign_problems(s.key, args.fingerprint, args.reason)
    if problems:
        return {"error": "; ".join(problems) + " (nothing was written)"}, REFUSED
    kept = register.in_force(conn, s.key)
    if not args.confirm_owner or args.dry_run:
        lines = ["VISTA PREVIA (sin --confirm-owner): no se ha escrito nada.",
                 f"Se firmaría {s.key} ({s.version}), huella {s.fingerprint[:12]}…, motivo: «{args.reason.strip()}».",
                 "La firma no enciende nada." if kept is None else f"Esa huella ya está firmada (fila {int(kept['id'])}): no se escribiría nada."]
        return {"preview": True, "written": False, "would_write": {"table": register.TABLE, "protocol_key": s.key, "protocol_version": s.version,
                                                                  "framework": s.framework, "fingerprint": s.fingerprint,
                                                                  "reason": args.reason.strip(), "decided_by": "owner"},
                "already": _row(kept), "lines": lines}, PREVIEW
    try:
        out = register.sign(conn, s.key, fingerprint=args.fingerprint, reason=args.reason, code_version=code_version())
        conn.commit()
    except (ValueError, psycopg.Error) as exc:
        conn.rollback()
        return {"error": f"{exc} (nothing was written)"}, REFUSED
    note = "firmado" if out["written"] else "ya estaba firmado para esta huella: no se ha escrito nada"
    return {"preview": False, **out, "protocol_key": s.key, "fingerprint": s.fingerprint, "note": note, "notice": NOTICE}, OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_protocols", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--key", help="show/sign: the protocol's key (AD-K02, INT-A02, AD-F06...)")
    ap.add_argument("--fingerprint", help="sign: the sha256 that `show` gives (the one in force)")
    ap.add_argument("--reason", help="sign: why, in the owner's words (10 to 600 characters)")
    ap.add_argument("--confirm-owner", action="store_true", help="sign: I am the owner and I sign this (without it nothing is written)")
    ap.add_argument("--dry-run", action="store_true", help="sign: show what would be written and write nothing (implied without --confirm-owner)")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return USAGE if exc.code not in (0, None) else OK
    missing = [] if args.command == "list" else ["--key"] if args.key is None else []
    if args.command == "sign":
        missing += [f for f, v in (("--fingerprint", args.fingerprint), ("--reason", args.reason)) if v is None]
    if missing:
        sys.stderr.write(f"{args.command} needs {', '.join(missing)}\n")
        return USAGE
    if args.command != "sign" and (args.fingerprint or args.reason or args.confirm_owner):
        sys.stderr.write("--fingerprint, --reason and --confirm-owner belong to sign\n")
        return USAGE
    from fbi.core.config import settings as platform

    writes = args.command == "sign" and args.confirm_owner and not args.dry_run
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options=WRITE if writes else READ_ONLY) as conn:
        doc, code = run(conn, args)
        conn.rollback()
    sys.stdout.write(json.dumps(doc, indent=1, default=str, ensure_ascii=False) + "\n")
    if "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
