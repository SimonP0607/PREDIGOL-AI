"""historical validation: each played match's state, and each competition-season's data score

A row in core.fixtures says the provider listed a match; it does not say the match is fit
to train or judge a model on. GATE C adds the judgement, versioned and recomputable:

* analytics.fixture_validation: one row per finished match - INGESTED (stored, no usable
  result yet), VALIDATED (passes every integrity rule), HISTORICAL_APPROVED (validated, rated
  by Elo, in a competition-season fit for modelling) or QUARANTINED (fails a hard rule: a
  provider duplicate, a score whose parts contradict each other, an extra-time match without
  its 90-minute score). ``failed`` names every rule that failed; nothing is deleted.
* analytics.competition_data_scores: one row per competition-season with finished matches -
  the share of results, integrity, statistics, line-ups, prices and Elo ratings, a weighted
  score, and the class it earns: MODEL_READY, PARTIAL, PRODUCT_ONLY or INSUFFICIENT.
* analytics.model_ready_fixtures: the approved matches with their competition, segment and
  class - the population the feature rebuild and every backtest read.

Revision ID: 0052
Revises: 0051
"""

from __future__ import annotations

from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS analytics.competition_data_scores (
            competition_season_id BIGINT       PRIMARY KEY REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            computed_at           TIMESTAMPTZ  NOT NULL,
            rule_version          TEXT         NOT NULL,
            class                 TEXT         NOT NULL
                                  CHECK (class IN ('MODEL_READY', 'PARTIAL', 'PRODUCT_ONLY', 'INSUFFICIENT')),
            score                 NUMERIC(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
            finished              INTEGER      NOT NULL CHECK (finished >= 0),
            approved              INTEGER      NOT NULL CHECK (approved >= 0),
            quarantined           INTEGER      NOT NULL CHECK (quarantined >= 0),
            components            JSONB        NOT NULL,
            reasons               JSONB        NOT NULL DEFAULT '[]'::jsonb
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS analytics.fixture_validation (
            fixture_id   BIGINT      PRIMARY KEY REFERENCES core.fixtures(id) ON DELETE CASCADE,
            state        TEXT        NOT NULL
                         CHECK (state IN ('INGESTED', 'VALIDATED', 'HISTORICAL_APPROVED', 'QUARANTINED')),
            rule_version TEXT        NOT NULL,
            failed       JSONB       NOT NULL DEFAULT '[]'::jsonb,
            validated_at TIMESTAMPTZ NOT NULL
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS fixture_validation_state ON analytics.fixture_validation (state)")
    op.execute("""
        CREATE OR REPLACE VIEW analytics.model_ready_fixtures AS
        SELECT f.id AS fixture_id, f.kickoff_at, f.competition_season_id, cs.competition_id, cs.season,
               c.name AS competition, c.country, c.type AS competition_type, c.gender, c.age_group,
               s.class AS competition_class, v.rule_version
          FROM analytics.fixture_validation v
          JOIN core.fixtures f ON f.id = v.fixture_id
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          JOIN analytics.competition_data_scores s ON s.competition_season_id = cs.id
         WHERE v.state = 'HISTORICAL_APPROVED'""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS analytics.model_ready_fixtures")
    op.execute("DROP TABLE IF EXISTS analytics.fixture_validation")
    op.execute("DROP TABLE IF EXISTS analytics.competition_data_scores")
