"""The messenger for QA (plan UX, A7): the same process as production's (fbi.messaging.runner), with a provider that
writes each message to a folder instead of sending it - the end-to-end tests read the invitation, recovery and
unlock links from there. It never sends an e-mail and never runs on the server (the compose file runs
``apps.messenger.main``).

    FBI_EMAIL_SINK_DIR=/path/to/folder FBI_EMAIL_SEND=1 python -m scripts.qa_messenger [--tick 1]

Each message is one JSON file: the address, the subject, the plain text (with its link), the template and the
time it was handed over - and, for commercial e-mail (plan UX, B8), its own sender and the one-click unsubscribe
headers. The folder is the QA machine's; nothing here is kept anywhere else.

``--digest-any-day`` (QA only): a consenting reader's weekly summary is due at the next cycle, whatever their day and
hour (production: their day of the week, from 09:00 in their zone - fbi.messaging.digest.due_now, unit-tested), so the
end-to-end test of B8 gets the e-mail and its links in a minute. Still once per reader and ISO week, still the day's cap.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fbi.core.config import settings
from fbi.messaging import digest, runner
from fbi.messaging.provider import Outgoing


class FolderSink:
    """A provider that keeps each message in a file (QA only)."""

    name = "qa-folder"

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def send(self, message: Outgoing) -> str:
        provider_id = f"qa-{uuid.uuid4().hex[:16]}"
        at = datetime.now(UTC).isoformat(timespec="milliseconds")
        record = {"id": provider_id, "to": message.to, "subject": message.subject, "text": message.text,
                  "template": message.tags.get("template"), "category": message.tags.get("category"), "at": at,
                  "sender": message.sender, "headers": dict(message.headers)}
        path = self.folder / f"{at.replace(':', '')}-{provider_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)  # the tests never read half a file
        return provider_id


def _due_any_day(user_id: int, zone: str | None, at: datetime) -> bool:
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tick", type=float, default=1.0, help="seconds between two sends (production: 15)")
    parser.add_argument("--cycle", type=float, default=60.0, help="seconds per cycle (production: 300)")
    parser.add_argument("--digest-any-day", action="store_true",
                        help="a reader's weekly summary is due at the next cycle (production: their day, from 09:00)")
    args = parser.parse_args(argv)
    folder = os.environ.get("FBI_EMAIL_SINK_DIR", "").strip()
    if not folder:
        print("FBI_EMAIL_SINK_DIR is not set: this messenger only writes to a folder (QA)")
        return 2
    if os.environ.get("FBI_RESEND_API_KEY"):
        print("FBI_RESEND_API_KEY is set: this is not a QA shell - refusing")
        return 2
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    sink = FolderSink(Path(folder))
    if args.digest_any_day:
        digest.due_now = _due_any_day  # QA only: see the module's docstring
    runner.run(stop, dsn=settings.database.psycopg_url, provider_factory=lambda: sink, tick_s=args.tick,
               cycle_s=args.cycle, alive_file=Path(folder) / ".alive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
