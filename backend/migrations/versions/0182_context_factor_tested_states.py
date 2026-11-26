"""intel.context_factors can say «tested, no effect» and «tested, with effect», each tied to the experiment (plan RP-4.5, finding H18)

WHY THIS EXISTS
---------------
The registry of context factors (revision 0088) knows two states: DESCRIPTIVE (born so; PrediGol says it, nothing uses it) and VALIDATED (a person
decided, citing an experiment, that it adds something). The audit of 24-nov found the two factors in the registry both descriptive and, measured
against the market, the rest-and-table residuals inside their error: a factor can be TESTED and found to do nothing, and today the registry cannot say
so. The plan asks for the two missing states so that «nobody has tested it» and «somebody tested it and it did nothing» stop looking the same.

WHAT CHANGES (additive; ``lock_timeout`` 10 s; no row is rewritten or deleted, the table stays append-only)
* ``status`` accepts ``TESTED_NO_EFFECT`` and ``TESTED_EFFECT`` besides the two it had.
* A row of either new state cites its experiment and the experiment's result, exactly as a validation does (the experiment's name, a non-empty
  result object, and the factor and version it is about), but it may be written by the system: measuring is not deciding. VALIDATED still needs a
  person, as before. Neither new state lets a model or the AI use the factor: only VALIDATED does (``fbi.intel.factors.usable_as_signal``).
* The two old constraints (the status list and «a validation needs a person and an experiment») are replaced by one list and one rule that says both.

Downgrade puts the two old constraints back NOT VALID (rows of the new states, if any were written, stay: the table is append-only, and a constraint
added NOT VALID is enforced for new rows only).

Revision ID: 0182
Revises: 0181
"""

from __future__ import annotations

from alembic import op

revision = "0182"
down_revision = "0181"
branch_labels = None
depends_on = None

CITES = """jsonb_typeof(evidence -> 'experiment') = 'string'
                    AND length(btrim(evidence ->> 'experiment')) > 0
                    AND jsonb_typeof(evidence -> 'result') = 'object'
                    AND evidence -> 'result' <> '{}'::jsonb
                    AND evidence ->> 'factor' = factor
                    AND evidence ->> 'version' = version"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE intel.context_factors DROP CONSTRAINT context_factors_status_check")
    op.execute("ALTER TABLE intel.context_factors DROP CONSTRAINT context_factors_validated_by_a_person_with_an_experiment")
    op.execute("ALTER TABLE intel.context_factors ADD CONSTRAINT context_factors_status_check "
               "CHECK (status IN ('DESCRIPTIVE', 'TESTED_NO_EFFECT', 'TESTED_EFFECT', 'VALIDATED'))")
    op.execute(f"""
        ALTER TABLE intel.context_factors ADD CONSTRAINT context_factors_a_claim_cites_its_experiment CHECK (
            status = 'DESCRIPTIVE' OR COALESCE(
                {CITES}
                AND (status IN ('TESTED_NO_EFFECT', 'TESTED_EFFECT') OR decided_by = 'owner'), false))""")
    op.execute("""
        COMMENT ON TABLE intel.context_factors IS
        'The decisions about each context factor of the pre-match packet, per version of the code that computes it. No row = DESCRIPTIVE:
         PrediGol says it, no model reads it and the AI may not use it to move a probability. TESTED_NO_EFFECT / TESTED_EFFECT: an experiment
         measured it (cites the experiment, its result, the factor and the version; the system may write it); neither lets anything use it.
         VALIDATED needs a person (decided_by owner, who) besides. Taking a validation back is a DESCRIPTIVE row. Each row cites the previous one
         of its (factor, version). Append-only. python -m scripts.context_factors list.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE intel.context_factors DROP CONSTRAINT context_factors_a_claim_cites_its_experiment")
    op.execute("ALTER TABLE intel.context_factors DROP CONSTRAINT context_factors_status_check")
    op.execute("ALTER TABLE intel.context_factors ADD CONSTRAINT context_factors_status_check "
               "CHECK (status IN ('DESCRIPTIVE', 'VALIDATED')) NOT VALID")
    op.execute(f"""
        ALTER TABLE intel.context_factors ADD CONSTRAINT context_factors_validated_by_a_person_with_an_experiment CHECK (
            status = 'DESCRIPTIVE' OR COALESCE(
                decided_by = 'owner'
                AND {CITES}, false)) NOT VALID""")
