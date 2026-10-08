"""PrediGol AI V2: the day in Bogotá, its passes, the L1 briefs, the adaptive budget and the daily learning

The AI now works on TODAY's matches (America/Bogota) that have a market, in three passes - the first from
00:05, a second six to four hours before kick-off, a last one after the line-ups - and learns every morning
from what happened. Everything new is written into the ``ai`` schema and is append-only like the rest:

* ``ai.day_plans``         the day's universe (its matches, which have a market, their priority) and the
                           day's budget. Prepared the day before (no model, no search), opened at 00:05.
* ``ai.match_briefs``      the L1 brief of a match by the economical model - or by the rules when no model may
                           answer: context, signals, data quality, injuries, changes, uncertainty and whether to
                           escalate (and why). Stored only when its input changes.
* ``ai.fixture_passes``    which pass ran for a match on its day, what it did and what it cost: a pass never
                           runs twice.
* ``ai.budget_alerts``     the month's spend crossing 70 / 85 / 95 / 100 % of the monthly budget, once each.
* ``ai.pick_postmortems``  each studied selection after its match (``pm-v2``): the ten questions answered from
                           what was stored before kick-off and the result, a class for a loss (MODEL_ERROR,
                           CONTEXT_ERROR, DATA_ERROR, MARKET_ERROR, EXECUTION_ERROR, NORMAL_VARIANCE, UNKNOWN), the
                           evidence it rests on.
* ``ai.learning_notes``    QUÉ APRENDIÓ PREDIGOL HOY: every note with the post-mortems and memory it rests on.
* ``ai.source_stats``      per day and domain: how often it came up, what it gave, what was kept or discarded,
                           what it cost (derived from the rows above; recomputed, not a record).

``ai.evidence`` gains ``last_seen_at`` and ``seen_count`` (first seen is ``retrieved_at``): a story seen again is
counted, never stored twice - the guard still refuses any change to an item's content. ``ai.research_cache``
gains ``last_hit_at``. New words: usage purposes ``match_brief`` and ``learning``, memory kind
``pick_postmortem``, cycle kinds ``day_start`` and ``prepare``; and ``audit.notifications`` learns ``ai_budget``, so a
budget alert reaches the owner's channel like any other notification.

Nothing here can change a pick, a probability, a rule or a model.

Revision ID: 0073
Revises: 0072
"""

from __future__ import annotations

from alembic import op

revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None

APPEND_ONLY = ("day_plans", "match_briefs", "fixture_passes", "budget_alerts", "pick_postmortems", "learning_notes")

PURPOSES_V1 = ("'evidence_extraction', 'pick_review', 'match_analysis', 'postmortem', 'pattern_review', "
               "'web_search', 'daily_report', 'ask', 'other'")
MEMORY_V1 = ("'match_result', 'pick_result', 'context_error', 'news_signal', 'injury_signal', 'market_signal', "
             "'model_failure', 'model_success', 'league_pattern', 'team_pattern', 'player_pattern', 'review_quality'")
CYCLES_V1 = "'analysis', 'postmortem', 'learning', 'evaluation'"
NOTIFY_V1 = ("'shadow_pick', 'pick_settled', 'first_capture', 'capture_failed', 'worker_down', 'run_recovered', "
             "'job_failing'")


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE ai.usage DROP CONSTRAINT usage_purpose_check;
        ALTER TABLE ai.usage ADD CONSTRAINT usage_purpose_check
            CHECK (purpose IN ({PURPOSES_V1}, 'match_brief', 'learning'));
        ALTER TABLE ai.memory_events DROP CONSTRAINT memory_events_kind_check;
        ALTER TABLE ai.memory_events ADD CONSTRAINT memory_events_kind_check
            CHECK (kind IN ({MEMORY_V1}, 'pick_postmortem'));
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({CYCLES_V1}, 'day_start', 'prepare'));
        ALTER TABLE audit.notifications DROP CONSTRAINT notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({NOTIFY_V1}, 'ai_budget'));

        ALTER TABLE ai.evidence ADD COLUMN last_seen_at TIMESTAMPTZ,
                                ADD COLUMN seen_count INTEGER NOT NULL DEFAULT 1 CHECK (seen_count >= 1);
        COMMENT ON COLUMN ai.evidence.last_seen_at IS
          'The last time a search or the provider returned this same item (first seen = retrieved_at).';
        ALTER TABLE ai.research_cache ADD COLUMN last_hit_at TIMESTAMPTZ;

        -- ── the day ──────────────────────────────────────────────────────────────────
        CREATE TABLE ai.day_plans (
            id                   BIGSERIAL   PRIMARY KEY,
            day                  DATE        NOT NULL,
            stage                TEXT        NOT NULL CHECK (stage IN ('prepared', 'opened')),
            created_at           TIMESTAMPTZ NOT NULL,
            version              TEXT        NOT NULL,
            fixtures_total       INTEGER     NOT NULL CHECK (fixtures_total >= 0),
            fixtures_with_market INTEGER     NOT NULL CHECK (fixtures_with_market >= 0
                                                             AND fixtures_with_market <= fixtures_total),
            universe             JSONB       NOT NULL CHECK (jsonb_typeof(universe) = 'array'),
            budget               JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            notes                JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            UNIQUE (day, stage)
        );
        COMMENT ON TABLE ai.day_plans IS
          'The matches of a Bogotá day, which of them have a market (the only ones the AI analyses) and the day''s '
          'budget: prepared the day before without any model or search, opened at 00:05.';

        CREATE TABLE ai.match_briefs (
            id           BIGSERIAL     PRIMARY KEY,
            fixture_id   BIGINT        NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            created_at   TIMESTAMPTZ   NOT NULL,
            pass         TEXT          NOT NULL CHECK (pass IN ('first', 'pre', 'final', 'request')),
            version      TEXT          NOT NULL,
            engine       TEXT          NOT NULL CHECK (engine IN ('llm', 'rules')),
            provider     TEXT,
            model        TEXT,
            packet_id    BIGINT        REFERENCES ai.match_packets(id),
            input_hash   TEXT          NOT NULL,
            status       TEXT          NOT NULL CHECK (status IN ('ok', 'invalid_output', 'failed', 'over_budget',
                                       'not_configured')),
            escalate     BOOLEAN       NOT NULL,
            reasons      TEXT[]        NOT NULL DEFAULT '{{}}',
            uncertainty  TEXT          CHECK (uncertainty IN ('low', 'medium', 'high')),
            data_quality TEXT          CHECK (data_quality IN ('good', 'fair', 'poor')),
            content      JSONB         NOT NULL,
            rejected     JSONB         NOT NULL DEFAULT '[]'::jsonb,
            usage_ids    BIGINT[]      NOT NULL DEFAULT '{{}}',
            cost_usd     NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            error        TEXT
        );
        CREATE INDEX ai_match_briefs_fixture ON ai.match_briefs (fixture_id, created_at DESC, id DESC);
        CREATE INDEX ai_match_briefs_input ON ai.match_briefs (input_hash);
        COMMENT ON TABLE ai.match_briefs IS
          'L1: what the economical model (or the rules, engine = rules) read in a match''s packet and evidence. '
          'It never gives a probability; escalate says whether the match deserves the intermediate model.';

        CREATE TABLE ai.fixture_passes (
            id          BIGSERIAL     PRIMARY KEY,
            fixture_id  BIGINT        NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            day         DATE          NOT NULL,
            pass        TEXT          NOT NULL CHECK (pass IN ('first', 'pre', 'final')),
            started_at  TIMESTAMPTZ   NOT NULL,
            finished_at TIMESTAMPTZ   NOT NULL,
            kickoff_at  TIMESTAMPTZ   NOT NULL,
            status      TEXT          NOT NULL CHECK (status IN ('ok', 'partial', 'skipped', 'failed')),
            escalated   BOOLEAN       NOT NULL DEFAULT false,
            reasons     TEXT[]        NOT NULL DEFAULT '{{}}',
            brief_id    BIGINT        REFERENCES ai.match_briefs(id),
            packet_id   BIGINT        REFERENCES ai.match_packets(id),
            counts      JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            cost_usd    NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            note        TEXT,
            UNIQUE (fixture_id, day, pass),
            CHECK (started_at <= finished_at)
        );
        CREATE INDEX ai_fixture_passes_day ON ai.fixture_passes (day, pass);

        CREATE TABLE ai.budget_alerts (
            id         BIGSERIAL     PRIMARY KEY,
            month      DATE          NOT NULL CHECK (extract(day FROM month) = 1),
            threshold  SMALLINT      NOT NULL CHECK (threshold IN (70, 85, 95, 100)),
            created_at TIMESTAMPTZ   NOT NULL,
            spent_usd  NUMERIC(12,6) NOT NULL CHECK (spent_usd >= 0),
            budget_usd NUMERIC(12,6) NOT NULL CHECK (budget_usd >= 0),
            UNIQUE (month, threshold)
        );

        -- ── what results taught ──────────────────────────────────────────────────────
        CREATE TABLE ai.pick_postmortems (
            id             BIGSERIAL     PRIMARY KEY,
            fixture_id     BIGINT        NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            market_key     TEXT          NOT NULL,
            selection      TEXT          NOT NULL,
            line           NUMERIC(6,2)  NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ   NOT NULL,
            version        TEXT          NOT NULL,
            roles          TEXT[]        NOT NULL,
            decision       TEXT          CHECK (decision IN ('APPROVE', 'DOWNGRADE', 'REJECT', 'ABSTAIN')),
            review_id      BIGINT        REFERENCES ai.pick_reviews(id),
            settled        TEXT          NOT NULL,
            verdict        TEXT          NOT NULL CHECK (verdict IN ('approved_won', 'approved_lost', 'caution_won',
                                         'caution_lost', 'rejected_would_have_won', 'rejected_correctly',
                                         'unreviewed_won', 'unreviewed_lost', 'push')),
            classification TEXT          CHECK (classification IN ('MODEL_ERROR', 'CONTEXT_ERROR', 'DATA_ERROR',
                                         'MARKET_ERROR', 'EXECUTION_ERROR', 'NORMAL_VARIANCE', 'UNKNOWN')),
            odds           NUMERIC(9,3),
            close_odds     NUMERIC(9,3),
            clv            NUMERIC(9,4),
            p_model        NUMERIC(8,6),
            p_market       NUMERIC(8,6),
            answers        JSONB         NOT NULL,
            evidence       JSONB         NOT NULL DEFAULT '{{}}'::jsonb,
            narrative      TEXT,
            usage_ids      BIGINT[]      NOT NULL DEFAULT '{{}}',
            UNIQUE (fixture_id, market_key, selection, line, version)
        );
        CREATE INDEX ai_pick_postmortems_created ON ai.pick_postmortems (created_at DESC);
        COMMENT ON TABLE ai.pick_postmortems IS
          'Each studied selection after its match: what PrediGol expected, what happened, the ten questions and - for '
          'a loss - its class. Written from what was stored before kick-off and the result; never acted on.';

        CREATE TABLE ai.learning_notes (
            id         BIGSERIAL   PRIMARY KEY,
            day        DATE        NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            version    TEXT        NOT NULL,
            kind       TEXT        NOT NULL CHECK (kind IN ('summary', 'approved', 'rejected', 'context', 'news',
                                   'injuries', 'market', 'model', 'sources', 'lesson')),
            title      TEXT        NOT NULL CHECK (length(btrim(title)) BETWEEN 3 AND 200),
            body       TEXT        NOT NULL CHECK (length(btrim(body)) BETWEEN 3 AND 1200),
            n          INTEGER     NOT NULL DEFAULT 0 CHECK (n >= 0),
            evidence   JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            engine     TEXT        NOT NULL CHECK (engine IN ('rules', 'llm')),
            usage_ids  BIGINT[]    NOT NULL DEFAULT '{{}}',
            dedup_key  TEXT        NOT NULL UNIQUE
        );
        CREATE INDEX ai_learning_notes_day ON ai.learning_notes (day DESC, id);
        COMMENT ON TABLE ai.learning_notes IS
          'QUÉ APRENDIÓ PREDIGOL HOY: observations from the day''s results with the evidence they rest on. An '
          'observation is not a rule: patterns become hypotheses, hypotheses need an experiment, the owner decides.';

        CREATE TABLE ai.source_stats (
            day         DATE          NOT NULL,
            domain      TEXT          NOT NULL,
            tier        TEXT          NOT NULL,
            results     INTEGER       NOT NULL DEFAULT 0 CHECK (results >= 0),
            evidence    INTEGER       NOT NULL DEFAULT 0 CHECK (evidence >= 0),
            useful      INTEGER       NOT NULL DEFAULT 0 CHECK (useful >= 0),
            discarded   INTEGER       NOT NULL DEFAULT 0 CHECK (discarded >= 0),
            cost_usd    NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            computed_at TIMESTAMPTZ   NOT NULL,
            PRIMARY KEY (day, domain)
        );
        COMMENT ON TABLE ai.source_stats IS
          'Derived per day and domain from the search cache and the evidence (recomputed): results = times the domain '
          'came up, evidence = items read from it, useful = kept and not contradicted, discarded = the rest.';
    """)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    # The new rows are dropped with their tables; the old words come back NOT VALID so a row written with a new
    # word (kept, never deleted) does not block the downgrade.
    op.execute(f"""
        DROP TABLE ai.source_stats;
        DROP TABLE ai.learning_notes;
        DROP TABLE ai.pick_postmortems;
        DROP TABLE ai.budget_alerts;
        DROP TABLE ai.fixture_passes;
        DROP TABLE ai.match_briefs;
        DROP TABLE ai.day_plans;
        ALTER TABLE ai.research_cache DROP COLUMN last_hit_at;
        ALTER TABLE ai.evidence DROP COLUMN seen_count, DROP COLUMN last_seen_at;
        ALTER TABLE audit.notifications DROP CONSTRAINT notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN ({NOTIFY_V1})) NOT VALID;
        ALTER TABLE ai.cycles DROP CONSTRAINT cycles_kind_check;
        ALTER TABLE ai.cycles ADD CONSTRAINT cycles_kind_check CHECK (kind IN ({CYCLES_V1})) NOT VALID;
        ALTER TABLE ai.memory_events DROP CONSTRAINT memory_events_kind_check;
        ALTER TABLE ai.memory_events ADD CONSTRAINT memory_events_kind_check CHECK (kind IN ({MEMORY_V1})) NOT VALID;
        ALTER TABLE ai.usage DROP CONSTRAINT usage_purpose_check;
        ALTER TABLE ai.usage ADD CONSTRAINT usage_purpose_check CHECK (purpose IN ({PURPOSES_V1})) NOT VALID;
    """)
