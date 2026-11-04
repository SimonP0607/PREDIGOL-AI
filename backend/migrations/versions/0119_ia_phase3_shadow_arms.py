"""Plan Maestro IA, Phase 3 - the arms of the shadow: three engines a review can carry, a kind of cycle for the orchestrator, and who was
assigned to which arm.

Phase 3 runs the multi-agent in SHADOW: beside the production reviewers (``rules`` and ``llm``, and the ``combined`` they add up to) three more
engines review a sample of the matches and write rows nobody reads for a decision - ``ma-v1`` (the Match Agent and the Council), ``ma-v1-h`` (the
same with the Haiku Council) and ``cs-v1`` (COUNCIL SOLO: Sonnet reading the compact view, no specialists). The decision layer reads only
``combined`` and ``rules`` (``fbi.intel.decision.REVIEWS_SQL``) and the readers of the table that count production figures name the production
engines: a shadow row moves nothing. This revision changes three things, all ADDITIVE:

* ``ai.pick_reviews``: the CHECK on ``engine`` (``pick_reviews_engine_check``) learns ``ma-v1``, ``ma-v1-h`` and ``cs-v1``. The rows written are
  not touched; the code that ran before this phase never writes the new words and finds the table as it left it.
* ``ai.cycles``: the CHECK on ``kind`` (``cycles_kind_check``) learns ``orchestrate``. The orchestrator is a job of its own with its own row in the
  ledger of the jobs of the AI layer, so that a raise in it can never roll back the cycle of the package or of the analysis (``ai_package`` is the
  precedent: revision 0112).
* ``ai.shadow_assignments`` (append-only, new): which arm each match was assigned to, once, before its first shadow pass. The arm is a function of
  the match (``fbi.ai.arms.bucket`` - a hash of the fixture id and the salt of the experiment) and of the share of the matches in the sample; the
  row stores the bucket, the two decisions and the share in force that day, so that raising the share later adds matches to the sample and never
  moves one that was already assigned ("ningun partido cambia de grupo"). The database holds the rule that the code applies: a match is sampled
  exactly when ``bucket < share * 10000``, and a COUNCIL SOLO match is a sampled one. No foreign key: the table is read by the orchestrator once
  per match and pass, and the tables it would point to are the busiest of the database (the lesson of 0076).

On a live database (the worker keeps writing): the two busy tables are altered FIRST and a wait longer than 10 s for either lock fails the migration
whole (the lesson of 0076, 13 Oct 2026, and the rule of 0111, 0112 and 0115). ``ai.pick_reviews`` is the one that is read through to validate the
widened list: 115,220 rows on 25 Oct 2026 (``docs/owner/IA_BASELINE_F0.md``), one pass over the table, with the lock held for that pass only.

Downgrade (``alembic downgrade`` is for development: production goes back by deploying the code that ran before, which works on this schema because
every change here only adds - docs/owner/IA_FASE1.md says it of the migrations of phase 1): the old lists come back NOT VALID, the way 0115,
0112 and 0073 did it. The reviews already
written with a shadow engine stay (a review is evidence and the table is append-only); the constraint judges only the rows written or changed from
then on, and the code that ran before never writes those engines. A cycle of the new kind still 'running' (a worker killed in the middle of one) is
closed first as failed, the way the recovery of a stopped worker closes it: the recovery of the code that ran before updates every cycle left
running in one statement, and a row the constraint refuses would stop it for the others too. The assignments go with their table, as the tables of
0111 and 0110 go with what they recorded: a later upgrade starts the experiment again, and the share and the bucket give the same arm to the same
match.

Revision ID: 0119
Revises: 0118
"""

from __future__ import annotations

from alembic import op

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None

ENGINES = ("rules", "llm", "combined")
"""The engines 0072 left (``fbi.ai.review``); the three of the shadow are the new ones."""
SHADOW_ENGINES = ("ma-v1", "ma-v1-h", "cs-v1")
"""``fbi.ai.config.SHADOW_ENGINES``: the multi-agent, the multi-agent with the Haiku Council and COUNCIL SOLO."""
KINDS = ("analysis", "postmortem", "learning", "evaluation", "day_start", "prepare", "package")
"""The kinds 0112 left (``fbi.ai.cycle`` opens each of them); ``orchestrate`` is the new one."""
BUCKETS = 10000
"""``fbi.ai.arms.BUCKETS``: the number of buckets a match falls into; a share of 0.3 samples the buckets below 3000."""

NAME = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""``fbi.ai.idempotency.NAME``: the name of an experiment - ASCII, no spaces, nothing that reads as a separator."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # On a live database the worker writes the reviews every few minutes and opens a cycle several times an hour: never wait for a lock longer
    # than 10 s (the lesson of 0076). The busy tables go first, so that a lock that cannot be had stops the migration before it has done anything.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE ai.pick_reviews DROP CONSTRAINT pick_reviews_engine_check;
        ALTER TABLE ai.pick_reviews ADD CONSTRAINT pick_reviews_engine_check CHECK (engine IN ({_in(ENGINES)}, {_in(SHADOW_ENGINES)}));
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({_in(KINDS)}, 'orchestrate'));
    """)

    # The arm of each match in the experiment (append-only: a match never changes group).
    op.execute(f"""
        CREATE TABLE ai.shadow_assignments (
            experiment   TEXT          NOT NULL CHECK (experiment ~ '{NAME}'),
            fixture_id   BIGINT        NOT NULL CHECK (fixture_id >= 1),
            bucket       INTEGER       NOT NULL CHECK (bucket BETWEEN 0 AND {BUCKETS - 1}),
            sampled      BOOLEAN       NOT NULL,
            council_solo BOOLEAN       NOT NULL,
            share        NUMERIC       NOT NULL CHECK (share > 0 AND share <= 1),
            assigned_at  TIMESTAMPTZ   NOT NULL,
            PRIMARY KEY (experiment, fixture_id),
            CONSTRAINT shadow_assignments_solo_is_sampled CHECK (NOT council_solo OR sampled),
            CONSTRAINT shadow_assignments_sample_rule CHECK (sampled = (bucket < share * {BUCKETS}))
        );
        COMMENT ON TABLE ai.shadow_assignments IS
          'The arm each match was assigned to in an experiment of the shadow (plan IA, sections 22 and 23), once, before its first shadow pass. '
          'Append-only: a match never changes group, whatever the share becomes later. bucket is a hash of the fixture id and the salt of the '
          'experiment (fbi.ai.arms.bucket), sampled says whether the match is in the sample (bucket below share * 10000: raising the share only '
          'adds matches), council_solo whether a second hash put it in the COUNCIL SOLO half of the sample. A match that is not sampled has a '
          'row too when the share was above zero, so that it is never assigned again.';
        COMMENT ON COLUMN ai.shadow_assignments.experiment IS
          'The experiment: the salt of the hash (fbi.ai.arms.SALT). Another salt is another experiment, with its own groups.';
        COMMENT ON COLUMN ai.shadow_assignments.fixture_id IS
          'core.fixtures.id (no foreign key: the busy tables are not pointed to from a table the orchestrator reads on every pass).';
        COMMENT ON COLUMN ai.shadow_assignments.bucket IS
          '0 to 9999: the first hash of the match. The sample of a share is the buckets below share * 10000, so the sample of a larger share holds '
          'the sample of a smaller one.';
        COMMENT ON COLUMN ai.shadow_assignments.council_solo IS
          'Whether the match also goes to COUNCIL SOLO (engine cs-v1): the half of the sample whose second hash says so, a quarter of the matches '
          'when the sample is the half of them. Only a sampled match can be one.';
        COMMENT ON COLUMN ai.shadow_assignments.share IS
          'The share of the matches in the sample that was in force when the match was assigned (FBI_AI_SHADOW_SAMPLE): why the match is in its group.';
    """)
    op.execute("CREATE TRIGGER shadow_assignments_append_only BEFORE UPDATE OR DELETE ON ai.shadow_assignments "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # The assignments go with their table (a development tool: production goes back by deploying the earlier code, on this schema).
    op.execute("DROP TABLE ai.shadow_assignments")
    op.execute("""
        UPDATE ai.cycles SET status = 'failed', finished_at = started_at, error = 'interrupted: the schema went back before the cycle finished'
         WHERE kind = 'orchestrate' AND status = 'running'
    """)
    op.execute(f"""
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({_in(KINDS)})) NOT VALID;
        ALTER TABLE ai.pick_reviews DROP CONSTRAINT pick_reviews_engine_check;
        ALTER TABLE ai.pick_reviews ADD CONSTRAINT pick_reviews_engine_check CHECK (engine IN ({_in(ENGINES)})) NOT VALID;
    """)
