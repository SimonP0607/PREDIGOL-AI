"""Plan Maestro IA, Phase 5 - the attribution of the shadow: which agent, in which version, was right or wrong about each settled selection.

Phase 3 runs the multi-agent in shadow (``ma-v1``, ``ma-v1-h``, ``cs-v1``: migration 0119). Phase 5 closes the loop after the result: the SERVER computes,
for every settled selection a shadow engine reviewed, whether each agent's stance pointed towards the result and towards the closing line, and
files the answer in a table of its own. The Post-Match Reviewer (``pmr-v1``) may only add a class to the rows the code left as ``UNKNOWN``; the
Learning Analyst (``la-v1``) reads the rows and proposes hypotheses per agent version. Nothing here is read by a pick, a filter, a decision, a user or a
gate of production. This revision is ADDITIVE:

* ``intel.agent_attributions`` (new, append-only): one row per settled selection, shadow engine, agent, agent version and signal. ``classified_by``
  says who wrote the class of a miss: ``code`` (the rule ``attr-v1``, ``fbi.ai.agents.attribution``) or ``pmr-v1`` (a refinement of a row of the code that
  was ``UNKNOWN``; ``basis_id`` points at it). Idempotent by a unique key: the live computation and the recomputation of an earlier day of the shadow
  write the same rows, and the second to arrive writes nothing. No foreign key: the tables it would point to are the busiest of the database (the
  lesson of 0076) and a row of evidence outlives a cleaned table.
* ``analytics.research_hypotheses`` and ``analytics.experiments``: the nullable columns ``agent`` and ``agent_version`` (both or neither): the agent
  version a hypothesis is about, and the agent version an experiment tests. Rows written before stay as they are (NULL).

On a live database (the worker keeps writing): the two existing tables are altered FIRST and a wait longer than 10 s for either lock fails the migration
whole (the lesson of 0076 and the rule of 0111, 0112, 0115 and 0119). Both are small (hundreds of rows) and neither is read by the decision layer.

Downgrade (``alembic downgrade`` is for development: production goes back by deploying the code that ran before, which works on this schema because
every change here only adds): the columns and the table go. The attributions go with their table, as the shadow assignments of 0119 go with theirs; a later
upgrade recomputes them from the shadow reviews, which stay.

Revision ID: 0120
Revises: 0119
"""

from __future__ import annotations

from alembic import op

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None

SHADOW_ENGINES = ("ma-v1", "ma-v1-h", "cs-v1")
"""``fbi.ai.config.SHADOW_ENGINES``: the engines whose agents are attributed."""
AGENTS = ("match", "stats", "council")
"""``fbi.ai.contracts.postmatch.Attributed``: the agents a signal is attributed to."""
SUBJECTS = ("match", "stats", "council", "reviewer")
"""``fbi.ai.contracts.learning.Subject``: the agent a hypothesis is about (the reviewer is the AI that runs today)."""
SIGNALS = ("ABSENCES", "LINEUP", "SCHEDULE", "STAKES", "FORM", "H2H", "TACTICS", "VENUE", "REFEREE", "MARKET_MOVE", "MODEL_MARKET_GAP", "NEWS",
           "RATE", "DATA_QUALITY", "VERDICT")
"""``fbi.ai.contracts.postmatch.AttributedSignal``: the 14 signals of ``aa-v1`` and the agent's own stance (``VERDICT``)."""
STANCES = ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN", "SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL")
"""The Council's verdicts and the Match Agent's stances."""
CLASSES = ("MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE", "UNKNOWN")
"""``fbi.intel.pm_questions.CLASSES``: one vocabulary of errors, the post-mortem's; ``NONE`` is the class of a hit and of a void."""
OUTCOMES = ("HIT", "MISS", "VOID")
SETTLED = ("win", "loss", "half_win", "half_loss", "push", "void")
CALIBRATIONS = ("MODEL_BETTER", "MARKET_BETTER", "EQUAL")
CLASSIFIERS = ("code", "pmr-v1")
VERSION = "^[a-z][a-z0-9]*(-[a-z0-9]+)*-v[1-9][0-9]{0,2}$"
"""``fbi.ai.agents.registry.VERSION_LABEL``."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # On a live database the worker writes every few minutes: never wait for a lock longer than 10 s (the lesson of 0076). The tables that exist go
    # first, so that a lock that cannot be had stops the migration before it has done anything.
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in ("analytics.research_hypotheses", "analytics.experiments"):
        short = table.split(".")[1]
        op.execute(f"""
            ALTER TABLE {table}
                ADD COLUMN agent         TEXT,
                ADD COLUMN agent_version TEXT,
                ADD CONSTRAINT {short}_agent_check CHECK (agent IS NULL OR agent IN ({_in(SUBJECTS)})),
                ADD CONSTRAINT {short}_agent_version_check CHECK (agent_version IS NULL OR agent_version ~ '{VERSION}'),
                ADD CONSTRAINT {short}_agent_pair CHECK ((agent IS NULL) = (agent_version IS NULL));
            COMMENT ON COLUMN {table}.agent IS
              'The agent the row is about (match, stats, council, or reviewer for the AI that runs today): what the Learning Analyst (la-v1) proposes '
              'a hypothesis for, and what an experiment tests. NULL for everything written before phase 5 and for what is about no agent.';
            COMMENT ON COLUMN {table}.agent_version IS
              'The version of that agent (council-v1...): a hypothesis is proposed PER VERSION, because a version that changes is another agent '
              '(plan IA, section 25). NULL exactly when agent is.';
        """)

    op.execute(f"""
        CREATE TABLE intel.agent_attributions (
            id                  BIGSERIAL     PRIMARY KEY,
            attribution_version TEXT          NOT NULL CHECK (attribution_version ~ '{VERSION}'),
            classified_by       TEXT          NOT NULL CHECK (classified_by IN ({_in(CLASSIFIERS)})),
            fixture_id          BIGINT        NOT NULL CHECK (fixture_id >= 1),
            market_key          TEXT          NOT NULL,
            selection           TEXT          NOT NULL,
            line                NUMERIC(6,2)  NOT NULL,
            engine              TEXT          NOT NULL CHECK (engine IN ({_in(SHADOW_ENGINES)})),
            agent               TEXT          NOT NULL CHECK (agent IN ({_in(AGENTS)})),
            agent_version       TEXT          NOT NULL CHECK (agent_version ~ '{VERSION}'),
            signal              TEXT          NOT NULL CHECK (signal IN ({_in(SIGNALS)})),
            stance              TEXT          NOT NULL CHECK (stance IN ({_in(STANCES)})),
            outcome             TEXT          NOT NULL CHECK (outcome IN ({_in(OUTCOMES)})),
            error_class         TEXT          NOT NULL CHECK (error_class IN ({_in(CLASSES)}, 'NONE')),
            settled             TEXT          NOT NULL CHECK (settled IN ({_in(SETTLED)})),
            toward_close        BOOLEAN,
            calibration         TEXT          CHECK (calibration IN ({_in(CALIBRATIONS)})),
            clv                 NUMERIC(9,4),
            review_id           BIGINT        NOT NULL CHECK (review_id >= 1),
            run_id              BIGINT        CHECK (run_id >= 1),
            postmortem_id       BIGINT        NOT NULL CHECK (postmortem_id >= 1),
            basis_id            BIGINT        CHECK (basis_id >= 1),
            source              TEXT          NOT NULL CHECK (source IN ('live', 'batch')),
            computed_at         TIMESTAMPTZ   NOT NULL,
            CONSTRAINT agent_attributions_a_miss_has_a_class CHECK ((outcome = 'MISS') = (error_class <> 'NONE')),
            CONSTRAINT agent_attributions_a_refinement_refines CHECK ((classified_by = 'code') = (basis_id IS NULL)),
            CONSTRAINT agent_attributions_a_refinement_refines_a_miss CHECK (classified_by = 'code' OR outcome = 'MISS')
        );
        CREATE UNIQUE INDEX agent_attributions_once ON intel.agent_attributions
            (fixture_id, market_key, selection, line, engine, agent, agent_version, signal, attribution_version, classified_by);
        CREATE UNIQUE INDEX agent_attributions_one_refinement ON intel.agent_attributions (basis_id) WHERE basis_id IS NOT NULL;
        CREATE INDEX agent_attributions_by_version ON intel.agent_attributions (agent, agent_version, outcome);
        CREATE INDEX agent_attributions_by_fixture ON intel.agent_attributions (fixture_id);

        COMMENT ON TABLE intel.agent_attributions IS
          'Which agent, in which version, was right or wrong about each settled selection of the shadow (plan IA, section 12, phase 5). Computed by '
          'CODE from the shadow reviews and the result (fbi.ai.agents.attribution, attr-v1); the Post-Match Reviewer (pmr-v1) may only add a class to a '
          'miss the code left UNKNOWN, as a second row. Codes only, no prose. Append-only; no pick, filter, decision or user reads it.';
        COMMENT ON COLUMN intel.agent_attributions.classified_by IS
          'Who wrote the class: code (the rule attr-v1) or pmr-v1 (a refinement of a row of the code whose class was UNKNOWN; basis_id is that row).';
        COMMENT ON COLUMN intel.agent_attributions.engine IS
          'The arm of the shadow the agent worked in (ma-v1, ma-v1-h, cs-v1): the Council of ma-v1-h is the Haiku one, so a version is judged per arm.';
        COMMENT ON COLUMN intel.agent_attributions.signal IS
          'A signal code of aa-v1 that drove the stance, or VERDICT: the agent''s own stance on the selection (the Council''s verdict, the Match Agent''s stance).';
        COMMENT ON COLUMN intel.agent_attributions.stance IS
          'The code the agent gave the selection (APPROVE, DOWNGRADE, REJECT, ABSTAIN; SUPPORT, NEUTRAL, CONCERN, REJECT_SIGNAL): the thing that is measured.';
        COMMENT ON COLUMN intel.agent_attributions.outcome IS
          'HIT: the stance pointed the way the result went (a selection approved that won, one rejected that lost). MISS: it did not. VOID: the agent '
          'took no side (ABSTAIN, NEUTRAL) or the selection was void.';
        COMMENT ON COLUMN intel.agent_attributions.error_class IS
          'The class of a MISS, in the words of the post-mortem pm-v6 (fbi.intel.pm_questions); NONE for a HIT and a VOID.';
        COMMENT ON COLUMN intel.agent_attributions.toward_close IS
          'Whether the stance pointed the way the closing line went (the CLV of the post-mortem: positive for a stance in favour, negative for one against). '
          'NULL when the selection has no closing line.';
        COMMENT ON COLUMN intel.agent_attributions.calibration IS
          'Whether the model was better calibrated than the market on this selection (the Brier score of its probability against the closing fair one); '
          'NULL when either is missing.';
        COMMENT ON COLUMN intel.agent_attributions.review_id IS 'ai.pick_reviews.id: the shadow review the stance was read from (no foreign key, see above).';
        COMMENT ON COLUMN intel.agent_attributions.run_id IS 'ai.agent_runs.id of the run that gave the stance, when the signals were read from it.';
        COMMENT ON COLUMN intel.agent_attributions.postmortem_id IS 'intel.postmortems.id: the post-mortem pm-v6 the result and the closing line were read from.';
        COMMENT ON COLUMN intel.agent_attributions.source IS
          'live: computed by the daily step ai_learn; batch: recomputed for an earlier day of the shadow. The rows are the same either way.';
    """)
    op.execute("CREATE TRIGGER agent_attributions_append_only BEFORE UPDATE OR DELETE ON intel.agent_attributions "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # The attributions go with their table (a development tool: production goes back by deploying the earlier code, on this schema).
    op.execute("DROP TABLE intel.agent_attributions")
    for table in ("analytics.research_hypotheses", "analytics.experiments"):
        short = table.split(".")[1]
        op.execute(f"""
            ALTER TABLE {table}
                DROP CONSTRAINT {short}_agent_pair,
                DROP CONSTRAINT {short}_agent_version_check,
                DROP CONSTRAINT {short}_agent_check,
                DROP COLUMN agent_version,
                DROP COLUMN agent
        """)
