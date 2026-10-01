"""a team we have never been told about is not thereby a club

core.teams.is_national was NOT NULL DEFAULT false, and a team can enter the
database from two places. ``/teams`` says whether a side is a national team, so
those rows are right. But ``FixtureRepository.ensure_teams`` creates a team from
a FIXTURE payload, which carries only an id and a name - and the default then
asserted "this is a club" about a side nobody had told us anything about.

Five rows were in that state, and three of them are national sides:

    10195  South Africa U23
    10371  Luxembourg U19
    16374  Seuzach
    26086  Spain U20
    10374  Montenegro U19

A youth national team filed as a club is the same defect as "Friendlies Clubs"
carrying an Elo weight of 0.90: the competition scope and the history weighting
read this flag, so a wrong value does not stay in this column. It propagates.

So the flag becomes nullable, and NULL means NOT TOLD. Nothing is invented, the
state is queryable, and ``/teams`` fills it in when the team is next resolved -
which for these five is one request each.

Revision ID: 0036
Revises: 0035
"""

from __future__ import annotations

from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE core.teams
    ALTER COLUMN is_national DROP NOT NULL,
    ALTER COLUMN is_national DROP DEFAULT;

COMMENT ON COLUMN core.teams.is_national IS
  'Whether this side is a national team, from /teams. NULL means the provider '
  'has not told us: the row was created from a fixture payload, which carries '
  'only an id and a name. It used to default to false, which asserted "club" '
  'about five teams nobody had described - three of them national youth sides. '
  'Readers must treat NULL as unknown, never as false: the competition scope '
  'and the history weighting both read this flag.';

-- Only the rows that were never described by /teams. A row WITH lineage was
-- told to us and keeps its answer.
UPDATE core.teams SET is_national = NULL WHERE source_payload_hash IS NULL;
"""

DOWNGRADE = """
UPDATE core.teams SET is_national = false WHERE is_national IS NULL;
ALTER TABLE core.teams
    ALTER COLUMN is_national SET DEFAULT false,
    ALTER COLUMN is_national SET NOT NULL;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
