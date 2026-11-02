"""The registry of context factors: which of the things PrediGol says about a match are only descriptions, and which an experiment has shown to add something (plan F6, pre-match v3)

WHY THIS EXISTS
---------------
Pre-match v3 puts more context in front of the AI and of the admin: the head-to-head weighed by competition, ground, recency and coach;
what a match alone does to its table and to its tie; the observable tactics of each side; rest and congestion from the calendar in
every competition. Each of them reads like evidence and none has been tested: nobody has shown that a head-to-head weighed that way
predicts a result better than the form of the two sides, or that "needs to win by two" moves a probability. A narrative with the look of
evidence is the risk the plan names for this phase.

So every such factor is born DESCRIPTIVE - PrediGol can say it, no model reads it (``tests/unit/test_context_isolation.py``) and the AI may
not use it to move a probability - and it becomes VALIDATED only when a person decides so, citing the experiment that tested THAT version
of the factor and the result of the experiment. Nothing in this revision changes a model, a forecast, a pick or what a user sees.

WHAT IS ADDED
-------------
``intel.context_factors``  the history of the decisions about each factor, one row per decision. A factor (a key such as ``h2h_weighted``)
    is decided per VERSION of the code that computes it: a validation is a statement about one computation, so a new version of the
    factor starts again as DESCRIPTIVE. The newest row of (factor, version) says what it is; no row means DESCRIPTIVE, which is where every
    factor starts - the table is EMPTY after this migration. A VALIDATED row must be a person's decision (``decided_by = 'owner'``, with
    ``who``), must name the experiment, hold its result and say it is about this factor and this version (a constraint, not a
    convention); taking a validation back is a new DESCRIPTIVE row. The rows of a factor form one line - each cites the one before it
    and two rows cannot cite the same one - so a decision cannot slip in behind another. Append-only (``intel.refuse_change``).
``intel.context_factors_latest``  the newest row of each (factor, version).

Additive. The downgrade drops the view and the table (a record of decisions: export it first if the revision is being undone on a database
that has had a decision). It leaves ``intel.refuse_change()`` (revision 0076's) alone.

Revision ID: 0088
Revises: 0087
"""

from __future__ import annotations

from alembic import op

revision = "0088"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new and refers only to itself.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE intel.context_factors (
            id          BIGSERIAL   PRIMARY KEY,
            factor      TEXT        NOT NULL CHECK (factor ~ '^[a-z][a-z0-9_]{1,62}$'),
            version     TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            status      TEXT        NOT NULL CHECK (status IN ('DESCRIPTIVE', 'VALIDATED')),
            decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            decided_by  TEXT        NOT NULL CHECK (decided_by IN ('owner', 'system')),
            who         TEXT        CHECK (who IS NULL OR length(btrim(who)) > 0),
            reason      TEXT        NOT NULL CHECK (length(btrim(reason)) >= 10),
            evidence    JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
            previous_id BIGINT,
            UNIQUE (id, factor, version),
            FOREIGN KEY (previous_id, factor, version) REFERENCES intel.context_factors (id, factor, version),
            CONSTRAINT context_factors_a_person_is_named CHECK ((decided_by = 'owner') = (who IS NOT NULL)),
            CONSTRAINT context_factors_validated_by_a_person_with_an_experiment CHECK (
                status = 'DESCRIPTIVE' OR COALESCE(
                    decided_by = 'owner'
                    AND jsonb_typeof(evidence -> 'experiment') = 'string'
                    AND length(btrim(evidence ->> 'experiment')) > 0
                    AND jsonb_typeof(evidence -> 'result') = 'object'
                    AND evidence -> 'result' <> '{}'::jsonb
                    AND evidence ->> 'factor' = factor
                    AND evidence ->> 'version' = version, false))
        )""")
    # one line per (factor, version): a single first decision, and no two decisions that follow the same one
    op.execute("CREATE UNIQUE INDEX context_factors_first ON intel.context_factors (factor, version) WHERE previous_id IS NULL")
    op.execute("CREATE UNIQUE INDEX context_factors_next ON intel.context_factors (previous_id) WHERE previous_id IS NOT NULL")
    op.execute("""
        COMMENT ON TABLE intel.context_factors IS
        'The decisions about each context factor of the pre-match packet (head-to-head, scenarios, tactics, rest and congestion),
         per version of the code that computes it. No row = DESCRIPTIVE: PrediGol says it, no model reads it and the AI may not use
         it to move a probability. VALIDATED needs a person (decided_by owner, who), the name of the experiment, its result and the
         factor and version it is about (constraint). Taking it back is a DESCRIPTIVE row. Each row cites the previous one of its
         (factor, version). Append-only. python -m scripts.context_factors list.'""")
    op.execute("""
        CREATE VIEW intel.context_factors_latest AS
        SELECT DISTINCT ON (factor, version) id, factor, version, status, decided_at, decided_by, who, reason, evidence, previous_id
          FROM intel.context_factors
         ORDER BY factor, version, id DESC""")
    op.execute("COMMENT ON VIEW intel.context_factors_latest IS "
               "'The newest decision of each (factor, version) of intel.context_factors: what each factor is today.'")
    op.execute("CREATE TRIGGER context_factors_append_only BEFORE UPDATE OR DELETE ON intel.context_factors "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS intel.context_factors_latest")
    op.execute("DROP TABLE IF EXISTS intel.context_factors")
