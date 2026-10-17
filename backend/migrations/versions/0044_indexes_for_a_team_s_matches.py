"""indexes for a team's matches

Every "this team's matches" question - team page, record, form, head-to-head,
a player's team - filtered core.fixtures (216,000 rows) on home_team_id OR
away_team_id with no index on either, so each one read the whole table. Two
indexes, each with the kick-off so "the last six before this one" is a range
scan.

Revision ID: 0044
Revises: 0043
"""

from __future__ import annotations

from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS fixtures_home_team_kickoff_idx ON core.fixtures (home_team_id, kickoff_at)")
    op.execute("CREATE INDEX IF NOT EXISTS fixtures_away_team_kickoff_idx ON core.fixtures (away_team_id, kickoff_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS core.fixtures_away_team_kickoff_idx")
    op.execute("DROP INDEX IF EXISTS core.fixtures_home_team_kickoff_idx")
