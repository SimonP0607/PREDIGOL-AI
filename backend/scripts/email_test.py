"""The real e-mail test of plan UX, A5 (SPF, DKIM and DMARC; a bounce marked by the webhook), from the operator's
command line - through the queue like every message, so the test is recorded too.

    python -m scripts.email_test queue --user you@gmail.com [--template privacy_request_answered | --all]
    python -m scripts.email_test status 42

``queue`` puts the template's sample message for an EXISTING account in the queue (the owner's own, or a test
account the owner created, e.g. with the address bounced@resend.dev for the bounce test); the messenger sends it
when FBI_EMAIL_SEND is on. ``status`` prints a message's fate: queued, sent, bounced, complained, failed or
suppressed, with the attempts and the provider's short error code. Nothing else of the reader is printed.

``--all`` is the QA mailbox of the closing plan (4.1): one sample of every e-mail a reader can receive, in the language
of the account, to see each in a real mail app - except the two that cannot be a sample (an invitation's own link, and
the weekly summary, which needs the reader's consent). The moments in a sample (the end of a trial, a maintenance's
hours) are moved to the days ahead of now, so that a message that waited in the queue is not dropped as «too late».

Exit status: 0 done, 1 refused (no such account, no such message), 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import psycopg

from fbi.core.config import settings
from fbi.messaging import outbox
from fbi.messaging.templates import COMMERCIAL, TEMPLATES, Template, TemplateError


def samples() -> list[Template]:
    """The templates that can be a sample: no one-use link (it belongs to one account's token) and not commercial."""
    return [t for _, t in sorted(TEMPLATES.items()) if t.grant is None and t.category not in COMMERCIAL]


def current_sample(template: Template, at: datetime | None = None) -> dict[str, str]:
    """The template's sample with its moments moved to the days ahead of ``at``: the earliest one a day from now, the
    others at the same distance from it as in the sample (a maintenance keeps its length)."""
    moment = at or datetime.now(UTC)
    params: Mapping[str, str] = dict(template.sample)
    found: dict[str, datetime] = {}
    for key, value in params.items():
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            found[key] = parsed
    if not found:
        return dict(params)
    shift = moment.replace(minute=0, second=0, microsecond=0) + timedelta(days=1) - min(found.values())
    return {k: ((found[k] + shift).astimezone(UTC).isoformat(timespec="seconds") if k in found else v)
            for k, v in params.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("queue", help="queue a template's sample message for an existing account")
    q.add_argument("--user", required=True, help="the account's address")
    # An e-mail with a one-use link (plan UX, A7) is never a sample: its link belongs to one account's token row.
    q.add_argument("--template", default="privacy_request_answered",
                   choices=sorted(n for n, t in TEMPLATES.items() if t.grant is None))
    q.add_argument("--all", action="store_true", help="one sample of every e-mail a reader can receive (QA mailbox)")
    s = sub.add_parser("status", help="a queued message's fate")
    s.add_argument("message_id", type=int)
    args = parser.parse_args(argv)
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=5) as conn:
        if args.command == "queue":
            row = conn.execute("SELECT id FROM auth.users WHERE email = lower(btrim(%s))", (args.user,)).fetchone()
            if row is None:
                print("no account with that address", file=sys.stderr)
                return 1
            chosen = samples() if args.all else [TEMPLATES[args.template]]
            queued: list[str] = []
            for template in chosen:
                try:
                    mid = outbox.enqueue(conn, user_id=int(row[0]), template=template.name,
                                         params=current_sample(template), dedup_key=f"email_test:{uuid.uuid4().hex}")
                except TemplateError as exc:
                    print(f"refused: {exc}", file=sys.stderr)
                    return 1
                queued.append(f"{mid} ({template.name})")
            conn.commit()
            switch = "on" if outbox.sending_enabled() else "OFF (it waits in the queue)"
            print(f"queued message{'s' if len(queued) > 1 else ''} {', '.join(queued)}; "
                  f"FBI_EMAIL_SEND in this shell: {switch}")
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
