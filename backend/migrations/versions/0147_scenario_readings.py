"""The readings of the scenarios engine (IA-082, plan piece AD-B02): one append-only table, and nothing else

WHY THIS EXISTS
---------------
``fbi.competitions.scenarios`` (``scenarios-v2``) says, for each team of a coded competition, what it is still playing for, what is
mathematically decided (proved) and how likely the rest is with our goal model. It runs in SHADOW (``FBI_SCENARIOS``, ``off`` by
default): when the owner turns it to ``shadow``, the worker writes one reading per live coded competition season every few hours, and
this table keeps them all, so that any reading can be traced to its inputs (the rules version and sha256, the model and its spec, the
number of simulations and the seed) and compared, later, with what happened.

WHAT CHANGES
------------
- ``intel.scenario_readings``: one row per (competition season, moment) with the whole reading as JSON. A reading whose inputs are
  the same as the newest one of its season is not written again (``input_hash``). Append-only: ``ai.refuse_change()``
  refuses UPDATE and DELETE.

Nothing reads it to decide, publish or price; no reader of the product reads it. No data is written by the migration.

Downgrade: drops the table and its function.

Revision ID: 0147
Revises: 0143 (provisional: the highest revision in this tree; it goes on top of the highest when the branches are merged)
"""

from alembic import op

revision = "0147"
down_revision = "0146"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE intel.scenario_readings (
            id                     BIGSERIAL    PRIMARY KEY,
            computed_at            TIMESTAMPTZ  NOT NULL,
            league_id              INTEGER      NOT NULL CHECK (league_id >= 1),
            season                 INTEGER      NOT NULL CHECK (season BETWEEN 1990 AND 2100),
            competition_season_id  BIGINT       NOT NULL REFERENCES core.competition_seasons(id),
            status                 TEXT         NOT NULL CHECK (status IN ('ok', 'reglamento_no_codificado')),
            engine_version         TEXT         NOT NULL CHECK (engine_version ~ '^scenarios-v[0-9]+$'),
            rules_version          INTEGER      CHECK (rules_version IS NULL OR rules_version >= 1),
            rules_sha256           TEXT         CHECK (rules_sha256 IS NULL OR rules_sha256 ~ '{SHA256}'),
            model                  TEXT,
            sims                   INTEGER      NOT NULL CHECK (sims >= 0),
            seed                   BIGINT       NOT NULL,
            input_hash             TEXT         NOT NULL CHECK (input_hash ~ '{SHA256}'),
            contradictions         INTEGER      NOT NULL DEFAULT 0 CHECK (contradictions >= 0),
            reading                JSONB        NOT NULL CHECK (jsonb_typeof(reading) = 'object'),
            code_version           TEXT,
            created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CHECK ((status = 'ok') = (rules_version IS NOT NULL AND rules_sha256 IS NOT NULL))
        );
        CREATE INDEX intel_scenario_readings_season ON intel.scenario_readings (competition_season_id, id DESC);
        CREATE INDEX intel_scenario_readings_at ON intel.scenario_readings (computed_at DESC);
        COMMENT ON TABLE intel.scenario_readings IS
          'IA-082: what each team of a coded competition is still playing for (scenarios-v2): objectives from the coded rules, what is '
          'proved decided, and the simulated probability of the rest with our goal model. Shadow only (FBI_SCENARIOS); append-only; '
          'nothing reads it to decide or publish.';
    """)
    op.execute("CREATE TRIGGER scenario_readings_append_only BEFORE UPDATE OR DELETE ON intel.scenario_readings "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.scenario_readings")
