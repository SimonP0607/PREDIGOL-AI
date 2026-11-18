"""The precomputed statistics of teams, players and competitions (plan EA, pieces EA-003 to EA-006): ``analytics.stat_documents``

WHY THIS EXISTS
---------------
The advanced profiles, the comparisons and the Match Center (contract C-13) draw percentiles, the goal pulse with its band, goals by
interval, the survival of 0-0, game states and the trends matrix with Wilson intervals. None of it is computed when a reader asks: a
nightly pass (``fbi.stats.job``, switch ``FBI_STATS_AGG``) reads what is already stored - ``market.fixture_outcomes``,
``core.fixture_team_stats``, ``core.fixture_events``, ``core.fixture_player_stats`` and the line-ups - and writes one document per entity,
competition season, scope and context. The page changes series; it never recomputes.

WHAT CHANGES
------------
* ``analytics.stat_documents``: one row per (kind, entity, competition season, scope, context) - ``kind`` is ``team``, ``player`` or
  ``league`` (the reference of a competition season: its distributions and the coverage of every metric). ``doc`` is the document as
  the contract's builder reads it, with the version of the calculation (``calc_version``), the sample it rests on and when it was
  computed. A newer pass replaces the row (the calculation is versioned; a new version is a new value of ``calc_version``).
* ``analytics.stat_runs``: one row per pass - when, which calculation, how many documents, how long, and why it stopped if it did.

Nothing here is read by a model, a pick, a decision or a settlement. A new table: no lock on ``core.fixtures`` (the lesson of 0163).
Downgrade: drops both tables (the documents are recomputed by the next pass).

Revision ID: 0167
Revises: 0166
"""

from __future__ import annotations

from alembic import op

revision = "0167"
down_revision = "0166"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE SCHEMA IF NOT EXISTS analytics;
        CREATE TABLE analytics.stat_documents (
            kind                   TEXT         NOT NULL CHECK (kind IN ('team', 'player', 'league')),
            entity_id              BIGINT       NOT NULL,
            competition_season_id  BIGINT       NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            scope                  TEXT         NOT NULL CHECK (scope IN ('u5', 'u10', 'u20', 'season')),
            context                TEXT         NOT NULL CHECK (context IN ('all', 'home', 'away')),
            calc_version           TEXT         NOT NULL CHECK (calc_version ~ '^[a-z][a-z0-9-]{1,40}-v[0-9]+$'),
            sample                 INTEGER      NOT NULL CHECK (sample >= 0),
            doc                    JSONB        NOT NULL CHECK (jsonb_typeof(doc) = 'object'),
            computed_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (kind, entity_id, competition_season_id, scope, context)
        );
        CREATE INDEX stat_documents_season ON analytics.stat_documents (competition_season_id, kind);
        CREATE INDEX stat_documents_entity ON analytics.stat_documents (kind, entity_id, computed_at DESC);
        COMMENT ON TABLE analytics.stat_documents IS
          'EA-003 to EA-006 (C-13): precomputed statistics of a team, a player or a competition season, by scope and context. Written by '
          'the nightly pass of fbi.stats.job (FBI_STATS_AGG) from stored data only; read by the statistics pages. No model, pick or '
          'settlement reads it.';

        CREATE TABLE analytics.stat_runs (
            id               BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            started_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            finished_at      TIMESTAMPTZ,
            calc_version     TEXT         NOT NULL,
            seasons          INTEGER      NOT NULL DEFAULT 0 CHECK (seasons >= 0),
            documents        INTEGER      NOT NULL DEFAULT 0 CHECK (documents >= 0),
            seconds          NUMERIC(10,2),
            stopped_reason   TEXT,
            code_version     TEXT
        );
        COMMENT ON TABLE analytics.stat_runs IS 'EA-003: one row per nightly pass of the statistics documents.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS analytics.stat_runs")
    op.execute("DROP TABLE IF EXISTS analytics.stat_documents")
