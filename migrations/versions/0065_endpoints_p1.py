"""P1 endpoints: /venues, /players/teams and the venue a fixture payload names

The contract audit left four API-Football endpoints PARTIAL (5 Oct 2026). Two of them need storage:

* ``core.venues.image_url`` - /venues and the venue block of /teams send the stadium's picture; it was dropped.
  Venues met only through a fixture (id, name, city) are completed by the ``venues`` reference feed, asked by id.
* ``core.fixtures.venue_name`` / ``venue_city`` - the venue AS THE FIXTURE PAYLOAD NAMES IT, also when the provider
  gives no venue id. A venue without an id cannot be keyed, so no ``core.venues`` row is made for it and
  ``venue_id`` stays NULL; until now its name was dropped too. Measured on 5 Oct 2026 over the 23,508 current
  tracked fixtures with no venue id: of the 17,240 found in the newest season payload of their competition, 7,095
  named a venue without an id, 10,145 sent no venue at all and none carried an id PrediGol had not stored (6,268
  were not in that payload and were not checked). Existing rows are filled from each fixture's own source payload
  (``scripts.reprocess_fixture_venues``, RAW only): no other column changes.
* ``core.player_team_seasons`` (+ ``_latest`` view) - /players/teams: the teams a player played for and the
  seasons, as the provider lists them (clubs and national sides alike), a snapshot per change.

Revision ID: 0065
Revises: 0064
"""

from __future__ import annotations

from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE core.venues ADD COLUMN IF NOT EXISTS image_url TEXT")
    op.execute("COMMENT ON COLUMN core.venues.image_url IS 'The provider''s picture of the stadium (/venues, or the "
               "venue block of /teams).'")
    op.execute("ALTER TABLE core.fixtures ADD COLUMN IF NOT EXISTS venue_name TEXT, "
               "ADD COLUMN IF NOT EXISTS venue_city TEXT")
    op.execute("COMMENT ON COLUMN core.fixtures.venue_name IS 'The venue as the fixture payload names it (also when "
               "the provider gives no venue id, so venue_id is NULL). Written with the row, from the same payload.'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.player_team_seasons (
            provider_player_id  INTEGER     NOT NULL,
            observed_at         TIMESTAMPTZ NOT NULL,
            ordinal             SMALLINT    NOT NULL,
            provider_team_id    INTEGER,
            team_name           TEXT,
            team_logo           TEXT,
            seasons             INTEGER[]   NOT NULL,
            payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            normalizer_version  TEXT        NOT NULL,
            PRIMARY KEY (provider_player_id, observed_at, ordinal)
        )""")
    op.execute("COMMENT ON TABLE core.player_team_seasons IS '/players/teams: the teams a player played for and in "
               "which seasons, in the provider''s order (clubs and national sides alike), a snapshot per change.'")
    op.execute("CREATE OR REPLACE VIEW core.player_team_seasons_latest AS SELECT t.* FROM core.player_team_seasons t "
               "WHERE t.observed_at = (SELECT max(x.observed_at) FROM core.player_team_seasons x "
               "WHERE x.provider_player_id = t.provider_player_id)")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.player_team_seasons_latest")
    op.execute("DROP TABLE IF EXISTS core.player_team_seasons")
    op.execute("ALTER TABLE core.fixtures DROP COLUMN IF EXISTS venue_name, DROP COLUMN IF EXISTS venue_city")
    op.execute("ALTER TABLE core.venues DROP COLUMN IF EXISTS image_url")
