"""core layer: normalised sporting model, provider independent

Source of truth: docs/rebuild/schema_v2/003_core.sql

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE core.competitions (
    id                  BIGSERIAL PRIMARY KEY,
    provider_league_id  INTEGER NOT NULL UNIQUE,
    name                TEXT    NOT NULL,
    country             TEXT,
    type                TEXT    NOT NULL CHECK (type IN ('league','cup','supercup','friendly')),
    entity_scope        TEXT    NOT NULL CHECK (entity_scope IN ('club','national_team')),
    competition_type    TEXT    NOT NULL CHECK (competition_type IN
                        ('domestic_league','domestic_cup','continental','international')),
    elo_weight          NUMERIC(4,2) NOT NULL DEFAULT 1.00 CHECK (elo_weight BETWEEN 0 AND 1),
    neutral_venue       BOOLEAN NOT NULL DEFAULT false,
    tier                SMALLINT,
    is_tracked          BOOLEAN NOT NULL DEFAULT false,
    logo_url            TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN core.competitions.elo_weight IS
  'Escala el factor K de Elo. Liga 1.0, continental 0.5-0.8, copa 0.4, amistoso 0.3.';
COMMENT ON COLUMN core.competitions.is_tracked IS
  'Las ligas activas se configuran en FBI_ACTIVE_LEAGUES / esta columna,
   NUNCA hardcodeadas en el dominio.';

CREATE TABLE core.competition_seasons (
    id             BIGSERIAL PRIMARY KEY,
    competition_id BIGINT  NOT NULL REFERENCES core.competitions(id) ON DELETE CASCADE,
    season         INTEGER NOT NULL,
    start_date     DATE,
    end_date       DATE,
    is_current     BOOLEAN NOT NULL DEFAULT false,
    has_odds       BOOLEAN NOT NULL DEFAULT false,
    coverage       JSONB   NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (competition_id, season)
);

CREATE TABLE core.venues (
    id               BIGSERIAL PRIMARY KEY,
    provider_venue_id INTEGER UNIQUE,
    name             TEXT NOT NULL,
    city             TEXT,
    country          TEXT,
    capacity         INTEGER
);

CREATE TABLE core.teams (
    id               BIGSERIAL PRIMARY KEY,
    provider_team_id INTEGER NOT NULL UNIQUE,
    name             TEXT    NOT NULL,
    short_name       TEXT,
    country          TEXT,
    is_national      BOOLEAN NOT NULL DEFAULT false,
    founded          INTEGER,
    venue_id         BIGINT REFERENCES core.venues(id),
    logo_url         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON core.teams (lower(name));

CREATE TABLE core.team_season_memberships (
    team_id                BIGINT NOT NULL REFERENCES core.teams(id) ON DELETE CASCADE,
    competition_season_id  BIGINT NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
    PRIMARY KEY (team_id, competition_season_id)
);

CREATE TABLE core.players (
    id                 BIGSERIAL PRIMARY KEY,
    provider_player_id INTEGER NOT NULL UNIQUE,
    name               TEXT    NOT NULL,
    firstname          TEXT,
    lastname           TEXT,
    birth_date         DATE,
    nationality        TEXT,
    position           TEXT,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE core.fixtures (
    id                    BIGSERIAL PRIMARY KEY,
    provider_fixture_id   BIGINT      NOT NULL UNIQUE,
    competition_season_id BIGINT      NOT NULL REFERENCES core.competition_seasons(id),
    home_team_id          BIGINT      NOT NULL REFERENCES core.teams(id),
    away_team_id          BIGINT      NOT NULL REFERENCES core.teams(id),
    venue_id              BIGINT      REFERENCES core.venues(id),
    kickoff_at            TIMESTAMPTZ NOT NULL,
    round                 TEXT,
    status_short          TEXT        NOT NULL DEFAULT 'NS',
    status_group          TEXT        NOT NULL DEFAULT 'scheduled'
                          CHECK (status_group IN ('scheduled','live','finished','cancelled','postponed')),
    is_neutral            BOOLEAN     NOT NULL DEFAULT false,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (home_team_id <> away_team_id)
);
CREATE INDEX ON core.fixtures (kickoff_at DESC);
CREATE INDEX ON core.fixtures (competition_season_id, kickoff_at);
CREATE INDEX ON core.fixtures (status_group, kickoff_at) WHERE status_group IN ('scheduled','live');

CREATE TABLE core.fixture_results (
    fixture_id      BIGINT PRIMARY KEY REFERENCES core.fixtures(id) ON DELETE CASCADE,
    goals_home      SMALLINT NOT NULL,
    goals_away      SMALLINT NOT NULL,
    ht_goals_home   SMALLINT,
    ht_goals_away   SMALLINT,
    et_goals_home   SMALLINT,
    et_goals_away   SMALLINT,
    pen_home        SMALLINT,
    pen_away        SMALLINT,
    outcome_1x2     TEXT GENERATED ALWAYS AS (
                        CASE WHEN goals_home > goals_away THEN 'Home'
                             WHEN goals_home = goals_away THEN 'Draw'
                             ELSE 'Away' END) STORED,
    total_goals     SMALLINT GENERATED ALWAYS AS (goals_home + goals_away) STORED,
    btts            BOOLEAN  GENERATED ALWAYS AS (goals_home > 0 AND goals_away > 0) STORED,
    settled_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (goals_home >= 0 AND goals_away >= 0)
);
COMMENT ON TABLE core.fixture_results IS
  'Solo partidos con resultado real. Un partido cancelado NO tiene fila aqui.';

CREATE TABLE core.standings (
    competition_season_id BIGINT   NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
    team_id               BIGINT   NOT NULL REFERENCES core.teams(id),
    snapshot_at           TIMESTAMPTZ NOT NULL,
    rank                  SMALLINT NOT NULL,
    points                SMALLINT NOT NULL,
    played                SMALLINT NOT NULL,
    wins                  SMALLINT NOT NULL,
    draws                 SMALLINT NOT NULL,
    losses                SMALLINT NOT NULL,
    goals_for             SMALLINT NOT NULL,
    goals_against         SMALLINT NOT NULL,
    form                  TEXT,
    "group"               TEXT,
    PRIMARY KEY (competition_season_id, team_id, snapshot_at)
);

CREATE TABLE core.team_season_stats (
    competition_season_id BIGINT NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
    team_id               BIGINT NOT NULL REFERENCES core.teams(id),
    snapshot_at           TIMESTAMPTZ NOT NULL,
    played_home           SMALLINT, played_away SMALLINT,
    wins_home             SMALLINT, wins_away   SMALLINT,
    goals_for_home        NUMERIC(6,3), goals_for_away     NUMERIC(6,3),
    goals_against_home    NUMERIC(6,3), goals_against_away NUMERIC(6,3),
    clean_sheets_home     SMALLINT, clean_sheets_away  SMALLINT,
    failed_to_score_home  SMALLINT, failed_to_score_away SMALLINT,
    form                  TEXT,
    raw                   JSONB,
    PRIMARY KEY (competition_season_id, team_id, snapshot_at)
);
COMMENT ON TABLE core.team_season_stats IS
  'goals_for_* / goals_against_* son PROMEDIOS por partido. El legacy tenia un bug
   (_parse_avg) que caia al TOTAL cuando faltaba el promedio, produciendo
   expected_goals de 108, 94, 90, 55 y 15 goles por partido. Los nombres de columna
   aqui son explicitos para que esa confusion no vuelva a ser posible.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS core.team_season_stats;
DROP TABLE IF EXISTS core.standings;
DROP TABLE IF EXISTS core.fixture_results;
DROP TABLE IF EXISTS core.fixtures;
DROP TABLE IF EXISTS core.players;
DROP TABLE IF EXISTS core.team_season_memberships;
DROP TABLE IF EXISTS core.teams;
DROP TABLE IF EXISTS core.venues;
DROP TABLE IF EXISTS core.competition_seasons;
DROP TABLE IF EXISTS core.competitions;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
