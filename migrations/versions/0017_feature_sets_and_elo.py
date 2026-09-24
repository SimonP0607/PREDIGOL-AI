"""feature sets with lineage, Elo history - and leakage the database refuses

Every feature vector the models see is stored as a feature set: which fixture
it describes, which feature version produced it, the data cut-off it was
computed as of, how many historical results it consumed and the kick-off of
the newest one, a hash of exactly those inputs, and the code that ran.

Two invariants are enforced by PostgreSQL rather than by convention:

  * newest_input_at < data_cutoff - no input can be as recent as the cut-off;
  * data_cutoff <= the fixture's kick-off - a pre-match feature set cannot be
    computed from a moment after the match started.

A bug that tried to persist a leaking feature set fails with a constraint
violation instead of quietly inflating every backtest built on it.

features.elo_ratings keeps the full rating history - team, rating before,
rating after, fixture, kick-off, version - so any rating can be recomputed and
audited, and a changed parameter set is a new version, never an overwrite.

Revision ID: 0017
Revises: 0016
"""

from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE features.feature_sets (
    id               BIGSERIAL   PRIMARY KEY,
    fixture_id       BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    feature_version  TEXT        NOT NULL,
    data_cutoff      TIMESTAMPTZ NOT NULL,
    generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    code_version     TEXT        NOT NULL,
    run_id           BIGINT      REFERENCES raw.ingestion_runs(id),
    input_hash       TEXT        NOT NULL,
    n_inputs         INTEGER     NOT NULL CHECK (n_inputs >= 0),
    newest_input_at  TIMESTAMPTZ,
    lineage          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (fixture_id, feature_version, data_cutoff, input_hash),
    CONSTRAINT feature_sets_no_input_at_or_after_cutoff
        CHECK (newest_input_at IS NULL OR newest_input_at < data_cutoff)
);

CREATE INDEX feature_sets_version_cutoff_idx ON features.feature_sets (feature_version, data_cutoff);

CREATE FUNCTION features.reject_post_kickoff_cutoff() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE ko TIMESTAMPTZ;
BEGIN
    SELECT kickoff_at INTO ko FROM core.fixtures WHERE id = NEW.fixture_id;
    IF ko IS NOT NULL AND NEW.data_cutoff > ko THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = format('feature set cut-off %s is after kick-off %s of fixture %s: that is leakage',
                             NEW.data_cutoff, ko, NEW.fixture_id);
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER feature_sets_cutoff_before_kickoff
    BEFORE INSERT OR UPDATE ON features.feature_sets
    FOR EACH ROW EXECUTE FUNCTION features.reject_post_kickoff_cutoff();

CREATE TABLE features.fixture_features (
    feature_set_id  BIGINT NOT NULL REFERENCES features.feature_sets(id) ON DELETE CASCADE,
    name            TEXT   NOT NULL REFERENCES features.feature_registry(name),
    value           DOUBLE PRECISION,
    PRIMARY KEY (feature_set_id, name)
);

COMMENT ON TABLE features.feature_sets IS
  'One feature vector for one fixture, as of one data cut-off. The CHECK and the
   trigger make it impossible to store a vector computed from anything at or
   after the cut-off, or a cut-off after kick-off.';
COMMENT ON COLUMN features.feature_sets.newest_input_at IS
  'Kick-off of the most recent historical result consumed. NULL when none was.';
COMMENT ON COLUMN features.feature_sets.input_hash IS
  'sha256 over the ordered (fixture id, score) pairs consumed: the same inputs
   always hash the same, so an unexplained change in a vector is detectable.
   Part of the unique key: when more history is backfilled, the same fixture
   and cut-off get a NEW feature set with more inputs - the old one, and every
   prediction made from it, stays auditable. Append-only.';
COMMENT ON COLUMN features.fixture_features.value IS
  'NULL means not computable from the available history (e.g. a team with no
   previous match), never zero.';

CREATE TABLE features.elo_ratings (
    elo_version     TEXT             NOT NULL,
    run_id          BIGINT           NOT NULL REFERENCES raw.ingestion_runs(id),
    team_id         BIGINT           NOT NULL REFERENCES core.teams(id),
    fixture_id      BIGINT           NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    kickoff_at      TIMESTAMPTZ      NOT NULL,
    rating_before   DOUBLE PRECISION NOT NULL,
    rating_after    DOUBLE PRECISION NOT NULL,
    expected_score  DOUBLE PRECISION NOT NULL CHECK (expected_score >= 0 AND expected_score <= 1),
    actual_score    DOUBLE PRECISION NOT NULL CHECK (actual_score IN (0, 0.5, 1)),
    k_factor        DOUBLE PRECISION NOT NULL CHECK (k_factor > 0),
    margin_multiplier DOUBLE PRECISION NOT NULL CHECK (margin_multiplier >= 1),
    computed_at     TIMESTAMPTZ      NOT NULL DEFAULT now(),
    PRIMARY KEY (elo_version, run_id, team_id, fixture_id)
);

CREATE INDEX elo_ratings_team_time_idx ON features.elo_ratings (elo_version, run_id, team_id, kickoff_at DESC);

COMMENT ON TABLE features.elo_ratings IS
  'Walk-forward Elo history. rating_before is what was known going into the
   fixture; rating_after is the update from its result. Every full computation is
   a run: backfilling an earlier season changes every later rating, and that is a
   new run, not an overwrite. A new parameter set is a new elo_version.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS features.elo_ratings;
DROP TABLE IF EXISTS features.fixture_features;
DROP TRIGGER IF EXISTS feature_sets_cutoff_before_kickoff ON features.feature_sets;
DROP FUNCTION IF EXISTS features.reject_post_kickoff_cutoff();
DROP TABLE IF EXISTS features.feature_sets;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
