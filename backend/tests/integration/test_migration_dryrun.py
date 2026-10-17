"""The migration runs end to end before anything is paid for.

The dry run creates its own scratch database on the test server, runs every
unit kind through the real client, raw store, normalisers and engine against a
fake HTTP layer, interrupts itself, resumes, replays - and drops the database.
"""

from __future__ import annotations

import psycopg
import pytest

from fbi.migration.dryrun import SCRATCH_PREFIX, dry_run
from tests.integration.conftest import ADMIN_URL

pytestmark = pytest.mark.integration


async def test_the_dry_run_passes_every_link_and_leaves_nothing_behind() -> None:
    report = await dry_run(ADMIN_URL)
    failed = [f"{c.name}: {c.detail}" for c in report.checks if not c.ok]
    assert report.ok, failed
    assert report.requests == sum(report.units.values()), "one request per unit"
    assert len(report.units) == 7
    with psycopg.connect(ADMIN_URL) as admin:
        left = admin.execute("SELECT count(*) FROM pg_database WHERE datname LIKE %s",
                             (SCRATCH_PREFIX + "%",)).fetchone()
    assert left == (0,), "the scratch database is dropped"
