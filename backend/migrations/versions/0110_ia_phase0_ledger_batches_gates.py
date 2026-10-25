"""Plan Maestro IA, Phase 0 - efficiency: the ledger learns what a cache write, a Batch call and a workspace are, the
Message Batches API gets its tables, the budget alerts get a scope, and the optimisations get an evidence gate.

All of it is ADDITIVE (docs/owner/IA_FASE0.md):

* ``ai.usage`` gains ``cache_write_tokens`` (+ ``cache_write_1h_tokens``, the part written for one hour; the rest is the
  5-minute entry) and ``cache_ttl``, ``thinking_tokens``, ``batch_id`` (``ai.batches.id``) and ``custom_id`` (the task's
  idempotency key), ``workspace`` and ``key_label`` (the NAMES - never a key), ``run_id`` (``ai.agent_runs`` in phase 1)
  and ``agent``. Rows already written keep NULL in them. A Batch result is recorded once: UNIQUE (batch_id, custom_id).
  ``ai.usage_scoped`` adds the scope - production, lab or exa - so Claude's money and Exa's are never one number.
* ``ai.batches`` / ``ai.batch_items``: the Message Batches API (``fbi.ai.batch``). A task is reserved as an item before it is
  sent (``submitting``), so a crash between the request and its note can never pay the same task twice; at most one OPEN
  item per ``custom_id``.
* ``ai.budget_alerts`` gains ``scope`` (production, lab, exa) and ``kind`` (month, projection), and its UNIQUE key becomes
  (month, scope, kind, threshold). Rows written by the earlier code take the defaults (production, month).
* ``ai.feature_gates`` (append-only): the evidence an optimisation needs before it switches itself on (``fbi.ai.gates``): the
  Batch probe, the structured-output stability test, the cache layout test. The newest row of a gate decides.
* ``ai.limit_hits`` (append-only): every time the provider said a spend limit is spent (HTTP 400 "workspace API usage limits",
  HTTP 429 ``enforced_spend_limit_reached``) - the budget treats the workspace as EXHAUSTED and tries again later, once.
* ``ai.match_briefs`` gains ``material_hash`` / ``material``: what changed MATERIALLY since a brief was written
  (``fbi.ai.material``), so a price that moves 2 % does not pay for the brief again.

On a live database (the worker keeps writing the ledger): the busy tables are locked FIRST and together, and a wait longer
than 10 s fails the migration whole (the lesson of 0076, 13 Oct 2026), so nothing is left half done and nothing else waits
behind it. The new tables hold no foreign key to a busy table for the same reason.

Revision ID: 0110
Revises: 0093
"""

from __future__ import annotations

from alembic import op

revision = "0110"
down_revision = "0093"
branch_labels = None
depends_on = None

APPEND_ONLY = ("feature_gates", "limit_hits")

USAGE_COLUMNS = ("cache_write_tokens", "cache_write_1h_tokens", "cache_ttl", "thinking_tokens", "batch_id", "custom_id",
                 "workspace", "key_label", "run_id", "agent")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE ai.budget_alerts, ai.usage, ai.match_briefs IN ACCESS EXCLUSIVE MODE")

    # ── the ledger ────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE ai.usage
            ADD COLUMN cache_write_tokens    INTEGER CHECK (cache_write_tokens IS NULL OR cache_write_tokens >= 0),
            ADD COLUMN cache_write_1h_tokens INTEGER CHECK (cache_write_1h_tokens IS NULL OR cache_write_1h_tokens >= 0),
            ADD COLUMN cache_ttl             TEXT    CHECK (cache_ttl IS NULL OR cache_ttl IN ('5m', '1h', 'mixed')),
            ADD COLUMN thinking_tokens       INTEGER CHECK (thinking_tokens IS NULL OR thinking_tokens >= 0),
            ADD COLUMN batch_id              BIGINT,
            ADD COLUMN custom_id             TEXT,
            ADD COLUMN workspace             TEXT,
            ADD COLUMN key_label             TEXT,
            ADD COLUMN run_id                BIGINT,
            ADD COLUMN agent                 TEXT;
        ALTER TABLE ai.usage ADD CONSTRAINT usage_cache_write_check
            CHECK (cache_write_1h_tokens IS NULL OR cache_write_tokens IS NULL
                   OR cache_write_1h_tokens <= cache_write_tokens);
        CREATE UNIQUE INDEX ai_usage_batch_once ON ai.usage (batch_id, custom_id) WHERE batch_id IS NOT NULL;
        CREATE INDEX ai_usage_custom ON ai.usage (custom_id) WHERE custom_id IS NOT NULL;
        COMMENT ON COLUMN ai.usage.input_tokens IS
          'ALL the input tokens of the call: the fresh ones, cached_tokens (read from the cache) and cache_write_tokens '
          '(written to it).';
        COMMENT ON COLUMN ai.usage.cache_write_tokens IS
          'Input written to the prompt cache (billed 1.25 times the input price for 5 minutes, 2 times for one hour); '
          'cache_write_1h_tokens is the part written for one hour. NULL before 0110.';
        COMMENT ON COLUMN ai.usage.batch_id IS 'ai.batches.id when the call went through the Message Batches API.';
        COMMENT ON COLUMN ai.usage.custom_id IS 'The task''s idempotency key (a Batch request''s custom_id).';
        COMMENT ON COLUMN ai.usage.workspace IS 'The Claude workspace that paid (PREDIGOL, PREDIGOL-LAB): a name, never a key.';
        COMMENT ON COLUMN ai.usage.key_label IS 'The API key''s NAME in the Console (worker-prod, worker-lab), never the key.';

        CREATE OR REPLACE FUNCTION ai.scope_of(tier TEXT, workspace TEXT) RETURNS TEXT
            LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
            SELECT CASE WHEN tier = 'search' THEN 'exa'
                        WHEN upper(coalesce(workspace, '')) LIKE '%LAB' THEN 'lab'
                        ELSE 'production' END
        $fn$;
        CREATE VIEW ai.usage_scoped AS
            SELECT u.*, ai.scope_of(u.tier, u.workspace) AS scope FROM ai.usage u;
        COMMENT ON VIEW ai.usage_scoped IS
          'ai.usage with the money''s scope: exa (every search), lab (a call made with the LAB workspace''s key) or production '
          '(the rest, including every row written before 0110).';
    """)

    # ── the Message Batches API ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE ai.batches (
            id             BIGSERIAL   PRIMARY KEY,
            batch_ref      TEXT        UNIQUE,
            provider       TEXT        NOT NULL,
            workspace      TEXT        NOT NULL,
            key_label      TEXT        NOT NULL,
            kind           TEXT        NOT NULL CHECK (kind IN ('production', 'lab', 'probe')),
            status         TEXT        NOT NULL CHECK (status IN ('submitting', 'in_progress', 'canceling', 'ended',
                                       'failed', 'abandoned')),
            created_at     TIMESTAMPTZ NOT NULL,
            submitted_at   TIMESTAMPTZ,
            ended_at       TIMESTAMPTZ,
            expires_at     TIMESTAMPTZ,
            last_polled_at TIMESTAMPTZ,
            processed_at   TIMESTAMPTZ,
            n_items        INTEGER     NOT NULL CHECK (n_items >= 0),
            counts         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            error          TEXT,
            CHECK (batch_ref IS NOT NULL OR status IN ('submitting', 'failed', 'abandoned'))
        );
        CREATE INDEX ai_batches_open ON ai.batches (created_at) WHERE processed_at IS NULL;
        COMMENT ON TABLE ai.batches IS
          'One Message Batches API batch (half price, up to 24 h). batch_ref is the provider''s id, NULL while it is being sent. '
          'processed_at: every result was recorded. The key is never stored: key_label names it.';

        CREATE TABLE ai.batch_items (
            id             BIGSERIAL     PRIMARY KEY,
            batch_id       BIGINT        NOT NULL REFERENCES ai.batches(id),
            custom_id      TEXT          NOT NULL CHECK (custom_id ~ '^[a-zA-Z0-9_-]{1,64}$'),
            purpose        TEXT          NOT NULL,
            tier           TEXT          NOT NULL,
            model          TEXT          NOT NULL,
            fixture_id     BIGINT,
            input_hash     TEXT          NOT NULL,
            prompt_version TEXT,
            est_cost_usd   NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (est_cost_usd >= 0),
            deadline_at    TIMESTAMPTZ,
            status         TEXT          NOT NULL CHECK (status IN ('submitting', 'submitted', 'succeeded', 'invalid',
                                         'errored', 'canceled', 'expired', 'late', 'abandoned')),
            created_at     TIMESTAMPTZ   NOT NULL,
            resolved_at    TIMESTAMPTZ,
            usage_id       BIGINT,
            context        JSONB         NOT NULL DEFAULT '{}'::jsonb,
            error          TEXT,
            UNIQUE (batch_id, custom_id)
        );
        CREATE UNIQUE INDEX ai_batch_items_open_once ON ai.batch_items (custom_id)
            WHERE status IN ('submitting', 'submitted');
        CREATE INDEX ai_batch_items_fixture ON ai.batch_items (fixture_id, status) WHERE fixture_id IS NOT NULL;
        COMMENT ON TABLE ai.batch_items IS
          'One task inside a batch. custom_id is the task''s idempotency key: at most one OPEN item (submitting or submitted) '
          'per key, so the same task is never paid twice. est_cost_usd counts against the budget until the result arrives. '
          'context: what is needed to validate and store the answer, never a prompt and never a key.';
    """)

    # ── the budget's alerts, by scope ─────────────────────────────────────────────
    op.execute("""
        ALTER TABLE ai.budget_alerts
            ADD COLUMN scope TEXT NOT NULL DEFAULT 'production' CHECK (scope IN ('production', 'lab', 'exa')),
            ADD COLUMN kind  TEXT NOT NULL DEFAULT 'month' CHECK (kind IN ('month', 'projection'));
        DO $do$
        DECLARE c text;
        BEGIN
            FOR c IN SELECT conname FROM pg_constraint
                      WHERE conrelid = 'ai.budget_alerts'::regclass AND contype = 'u'
            LOOP
                EXECUTE format('ALTER TABLE ai.budget_alerts DROP CONSTRAINT %I', c);
            END LOOP;
        END
        $do$;
        ALTER TABLE ai.budget_alerts ADD CONSTRAINT budget_alerts_scope_key UNIQUE (month, scope, kind, threshold);
        COMMENT ON COLUMN ai.budget_alerts.kind IS
          'month: the spend of the month crossed threshold % of the scope''s envelope. projection: the month''s PROJECTED '
          'spend did (spent_usd is then the projection). An alert warns; it never degrades anything.';
    """)

    # ── the evidence an optimisation needs, and the spend limits the provider reported ──
    op.execute("""
        CREATE TABLE ai.feature_gates (
            id            BIGSERIAL   PRIMARY KEY,
            gate          TEXT        NOT NULL CHECK (gate IN ('batch', 'native_schema', 'cache_layout', 'gate_a')),
            at            TIMESTAMPTZ NOT NULL,
            passed        BOOLEAN     NOT NULL,
            evidence      JSONB       NOT NULL,
            evidence_hash TEXT        NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
            decided_by    TEXT        NOT NULL CHECK (decided_by IN ('script', 'owner')),
            code_version  TEXT
        );
        CREATE INDEX ai_feature_gates_gate ON ai.feature_gates (gate, at DESC);
        COMMENT ON TABLE ai.feature_gates IS
          'The evidence behind an optimisation of the AI layer switching itself on (FBI_AI_<NAME>=auto): written by '
          'scripts/ia_probe.py and scripts/ia_equivalence.py from real measurements, never by hand. The newest row of a gate '
          'decides; a row with passed = false switches it off again.';

        CREATE TABLE ai.limit_hits (
            id          BIGSERIAL   PRIMARY KEY,
            at          TIMESTAMPTZ NOT NULL,
            provider    TEXT        NOT NULL,
            workspace   TEXT        NOT NULL,
            key_label   TEXT,
            kind        TEXT        NOT NULL CHECK (kind IN ('workspace_limit', 'tier_cap')),
            http_status INTEGER     NOT NULL,
            request_id  TEXT,
            purpose     TEXT
        );
        CREATE INDEX ai_limit_hits_at ON ai.limit_hits (workspace, at DESC);
        COMMENT ON TABLE ai.limit_hits IS
          'The provider answered that a spend limit is spent (HTTP 400 "workspace API usage limits"; HTTP 429 '
          'enforced_spend_limit_reached). The workspace is EXHAUSTED for a while: the rules reviewer decides and the layer '
          'tries once more later - never in a loop.';
    """)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")

    # ── what changed materially since a brief was written ─────────────────────────
    op.execute("""
        ALTER TABLE ai.match_briefs ADD COLUMN material_hash TEXT, ADD COLUMN material JSONB;
        CREATE INDEX ai_match_briefs_material ON ai.match_briefs (fixture_id, material_hash)
            WHERE material_hash IS NOT NULL;
        COMMENT ON COLUMN ai.match_briefs.material_hash IS
          'material-v1 (fbi.ai.material): lineups, absences, evidence, kick-off, scenario and candidates, without the prices.';
        COMMENT ON COLUMN ai.match_briefs.material IS
          'The material snapshot the brief was written under, prices included: a later input is compared with it.';
    """)


def downgrade() -> None:
    # The additions go; what they recorded goes with them (the ledger's old columns keep every cost). The append-only guard is
    # lifted for this transaction only, as the earlier migrations do.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL fbi.ai_maintenance = 'on'")
    op.execute("""
        ALTER TABLE ai.match_briefs DROP COLUMN material, DROP COLUMN material_hash;
        DROP TABLE ai.limit_hits;
        DROP TABLE ai.feature_gates;
        DELETE FROM ai.budget_alerts WHERE scope <> 'production' OR kind <> 'month';
        ALTER TABLE ai.budget_alerts DROP CONSTRAINT budget_alerts_scope_key;
        ALTER TABLE ai.budget_alerts ADD CONSTRAINT budget_alerts_month_threshold_key UNIQUE (month, threshold);
        ALTER TABLE ai.budget_alerts DROP COLUMN kind, DROP COLUMN scope;
        DROP TABLE ai.batch_items;
        DROP TABLE ai.batches;
        DROP VIEW ai.usage_scoped;
        DROP FUNCTION ai.scope_of(TEXT, TEXT);
        DROP INDEX ai.ai_usage_custom;
        DROP INDEX ai.ai_usage_batch_once;
        ALTER TABLE ai.usage DROP CONSTRAINT usage_cache_write_check;
    """)
    for column in USAGE_COLUMNS:
        op.execute(f"ALTER TABLE ai.usage DROP COLUMN {column}")
