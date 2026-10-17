"""the provider's player id 0 is nobody, not one person

API-Football sends ``player.id = 0`` for a player it cannot identify (lower
leagues, youth sides). The identity writer upserted that like any id, so
core.players held ONE row, id 0, named after whichever unidentified player was
written last - "enrick reuperne" - and every query joining statistics to
players credited that one name with 3,926 matches, 499 of them in the last 30
days. The Players page listed him as the most productive player in the world.

The writer now skips id 0 (``IdentityReport.skipped_no_id``). This removes the
row it made, and the same for coaches. The match statistics themselves are
kept as they are: they belong to a match and a side, just not to anyone we can
name, and their raw payloads are untouched.

Revision ID: 0043
Revises: 0042
"""

from __future__ import annotations

from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM core.players WHERE provider_player_id <= 0")
    # Line-ups linked to the id-0 "coach" go back to name only (the name the
    # provider sent stays on the line-up row).
    op.execute("UPDATE core.fixture_lineups SET coach_id = NULL "
               "WHERE coach_id IN (SELECT id FROM core.coaches WHERE provider_coach_id <= 0)")
    op.execute("DELETE FROM core.coaches WHERE provider_coach_id <= 0")
    op.execute("ALTER TABLE core.players ADD CONSTRAINT players_have_a_real_provider_id "
               "CHECK (provider_player_id > 0)")
    op.execute("ALTER TABLE core.coaches ADD CONSTRAINT coaches_have_a_real_provider_id "
               "CHECK (provider_coach_id > 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE core.coaches DROP CONSTRAINT coaches_have_a_real_provider_id")
    op.execute("ALTER TABLE core.players DROP CONSTRAINT players_have_a_real_provider_id")
