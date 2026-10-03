"""indexes for looking a player up

A player's appearances live in core.fixture_player_stats (5.2 M rows) under a
primary key that starts with the fixture, so every "this player's matches"
query read the whole table: the Players page took seconds per row. The same for
absences. One index each, on the provider's player id - the column every
player-shaped query joins on.

Revision ID: 0042
Revises: 0041
"""

from __future__ import annotations

from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS fixture_player_stats_player_idx "
               "ON core.fixture_player_stats (provider_player_id)")
    op.execute("CREATE INDEX IF NOT EXISTS player_absences_player_idx ON core.player_absences (provider_player_id)")
    op.execute("CREATE INDEX IF NOT EXISTS player_absences_fixture_idx ON core.player_absences (fixture_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.player_absences_fixture_idx")
    op.execute("DROP INDEX IF EXISTS core.player_absences_player_idx")
    op.execute("DROP INDEX IF EXISTS core.fixture_player_stats_player_idx")
