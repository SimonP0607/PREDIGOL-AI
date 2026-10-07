"""Entry point the compose file runs: python -m apps.worker.main"""

from __future__ import annotations

import asyncio

from apps.worker.scheduler import main

if __name__ == "__main__":
    from fbi.core import sentry

    sentry.init("worker")  # only with FBI_SENTRY_DSN set
    asyncio.run(main())
