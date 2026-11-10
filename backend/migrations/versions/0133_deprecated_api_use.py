"""Uses of an API endpoint on its way out, counted per UTC day (plan Cuotas, BE-033)

WHY THIS EXISTS
---------------
``GET /odds/best`` and the old Cuotas page it feeds stay while the explorer (``FBI_ODDS_EXPLORER``) settles in; they go once seven
days pass with no reader using them. The API's request log said so only until the container was recreated - every deploy - so
the evidence did not survive the week it has to cover. This table keeps it: one row per UTC day, endpoint, kind of caller and
role, with how many calls and the first and last of them. No user, no session, no address: a count.

``caller`` is read from the User-Agent (``fbi.api.services.deprecated.caller_kind``): ``browser`` (a reader's page), ``e2e``
(Playwright, headless browsers), ``testclient`` (the baseline snapshot and the tests, in-process), ``script`` (curl, httpx,
requests: the load test, an operator) and ``other``. Retiring waits on ``browser`` rows only.

Additive only: one new table. Privileges: the API inserts and updates it through ``deploy/vps/db/grants.sql`` (run by the release
after every migration); everyone with the read grant reads it. Downgrade drops it.

Revision ID: 0133
Revises: 0132
"""

from __future__ import annotations

from alembic import op

revision = "0133"
down_revision = "0132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE audit.deprecated_api_use (
            day       DATE        NOT NULL,
            endpoint  TEXT        NOT NULL CHECK (length(endpoint) BETWEEN 1 AND 120),
            caller    TEXT        NOT NULL CHECK (caller IN ('browser', 'e2e', 'testclient', 'script', 'other')),
            role      TEXT        NOT NULL CHECK (length(role) BETWEEN 1 AND 40),
            calls     BIGINT      NOT NULL DEFAULT 1 CHECK (calls >= 1),
            first_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (day, endpoint, caller, role)
        )""")
    op.execute("""
        COMMENT ON TABLE audit.deprecated_api_use IS
        'Calls to API endpoints on their way out (plan Cuotas, BE-033: /odds/best and the old Cuotas page), per UTC day, kind of
         caller (browser, e2e, testclient, script, other: read from the User-Agent) and role. A count only: no user, session or
         address. The endpoint is retired once seven days pass without browser rows (backend/docs/owner/CUOTAS_REFRESCOS_Y_API_BE011.md).'""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.deprecated_api_use")
