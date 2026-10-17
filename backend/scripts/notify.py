"""Run the notifier once.

    python -m scripts.notify            # show what would be announced; nothing stored or sent
    python -m scripts.notify --apply    # record and send (Telegram if FBI_TELEGRAM_BOT_TOKEN/CHAT_ID are set)

The bot informs about shadow picks, settlements, the first real capture and
failures. It never places a bet and nothing it sends is a recommendation.
"""

from __future__ import annotations

import argparse

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.notify.service import channel_from_env, collect, run_notifier


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="notify", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    channel = channel_from_env()
    print(f"channel: {'telegram' if channel else 'none configured (messages are recorded as skipped)'}")
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if not args.apply:
            for d in collect(conn, at=now()):
                print(f"- [{d.kind}] {d.title}")
            print("dry run - nothing stored or sent (use --apply)")
            return 0
        r = run_notifier(conn, channel)
    if channel is not None:
        channel.close()
    print(f"drafted {r.drafted}, new {r.new}, sent {r.sent}, skipped {r.skipped}, failed {r.failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
