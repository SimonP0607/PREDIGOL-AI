"""match detail: team statistics, events, lineups, player statistics, absences, coverage

What a historical backfill brings besides fixtures and scores, in tables that
already exist before the first request is paid for:

* ``core.fixture_team_stats`` - per team and per source: shots, shots on
  target, corners, cards, possession, passes, expected goals. Two sources on
  purpose: Football-Data.co.uk (shots, corners, fouls, cards for the big
  leagues, already in the raw store) and API-Football /fixtures?ids= (the
  sixteen documented statistics plus expected goals where it sends them).
  A value the source did not report is NULL - never zero.
* ``core.fixture_events`` - goals, cards, substitutions and VAR decisions with
  their minute, in the order the provider listed them. No coordinates: the
  provider has none.
* ``core.fixture_lineups`` / ``core.fixture_lineup_players`` - formation, coach,
  starting eleven and bench, with the provider's grid position.
* ``core.fixture_player_stats`` - one row per player and fixture.
* ``core.player_absences`` - /injuries: who was missing or doubtful for a
  fixture and why (the provider keeps these from April 2021 only).
* ``raw.league_coverage`` - the provider's own per-season coverage flags,
  which decide what the backfill asks for: a season flagged without
  statistics is not queried for statistics.

Every row names the payload it came from.

Revision ID: 0022
Revises: 0021
"""

from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE core.fixture_team_stats (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    team_side           TEXT        NOT NULL CHECK (team_side IN ('home', 'away')),
    source              TEXT        NOT NULL CHECK (source IN ('api-football', 'football-data.co.uk')),
    shots               SMALLINT    CHECK (shots >= 0),
    shots_on_target     SMALLINT    CHECK (shots_on_target >= 0),
    shots_off_target    SMALLINT    CHECK (shots_off_target >= 0),
    shots_blocked       SMALLINT    CHECK (shots_blocked >= 0),
    shots_inside_box    SMALLINT    CHECK (shots_inside_box >= 0),
    shots_outside_box   SMALLINT    CHECK (shots_outside_box >= 0),
    corners             SMALLINT    CHECK (corners >= 0),
    fouls               SMALLINT    CHECK (fouls >= 0),
    offsides            SMALLINT    CHECK (offsides >= 0),
    yellow_cards        SMALLINT    CHECK (yellow_cards >= 0),
    red_cards           SMALLINT    CHECK (red_cards >= 0),
    saves               SMALLINT    CHECK (saves >= 0),
    possession_pct      NUMERIC(5,2) CHECK (possession_pct BETWEEN 0 AND 100),
    passes              SMALLINT    CHECK (passes >= 0),
    passes_accurate     SMALLINT    CHECK (passes_accurate >= 0),
    expected_goals      NUMERIC(6,3) CHECK (expected_goals >= 0),
    goals_prevented     NUMERIC(6,3),
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fixture_id, team_side, source),
    CHECK (shots_on_target IS NULL OR shots IS NULL OR shots_on_target <= shots),
    CHECK (passes_accurate IS NULL OR passes IS NULL OR passes_accurate <= passes)
);
COMMENT ON TABLE core.fixture_team_stats IS
  'Team match statistics per source. NULL means the source did not report it - never zero.
   Written with the payload they came from; a newer payload for the same fixture and source replaces the row.';

CREATE TABLE core.fixture_events (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    source              TEXT        NOT NULL CHECK (source IN ('api-football')),
    seq                 SMALLINT    NOT NULL CHECK (seq >= 0),
    minute              SMALLINT    NOT NULL CHECK (minute >= 0),
    extra_minute        SMALLINT    CHECK (extra_minute >= 0),
    team_side           TEXT        CHECK (team_side IN ('home', 'away')),
    provider_team_id    INTEGER,
    provider_player_id  INTEGER,
    player_name         TEXT,
    provider_assist_id  INTEGER,
    assist_name         TEXT,
    event_type          TEXT        NOT NULL,
    detail              TEXT,
    comments            TEXT,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fixture_id, source, seq)
);
COMMENT ON TABLE core.fixture_events IS
  'Goals, cards, substitutions and VAR decisions, in the provider''s order. No pitch coordinates exist in this source.
   The list for a fixture is replaced as a whole when a newer payload arrives (VAR can overturn a goal).';

CREATE TABLE core.fixture_lineups (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    team_side           TEXT        NOT NULL CHECK (team_side IN ('home', 'away')),
    source              TEXT        NOT NULL CHECK (source IN ('api-football')),
    formation           TEXT,
    provider_coach_id   INTEGER,
    coach_name          TEXT,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fixture_id, team_side, source)
);

CREATE TABLE core.fixture_lineup_players (
    fixture_id          BIGINT      NOT NULL,
    team_side           TEXT        NOT NULL,
    source              TEXT        NOT NULL,
    provider_player_id  INTEGER     NOT NULL,
    player_name         TEXT,
    shirt_number        SMALLINT,
    position            TEXT,
    grid                TEXT,
    is_starter          BOOLEAN     NOT NULL,
    PRIMARY KEY (fixture_id, team_side, source, provider_player_id),
    FOREIGN KEY (fixture_id, team_side, source)
        REFERENCES core.fixture_lineups(fixture_id, team_side, source) ON DELETE CASCADE
);

CREATE TABLE core.fixture_player_stats (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    source              TEXT        NOT NULL CHECK (source IN ('api-football')),
    provider_player_id  INTEGER     NOT NULL,
    team_side           TEXT        NOT NULL CHECK (team_side IN ('home', 'away')),
    player_name         TEXT,
    minutes             SMALLINT    CHECK (minutes >= 0),
    rating              NUMERIC(4,2),
    is_captain          BOOLEAN,
    is_substitute       BOOLEAN,
    shots_total         SMALLINT    CHECK (shots_total >= 0),
    shots_on            SMALLINT    CHECK (shots_on >= 0),
    goals               SMALLINT    CHECK (goals >= 0),
    goals_conceded      SMALLINT    CHECK (goals_conceded >= 0),
    assists             SMALLINT    CHECK (assists >= 0),
    saves               SMALLINT    CHECK (saves >= 0),
    passes_total        SMALLINT    CHECK (passes_total >= 0),
    passes_key          SMALLINT    CHECK (passes_key >= 0),
    passes_accuracy_pct NUMERIC(5,2),
    tackles             SMALLINT    CHECK (tackles >= 0),
    blocks              SMALLINT    CHECK (blocks >= 0),
    interceptions       SMALLINT    CHECK (interceptions >= 0),
    duels_total         SMALLINT    CHECK (duels_total >= 0),
    duels_won           SMALLINT    CHECK (duels_won >= 0),
    dribbles_attempts   SMALLINT    CHECK (dribbles_attempts >= 0),
    dribbles_success    SMALLINT    CHECK (dribbles_success >= 0),
    fouls_drawn         SMALLINT    CHECK (fouls_drawn >= 0),
    fouls_committed     SMALLINT    CHECK (fouls_committed >= 0),
    yellow_cards        SMALLINT    CHECK (yellow_cards >= 0),
    red_cards           SMALLINT    CHECK (red_cards >= 0),
    penalties_scored    SMALLINT    CHECK (penalties_scored >= 0),
    penalties_missed    SMALLINT    CHECK (penalties_missed >= 0),
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fixture_id, source, provider_player_id)
);

CREATE TABLE core.player_absences (
    source              TEXT        NOT NULL CHECK (source IN ('api-football')),
    provider_fixture_id INTEGER     NOT NULL,
    provider_player_id  INTEGER     NOT NULL,
    fixture_id          BIGINT      REFERENCES core.fixtures(id) ON DELETE SET NULL,
    provider_team_id    INTEGER,
    player_name         TEXT,
    absence_type        TEXT,
    reason              TEXT,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source, provider_fixture_id, provider_player_id)
);
COMMENT ON TABLE core.player_absences IS
  'Players reported missing or doubtful for a fixture (API-Football /injuries; available from April 2021 only).';

CREATE TABLE raw.league_coverage (
    provider            TEXT        NOT NULL DEFAULT 'api_football',
    provider_league_id  INTEGER     NOT NULL,
    season              INTEGER     NOT NULL,
    league_name         TEXT,
    country             TEXT,
    league_type         TEXT,
    is_current          BOOLEAN,
    start_date          DATE,
    end_date            DATE,
    events              BOOLEAN,
    lineups             BOOLEAN,
    statistics_fixtures BOOLEAN,
    statistics_players  BOOLEAN,
    standings           BOOLEAN,
    players             BOOLEAN,
    top_scorers         BOOLEAN,
    top_assists         BOOLEAN,
    top_cards           BOOLEAN,
    injuries            BOOLEAN,
    predictions         BOOLEAN,
    odds                BOOLEAN,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    observed_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (provider, provider_league_id, season)
);
COMMENT ON TABLE raw.league_coverage IS
  'The provider''s coverage flags per league and season, as observed at observed_at. They describe what the provider
   says it has; "true does not guarantee 100% availability" (provider docs). The migration planner reads them.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS raw.league_coverage;
DROP TABLE IF EXISTS core.player_absences;
DROP TABLE IF EXISTS core.fixture_player_stats;
DROP TABLE IF EXISTS core.fixture_lineup_players;
DROP TABLE IF EXISTS core.fixture_lineups;
DROP TABLE IF EXISTS core.fixture_events;
DROP TABLE IF EXISTS core.fixture_team_stats;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
