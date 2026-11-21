"""A reader's subscribable calendar of the teams they follow (Plan Maestro PM, PM-14-06, OP-43)

WHY THIS EXISTS
---------------
A reader cannot take the matches of the teams they follow to their own calendar (Google, Apple, Outlook). PM-14-06 gives each reader,
when they ask for it, a secret iCalendar link (``.../calendar/feed/<token>.ics``) that a calendar client reads every few hours: the
fixtures of the teams in ``customer.favorites``, with no price, no probability and no pick. The code comes in a later PR, behind
``FBI_CALENDAR_FEED`` (born off); this revision only lays the table down.

customer.calendar_feeds
-----------------------
One row per link ever made: whose it is (``auth.users``), the SHA-256 of its secret (``link_sha256``, 64 hex digits - the secret itself,
256 random bits, is shown to the reader once and never stored, as ``auth`` does with its one-use links), when it was made, when it was
revoked (a new link revokes the previous one; the reader can revoke it at any time) and when a calendar last read it (``last_read_at``,
written at most once an hour: it tells the reader whether a leaked link is in use). At most ONE live link per reader (a partial unique
index). No email, no name, no team in the row: the link is a key, the favourites stay where they are.

The security review of the link (``backend/docs/owner/BE_084_REVISION_SEGURIDAD_CALENDARIO.md``) is the code's condition, not this
table's: an empty table changes nothing.

Additive only: one new table in ``customer``, a foreign key to ``auth.users`` (ON DELETE RESTRICT: an account is anonymised, never
deleted - A7 - and its links are deleted then, with the rest of what the reader keeps), no change to an existing table, no row written.
Privileges: ``deploy/vps/db/grants.sql`` - the API makes, revokes, touches and deletes (INSERT, UPDATE, DELETE); the worker of PrediGol
Intelligence never reads ``customer`` (its default privileges there are revoked). Downgrade drops it only while it is empty.

Revision ID: 0171
Revises: 0170
"""

from __future__ import annotations

from alembic import op

revision = "0171"
down_revision = "0170"
branch_labels = None
depends_on = None

TABLE = "customer.calendar_feeds"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE {TABLE} (
            id            BIGSERIAL     PRIMARY KEY,
            user_id       BIGINT        NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            link_sha256   TEXT          NOT NULL UNIQUE CHECK (link_sha256 ~ '^[0-9a-f]{{64}}$'),
            created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
            revoked_at    TIMESTAMPTZ,
            revoked_why   TEXT          CHECK (revoked_why IS NULL OR revoked_why IN ('reader', 'replaced', 'owner', 'account')),
            last_read_at  TIMESTAMPTZ,
            CHECK ((revoked_at IS NULL) = (revoked_why IS NULL)),
            CHECK (revoked_at IS NULL OR revoked_at >= created_at),
            CHECK (last_read_at IS NULL OR last_read_at >= created_at)
        );
        CREATE UNIQUE INDEX calendar_feeds_one_live ON {TABLE} (user_id) WHERE revoked_at IS NULL;
        COMMENT ON TABLE {TABLE} IS
          'PM-14-06: a reader''s secret iCalendar link of the teams they follow. Only the SHA-256 of the secret is kept; at most one live '
          'link per reader; revoked, never edited otherwise; deleted when the account is anonymised (A7). No price, probability or pick '
          'is ever served through it.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a reader's link: an empty table is dropped; one with rows stops the downgrade (the code goes back, the table stays).
    op.execute(
        "DO $refuse$\nBEGIN\n"
        f"  IF to_regclass('{TABLE}') IS NOT NULL THEN\n"
        f"    IF EXISTS (SELECT 1 FROM {TABLE}) THEN\n"
        f"      RAISE EXCEPTION '0171 downgrade refused: {TABLE} holds readers'' links (PM-14-06); the table stays';\n"
        "    END IF;\n"
        "  END IF;\n"
        "END\n$refuse$"
    )
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
