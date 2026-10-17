"""competition media: country code and flag

``core.competitions.logo_url`` has existed since 0003 and was never written, and the
competition's country was kept as a name only. The provider's ``/leagues`` payload -
already stored in RAW - carries both the league logo and the country's code and flag,
so the product can show them without a single new request
(``scripts/backfill_competition_media.py`` reads them from the stored payload).

Two columns, both nullable: NULL means the stored payload did not say, never "none".

Revision ID: 0046
Revises: 0045
"""

from __future__ import annotations

from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.competitions ADD COLUMN IF NOT EXISTS country_code TEXT "
               "CHECK (country_code ~ '^[A-Z]{2}(-[A-Z]{2,3})?$')")
    op.execute("ALTER TABLE core.competitions ADD COLUMN IF NOT EXISTS flag_url TEXT "
               "CHECK (flag_url ~ '^https://')")
    op.execute("COMMENT ON COLUMN core.competitions.flag_url IS "
               "'The country flag as the provider published it in /leagues. NULL: not told (World, or not stored).'")


def downgrade() -> None:
    op.execute("ALTER TABLE core.competitions DROP COLUMN IF EXISTS flag_url")
    op.execute("ALTER TABLE core.competitions DROP COLUMN IF EXISTS country_code")
