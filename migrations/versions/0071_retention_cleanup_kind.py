"""audit.storage_cleanups records routine retention too (kind 'retention')

The owner's daily maintenance on the server (scripts/db_maintenance.py retention) removes operational leftovers
only - sessions revoked or expired 90 days ago, per-minute request counters older than 35 days - and records each
removal here, like the in-play cleanup did: the table, the rows removed, the newest verified backup at the time.

Revision ID: 0071
Revises: 0070
"""

from __future__ import annotations

from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit.storage_cleanups DROP CONSTRAINT IF EXISTS storage_cleanups_kind_check;
        ALTER TABLE audit.storage_cleanups ADD CONSTRAINT storage_cleanups_kind_check
            CHECK (kind IN ('inplay_archive', 'inplay_drop', 'inplay_raw_purge', 'retention'));
    """)


def downgrade() -> None:
    # A schema can be reversed; the rows it recorded are history and stay - unless there are 'retention' rows,
    # which the old constraint cannot hold: then the downgrade refuses.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM audit.storage_cleanups WHERE kind = 'retention') THEN
            RAISE EXCEPTION 'audit.storage_cleanups holds retention records: refusing to drop the kind';
          END IF;
        END $$;
        ALTER TABLE audit.storage_cleanups DROP CONSTRAINT IF EXISTS storage_cleanups_kind_check;
        ALTER TABLE audit.storage_cleanups ADD CONSTRAINT storage_cleanups_kind_check
            CHECK (kind IN ('inplay_archive', 'inplay_drop', 'inplay_raw_purge'));
    """)
