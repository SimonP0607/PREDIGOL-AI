"""The reader's «solo fútbol» mode and voluntary pause (Plan Maestro PM, PM-14-07, OP-46)

WHY THIS EXISTS
---------------
Someone who wants to follow football without prices has no way to hide them. PM-14-07 gives each reader two choices of their own:
«solo fútbol» (no price, no pick, no parlay anywhere) and a voluntary pause (the same, until a date they chose). The code comes in a
later PR, behind ``FBI_WELLBEING`` (born off); this revision only lays the table down, alone, as the plan asks (the migration goes by
itself, with its backup and restore test, before any code reads it).

customer.wellbeing
------------------
One row per reader who ever chose anything: ``football_only`` (the mode is on) and ``paused_until`` (a pause that runs until then; NULL
none). Nothing else: no reason, no counter, no reading of how often prices were looked at - what a reader chose, and when. A reader with
no row has both off. Whether a pause may be cut short is a rule of the code, not of the table.

Additive only: one new table in ``customer``, a foreign key to ``auth.users`` (ON DELETE RESTRICT: an account is anonymised, never
deleted - A7 - and its row is deleted then), no change to an existing table, no row written. Privileges: ``deploy/vps/db/grants.sql`` -
the API reads and writes it (INSERT, UPDATE, DELETE: the delete is the anonymisation's); the worker of PrediGol Intelligence never reads
``customer``. Downgrade drops it only while it is empty.

Revision ID: 0176
Revises: 0175
"""

from __future__ import annotations

from alembic import op

revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None

TABLE = "customer.wellbeing"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE {TABLE} (
            user_id       BIGINT       PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
            football_only BOOLEAN      NOT NULL DEFAULT false,
            paused_until  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CHECK (updated_at >= created_at)
        );
        COMMENT ON TABLE {TABLE} IS
          'PM-14-07: what a reader chose about seeing prices: football_only (no price, pick or parlay anywhere) and paused_until (the '
          'same until a date they chose). Nothing else is kept. Deleted when the account is anonymised (A7).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a reader's choice: an empty table is dropped; one with rows stops the downgrade (the code goes back, the table stays).
    op.execute(
        "DO $refuse$\nBEGIN\n"
        f"  IF to_regclass('{TABLE}') IS NOT NULL THEN\n"
        f"    IF EXISTS (SELECT 1 FROM {TABLE}) THEN\n"
        f"      RAISE EXCEPTION '0176 downgrade refused: {TABLE} holds readers'' choices (PM-14-07); the table stays';\n"
        "    END IF;\n"
        "  END IF;\n"
        "END\n$refuse$"
    )
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
