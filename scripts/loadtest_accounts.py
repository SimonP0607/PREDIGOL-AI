"""Accounts for the load test of the server rehearsal (deploy/vps/bin/loadtest.py) - and their end.

    python -m scripts.loadtest_accounts create --count 200 --out /out/loadtest.txt --confirm
    python -m scripts.loadtest_accounts disable --confirm

`create` makes USER accounts loadtest-001@loadtest.predigol.local ... with ONE generated password, written to
--out (mode 0600: "email<TAB>password" per line) and nowhere else. Existing ones get that password again.
`disable` disables every account of that domain and ends its sessions. Nothing is ever deleted (the audit trail
keeps them). Both are dry runs without --confirm.

Only for the rehearsal, before the cut-over: the cut-over imports into an EMPTY database, so none of these
accounts reaches production.
Exit status: 0 done (or dry run), 1 refused.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from fbi.auth import store
from fbi.auth.db import write_connection
from fbi.auth.service import AuthError, create_user_unattended, set_password_unattended
from scripts.create_user import generated_password

DOMAIN = "loadtest.predigol.local"


def _email(n: int) -> str:
    return f"loadtest-{n:03d}@{DOMAIN}"


def cmd_create(args: argparse.Namespace) -> int:
    if not 1 <= args.count <= 1000:
        print("--count must be 1..1000", file=sys.stderr)
        return 1
    if not args.confirm:
        print(f"dry run: would create or reset {args.count} accounts {_email(1)} .. {_email(args.count)}")
        return 0
    password = generated_password(24)
    lines = []
    created = reset = 0
    for n in range(1, args.count + 1):
        email = _email(n)
        try:
            create_user_unattended(email=email, display_name=f"Load test {n:03d}", role="USER",
                                   password=password, language="es", timezone="America/Bogota")
            created += 1
        except AuthError as exc:
            if exc.code != "email_taken":
                raise
            set_password_unattended(email=email, password=password)
            reset += 1
        lines.append(f"{email}\t{password}\n")
    out: Path = args.out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.writelines(lines)
    os.chmod(out, 0o600)
    print(f"{created} created, {reset} reset; credentials in {out} (0600)")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        rows = [r for r in store.list_users(conn) if str(r["email"]).endswith("@" + DOMAIN)]
        if not args.confirm:
            print(f"dry run: would disable {len(rows)} accounts of {DOMAIN}")
            return 0
        ended = 0
        for r in rows:
            if r["status"] != "disabled":
                store.update_user(conn, int(r["id"]), {"status": "disabled"})
            ended += store.revoke_user_sessions(conn, int(r["id"]), "load_test_finished")
            store.record_event(conn, "user.disabled", target_user_id=r["id"],
                               detail={"by": "command_line", "reason": "load_test_finished"})
    print(f"{len(rows)} accounts of {DOMAIN} disabled, {ended} session(s) ended")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="loadtest_accounts", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create")
    p.add_argument("--count", type=int, default=200)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--confirm", action="store_true")
    p = sub.add_parser("disable")
    p.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    return cmd_create(args) if args.cmd == "create" else cmd_disable(args)


if __name__ == "__main__":
    raise SystemExit(main())
