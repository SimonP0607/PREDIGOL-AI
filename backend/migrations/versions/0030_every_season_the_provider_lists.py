"""seasons: keep every one the provider lists, not only the current one

WHAT WAS THROWN AWAY
--------------------
``/leagues`` returns, for every competition, EVERY season the provider holds -
each with its start, its end, whether it is current, and twelve coverage flags.
``refresh_seasons`` read all of that and wrote exactly one row per competition:
the current season. Every other season the provider listed was parsed and
dropped, and ``SeasonRef.has_fixtures`` was parsed and never stored at all.

The flags themselves survive in ``raw.league_coverage`` (that is what RAW is
for), so nothing is lost permanently. What was missing is the catalogue side: a
season the provider lists and we have no row for cannot be planned against,
cannot carry fixtures, and cannot be reported as "known but not fetched" - it is
simply invisible.

WHAT CHANGES
------------
``has_fixtures``  the provider's own claim that a season has a fixture list. It
                  was being parsed and discarded. A season the provider lists
                  WITHOUT fixtures is not a gap in our backfill; it is a season
                  that does not exist to be fetched.
``listed_at``     when the provider last named this season. A season that stops
                  being listed is not deleted - the fixtures we hold for it are
                  real - but it stops being refreshed, and this is how that is
                  visible.

``coverage`` (JSONB, present since 0003) stays deliberately unwritten: the flags
live in ``raw.league_coverage`` with the payload they came from, and keeping a
second copy here would be two truths that can drift.

Revision ID: 0030
Revises: 0029
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE core.competition_seasons
    ADD COLUMN has_fixtures BOOLEAN,
    ADD COLUMN listed_at    TIMESTAMPTZ;

COMMENT ON COLUMN core.competition_seasons.has_fixtures IS
  'La afirmacion del proveedor de que esta temporada tiene lista de partidos.
   NULL = no lo sabemos (fila anterior a esta revision, o temporada que nunca
   aparecio en /leagues). false = existe y no hay nada que traer, que NO es un
   hueco de nuestro backfill.';
COMMENT ON COLUMN core.competition_seasons.listed_at IS
  'Ultima vez que /leagues nombro esta temporada. Una temporada que deja de
   listarse no se borra - los partidos que tenemos ocurrieron - pero deja de
   refrescarse, y asi se ve.';
COMMENT ON COLUMN core.competition_seasons.coverage IS
  'Deliberadamente sin escribir: los flags de cobertura viven en
   raw.league_coverage con el payload del que salieron. Dos copias serian dos
   verdades que pueden divergir.';

CREATE INDEX competition_seasons_listed
    ON core.competition_seasons (competition_id, season DESC) WHERE listed_at IS NOT NULL;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS core.competition_seasons_listed;
ALTER TABLE core.competition_seasons
    DROP COLUMN IF EXISTS listed_at,
    DROP COLUMN IF EXISTS has_fixtures;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
