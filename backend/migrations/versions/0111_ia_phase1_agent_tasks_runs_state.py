"""Plan Maestro IA, Phase 1 - the tables the agents work through, and who may promote one.

All of it is ADDITIVE and nothing reads it yet (docs/owner/IA_FASE1.md): the code that ran before this phase finds the schema it wrote.

* ``ai.agent_tasks``: the queue of the orchestrator (``fbi.ai.orchestrator``, phase 2) and, with ``ai.batches``, the only AI table
  whose rows change. A task is one question put to one agent: its identity is the fields ``fbi.ai.idempotency.TaskIdentity`` hashes
  into ``idem_key`` (UNIQUE: the same question is one row, so it is asked once), and a trigger holds them still. The state moves only
  along the lines the plan draws (planned > queued > running > done | failed | skipped | expired; a failed, skipped or expired task
  may be planned again, a done one never), the attempts count up by one when a task starts and stop at three, and a task is never
  deleted. ``reserved_usd`` is GENERATED: the estimate while the task is queued or running (and not travelling in a Batch, whose item
  carries it), zero otherwise - the reservation cannot be forgotten, because nothing has to release it.
* ``ai.agent_runs`` (append-only): one row per attempt, whatever came of it (``ok``, ``invalid``, ``timeout``, ``abstain``,
  ``skipped``, ``expired``, ``budget_skip``) - section 32 of the plan. At most ONE run per ``idem_key`` holds a model's answer
  (UNIQUE ... WHERE status IN ('ok', 'invalid', 'abstain')): paying twice for the same question is a constraint violation, not a bug
  somebody has to notice.
* ``ai.match_runs`` (append-only) and the view ``ai.match_state``: what the system knew and decided about a match at the end of a
  pass - data, market, model, research, agents, contradictions, candidates, risks, final - and the newest live row of each match.
* ``intel.promotions`` admits the entity ``agent`` (one row per agent, family and version, signed by the owner) and the database,
  not a prompt, enforces who writes it: a ROW POLICY. Every role but the owner (the table's) refuses an ``agent`` row, and the
  role ``predigol_rollback`` - created by the operator (db/roles.sql), reached by the worker with SET ROLE - can write exactly one
  kind of row: the demotion, by the system, of the champion the family has right now (``intel.agent_champion``: the one function that
  says who that is, for the policy and for whoever reads it), dated from that champion's promotion to now. It cannot promote, and it
  cannot write the other entities. The row's shape is a CHECK for everybody, the owner included.

On a live database (the worker keeps writing): the busy table is locked FIRST and a wait longer than 10 s fails the migration whole
(the lesson of 0076, 13 Oct 2026). The new tables hold no foreign key to a busy table.

Revision ID: 0111
Revises: 0110
"""

from __future__ import annotations

from alembic import op

revision = "0111"
down_revision = "0110"
branch_labels = None
depends_on = None

# The vocabularies below are the code's, and tests/integration/test_agent_tables_0111.py reads them back out of the database and holds
# them equal: the families (fbi.ai.contracts.base.FAMILIES), the tasks (fbi.ai.router.TASKS and the tasks the registry knows, the old
# route's review included), the passes (fbi.ai.contracts.mcp.PassKind).
FAMILIES = ("1X2", "DC", "AH", "OU", "BTTS", "CORNERS", "CARDS")
PASS_KINDS = ("first", "pre", "final", "request")
TASKS = ("context", "evaluation", "extraction", "narrative", "council", "analyst", "loss_review", "escalation", "owner_research",
         "review_analysis", "review_final")
TASK_STATES = ("planned", "queued", "running", "done", "failed", "skipped", "expired")
RUN_STATUSES = ("ok", "invalid", "timeout", "abstain", "skipped", "expired", "budget_skip")
ROLES = ("CHAMPION", "CHALLENGER", "RETIRED", "REJECTED", "VALIDATED", "NOT_VALIDATED")
ENTITIES = ("calibrator", "market_edge", "selection_rule", "model", "agent")
ROLLBACK_ROLE = "predigol_rollback"
APPEND_ONLY = ("agent_runs", "match_runs")

SHA256 = "^[0-9a-f]{64}$"
NAME = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
"""``fbi.ai.idempotency.NAME``: an agent, a version or a model - ASCII, no spaces, nothing that reads as a separator."""
PROMOTION_NAME = ("^[a-z][a-z0-9]*(_[a-z0-9]+)*@[a-z][a-z0-9]*(-[a-z0-9]+)*-v[1-9][0-9]{0,2}"
                  "([+][a-z][a-z0-9]*(-[a-z0-9]+)*-v[1-9][0-9]{0,2})*$")
"""``fbi.ai.agents.registry.PROMOTION_NAME``: ``agent@version`` and, for an agent that reads the answers of others, ``+upstream-version``."""
GATE_VERSION = "^[a-z][a-z0-9]*(-[a-z0-9]+)*-v[1-9][0-9]{0,2}$"


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # On a live database: never wait for a lock while holding others. The one table that is altered is locked first; a wait longer
    # than 10 s fails the migration whole (transactional DDL), so the deploy retries or stops with nothing changed.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("LOCK TABLE intel.promotions IN ACCESS EXCLUSIVE MODE")

    op.execute("""
        CREATE FUNCTION ai.candidates_ok(candidates TEXT[]) RETURNS BOOLEAN
            LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
            SELECT candidates IS NOT NULL
               AND cardinality(candidates) <= 12
               AND NOT EXISTS (SELECT 1 FROM unnest(candidates) AS c WHERE c IS NULL OR c !~ '^c[0-9]{1,3}$')
               AND (SELECT count(DISTINCT c) FROM unnest(candidates) AS c) = cardinality(candidates)
        $fn$;
        COMMENT ON FUNCTION ai.candidates_ok(TEXT[]) IS
          'The selections a task asks about, as the package names them (c1, c2...): at most 12, each once.';
    """)

    # ── every attempt of every task (append-only) ─────────────────────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE ai.agent_runs (
            id               BIGSERIAL     PRIMARY KEY,
            run_kind         TEXT          NOT NULL CHECK (run_kind IN ('live', 'shadow', 'replay', 'battery')),
            reason           TEXT          NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 200),
            parent_run_id    BIGINT        REFERENCES ai.agent_runs(id),
            task_kind        TEXT          NOT NULL CHECK (task_kind IN ({_in(TASKS)})),
            pass_kind        TEXT          NOT NULL CHECK (pass_kind IN ({_in(PASS_KINDS)})),
            fixture_id       BIGINT        CHECK (fixture_id IS NULL OR fixture_id >= 1),
            candidates       TEXT[]        NOT NULL DEFAULT '{{}}' CHECK (ai.candidates_ok(candidates)),
            started_at       TIMESTAMPTZ   NOT NULL,
            finished_at      TIMESTAMPTZ   NOT NULL,
            known_at         TIMESTAMPTZ,
            model            TEXT          CHECK (model IS NULL OR model ~ '{NAME}'),
            effort           TEXT          CHECK (effort IS NULL OR effort IN ('low', 'medium')),
            agent            TEXT          NOT NULL CHECK (agent ~ '{NAME}'),
            agent_version    TEXT          NOT NULL CHECK (agent_version ~ '{NAME}'),
            prompt_version   TEXT          NOT NULL CHECK (prompt_version ~ '{NAME}'),
            schema_version   TEXT          NOT NULL CHECK (schema_version ~ '{NAME}'),
            router_version   TEXT          NOT NULL CHECK (router_version ~ '{NAME}'),
            package_hash     TEXT          CHECK (package_hash IS NULL OR package_hash ~ '{SHA256}'),
            slice_hash       TEXT          CHECK (slice_hash IS NULL OR slice_hash ~ '{SHA256}'),
            idem_key         TEXT          NOT NULL CHECK (idem_key ~ '{SHA256}'),
            attempt          SMALLINT      NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 3),
            evidence_ids     BIGINT[]      NOT NULL DEFAULT '{{}}',
            data_refs        TEXT[]        NOT NULL DEFAULT '{{}}',
            output           JSONB         CHECK (output IS NULL OR jsonb_typeof(output) = 'object'),
            verdict          TEXT          CHECK (verdict IS NULL OR length(verdict) BETWEEN 1 AND 64),
            input_tokens     INTEGER       CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens    INTEGER       CHECK (output_tokens IS NULL OR output_tokens >= 0),
            cached_tokens    INTEGER       CHECK (cached_tokens IS NULL OR cached_tokens >= 0),
            cache_write_tokens INTEGER     CHECK (cache_write_tokens IS NULL OR cache_write_tokens >= 0),
            thinking_tokens  INTEGER       CHECK (thinking_tokens IS NULL OR thinking_tokens >= 0),
            cache_ttl        TEXT          CHECK (cache_ttl IS NULL OR cache_ttl IN ('5m', '1h', 'mixed')),
            batch_id         BIGINT,
            custom_id        TEXT          CHECK (custom_id IS NULL OR custom_id ~ '^[a-zA-Z0-9_-]{{1,64}}$'),
            cost_usd         NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            workspace        TEXT,
            key_label        TEXT,
            usage_id         BIGINT,
            latency_ms       INTEGER       CHECK (latency_ms IS NULL OR latency_ms >= 0),
            queue_ms         INTEGER       CHECK (queue_ms IS NULL OR queue_ms >= 0),
            status           TEXT          NOT NULL CHECK (status IN ({_in(RUN_STATUSES)})),
            error            TEXT          CHECK (error IS NULL OR length(error) <= 2000),
            CONSTRAINT agent_runs_attempt_once UNIQUE (idem_key, attempt),
            CONSTRAINT agent_runs_time CHECK (finished_at >= started_at AND (known_at IS NULL OR known_at <= started_at)),
            CONSTRAINT agent_runs_tokens CHECK (coalesce(cached_tokens, 0) + coalesce(cache_write_tokens, 0)
                                                <= coalesce(input_tokens, 0)),
            CONSTRAINT agent_runs_answer CHECK (
                status NOT IN ('ok', 'invalid', 'abstain')
                OR (model IS NOT NULL AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)),
            CONSTRAINT agent_runs_output CHECK (
                (status IN ('ok', 'abstain') AND output IS NOT NULL)
                OR (status NOT IN ('ok', 'abstain') AND output IS NULL AND verdict IS NULL)),
            CONSTRAINT agent_runs_unpaid CHECK (
                status NOT IN ('skipped', 'budget_skip', 'timeout')
                OR (cost_usd = 0 AND input_tokens IS NULL AND output_tokens IS NULL)),
            CONSTRAINT agent_runs_error CHECK (status IN ('ok', 'abstain') OR error IS NOT NULL)
        );
        CREATE UNIQUE INDEX ai_agent_runs_paid_once ON ai.agent_runs (idem_key)
            WHERE status IN ('ok', 'invalid', 'abstain');
        CREATE INDEX ai_agent_runs_fixture ON ai.agent_runs (fixture_id, started_at DESC) WHERE fixture_id IS NOT NULL;
        CREATE INDEX ai_agent_runs_agent ON ai.agent_runs (agent, agent_version, started_at DESC);
        CREATE INDEX ai_agent_runs_unwell ON ai.agent_runs (status, started_at DESC) WHERE status <> 'ok';
        CREATE INDEX ai_agent_runs_batch ON ai.agent_runs (batch_id, custom_id) WHERE batch_id IS NOT NULL;
        CREATE INDEX ai_agent_runs_parent ON ai.agent_runs (parent_run_id) WHERE parent_run_id IS NOT NULL;
        COMMENT ON TABLE ai.agent_runs IS
          'One row per ATTEMPT of a task, whatever came of it (plan section 32): why it ran, what for, when, with which model, agent, '
          'prompt and schema, over which hashes, citing which evidence, with what answer, tokens, cost and latency, and how it ended. '
          'Append-only. The prompt itself is not stored: its version and the hash of the slice are enough to rebuild it from the '
          'stored package. At most ONE row per idem_key holds a model answer (ok, invalid, abstain): a question is paid once.';
        COMMENT ON COLUMN ai.agent_runs.known_at IS 'The moment of the knowledge the run read (the package''s known_at): the leak audit''s subject.';
        COMMENT ON COLUMN ai.agent_runs.model IS 'The model the API answered with, not the one asked for. NULL when no call was made.';
        COMMENT ON COLUMN ai.agent_runs.output IS 'The validated JSON of the contract (aa-v1, cd-v1, pmr-v1, la-v1). NULL unless status is ok or abstain.';
        COMMENT ON COLUMN ai.agent_runs.input_tokens IS
          'ALL the input tokens of the call, as in ai.usage: the fresh ones, cached_tokens (read) and cache_write_tokens (written).';
        COMMENT ON COLUMN ai.agent_runs.workspace IS 'The Claude workspace that paid (PREDIGOL, PREDIGOL-LAB): a name, never a key.';
        COMMENT ON COLUMN ai.agent_runs.key_label IS 'The API key''s NAME in the Console, never the key.';
        COMMENT ON COLUMN ai.agent_runs.usage_id IS 'ai.usage.id of the call, when it made one (no foreign key: that table is busy).';
        COMMENT ON COLUMN ai.agent_runs.attempt IS 'Which attempt of the task this is (1 to 3): only transport failures are retried.';
    """)

    # ── the queue ─────────────────────────────────────────────────────────────────────────────────────────────
    op.execute(f"""
        CREATE TABLE ai.agent_tasks (
            id             BIGSERIAL     PRIMARY KEY,
            idem_key       TEXT          NOT NULL UNIQUE CHECK (idem_key ~ '{SHA256}'),
            custom_id      TEXT          NOT NULL,
            workspace      TEXT          NOT NULL CHECK (workspace IN ('production', 'lab')),
            agent          TEXT          NOT NULL CHECK (agent ~ '{NAME}'),
            agent_version  TEXT          NOT NULL CHECK (agent_version ~ '{NAME}'),
            prompt_version TEXT          NOT NULL CHECK (prompt_version ~ '{NAME}'),
            schema_version TEXT          NOT NULL CHECK (schema_version ~ '{NAME}'),
            model          TEXT          NOT NULL CHECK (model ~ '{NAME}'),
            effort         TEXT          NOT NULL CHECK (effort IN ('low', 'medium')),
            input_version  TEXT          NOT NULL CHECK (input_version ~ '{NAME}'),
            input_hash     TEXT          NOT NULL CHECK (input_hash ~ '{SHA256}'),
            pass_kind      TEXT          NOT NULL CHECK (pass_kind IN ({_in(PASS_KINDS)})),
            fixture_id     BIGINT        NOT NULL CHECK (fixture_id >= 1),
            candidates     TEXT[]        NOT NULL DEFAULT '{{}}' CHECK (ai.candidates_ok(candidates)),
            run_kind       TEXT          NOT NULL CHECK (run_kind IN ('live', 'shadow', 'replay')),
            task_kind      TEXT          NOT NULL CHECK (task_kind IN ({_in(TASKS)})),
            reason         TEXT          NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 200),
            router_version TEXT          NOT NULL CHECK (router_version ~ '{NAME}'),
            route          JSONB         NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(route) = 'object'),
            package_hash   TEXT          CHECK (package_hash IS NULL OR package_hash ~ '{SHA256}'),
            priority       INTEGER       NOT NULL CHECK (priority BETWEEN 0 AND 1000000),
            est_cost_usd   NUMERIC(12,6) NOT NULL CHECK (est_cost_usd > 0),
            state          TEXT          NOT NULL DEFAULT 'planned' CHECK (state IN ({_in(TASK_STATES)})),
            created_at     TIMESTAMPTZ   NOT NULL,
            not_before     TIMESTAMPTZ   NOT NULL,
            deadline_at    TIMESTAMPTZ   NOT NULL,
            queued_at      TIMESTAMPTZ,
            started_at     TIMESTAMPTZ,
            finished_at    TIMESTAMPTZ,
            attempts       SMALLINT      NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
            batch_id       BIGINT,
            last_run_id    BIGINT        REFERENCES ai.agent_runs(id),
            reserved_usd   NUMERIC(12,6) GENERATED ALWAYS AS (
                               CASE WHEN state IN ('queued', 'running') AND batch_id IS NULL THEN est_cost_usd
                                    ELSE 0::numeric END) STORED,
            CONSTRAINT agent_tasks_window CHECK (not_before <= deadline_at),
            CONSTRAINT agent_tasks_custom_id CHECK (custom_id = left(idem_key, 48)),
            CONSTRAINT agent_tasks_times CHECK (
                (state NOT IN ('queued', 'running', 'done', 'failed') OR queued_at IS NOT NULL)
                AND (state NOT IN ('running', 'done', 'failed') OR started_at IS NOT NULL)
                AND (state NOT IN ('done', 'failed', 'skipped', 'expired') OR finished_at IS NOT NULL)
                AND (state NOT IN ('planned', 'queued', 'running') OR finished_at IS NULL)
                AND (state <> 'running' OR attempts >= 1)),
            CONSTRAINT agent_tasks_ends_in_a_run CHECK (
                state NOT IN ('done', 'failed', 'skipped', 'expired') OR last_run_id IS NOT NULL)
        );
        CREATE INDEX ai_agent_tasks_claim ON ai.agent_tasks (priority, deadline_at, id) WHERE state = 'queued';
        CREATE INDEX ai_agent_tasks_open ON ai.agent_tasks (deadline_at) WHERE state IN ('planned', 'queued', 'running');
        CREATE INDEX ai_agent_tasks_fixture ON ai.agent_tasks (fixture_id, state);
        CREATE INDEX ai_agent_tasks_reserved ON ai.agent_tasks (workspace) INCLUDE (reserved_usd) WHERE reserved_usd > 0;
        CREATE INDEX ai_agent_tasks_batch ON ai.agent_tasks (batch_id) WHERE batch_id IS NOT NULL;
        COMMENT ON TABLE ai.agent_tasks IS
          'The orchestrator''s queue (plan section 18): one row per question put to one agent. It, with ai.batches, is the only AI '
          'table whose rows change - only state, attempts, times, batch_id and last_run_id, and only along the lines the plan draws '
          '(a trigger holds the rest): planned > queued > running > done | failed | skipped | expired; a failed, skipped or expired task '
          'may be planned again, a done one never; no task is ever deleted. Claimed with FOR UPDATE SKIP LOCKED. Every ending leaves a '
          'row in ai.agent_runs and last_run_id points at it.';
        COMMENT ON COLUMN ai.agent_tasks.idem_key IS
          'fbi.ai.idempotency.idem_key: the sha256 of everything that can change the answer. UNIQUE: the same question is one row, so '
          'it is asked, and paid, once.';
        COMMENT ON COLUMN ai.agent_tasks.priority IS 'Smaller first: the final pass before the pre before the first, candidates before context, production before the LAB.';
        COMMENT ON COLUMN ai.agent_tasks.est_cost_usd IS 'What the task is estimated to cost, from the price table and the slice''s tokens. Never changes.';
        COMMENT ON COLUMN ai.agent_tasks.reserved_usd IS
          'GENERATED: est_cost_usd while the task is queued or running and not in a Batch (a Batch item carries its own estimate), zero '
          'otherwise. The budget adds it to the month''s spend: the real cost is written to ai.usage when the call ends and the '
          'reservation goes by itself.';
        COMMENT ON COLUMN ai.agent_tasks.last_run_id IS 'The ai.agent_runs row of the last attempt. Every ending state has one.';
        COMMENT ON COLUMN ai.agent_tasks.batch_id IS 'ai.batches.id when the task travels in the Message Batches API (no foreign key: that table is written every 5 minutes).';
    """)

    # ── the state of a match at the end of a pass (append-only) and its current view ─────────────────────────────
    op.execute(f"""
        CREATE TABLE ai.match_runs (
            id              BIGSERIAL   PRIMARY KEY,
            fixture_id      BIGINT      NOT NULL CHECK (fixture_id >= 1),
            run_kind        TEXT        NOT NULL CHECK (run_kind IN ('live', 'shadow', 'replay')),
            pass_kind       TEXT        NOT NULL CHECK (pass_kind IN ({_in(PASS_KINDS)})),
            known_at        TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL,
            state_version   TEXT        NOT NULL CHECK (state_version ~ '{NAME}'),
            package_version TEXT        CHECK (package_version IS NULL OR package_version ~ '{NAME}'),
            package_hash    TEXT        CHECK (package_hash IS NULL OR package_hash ~ '{SHA256}'),
            packet_id       BIGINT,
            elapsed_ms      INTEGER     CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0),
            slices          JSONB       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(slices) = 'array'),
            blocking        TEXT[]      NOT NULL DEFAULT '{{}}',
            flags           TEXT[]      NOT NULL DEFAULT '{{}}',
            data_status     JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(data_status) = 'object'),
            market_status   JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(market_status) = 'object'),
            model_status    JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(model_status) = 'object'),
            research_status JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(research_status) = 'object'),
            agents          JSONB       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(agents) = 'array'),
            contradictions  JSONB       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(contradictions) = 'array'),
            candidates      JSONB       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(candidates) = 'array'),
            risks           JSONB       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(risks) = 'array'),
            final           JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(final) = 'object'),
            CONSTRAINT match_runs_time CHECK (known_at <= created_at),
            CONSTRAINT match_runs_once UNIQUE (fixture_id, run_kind, pass_kind, known_at)
        );
        CREATE INDEX ai_match_runs_live ON ai.match_runs (fixture_id, known_at DESC, id DESC) WHERE run_kind = 'live';
        COMMENT ON TABLE ai.match_runs IS
          'What the system knew and decided about a match at the end of a pass (plan sections 4 and 18), one row per pass and moment '
          'of knowledge. Append-only: a later pass is another row. data_status, market_status, model_status and research_status say '
          'what there is; agents lists the agents foreseen, run, failed or waiting with their version, model and cost; contradictions '
          'the rules of contra-v1 that fired; candidates the selections with the state the decision layer gave them; risks the flags; '
          'final the Council''s verdict, the final state and the moment it was frozen. A row built before any agent ran (phase 1, no '
          'model) has them empty. The statuses are written by the code that builds the row (state_version) and are never read back '
          'as instructions.';
        COMMENT ON COLUMN ai.match_runs.slices IS 'ai.package.Slice.measures() of each slice: name, hash, tokens, cap, fits, trimmed, blocks. Never its content.';
        COMMENT ON COLUMN ai.match_runs.packet_id IS 'ai.match_packets.id of the stored packet the package was derived from (no foreign key: that table is busy).';
        COMMENT ON COLUMN ai.match_runs.run_kind IS 'live: the match as the system sees it; shadow: an arm under test; replay: a backtest over a stored package. Only live feeds ai.match_state.';

        CREATE VIEW ai.match_state AS
            SELECT DISTINCT ON (fixture_id)
                   id AS match_run_id, fixture_id, pass_kind, known_at, created_at, state_version, package_version, package_hash,
                   packet_id, elapsed_ms, slices, blocking, flags, data_status, market_status, model_status, research_status,
                   agents, contradictions, candidates, risks, final
              FROM ai.match_runs
             WHERE run_kind = 'live'
             ORDER BY fixture_id, known_at DESC, id DESC;
        COMMENT ON VIEW ai.match_state IS
          'The current state of each match: the newest LIVE row of ai.match_runs (the latest knowledge, then the latest write). The '
          'Council reads its compact form; the administrator''s match file shows it whole.';
    """)

    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")

    # The queue changes state, but not at will.
    op.execute("""
        CREATE FUNCTION ai.agent_tasks_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.ai_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ai.agent_tasks: a task is never deleted (DELETE refused)' USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.state = 'done' THEN
                RAISE EXCEPTION 'ai.agent_tasks: task % is done and final (UPDATE refused)', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF (NEW.id, NEW.idem_key, NEW.custom_id, NEW.workspace, NEW.agent, NEW.agent_version, NEW.prompt_version,
                NEW.schema_version, NEW.model, NEW.effort, NEW.input_version, NEW.input_hash, NEW.pass_kind, NEW.fixture_id,
                NEW.candidates, NEW.run_kind, NEW.task_kind, NEW.reason, NEW.router_version, NEW.route, NEW.package_hash,
                NEW.est_cost_usd, NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.idem_key, OLD.custom_id, OLD.workspace, OLD.agent, OLD.agent_version, OLD.prompt_version,
                OLD.schema_version, OLD.model, OLD.effort, OLD.input_version, OLD.input_hash, OLD.pass_kind, OLD.fixture_id,
                OLD.candidates, OLD.run_kind, OLD.task_kind, OLD.reason, OLD.router_version, OLD.route, OLD.package_hash,
                OLD.est_cost_usd, OLD.created_at) THEN
                RAISE EXCEPTION 'ai.agent_tasks: what task % is never changes (UPDATE refused)', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.state <> OLD.state AND NOT ((OLD.state, NEW.state) IN (
                    ('planned', 'queued'), ('planned', 'skipped'), ('planned', 'expired'),
                    ('queued', 'running'), ('queued', 'skipped'), ('queued', 'expired'),
                    ('running', 'done'), ('running', 'failed'), ('running', 'expired'), ('running', 'queued'),
                    ('running', 'skipped'),
                    ('failed', 'planned'), ('skipped', 'planned'), ('expired', 'planned'))) THEN
                RAISE EXCEPTION 'ai.agent_tasks: task % cannot go from % to % (UPDATE refused)', OLD.id, OLD.state, NEW.state
                    USING ERRCODE = 'check_violation';
            END IF;
            -- the attempts count up by one when a task starts, and go back to zero only when it is planned again
            IF NEW.attempts <> OLD.attempts THEN
                IF NOT ((OLD.state = 'queued' AND NEW.state = 'running' AND NEW.attempts = OLD.attempts + 1)
                        OR (NEW.state = 'planned' AND OLD.state <> 'planned' AND NEW.attempts = 0)) THEN
                    RAISE EXCEPTION 'ai.agent_tasks: the attempts of task % move only when it starts (+1) or is planned again (0)', OLD.id
                        USING ERRCODE = 'check_violation';
                END IF;
            ELSIF OLD.state = 'queued' AND NEW.state = 'running' THEN
                RAISE EXCEPTION 'ai.agent_tasks: task % starts without counting the attempt', OLD.id USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
        COMMENT ON FUNCTION ai.agent_tasks_guard() IS
          'What may change in a row of ai.agent_tasks: only its state, along the plan''s lines, its attempts, its times, batch_id and '
          'last_run_id; never what the task is; nothing once it is done; no deletion. SET LOCAL fbi.ai_maintenance = ''on'' lifts it for '
          'one transaction (the migrations and the owner''s repairs).';
        CREATE TRIGGER agent_tasks_guard BEFORE UPDATE OR DELETE ON ai.agent_tasks
            FOR EACH ROW EXECUTE FUNCTION ai.agent_tasks_guard();
    """)

    # ── intel.promotions: the entity agent, and who may write it ──────────────────────────────────────────────
    op.execute(f"""
        ALTER TABLE intel.promotions DROP CONSTRAINT promotions_entity_check;
        ALTER TABLE intel.promotions ADD CONSTRAINT promotions_entity_check CHECK (entity IN ({_in(ENTITIES)}));

        -- The shape of an agent promotion, for EVERY role (the owner too): one family, the agent and its version in the registry's
        -- grammar, the gate, the hash of the report the decision rests on and a reason a person can read back. The system signs
        -- exactly one kind of row: the demotion of a champion. The whole branch is wrapped so that a NULL anywhere refuses the row
        -- (a CHECK lets NULL through).
        ALTER TABLE intel.promotions ADD CONSTRAINT promotions_agent_shape CHECK (
            entity <> 'agent'
            OR coalesce(
                market_key IN ({_in(FAMILIES)})
                AND model_name ~ '{PROMOTION_NAME}'
                AND entity_id IS NULL
                AND (from_role IS NULL OR from_role IN ({_in(ROLES)}))
                AND from_role IS DISTINCT FROM to_role
                AND gate_version ~ '{GATE_VERSION}'
                AND jsonb_typeof(criteria) = 'object'
                AND criteria ->> 'report_hash' ~ '{SHA256}'
                AND length(btrim(reason)) >= 20
                AND (decided_by = 'owner'
                     OR (from_role = 'CHAMPION' AND to_role IN ('CHALLENGER', 'RETIRED'))),
                false));
        COMMENT ON CONSTRAINT promotions_agent_shape ON intel.promotions IS
          'An agent promotion (plan section 25): market_key is the family, model_name is agent@version[+upstream versions], criteria '
          'carries the hash of the gate report, the reason is readable, and a row signed by the system can only demote a champion.';

        -- Who is the champion of a family: the agent of the newest CHAMPION row of the family, unless a later row of the same agent
        -- ended it (CHALLENGER, RETIRED or REJECTED; a VALIDATED or NOT_VALIDATED row is a report, it ends nothing). No champion, no
        -- row: the family runs on the quantitative pipeline and the language model of today. The row policy asks this and so does the
        -- engine filter that decides what a family reads: one definition, here.
        CREATE FUNCTION intel.agent_champion(family TEXT)
        RETURNS TABLE (model_name TEXT, since TIMESTAMPTZ, promotion_id BIGINT)
        LANGUAGE sql STABLE AS $fn$
            SELECT newest.model_name, newest.at, newest.id
              FROM (SELECT p.model_name, p.at, p.id
                      FROM intel.promotions p
                     WHERE p.entity = 'agent' AND p.market_key = family AND p.to_role = 'CHAMPION'
                     ORDER BY p.at DESC, p.id DESC
                     LIMIT 1) newest
             WHERE NOT EXISTS (SELECT 1 FROM intel.promotions ended
                                WHERE ended.entity = 'agent' AND ended.market_key = family
                                  AND ended.model_name = newest.model_name
                                  AND ended.to_role IN ('CHALLENGER', 'RETIRED', 'REJECTED')
                                  AND (ended.at, ended.id) > (newest.at, newest.id))
        $fn$;
        COMMENT ON FUNCTION intel.agent_champion(TEXT) IS
          'The champion of a family (plan section 25): the agent of the newest CHAMPION row, unless a later row of that agent ended it '
          '(CHALLENGER, RETIRED, REJECTED). Zero rows when there is none. Used by the row policy of intel.promotions and by whoever decides '
          'which engine a family reads.';

        -- Row security. The table's OWNER (the migrations' role, which the owner's signing command uses) and the superuser are not
        -- subject to it. Everyone else: may read; may write any entity but agent; and the role predigol_rollback - which exists once the
        -- operator creates it (db/roles.sql) and which the worker reaches with SET ROLE - may write ONE row: the demotion by the system
        -- of the agent that is the champion of that family right now, dated no earlier than that champion's own promotion (or the
        -- demotion would not be the newest row and would change nothing) and no later than a few minutes from now (a clock that
        -- is wrong cannot stop the next roll-back). UPDATE and DELETE stay visible to every role so that the append-only trigger
        -- answers them with its error, not with silence.
        ALTER TABLE intel.promotions ENABLE ROW LEVEL SECURITY;
        CREATE POLICY promotions_read ON intel.promotions FOR SELECT USING (true);
        CREATE POLICY promotions_write ON intel.promotions FOR INSERT WITH CHECK (
            CASE WHEN current_user = '{ROLLBACK_ROLE}' THEN
                entity = 'agent'
                AND decided_by = 'system'
                AND from_role = 'CHAMPION'
                AND to_role IN ('CHALLENGER', 'RETIRED')
                AND at <= now() + interval '5 minutes'
                AND EXISTS (SELECT 1 FROM intel.agent_champion(promotions.market_key) champion
                             WHERE champion.model_name = promotions.model_name AND promotions.at >= champion.since)
            ELSE entity <> 'agent'
            END);
        CREATE POLICY promotions_change ON intel.promotions FOR UPDATE USING (true);
        CREATE POLICY promotions_remove ON intel.promotions FOR DELETE USING (true);
        COMMENT ON POLICY promotions_write ON intel.promotions IS
          'Nobody but the owner writes an agent promotion; the only exception is the automatic roll-back (plan sections 25 and 32).';
    """)


def downgrade() -> None:
    # The additions go. An agent promotion is a decision the owner signed: it is never destroyed, so while one exists the migration
    # refuses to go back (nothing has changed yet: the DDL is transactional). The tables go with what they recorded, as the ledger's
    # migration does; the append-only guard is lifted for this transaction only.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL fbi.ai_maintenance = 'on'")
    op.execute("LOCK TABLE intel.promotions IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $do$
        BEGIN
            IF EXISTS (SELECT 1 FROM intel.promotions WHERE entity = 'agent') THEN
                RAISE EXCEPTION '0111 cannot be downgraded: intel.promotions holds promotions of agents, which are never deleted';
            END IF;
        END
        $do$;
    """)
    op.execute(f"""
        DROP POLICY promotions_remove ON intel.promotions;
        DROP POLICY promotions_change ON intel.promotions;
        DROP POLICY promotions_write ON intel.promotions;
        DROP POLICY promotions_read ON intel.promotions;
        DROP FUNCTION intel.agent_champion(TEXT);
        ALTER TABLE intel.promotions DISABLE ROW LEVEL SECURITY;
        ALTER TABLE intel.promotions DROP CONSTRAINT promotions_agent_shape;
        ALTER TABLE intel.promotions DROP CONSTRAINT promotions_entity_check;
        ALTER TABLE intel.promotions ADD CONSTRAINT promotions_entity_check CHECK (entity IN ({_in(ENTITIES[:-1])}));

        DROP TRIGGER agent_tasks_guard ON ai.agent_tasks;
        DROP FUNCTION ai.agent_tasks_guard();
        DROP VIEW ai.match_state;
        DROP TABLE ai.match_runs;
        DROP TABLE ai.agent_tasks;
        DROP TABLE ai.agent_runs;
        DROP FUNCTION ai.candidates_ok(TEXT[]);
    """)
