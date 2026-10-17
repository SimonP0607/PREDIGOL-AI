"""Create an account, or reset its password, from the operator's command line.

    python -m scripts.create_user --email you@example.com --role SUPER_ADMIN \\
        --name "Your Name" --generate --out ~/.fbi/predigol-admin.txt
    python -m scripts.create_user --email you@example.com --reset --generate --out FILE

The password never touches Git, the shell history or a log:
  --generate   a random 24-character password is written to --out (mode 0600) and
               nowhere else; the file is refused if it already exists (use --force);
  otherwise    the password is read from the FBI_NEW_PASSWORD environment variable
               or typed at a hidden prompt.

Exit status: 0 done, 1 refused (address taken, weak password...), 2 usage error.
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import string
import sys
from pathlib import Path

from fbi.auth.service import AuthError, create_user_unattended, set_password_unattended

ALPHABET = string.ascii_letters + string.digits + "-_.!@#%+="


def generated_password(length: int = 24) -> str:
    while True:
        pw = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def write_secret(path: Path, email: str, password: str, *, force: bool) -> None:
    path = path.expanduser()
    if path.exists() and not force:
        raise SystemExit(f"refusing to overwrite {path} (use --force)")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"email: {email}\npassword: {password}\n")
    os.chmod(path, 0o600)


def main() -> int:
    parser = argparse.ArgumentParser(prog="create_user", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--role", default="USER", choices=["USER", "SUPER_ADMIN"])
    parser.add_argument("--language", default="es", choices=["es", "en"])
    parser.add_argument("--timezone", default="UTC")
    parser.add_argument("--reset", action="store_true", help="set a new password on an existing account")
    parser.add_argument("--generate", action="store_true", help="generate the password and write it to --out")
    parser.add_argument("--out", type=Path, help="where --generate writes the credentials (mode 0600)")
    parser.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    args = parser.parse_args()

    if args.generate:
        if args.out is None:
            parser.error("--generate needs --out")
        password = generated_password()
    else:
        password = os.environ.get("FBI_NEW_PASSWORD") or getpass.getpass("New password: ")
    try:
        if args.reset:
            row = set_password_unattended(email=args.email, password=password)
        else:
            row = create_user_unattended(email=args.email, display_name=args.name, role=args.role,
                                         password=password, language=args.language, timezone=args.timezone)
    except AuthError as exc:
        detail = f" ({', '.join(exc.problems)})" if exc.problems else ""
        print(f"refused: {exc.code}{detail}", file=sys.stderr)
        return 1
    if args.generate:
        write_secret(args.out, row["email"], password, force=args.force)
        print(f"{row['email']} ({row['role']}): password written to {args.out.expanduser()} (mode 0600)")
    else:
        print(f"{row['email']} ({row['role']}): done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
