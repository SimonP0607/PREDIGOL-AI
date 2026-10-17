"""identity: coaches, and provenance on the entities that had none

WHAT WAS RAW-ONLY
-----------------
``/teams?league&season`` has been fetched 54 times and returned 1,604 teams. Every
one of them was stored as raw bytes and normalised into nothing: the unit writes
zero rows by design (``backfill.py``), so ``core.venues`` stayed almost empty and
``core.teams`` only ever gained the stub rows the fixtures importer needs.
``core.players`` had no writer at all, and nothing anywhere knew what a coach was,
although ``core.fixture_lineups`` has been storing ``provider_coach_id`` and
``coach_name`` side by side for every line-up.

Storing a name twice under two ids is how a data platform ends up with two
Manchester Uniteds, so identity is modelled the same way everywhere: OUR id, and
the provider's reference, unique. That part of the schema was already right - the
``provider_*_id UNIQUE`` columns exist - so this revision adds what was missing
around it rather than changing it.

WHAT THIS ADDS
--------------
``core.coaches``  the missing entity, with the provider's id unique, so a line-up
                  can point at a coach instead of repeating a name.
lineage columns   ``core.teams``, ``core.venues``, ``core.players`` and
                  ``core.team_season_memberships`` now record the payload and the
                  instant they were written from, like every other normalized
                  table in the schema. Nullable, because the rows that already
                  exist were written before the rule and backdating their
                  provenance would be a lie.
``core.fixture_lineups.coach_id``  the line-up's coach as an id, beside the name
                  the provider sent. The name stays: it is what the provider said,
                  and the id is what we made of it.

Revision ID: 0029
Revises: 0028
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE core.coaches (
    id                  BIGSERIAL PRIMARY KEY,
    provider_coach_id   INTEGER     NOT NULL UNIQUE,
    name                TEXT        NOT NULL,
    firstname           TEXT,
    lastname            TEXT,
    birth_date          DATE,
    nationality         TEXT,
    source_payload_hash TEXT        REFERENCES raw.ingestion_payloads(hash),
    source_fetched_at   TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE core.coaches IS
  'Identidad de entrenador: id nuestro + referencia del proveedor unica. Las
   alineaciones guardaban provider_coach_id y coach_name juntos sin que nada
   supiera que era un entrenador.';

ALTER TABLE core.teams
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ;
ALTER TABLE core.venues
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ,
    ADD COLUMN surface             TEXT,
    ADD COLUMN address             TEXT;
ALTER TABLE core.players
    ADD COLUMN height_cm           SMALLINT CHECK (height_cm IS NULL OR height_cm BETWEEN 100 AND 250),
    ADD COLUMN weight_kg           SMALLINT CHECK (weight_kg IS NULL OR weight_kg BETWEEN 30 AND 200),
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ;
ALTER TABLE core.team_season_memberships
    ADD COLUMN source_payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
    ADD COLUMN source_fetched_at   TIMESTAMPTZ;

COMMENT ON COLUMN core.teams.source_payload_hash IS
  'El payload del que salio esta fila. NULL en las filas escritas antes de esta
   revision: retro-fecharlas seria inventar procedencia.';

ALTER TABLE core.fixture_lineups
    ADD COLUMN coach_id BIGINT REFERENCES core.coaches(id);
COMMENT ON COLUMN core.fixture_lineups.coach_id IS
  'El entrenador como identidad. coach_name se conserva: es lo que dijo el
   proveedor, y esto es lo que nosotros hicimos con ello.';

CREATE INDEX fixture_lineups_coach ON core.fixture_lineups (coach_id) WHERE coach_id IS NOT NULL;
CREATE INDEX teams_venue ON core.teams (venue_id) WHERE venue_id IS NOT NULL;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS core.teams_venue;
DROP INDEX IF EXISTS core.fixture_lineups_coach;
ALTER TABLE core.fixture_lineups DROP COLUMN IF EXISTS coach_id;
ALTER TABLE core.team_season_memberships
    DROP COLUMN IF EXISTS source_fetched_at, DROP COLUMN IF EXISTS source_payload_hash;
ALTER TABLE core.players
    DROP COLUMN IF EXISTS source_fetched_at, DROP COLUMN IF EXISTS source_payload_hash,
    DROP COLUMN IF EXISTS weight_kg, DROP COLUMN IF EXISTS height_cm;
ALTER TABLE core.venues
    DROP COLUMN IF EXISTS address, DROP COLUMN IF EXISTS surface,
    DROP COLUMN IF EXISTS source_fetched_at, DROP COLUMN IF EXISTS source_payload_hash;
ALTER TABLE core.teams
    DROP COLUMN IF EXISTS source_fetched_at, DROP COLUMN IF EXISTS source_payload_hash;
DROP TABLE IF EXISTS core.coaches;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
