"""the AI research layer and the evolution loop: runs, claims with provenance, reports, flags,
hypotheses and memory

GATE H. A language model may READ the platform through whitelisted tools and WRITE only here:

* ``analytics.ai_runs`` - every call: what for, which model, tokens, cost, and how it ended
  (``not_configured`` and ``over_budget`` are endings too, recorded rather than silent).
* ``analytics.ai_claims`` - a statement about the world with its provenance: the source URL a
  research tool returned in the same run, when it was published and retrieved, and a grade
  CONFIRMED (official source) / REPORTED (reputable outlet) / RUMOR. A claim without a source
  is refused by the schema.
* ``analytics.ai_reports`` - the daily research report, one per product day and source.
* ``analytics.ai_pick_flags`` - the pick reviewer's output: FLAGS ONLY (a code, a severity, a
  note, the claims behind it). There is no column for a probability, a stake or a decision:
  the reviewer cannot change a pick, and the schema says so.

GATE I. The evolution loop never lets a bad result change a rule on its own:

* ``analytics.research_hypotheses`` - a proposed experiment (by the AI, the owner or the
  system; a system proposal carries a ``dedup_key`` so it is made once), which only the owner
  accepts or rejects; experiments run in research and nothing is promoted without a passed
  gate and an explicit promotion;
* ``analytics.research_memory`` - what was learned, with the experiments that showed it, kept
  (superseded, never deleted).

Revision ID: 0055
Revises: 0054
"""

from __future__ import annotations

from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS analytics.ai_runs (
            id            BIGSERIAL   PRIMARY KEY,
            kind          TEXT        NOT NULL CHECK (kind IN ('ask', 'daily_report', 'pick_review')),
            model         TEXT,
            started_at    TIMESTAMPTZ NOT NULL,
            finished_at   TIMESTAMPTZ,
            status        TEXT        NOT NULL DEFAULT 'running'
                          CHECK (status IN ('running', 'ok', 'failed', 'not_configured', 'over_budget')),
            input_tokens  INTEGER     NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
            output_tokens INTEGER     NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
            cost_usd      NUMERIC(10,5) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            tool_calls    INTEGER     NOT NULL DEFAULT 0,
            detail        JSONB       NOT NULL DEFAULT '{}'::jsonb,
            error         TEXT,
            CHECK ((status = 'running') = (finished_at IS NULL))
        );
        CREATE INDEX IF NOT EXISTS ai_runs_month ON analytics.ai_runs (started_at);

        CREATE TABLE IF NOT EXISTS analytics.ai_claims (
            id           BIGSERIAL   PRIMARY KEY,
            run_id       BIGINT      NOT NULL REFERENCES analytics.ai_runs(id) ON DELETE CASCADE,
            fixture_id   BIGINT      REFERENCES core.fixtures(id) ON DELETE SET NULL,
            team_id      BIGINT      REFERENCES core.teams(id) ON DELETE SET NULL,
            claim        TEXT        NOT NULL CHECK (length(btrim(claim)) BETWEEN 5 AND 600),
            source_url   TEXT        NOT NULL CHECK (source_url ~ '^https?://'),
            also_urls    TEXT[]      NOT NULL DEFAULT '{}',
            publisher    TEXT,
            published_at TIMESTAMPTZ,
            retrieved_at TIMESTAMPTZ NOT NULL,
            confidence   TEXT        NOT NULL CHECK (confidence IN ('CONFIRMED', 'REPORTED', 'RUMOR')),
            CHECK (published_at IS NULL OR published_at <= retrieved_at)
        );

        CREATE TABLE IF NOT EXISTS analytics.ai_reports (
            id          BIGSERIAL   PRIMARY KEY,
            run_id      BIGINT      NOT NULL REFERENCES analytics.ai_runs(id) ON DELETE CASCADE,
            day         DATE        NOT NULL,
            source      TEXT        NOT NULL CHECK (source IN ('qualified', 'evaluation')),
            markdown    TEXT        NOT NULL,
            claims      INTEGER     NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL,
            UNIQUE (day, source, run_id)
        );

        CREATE TABLE IF NOT EXISTS analytics.ai_pick_flags (
            id          BIGSERIAL   PRIMARY KEY,
            run_id      BIGINT      NOT NULL REFERENCES analytics.ai_runs(id) ON DELETE CASCADE,
            set_id      BIGINT      REFERENCES picks.daily_sets(id) ON DELETE CASCADE,
            rank        SMALLINT,
            fixture_id  BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            code        TEXT        NOT NULL CHECK (code IN ('injury_news', 'lineup_uncertain', 'suspension',
                                                             'rotation_risk', 'motivation', 'stale_price',
                                                             'data_gap', 'kickoff_change', 'weather', 'other')),
            severity    TEXT        NOT NULL CHECK (severity IN ('info', 'warn', 'review')),
            note        TEXT        NOT NULL CHECK (length(btrim(note)) BETWEEN 3 AND 500),
            claim_ids   BIGINT[]    NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL,
            CHECK ((set_id IS NULL) = (rank IS NULL))
        );
        COMMENT ON TABLE analytics.ai_pick_flags IS
          'Flags only. No probability, stake or decision column exists: the reviewer cannot change a pick.';

        CREATE TABLE IF NOT EXISTS analytics.research_hypotheses (
            id             BIGSERIAL   PRIMARY KEY,
            proposed_by    TEXT        NOT NULL CHECK (proposed_by IN ('ai', 'owner', 'system')),
            title          TEXT        NOT NULL CHECK (length(btrim(title)) BETWEEN 5 AND 160),
            hypothesis     TEXT        NOT NULL,
            rationale      TEXT        NOT NULL,
            evidence       JSONB       NOT NULL DEFAULT '{}'::jsonb,
            status         TEXT        NOT NULL DEFAULT 'PROPOSED'
                           CHECK (status IN ('PROPOSED', 'ACCEPTED', 'REJECTED', 'RUNNING', 'DONE')),
            experiment_ids BIGINT[]    NOT NULL DEFAULT '{}',
            dedup_key      TEXT,
            created_at     TIMESTAMPTZ NOT NULL,
            decided_at     TIMESTAMPTZ,
            decided_by     BIGINT      REFERENCES auth.users(id) ON DELETE SET NULL,
            decision_note  TEXT,
            CHECK ((status IN ('PROPOSED')) = (decided_at IS NULL))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS research_hypotheses_dedup
            ON analytics.research_hypotheses (dedup_key) WHERE dedup_key IS NOT NULL;

        CREATE TABLE IF NOT EXISTS analytics.research_memory (
            id            BIGSERIAL   PRIMARY KEY,
            topic         TEXT        NOT NULL,
            finding       TEXT        NOT NULL,
            evidence      JSONB       NOT NULL DEFAULT '{}'::jsonb,
            source        TEXT        NOT NULL CHECK (source IN ('research_v2', 'prospective', 'audit', 'owner')),
            created_at    TIMESTAMPTZ NOT NULL,
            superseded_by BIGINT      REFERENCES analytics.research_memory(id)
        );
        CREATE INDEX IF NOT EXISTS research_memory_topic ON analytics.research_memory (topic, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS analytics.research_memory;
        DROP TABLE IF EXISTS analytics.research_hypotheses;
        DROP TABLE IF EXISTS analytics.ai_pick_flags;
        DROP TABLE IF EXISTS analytics.ai_reports;
        DROP TABLE IF EXISTS analytics.ai_claims;
        DROP TABLE IF EXISTS analytics.ai_runs;
    """)
