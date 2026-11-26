"""The store of verdicts of the experiments and the state «ARCHIVED» of a hypothesis (plan RP-8.1, findings H24 and H25)

WHY THIS EXISTS
---------------
The learning cycle has hypotheses with a history of stages (``analytics.research_hypotheses``) and experiments with their gate, but no place that says,
once and for good, WHAT an experiment concluded: 65 experiments, the last one of 4-Oct, 0 proposals. The plan asks for a store of verdicts bound to the
protocol and the thresholds that were fixed before the data was seen, and for a state that lets 96 undecided hypotheses be put away without deleting
any of them.

WHAT CHANGES (additive; ``lock_timeout`` 10 s; no row is rewritten or deleted)
* ``analytics.experiment_verdicts``: append-only. One row is one verdict (``exito``, ``abandono`` or ``insuficiente``) of one experiment of the plan
  (``EXP-E1`` ... ``EXP-E8``), with the version and the FINGERPRINT of the protocol it stands on (64 hex), the thresholds and the population it was judged
  on, the day it was computed and who recorded it. A verdict of success or abandonment carries its mean and its interval; «insufficient» may not. Nothing is
  updated or deleted (trigger); a newer verdict of the same experiment supersedes the older one in the view ``analytics.experiment_verdicts_latest``.
  The rule that the protocol exists BEFORE the verdict (the registry, the fingerprint, the date of the signature) is checked by the code that writes
  (``fbi.research.verdicts.record``), which refuses to write otherwise; the table keeps the fingerprint so that the claim can be audited later.
* ``analytics.research_hypotheses`` accepts the status ``ARCHIVED``: a hypothesis put away with its reason in the history of stages (RP-8.2). Archiving
  is a state, not a deletion, and a later decision may reopen it.

Downgrade drops the view and the table of verdicts and puts the old status list back NOT VALID (rows already ``ARCHIVED`` stay: a constraint added NOT VALID
holds for new rows only).

Revision ID: 0183
Revises: 0182
"""

from __future__ import annotations

from alembic import op

revision = "0183"
down_revision = "0182"
branch_labels = None
depends_on = None

OLD_STATUSES = "'PROPOSED', 'INVESTIGATING', 'ACCEPTED', 'REJECTED', 'RUNNING', 'SHADOW', 'DONE', 'PROMOTED'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE analytics.experiment_verdicts (
            id                   BIGSERIAL        PRIMARY KEY,
            experiment           TEXT             NOT NULL CHECK (experiment ~ '^EXP-E[0-9]{1,2}$'),
            protocol_version     TEXT             NOT NULL CHECK (length(btrim(protocol_version)) > 0),
            protocol_fingerprint TEXT             NOT NULL CHECK (protocol_fingerprint ~ '^[0-9a-f]{64}$'),
            verdict              TEXT             NOT NULL CHECK (verdict IN ('exito', 'abandono', 'insuficiente')),
            reason               TEXT             NOT NULL CHECK (length(btrim(reason)) >= 10),
            n                    INTEGER          NOT NULL CHECK (n >= 0),
            mean                 DOUBLE PRECISION,
            low                  DOUBLE PRECISION,
            high                 DOUBLE PRECISION,
            adjusted_p           DOUBLE PRECISION CHECK (adjusted_p IS NULL OR adjusted_p BETWEEN 0 AND 1),
            thresholds           JSONB            NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(thresholds) = 'object'),
            population           JSONB            NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(population) = 'object'),
            computed_at          TIMESTAMPTZ      NOT NULL,
            recorded_at          TIMESTAMPTZ      NOT NULL DEFAULT now(),
            recorded_by          TEXT             NOT NULL CHECK (recorded_by IN ('system', 'owner')),
            CONSTRAINT experiment_verdicts_a_decided_verdict_has_its_figures CHECK (
                verdict = 'insuficiente' OR (mean IS NOT NULL AND low IS NOT NULL AND high IS NOT NULL AND low <= high))
        )""")
    op.execute("CREATE INDEX experiment_verdicts_by_experiment ON analytics.experiment_verdicts (experiment, id DESC)")
    op.execute("""
        COMMENT ON TABLE analytics.experiment_verdicts IS
        'What each experiment of the plan concluded (exito, abandono, insuficiente), with the version and the fingerprint of the protocol fixed
         before its data, the thresholds and the population it was judged on. Append-only; a newer verdict of the same experiment supersedes the
         older (view experiment_verdicts_latest). The code that writes refuses a verdict whose protocol is not registered, whose fingerprint
         differs or that was computed before the protocol was signed (fbi.research.verdicts.record).'""")
    op.execute("""
        CREATE VIEW analytics.experiment_verdicts_latest AS
        SELECT DISTINCT ON (experiment) id, experiment, protocol_version, protocol_fingerprint, verdict, reason, n, mean, low, high, adjusted_p,
               thresholds, population, computed_at, recorded_at, recorded_by
          FROM analytics.experiment_verdicts
         ORDER BY experiment, id DESC""")
    op.execute("CREATE TRIGGER experiment_verdicts_append_only BEFORE UPDATE OR DELETE ON analytics.experiment_verdicts "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")
    op.execute("ALTER TABLE analytics.research_hypotheses DROP CONSTRAINT research_hypotheses_status_check")
    op.execute(f"ALTER TABLE analytics.research_hypotheses ADD CONSTRAINT research_hypotheses_status_check "
               f"CHECK (status IN ({OLD_STATUSES}, 'ARCHIVED'))")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE analytics.research_hypotheses DROP CONSTRAINT research_hypotheses_status_check")
    op.execute(f"ALTER TABLE analytics.research_hypotheses ADD CONSTRAINT research_hypotheses_status_check "
               f"CHECK (status IN ({OLD_STATUSES})) NOT VALID")
    op.execute("DROP VIEW IF EXISTS analytics.experiment_verdicts_latest")
    op.execute("DROP TABLE IF EXISTS analytics.experiment_verdicts")
