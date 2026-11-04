"""Entry point the compose file runs: python -m apps.messenger.main

The messenger (fbi.messaging.runner) sends the readers' messages and drafts the owner's notices about them, with
the API's database role. ``python -m apps.messenger.main --alive`` is the container's health check: exit 0 when a
tick touched the alive file in the last two minutes (it imports nothing of the application: it runs every minute).
"""

from __future__ import annotations

import os
import sys
import time

ALIVE_FILE = os.environ.get("FBI_MESSENGER_ALIVE_FILE", "/tmp/predigol-messenger.alive")
ALIVE_WITHIN_S = 120.0


def alive_now() -> bool:
    try:
        return time.time() - os.stat(ALIVE_FILE).st_mtime < ALIVE_WITHIN_S
    except OSError:
        return False


def main(argv: list[str]) -> int:
    if "--alive" in argv:
        return 0 if alive_now() else 1
    import signal
    import threading
    from types import FrameType

    from fbi.core import sentry
    from fbi.core.config import settings
    from fbi.core.logging import configure
    from fbi.messaging.runner import run

    configure(settings.runtime.log_level)
    sentry.init("messenger")  # only with FBI_SENTRY_DSN set
    stop = threading.Event()

    def _stop(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop)
    run(stop, dsn=settings.database.psycopg_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
