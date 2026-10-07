"""Accounts from the operator's command line - for the cut-over and for emergencies (the owner locked out, a lost
phone with no other SUPER_ADMIN). Everything it changes is recorded in auth.audit_events (by: command_line).

    python -m scripts.accounts list
    python -m scripts.accounts disable --domain predigol.local            # dry run: who would be disabled
    python -m scripts.accounts disable --domain predigol.local --confirm  # QA / test accounts off, sessions ended
    python -m scripts.accounts disable --email someone@example.com --confirm
    python -m scripts.accounts require-password-change --email owner@example.com
    python -m scripts.accounts revoke-sessions --all                       # everyone signs in again
    python -m scripts.accounts unlock --email owner@example.com
    python -m scripts.accounts mfa-reset --email owner@example.com         # a lost phone
    python -m scripts.accounts mfa-enroll --email qa.admin@predigol.local --secret-out ~/.fbi/qa-admin-totp.txt

mfa-enroll is for TEST accounts (E2E against a server that requires a second factor): it writes the authenticator
secret to a 0600 file. It refuses any address outside --test-domain (default predigol.local).

Addresses are printed masked. Exit status: 0 done, 1 refused, 2 usage error.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from fbi.auth import crypto, store, totp
from fbi.auth.db import write_connection
from fbi.auth.service import mfa_required_for, normalize_email

BY = {"by": "command_line"}


def masked(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:3]}...@{domain}"


def _users(conn: Any, *, emails: list[str], domain: str | None, everyone: bool = False) -> list[dict[str, Any]]:
    rows = store.list_users(conn)
    if everyone:
        return rows
    wanted = {normalize_email(e) for e in emails}
    return [r for r in rows if r["email"] in wanted or (domain and r["email"].endswith("@" + domain.lower()))]


def cmd_list(_: argparse.Namespace) -> int:
    with write_connection() as conn:
        rows = store.list_users(conn)
    print(f"{'id':>4}  {'email':28} {'role':12} {'status':9} {'2fa':9} {'locked':7} {'new_pw':7} last_login")
    for r in rows:
        mfa = "on" if r["totp_enabled_at"] else ("required" if mfa_required_for(r) else "-")
        print(f"{r['id']:>4}  {masked(r['email']):28} {r['role']:12} {r['status']:9} {mfa:9} "
              f"{'yes' if r['is_locked'] else '-':7} {'yes' if r['must_change_password'] else '-':7} "
              f"{r['last_login_at'] or '-'}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        targets = [r for r in _users(conn, emails=args.email, domain=args.domain) if r["status"] == "active"]
        admins_left = store.count_active_super_admins(conn) - sum(1 for r in targets if r["role"] == "SUPER_ADMIN")
        for r in targets:
            print(f"{'disable' if args.confirm else 'would disable'} {masked(r['email'])} ({r['role']})")
        if admins_left < 1:
            print("refused: no active SUPER_ADMIN would be left", file=sys.stderr)
            return 1
        if not args.confirm:
            print(f"{len(targets)} account(s); nothing changed (add --confirm)")
            return 0
        for r in targets:
            store.update_user(conn, int(r["id"]), {"status": "disabled"})
            n = store.revoke_user_sessions(conn, int(r["id"]), "account_disabled")
            store.record_event(conn, "user.status_changed", target_user_id=r["id"],
                               detail=BY | {"from": "active", "to": "disabled", "sessions_revoked": n})
    print(f"{len(targets)} account(s) disabled")
    return 0


def _one(conn: Any, email: str) -> dict[str, Any]:
    row = store.user_by_email(conn, normalize_email(email))
    if row is None:
        raise SystemExit(f"no account {masked(normalize_email(email))}")
    return row


def cmd_require_password_change(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        row = _one(conn, args.email)
        store.update_user(conn, int(row["id"]), {"must_change_password": True})
        n = store.revoke_user_sessions(conn, int(row["id"]), "password_change_required")
        store.record_event(conn, "user.password_change_required", target_user_id=row["id"],
                           detail=BY | {"sessions_revoked": n})
    print(f"{masked(row['email'])} chooses a new password at the next sign-in ({n} session(s) ended)")
    return 0


def cmd_revoke_sessions(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        targets = _users(conn, emails=args.email, domain=args.domain, everyone=args.all)
        total = 0
        for r in targets:
            n = store.revoke_user_sessions(conn, int(r["id"]), "revoked_by_operator")
            if n:
                store.record_event(conn, "session.revoked", target_user_id=r["id"], detail=BY | {"count": n})
            total += n
    print(f"{total} session(s) ended for {len(targets)} account(s)")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        row = _one(conn, args.email)
        store.unlock(conn, int(row["id"]))
        store.record_event(conn, "user.unlocked", target_user_id=row["id"], detail=BY)
    print(f"{masked(row['email'])} unlocked")
    return 0


def cmd_mfa_reset(args: argparse.Namespace) -> int:
    with write_connection() as conn:
        row = _one(conn, args.email)
        store.clear_totp(conn, int(row["id"]))
        n = store.revoke_user_sessions(conn, int(row["id"]), "mfa_reset")
        store.record_event(conn, "mfa.reset", target_user_id=row["id"], detail=BY | {"sessions_revoked": n})
    print(f"{masked(row['email'])}: second factor removed; it is set up again at the next sign-in when required")
    return 0


def cmd_mfa_enroll(args: argparse.Namespace) -> int:
    email = normalize_email(args.email)
    if not email.endswith("@" + args.test_domain.lower()):
        print(f"refused: mfa-enroll is for test accounts (@{args.test_domain}) only", file=sys.stderr)
        return 1
    out = args.secret_out.expanduser()
    if out.exists() and not args.force:
        print(f"refused: {out} exists (use --force)", file=sys.stderr)
        return 1
    secret = totp.new_secret()
    with write_connection() as conn:
        row = _one(conn, email)
        uid = int(row["id"])
        store.set_totp(conn, uid, crypto.seal_totp(uid, secret), totp.step_at() - 2)
        store.replace_recovery_codes(conn, uid, [])
        store.record_event(conn, "mfa.enrolled", target_user_id=uid, detail=BY | {"test_account": True})
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(totp.b32(secret) + "\n")
    os.chmod(out, 0o600)
    print(f"{masked(email)}: authenticator secret written to {out} (0600)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="accounts", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("disable")
    p.add_argument("--email", action="append", default=[])
    p.add_argument("--domain")
    p.add_argument("--confirm", action="store_true")
    for name in ("require-password-change", "unlock", "mfa-reset"):
        sub.add_parser(name).add_argument("--email", required=True)
    p = sub.add_parser("revoke-sessions")
    p.add_argument("--email", action="append", default=[])
    p.add_argument("--domain")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("mfa-enroll")
    p.add_argument("--email", required=True)
    p.add_argument("--secret-out", type=Path, required=True)
    p.add_argument("--test-domain", default="predigol.local")
    p.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.cmd in ("disable", "revoke-sessions") and not (args.email or args.domain or getattr(args, "all", False)):
        parser.error("name the accounts: --email, --domain" + (" or --all" if args.cmd == "revoke-sessions" else ""))
    handler = {"list": cmd_list, "disable": cmd_disable, "require-password-change": cmd_require_password_change,
               "revoke-sessions": cmd_revoke_sessions, "unlock": cmd_unlock, "mfa-reset": cmd_mfa_reset,
               "mfa-enroll": cmd_mfa_enroll}[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
