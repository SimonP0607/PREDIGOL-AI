"""the AI decision layer: match packets, evidence with provenance, pick reviews, match analyses,
memory, post-mortems, the AI's own shadow evaluation and every model call's cost

A language model - or the deterministic reviewer that stands in for it - READS the platform and
WRITES only into the new ``ai`` schema (and proposes hypotheses into the existing evolution loop).
Nothing here can change a pick, a probability, a threshold or a model:

* ``ai.match_packets``        the frozen, hashed context a review reads (as of a moment, with the
                              source of every block); a new packet when the inputs change.
* ``ai.sources`` / ``ai.evidence``  what is known about a match from outside the numbers (injuries,
                              suspensions, line-ups, news) with its source, dates, tier and status
                              CONFIRMED / PROBABLE / RUMOR / CONTRADICTORY / OUTDATED. The content
                              of an evidence row never changes; its status may, and every change
                              is kept in ``status_history``.
* ``ai.research_cache``       a story, a URL or a search answered once, reused until it expires.
* ``ai.pick_reviews``         APPROVE / DOWNGRADE / REJECT / ABSTAIN for a candidate, with the
                              packet, the evidence, the prompt version, the model and the cost.
* ``ai.match_analyses``       the per-match analysis (at most three selections) the product shows.
* ``ai.memory_events`` / ``ai.postmortems``  what each result taught, with its evidence.
* ``ai.shadow_reports``       model alone vs model + AI vs market, before the AI may touch users.
* ``ai.correlation_estimates`` measured dependence between legs (parlays), never assumed.
* ``ai.usage``                one row per model or search call: tokens, searches, cost, outcome.
* ``ai.cycles`` / ``ai.run_requests``  the AI jobs' own ledger and the owner's "run now".

Append-only by trigger (``ai.refuse_change``): packets, reviews, analyses, memory, post-mortems,
shadow reports, correlation estimates and usage. The owner can lift it inside one transaction
(``SET LOCAL fbi.ai_maintenance = 'on'``) for a documented retention task; nothing in the
application does.

The evolution loop (``analytics.research_hypotheses``) gains the owner's three answers -
REJECTED, INVESTIGATING (look further) and ACCEPTED (approve the experiment) - the stages an
accepted experiment goes through (RUNNING, SHADOW, DONE) and PROMOTED, which only an explicit
promotion by the owner after the gate sets. Each hypothesis says what it would change
(``target``) and keeps the history of its stages.

Revision ID: 0072
Revises: 0071
"""

from __future__ import annotations

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

APPEND_ONLY = ("match_packets", "pick_reviews", "match_analyses", "memory_events", "postmortems",
               "shadow_reports", "correlation_estimates", "usage")


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA IF NOT EXISTS ai;

        CREATE OR REPLACE FUNCTION ai.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.ai_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'ai.%: append-only (% refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$;

        -- ── every model or search call ───────────────────────────────────────────
        CREATE TABLE ai.usage (
            id             BIGSERIAL     PRIMARY KEY,
            at             TIMESTAMPTZ   NOT NULL,
            purpose        TEXT          NOT NULL CHECK (purpose IN ('evidence_extraction', 'pick_review',
                                         'match_analysis', 'postmortem', 'pattern_review', 'web_search',
                                         'daily_report', 'ask', 'other')),
            tier           TEXT          NOT NULL CHECK (tier IN ('bulk', 'analysis', 'final', 'search')),
            provider       TEXT          NOT NULL,
            model          TEXT          NOT NULL,
            prompt_version TEXT,
            fixture_id     BIGINT        REFERENCES core.fixtures(id) ON DELETE SET NULL,
            input_tokens   INTEGER       NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
            output_tokens  INTEGER       NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
            cached_tokens  INTEGER       NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
            searches       INTEGER       NOT NULL DEFAULT 0 CHECK (searches >= 0),
            vision_items   INTEGER       NOT NULL DEFAULT 0 CHECK (vision_items >= 0),
            cost_usd       NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            latency_ms     INTEGER       CHECK (latency_ms IS NULL OR latency_ms >= 0),
            status         TEXT          NOT NULL CHECK (status IN ('ok', 'failed', 'timeout', 'refused',
                                         'over_budget', 'invalid_output')),
            error          TEXT,
            input_hash     TEXT,
            request_id     TEXT
        );
        CREATE INDEX ai_usage_at ON ai.usage (at);
        CREATE INDEX ai_usage_fixture ON ai.usage (fixture_id) WHERE fixture_id IS NOT NULL;
        COMMENT ON TABLE ai.usage IS
          'One row per provider call (model or search): tokens, searches, images, cost and how it ended. '
          'No prompt and no key is stored; input_hash identifies what was sent.';

        -- ── the frozen context of a match ─────────────────────────────────────────
        CREATE TABLE ai.match_packets (
            id             BIGSERIAL   PRIMARY KEY,
            fixture_id     BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            packet_version TEXT        NOT NULL,
            as_of          TIMESTAMPTZ NOT NULL,
            built_at       TIMESTAMPTZ NOT NULL,
            packet_hash    TEXT        NOT NULL CHECK (packet_hash ~ '^[0-9a-f]{64}$'),
            content        JSONB       NOT NULL,
            sources        JSONB       NOT NULL DEFAULT '[]'::jsonb,
            missing        TEXT[]      NOT NULL DEFAULT '{}',
            quality        JSONB       NOT NULL DEFAULT '{}'::jsonb,
            approx_tokens  INTEGER     NOT NULL DEFAULT 0 CHECK (approx_tokens >= 0),
            CHECK (as_of <= built_at)
        );
        CREATE INDEX ai_match_packets_fixture ON ai.match_packets (fixture_id, as_of DESC, id DESC);
        COMMENT ON TABLE ai.match_packets IS
          'What a review of this match could know at as_of - nothing recorded after it - with the source of '
          'every block. Identical inputs hash identically: a packet is stored only when it differs from the '
          'newest one of its match (a change log; the newest row is always the current context).';

        -- ── where evidence comes from ─────────────────────────────────────────────
        CREATE TABLE ai.sources (
            domain     TEXT        PRIMARY KEY CHECK (domain = lower(domain) AND domain !~ '^www\\.'),
            tier       TEXT        NOT NULL CHECK (tier IN ('official', 'competition', 'club', 'provider',
                                   'journalist', 'media', 'aggregator', 'social', 'unknown')),
            name       TEXT,
            country    TEXT,
            notes      TEXT,
            added_by   TEXT        NOT NULL CHECK (added_by IN ('seed', 'owner')),
            added_at   TIMESTAMPTZ NOT NULL
        );

        CREATE TABLE ai.evidence (
            id                BIGSERIAL    PRIMARY KEY,
            fixture_id        BIGINT       REFERENCES core.fixtures(id) ON DELETE CASCADE,
            team_id           BIGINT       REFERENCES core.teams(id) ON DELETE SET NULL,
            provider_player_id INTEGER,
            kind              TEXT         NOT NULL CHECK (kind IN ('injury', 'suspension', 'doubtful', 'lineup',
                                           'coach', 'news', 'transfer', 'motivation', 'weather', 'travel',
                                           'schedule', 'other')),
            claim             TEXT         NOT NULL CHECK (length(btrim(claim)) BETWEEN 5 AND 600),
            origin            TEXT         NOT NULL CHECK (origin IN ('provider', 'web', 'owner')),
            source_name       TEXT         NOT NULL,
            source_url        TEXT         CHECK (source_url IS NULL OR source_url ~ '^https?://'),
            source_domain     TEXT,
            source_tier       TEXT         NOT NULL CHECK (source_tier IN ('official', 'competition', 'club',
                                           'provider', 'journalist', 'media', 'aggregator', 'social', 'unknown')),
            author            TEXT,
            published_at      TIMESTAMPTZ,
            retrieved_at      TIMESTAMPTZ  NOT NULL,
            event_at          TIMESTAMPTZ,
            story_key         TEXT         NOT NULL,
            content_hash      TEXT         NOT NULL,
            payload_hash      TEXT         REFERENCES raw.ingestion_payloads(hash),
            confidence        NUMERIC(4,3) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            relevance         NUMERIC(4,3) NOT NULL CHECK (relevance BETWEEN 0 AND 1),
            attributes        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            status            TEXT         NOT NULL CHECK (status IN ('CONFIRMED', 'PROBABLE', 'RUMOR',
                                           'CONTRADICTORY', 'OUTDATED')),
            status_reason     TEXT         NOT NULL,
            status_changed_at TIMESTAMPTZ  NOT NULL,
            status_history    JSONB        NOT NULL DEFAULT '[]'::jsonb,
            UNIQUE (story_key, content_hash),
            CHECK (published_at IS NULL OR published_at <= retrieved_at),
            CHECK (origin <> 'web' OR source_url IS NOT NULL)
        );
        CREATE INDEX ai_evidence_fixture ON ai.evidence (fixture_id, retrieved_at DESC);
        CREATE INDEX ai_evidence_team ON ai.evidence (team_id, retrieved_at DESC) WHERE team_id IS NOT NULL;
        CREATE INDEX ai_evidence_story ON ai.evidence (story_key);
        COMMENT ON TABLE ai.evidence IS
          'A fact or report about a match from outside the numbers. Content never changes (a corrected fact is a '
          'new row); status changes are kept in status_history. A web claim always carries its URL.';

        CREATE OR REPLACE FUNCTION ai.evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('fbi.ai_maintenance', true), '') = 'on' THEN RETURN OLD; END IF;
                RAISE EXCEPTION 'ai.evidence: rows are never deleted' USING ERRCODE = 'check_violation';
            END IF;
            IF (NEW.fixture_id, NEW.team_id, NEW.provider_player_id, NEW.kind, NEW.claim, NEW.origin,
                NEW.source_name, NEW.source_url, NEW.source_domain, NEW.source_tier, NEW.author, NEW.published_at,
                NEW.retrieved_at, NEW.event_at, NEW.story_key, NEW.content_hash, NEW.payload_hash, NEW.confidence,
                NEW.relevance, NEW.attributes)
               IS DISTINCT FROM
               (OLD.fixture_id, OLD.team_id, OLD.provider_player_id, OLD.kind, OLD.claim, OLD.origin,
                OLD.source_name, OLD.source_url, OLD.source_domain, OLD.source_tier, OLD.author, OLD.published_at,
                OLD.retrieved_at, OLD.event_at, OLD.story_key, OLD.content_hash, OLD.payload_hash, OLD.confidence,
                OLD.relevance, OLD.attributes) THEN
                RAISE EXCEPTION 'ai.evidence: the content of evidence never changes (store a new row)'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status OR NEW.status_reason IS DISTINCT FROM OLD.status_reason THEN
                NEW.status_history := OLD.status_history || jsonb_build_array(jsonb_build_object(
                    'status', OLD.status, 'reason', OLD.status_reason, 'from', OLD.status_changed_at,
                    'until', NEW.status_changed_at));
            ELSE
                NEW.status_history := OLD.status_history;
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER evidence_guard BEFORE UPDATE OR DELETE ON ai.evidence
            FOR EACH ROW EXECUTE FUNCTION ai.evidence_guard();

        CREATE TABLE ai.research_cache (
            scope        TEXT        NOT NULL CHECK (scope IN ('fixture', 'team', 'player', 'url', 'story', 'search')),
            key          TEXT        NOT NULL,
            fetched_at   TIMESTAMPTZ NOT NULL,
            expires_at   TIMESTAMPTZ NOT NULL,
            content_hash TEXT        NOT NULL,
            payload      JSONB       NOT NULL,
            hits         INTEGER     NOT NULL DEFAULT 0 CHECK (hits >= 0),
            PRIMARY KEY (scope, key),
            CHECK (expires_at > fetched_at)
        );
        COMMENT ON TABLE ai.research_cache IS
          'A research answer reused until it expires (a cache, not a record: the evidence it produced is in '
          'ai.evidence).';

        -- ── reviews and analyses ──────────────────────────────────────────────────
        CREATE TABLE ai.pick_reviews (
            id             BIGSERIAL     PRIMARY KEY,
            reviewed_at    TIMESTAMPTZ   NOT NULL,
            fixture_id     BIGINT        NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            pick_id        BIGINT        REFERENCES picks.picks(id) ON DELETE SET NULL,
            market_key     TEXT          NOT NULL,
            selection      TEXT          NOT NULL,
            line           NUMERIC(6,2)  NOT NULL DEFAULT 0,
            odds           NUMERIC(9,3),
            bookmaker_id   INTEGER       REFERENCES market.bookmakers(id),
            p_model        NUMERIC(8,6),
            p_low          NUMERIC(8,6),
            p_market       NUMERIC(8,6),
            edge           NUMERIC(9,6),
            ev             NUMERIC(10,6),
            engine         TEXT          NOT NULL CHECK (engine IN ('rules', 'llm', 'combined')),
            engine_version TEXT          NOT NULL,
            provider       TEXT,
            model          TEXT,
            packet_id      BIGINT        REFERENCES ai.match_packets(id),
            input_hash     TEXT          NOT NULL,
            decision       TEXT          NOT NULL CHECK (decision IN ('APPROVE', 'DOWNGRADE', 'REJECT', 'ABSTAIN')),
            confidence     NUMERIC(4,3)  NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            context_score  NUMERIC(4,3)  CHECK (context_score BETWEEN 0 AND 1),
            model_score    NUMERIC(4,3)  CHECK (model_score BETWEEN 0 AND 1),
            market_score   NUMERIC(4,3)  CHECK (market_score BETWEEN 0 AND 1),
            fair_odds      NUMERIC(9,3),
            minimum_playable_odds NUMERIC(9,3),
            output         JSONB         NOT NULL,
            sources        JSONB         NOT NULL DEFAULT '[]'::jsonb,
            evidence_ids   BIGINT[]      NOT NULL DEFAULT '{}',
            tool_calls     JSONB         NOT NULL DEFAULT '[]'::jsonb,
            usage_ids      BIGINT[]      NOT NULL DEFAULT '{}',
            cost_usd       NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            mode           TEXT          NOT NULL CHECK (mode IN ('off', 'shadow', 'enforce')),
            status         TEXT          NOT NULL CHECK (status IN ('ok', 'fallback', 'invalid_output', 'failed',
                                         'over_budget')),
            error          TEXT
        );
        CREATE INDEX ai_pick_reviews_fixture ON ai.pick_reviews (fixture_id, reviewed_at DESC);
        CREATE INDEX ai_pick_reviews_day ON ai.pick_reviews (reviewed_at);
        CREATE INDEX ai_pick_reviews_subject ON ai.pick_reviews
            (fixture_id, market_key, selection, line, engine, reviewed_at DESC, id DESC);
        CREATE INDEX ai_pick_reviews_input ON ai.pick_reviews (input_hash);
        COMMENT ON TABLE ai.pick_reviews IS
          'A review can only confirm, lower, reject or abstain: there is no column for a probability it could raise '
          'or a pick it could create. engine combined = the most conservative of the engines that reviewed. A row '
          'is added only when the review differs from the newest one of the same selection and engine.';

        CREATE TABLE ai.match_analyses (
            id              BIGSERIAL   PRIMARY KEY,
            fixture_id      BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            built_at        TIMESTAMPTZ NOT NULL,
            rule_version    TEXT        NOT NULL,
            input_hash      TEXT        NOT NULL,
            packet_id       BIGINT      REFERENCES ai.match_packets(id),
            market_observed BOOLEAN     NOT NULL,
            cards           JSONB       NOT NULL,
            summary         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            engines         TEXT[]      NOT NULL DEFAULT '{}',
            CHECK (jsonb_typeof(cards) = 'array' AND jsonb_array_length(cards) <= 3)
        );
        CREATE INDEX ai_match_analyses_fixture ON ai.match_analyses (fixture_id, built_at DESC, id DESC);
        COMMENT ON TABLE ai.match_analyses IS
          'The PREDIGOL ANALYSIS of a match (at most three cards), computed once and read by every user. A row is '
          'added only when it differs from the newest one of its match.';

        -- ── what results taught ───────────────────────────────────────────────────
        CREATE TABLE ai.memory_events (
            id          BIGSERIAL    PRIMARY KEY,
            created_at  TIMESTAMPTZ  NOT NULL,
            kind        TEXT         NOT NULL CHECK (kind IN ('match_result', 'pick_result', 'context_error',
                                     'news_signal', 'injury_signal', 'market_signal', 'model_failure',
                                     'model_success', 'league_pattern', 'team_pattern', 'player_pattern',
                                     'review_quality')),
            entity_type TEXT         NOT NULL CHECK (entity_type IN ('fixture', 'pick', 'team', 'player',
                                     'competition', 'market', 'model', 'source', 'reviewer')),
            entity_id   TEXT         NOT NULL,
            fixture_id  BIGINT       REFERENCES core.fixtures(id) ON DELETE SET NULL,
            hypothesis  TEXT,
            evidence    JSONB        NOT NULL DEFAULT '{}'::jsonb,
            result      TEXT,
            confidence  NUMERIC(4,3) CHECK (confidence BETWEEN 0 AND 1),
            sources     JSONB        NOT NULL DEFAULT '[]'::jsonb,
            version     TEXT         NOT NULL,
            dedup_key   TEXT         UNIQUE
        );
        CREATE INDEX ai_memory_kind ON ai.memory_events (kind, created_at DESC);
        CREATE INDEX ai_memory_entity ON ai.memory_events (entity_type, entity_id);

        CREATE TABLE ai.postmortems (
            id          BIGSERIAL   PRIMARY KEY,
            fixture_id  BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL,
            version     TEXT        NOT NULL,
            outcome     JSONB       NOT NULL,
            expected    JSONB       NOT NULL,
            findings    JSONB       NOT NULL,
            narrative   TEXT,
            usage_ids   BIGINT[]    NOT NULL DEFAULT '{}',
            UNIQUE (fixture_id, version)
        );

        CREATE TABLE ai.shadow_reports (
            id          BIGSERIAL   PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL,
            window_from DATE        NOT NULL,
            window_to   DATE        NOT NULL,
            engine      TEXT        NOT NULL,
            arms        JSONB       NOT NULL,
            gate        JSONB       NOT NULL,
            version     TEXT        NOT NULL,
            CHECK (window_from <= window_to)
        );

        CREATE TABLE ai.correlation_estimates (
            id           BIGSERIAL    PRIMARY KEY,
            estimated_at TIMESTAMPTZ  NOT NULL,
            scope        TEXT         NOT NULL CHECK (scope IN ('same_competition_day')),
            market       TEXT         NOT NULL CHECK (market IN ('home_win', 'draw', 'away_win', 'over_2_5', 'btts')),
            rho          NUMERIC(8,5) NOT NULL CHECK (rho BETWEEN -1 AND 1),
            se           NUMERIC(8,5) NOT NULL CHECK (se >= 0),
            n_groups     INTEGER      NOT NULL CHECK (n_groups >= 0),
            n_matches    INTEGER      NOT NULL CHECK (n_matches >= 0),
            window_from  DATE         NOT NULL,
            window_to    DATE         NOT NULL,
            version      TEXT         NOT NULL
        );

        -- ── the AI jobs' own ledger ───────────────────────────────────────────────
        CREATE TABLE ai.cycles (
            id           BIGSERIAL     PRIMARY KEY,
            kind         TEXT          NOT NULL CHECK (kind IN ('analysis', 'postmortem', 'learning', 'evaluation')),
            started_at   TIMESTAMPTZ   NOT NULL,
            finished_at  TIMESTAMPTZ,
            status       TEXT          NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'partial',
                                       'failed')),
            mode         TEXT          NOT NULL CHECK (mode IN ('off', 'shadow', 'enforce')),
            budget_state TEXT          NOT NULL,
            counts       JSONB         NOT NULL DEFAULT '{}'::jsonb,
            cost_usd     NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            error        TEXT,
            CHECK ((status = 'running') = (finished_at IS NULL))
        );
        CREATE INDEX ai_cycles_kind ON ai.cycles (kind, started_at DESC);

        CREATE TABLE ai.run_requests (
            id           BIGSERIAL   PRIMARY KEY,
            kind         TEXT        NOT NULL CHECK (kind IN ('analysis', 'postmortem', 'learning', 'evaluation')),
            fixture_id   BIGINT      REFERENCES core.fixtures(id) ON DELETE CASCADE,
            requested_at TIMESTAMPTZ NOT NULL,
            requested_by BIGINT,
            status       TEXT        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done',
                                     'failed')),
            picked_at    TIMESTAMPTZ,
            cycle_id     BIGINT      REFERENCES ai.cycles(id) ON DELETE SET NULL
        );
        CREATE INDEX ai_run_requests_queued ON ai.run_requests (requested_at) WHERE status = 'queued';
    """)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")

    # The evolution loop: the owner's three answers and the stages of an accepted experiment.
    op.execute("""
        ALTER TABLE analytics.research_hypotheses DROP CONSTRAINT research_hypotheses_status_check;
        ALTER TABLE analytics.research_hypotheses ADD CONSTRAINT research_hypotheses_status_check
            CHECK (status IN ('PROPOSED', 'INVESTIGATING', 'ACCEPTED', 'REJECTED', 'RUNNING', 'SHADOW', 'DONE',
                              'PROMOTED'));
        ALTER TABLE analytics.research_hypotheses
            ADD COLUMN target TEXT NOT NULL DEFAULT 'other'
                CHECK (target IN ('models', 'backtesting', 'analytics', 'features', 'rankings', 'pick_engine',
                                  'decision_rules', 'data', 'ai', 'other')),
            ADD COLUMN stage_history JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN outcome JSONB;
        COMMENT ON COLUMN analytics.research_hypotheses.target IS
          'What the hypothesis would change if it were ever promoted. A proposal changes nothing by itself.';
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE analytics.research_hypotheses SET status = 'PROPOSED', decided_at = NULL
         WHERE status = 'INVESTIGATING';
        UPDATE analytics.research_hypotheses SET status = 'RUNNING' WHERE status = 'SHADOW';
        UPDATE analytics.research_hypotheses SET status = 'DONE' WHERE status = 'PROMOTED';
        ALTER TABLE analytics.research_hypotheses DROP CONSTRAINT research_hypotheses_status_check;
        ALTER TABLE analytics.research_hypotheses ADD CONSTRAINT research_hypotheses_status_check
            CHECK (status IN ('PROPOSED', 'ACCEPTED', 'REJECTED', 'RUNNING', 'DONE'));
        ALTER TABLE analytics.research_hypotheses DROP COLUMN target, DROP COLUMN stage_history,
            DROP COLUMN outcome;
        DROP SCHEMA ai CASCADE;
    """)
