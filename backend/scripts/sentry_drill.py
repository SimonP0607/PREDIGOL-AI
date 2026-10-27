"""A drill of the "new exception" alert (security plan S3.5, docs/owner/SIMULACROS_AVISOS.md): ONE made-up error, sent to Sentry with the very
settings the API and the worker use (fbi.core.sentry), so that Sentry's rule "a new issue -> an email to the owner" is seen working.

    python -m scripts.sentry_drill          # on the server: bin/predigolctl sentry-drill

The error has a class of its own (SentryDrillError) and a fingerprint of its own (the UTC time), so Sentry opens a NEW issue on every run - a repeated one would be grouped
with the last and would not alert. Nothing personal leaves with it (fbi.core.sentry sends no user, no IP, no cookies, no local variables), and the DSN is never
printed. Mark the issue "resolved" in Sentry afterwards.

Exit status: 0 the event was taken by the SDK and flushed | 1 the SDK would not start or dropped it | 2 FBI_SENTRY_DSN is empty (Sentry is off).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from fbi.core import sentry


class SentryDrillError(Exception):
    """The made-up error of the drill: a class of its own, so that nobody mistakes it for a real one in Sentry's list of issues."""


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    if sentry.options("drill") is None:
        print(
            "sentry_drill: FBI_SENTRY_DSN is empty in app.env: Sentry is off and nothing was sent",
            file=sys.stderr,
        )
        return 2
    if not sentry.init("drill"):
        print(
            "sentry_drill: the Sentry SDK did not start (is the DSN valid?): nothing was sent",
            file=sys.stderr,
        )
        return 1
    import sentry_sdk

    when = stamp()
    event_id = None
    with sentry_sdk.new_scope() as scope:
        scope.fingerprint = ["simulacro", when]
        scope.set_tag("drill", "true")
        try:
            raise SentryDrillError(
                f"SIMULACRO {when}: error inventado para probar el aviso de excepción nueva (no es un fallo)"
            )
        except SentryDrillError as exc:
            event_id = sentry_sdk.capture_exception(exc)
    sentry_sdk.flush(timeout=10)
    if not event_id:
        print(
            "sentry_drill: the SDK dropped the event (nothing was sent); is Sentry's quota spent?",
            file=sys.stderr,
        )
        return 1
    print(
        f"sentry_drill: event {event_id} sent at {when} UTC. Sentry opens a NEW issue called SentryDrillError and emails the owner: note the time it arrives. "
        "Mark that issue resolved afterwards"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
