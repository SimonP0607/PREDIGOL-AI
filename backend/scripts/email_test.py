"""The real e-mail test of plan UX, A5 (SPF, DKIM and DMARC; a bounce marked by the webhook), from the operator's
command line - through the queue like every message, so the test is recorded too.

    python -m scripts.email_test queue --user you@gmail.com [--template privacy_request_answered]
    python -m scripts.email_test status 42

``queue`` puts the template's sample message for an EXISTING account in the queue (the owner's own, or a test
account the owner created, e.g. with the address bounced@resend.dev for the bounce test); the messenger sends it
when FBI_EMAIL_SEND is on. ``status`` prints a message's fate: queued, sent, bounced, complained, failed or
suppressed, with the attempts and the provider's short error code. Nothing else of the reader is printed.

Exit status: 0 done, 1 refused (no such account, no such message), 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
import uuid

import psycopg

from fbi.core.config import settings
from fbi.messaging import outbox
from fbi.messaging.templates import TEMPLATES, TemplateError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("queue", help="queue a template's sample message for an existing account")
    q.add_argument("--user", required=True, help="the account's address")
    # An e-mail with a one-use link (plan UX, A7) is never a sample: its link belongs to one account's token row.
    q.add_argument("--template", default="privacy_request_answered",
                   choices=sorted(n for n, t in TEMPLATES.items() if t.grant is None))
    s = sub.add_parser("status", help="a queued message's fate")
    s.add_argument("message_id", type=int)
    args = parser.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=5) as conn:
        if args.command == "queue":
            row = conn.execute("SELECT id FROM auth.users WHERE email = lower(btrim(%s))", (args.user,)).fetchone()
            if row is None:
                print("no account with that address", file=sys.stderr)
                return 1
            template = TEMPLATES[args.template]
            try:
                mid = outbox.enqueue(conn, user_id=int(row[0]), template=template.name, params=dict(template.sample),
                                     dedup_key=f"email_test:{uuid.uuid4().hex}")
            except TemplateError as exc:
                print(f"refused: {exc}", file=sys.stderr)
                return 1
            conn.commit()
            switch = "on" if outbox.sending_enabled() else "OFF (it waits in the queue)"
            print(f"queued message {mid} ({template.name}); FBI_EMAIL_SEND in this shell: {switch}")
            return 0
        found = conn.execute("SELECT template, status, attempts, last_error, provider_id IS NOT NULL, sent_at "
                             "FROM customer.messages_outbox WHERE id = %s", (args.message_id,)).fetchone()
        if found is None:
            print("no such message", file=sys.stderr)
            return 1
        template, status, attempts, last_error, accepted, sent_at = found
        print(f"message {args.message_id} ({template}): {status}, {attempts} attempt(s)"
              + (f", accepted by the provider at {sent_at:%Y-%m-%d %H:%M} UTC" if accepted else "")
              + (f", last error: {last_error}" if last_error else ""))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
