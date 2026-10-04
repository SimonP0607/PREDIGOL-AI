"""fixture facts and player extras: fields the provider sends that the normalizers dropped (field coverage audit)

The field coverage audit (4 Oct 2026) found fields every /fixtures payload carries with values that no
table held: the referee, each side's winner flag and when each half started; and, per player and match,
the position actually played, offsides, times dribbled past, penalties won, committed and saved. They
stay in RAW, so they are filled from the stored payloads - no request - into NEW tables:

* ``core.fixture_facts`` - one row per change of what a fixture's payloads say (referee, country, winner
  flags, half starts), with the payload that said it and the normalizer version. The first observation
  that says anything, and every later one that says something different, add a row; nothing is updated.
* ``core.fixture_player_extras`` - the same for a player's per-match extras.
* ``core.fixture_facts_latest`` / ``core.fixture_player_extras_latest`` - the newest row of each.

Revision ID: 0058
Revises: 0057
"""

from __future__ import annotations

from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.fixture_facts (
            fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            observed_at         TIMESTAMPTZ NOT NULL,
            referee             TEXT,
            referee_country     TEXT,
            home_winner         BOOLEAN,
            away_winner         BOOLEAN,
            first_half_at       TIMESTAMPTZ,
            second_half_at      TIMESTAMPTZ,
            payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            normalizer_version  TEXT        NOT NULL,
            PRIMARY KEY (fixture_id, observed_at),
            CHECK (NOT (home_winner AND away_winner))
        )""")
    op.execute("""
        COMMENT ON TABLE core.fixture_facts IS
        'What /fixtures payloads say about a match beyond identity, status and score (referee, winner flags,
         half starts): a row per change, with the payload that said it. Filled from RAW for the past.'""")
    op.execute("""
        CREATE OR REPLACE VIEW core.fixture_facts_latest AS
        SELECT DISTINCT ON (fixture_id) * FROM core.fixture_facts ORDER BY fixture_id, observed_at DESC""")
    op.execute("CREATE INDEX IF NOT EXISTS fixture_facts_referee ON core.fixture_facts (referee) "
               "WHERE referee IS NOT NULL")
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.fixture_player_extras (
            fixture_id           BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            provider_player_id   INTEGER     NOT NULL,
            observed_at          TIMESTAMPTZ NOT NULL,
            team_side            TEXT        CHECK (team_side IN ('home', 'away')),
            position_played      TEXT,
            offsides             SMALLINT    CHECK (offsides >= 0),
            dribbled_past        SMALLINT    CHECK (dribbled_past >= 0),
            penalties_won        SMALLINT    CHECK (penalties_won >= 0),
            penalties_committed  SMALLINT    CHECK (penalties_committed >= 0),
            penalties_saved      SMALLINT    CHECK (penalties_saved >= 0),
            payload_hash         TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            normalizer_version   TEXT        NOT NULL,
            PRIMARY KEY (fixture_id, provider_player_id, observed_at)
        )""")
    op.execute("""
        COMMENT ON TABLE core.fixture_player_extras IS
        'Per player and match, what /fixtures?ids= sends that core.fixture_player_stats has no column for: the
         position played, offsides, dribbled past, penalties won / committed / saved. A row per change.'""")
    op.execute("""
        CREATE OR REPLACE VIEW core.fixture_player_extras_latest AS
        SELECT DISTINCT ON (fixture_id, provider_player_id) * FROM core.fixture_player_extras
         ORDER BY fixture_id, provider_player_id, observed_at DESC""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.fixture_player_extras_latest; DROP TABLE IF EXISTS core.fixture_player_extras; "
               "DROP VIEW IF EXISTS core.fixture_facts_latest; DROP TABLE IF EXISTS core.fixture_facts;")
