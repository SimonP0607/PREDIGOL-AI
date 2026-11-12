"""The replay bank of the deliberations (IA-047, plan piece INT-C02): its own four tables, and nothing else

WHY THIS EXISTS
---------------
To compare a variant of an agent or of the Council with the agent in force on the same inputs, without waiting for days of
shadow, the bank asks the stored runs of the shadow again through the LAB's Message Batches route (``fbi.ai.replay``). Its
results must never be runs of the shadow: ``ai.agent_runs`` is what Gate B counts (invalid outputs per agent and version,
duplicate payments, the agents that ran) and what the leak audit reads every night. So the bank keeps everything in tables of
its own.

WHAT CHANGES
------------
- ``ai.replay_bank_items``: every stored run the bank looked at, ADMITTED (its question derived again byte for byte: the
  package, the slice or the Council's view, the identity and the request's hash) or excluded with one closed code. What the
  gate compares of the stored answer (``stored_units``) is copied here, so a verdict never depends on re-reading the shadow.
- ``ai.replay_runs``: one row per run sent with the owner's confirmation: the selection, the asks, the estimate, the worst
  case, the cap and the protocol it ran under.
- ``ai.replay_results``: one row per answer of a replay that came back (stored run, variant, repetition), read as the shadow
  reads its own: status, the contract's output, the words the gate compares.
- ``ai.replay_assessments``: each verdict of the rule of reproducibility (``replay-measure-v1``) per variant and scope, with
  the evidence to recompute it.

All four are append-only (``ai.refuse_change()``). The only foreign keys are between these new tables; none points at a
table the worker writes all the time (``ai.agent_runs``, ``ai.batch_items``, ``ai.usage``): their ids are kept by the code
that writes them (the lesson of 0076, 0100 and 0110). Nothing that exists changes.

Downgrade: drops the four tables; the bank is built again from the runs of the shadow, which are never deleted (what was
paid for a replay stays in ``ai.usage`` and ``ai.batch_items``).

Revision ID: 0135
Revises: 0134
"""

from alembic import op

revision = "0135"
down_revision = "0134"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
NAME = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
BANK_VERSION = "^replay-bank-v[1-9][0-9]{0,2}$"
VARIANT = "^[a-z][a-z0-9_-]{0,63}$"
SCOPE = "^[a-z][a-z0-9_-]{0,31}/[a-z][a-z0-9_-]{0,31}$"
TABLES = ("replay_assessments", "replay_results", "replay_runs", "replay_bank_items")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.replay_bank_items (
            id                   BIGSERIAL     PRIMARY KEY,
            bank_version         TEXT          NOT NULL CHECK (bank_version ~ '{BANK_VERSION}'),
            source_run_id        BIGINT        NOT NULL CHECK (source_run_id >= 1),
            created_at           TIMESTAMPTZ   NOT NULL,
            scope                TEXT          NOT NULL CHECK (scope ~ '{SCOPE}'),
            admitted             BOOLEAN       NOT NULL,
            reason               TEXT          CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 120),
            fixture_id           BIGINT        NOT NULL CHECK (fixture_id >= 1),
            pass_kind            TEXT          NOT NULL CHECK (pass_kind IN ('first', 'pre', 'final', 'request')),
            known_at             TIMESTAMPTZ   NOT NULL,
            run_started_at       TIMESTAMPTZ   NOT NULL,
            agent                TEXT          NOT NULL CHECK (agent ~ '{NAME}'),
            agent_version        TEXT          NOT NULL CHECK (agent_version ~ '{NAME}'),
            prompt_version       TEXT          NOT NULL CHECK (prompt_version ~ '{NAME}'),
            schema_version       TEXT          NOT NULL CHECK (schema_version ~ '{NAME}'),
            task_kind            TEXT          NOT NULL CHECK (task_kind ~ '^[a-z][a-z_]{{0,31}}$'),
            model                TEXT          CHECK (model IS NULL OR model ~ '{NAME}'),
            effort               TEXT          CHECK (effort IS NULL OR effort IN ('low', 'medium')),
            idem_key             TEXT          NOT NULL CHECK (idem_key ~ '{SHA256}'),
            package_hash         TEXT          CHECK (package_hash IS NULL OR package_hash ~ '{SHA256}'),
            input_hash           TEXT          CHECK (input_hash IS NULL OR input_hash ~ '{SHA256}'),
            request_hash         TEXT          CHECK (request_hash IS NULL OR request_hash ~ '{SHA256}'),
            packet_id            BIGINT,
            package_version      TEXT          CHECK (package_version IS NULL OR package_version ~ '{NAME}'),
            candidates           TEXT[]        NOT NULL DEFAULT '{{}}',
            stored_status        TEXT          NOT NULL CHECK (stored_status IN ('ok', 'abstain', 'invalid')),
            stored_units         JSONB         NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(stored_units) = 'object'),
            stored_confidence    JSONB         NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(stored_confidence) = 'object'),
            stored_cost_usd      NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (stored_cost_usd >= 0),
            stored_in_batch      BOOLEAN       NOT NULL,
            stored_input_tokens  INTEGER       CHECK (stored_input_tokens IS NULL OR stored_input_tokens >= 0),
            stored_output_tokens INTEGER       CHECK (stored_output_tokens IS NULL OR stored_output_tokens >= 0),
            CONSTRAINT replay_bank_items_reason CHECK (admitted = (reason IS NULL)),
            CONSTRAINT replay_bank_items_admitted CHECK (
                NOT admitted OR (package_hash IS NOT NULL AND input_hash IS NOT NULL AND request_hash IS NOT NULL
                                 AND packet_id IS NOT NULL AND package_version IS NOT NULL AND model IS NOT NULL))
        );
        CREATE UNIQUE INDEX ai_replay_bank_items_once ON ai.replay_bank_items (bank_version, source_run_id);
        CREATE INDEX ai_replay_bank_items_scope ON ai.replay_bank_items (bank_version, scope, admitted);
        COMMENT ON TABLE ai.replay_bank_items IS
          'The replay bank (IA-047): every stored run of the shadow the bank looked at, admitted (its question derived again '
          'byte for byte from what the database keeps) or excluded with one closed code. Append-only. Never a run of the shadow.';
        COMMENT ON COLUMN ai.replay_bank_items.source_run_id IS 'ai.agent_runs.id of the stored run (no foreign key: that table is busy).';
        COMMENT ON COLUMN ai.replay_bank_items.input_hash IS 'What the model read: the slice''s hash, or the Council''s view''s (the identity''s input).';
        COMMENT ON COLUMN ai.replay_bank_items.request_hash IS 'The hash of the request rebuilt, equal to ai.usage.input_hash of the stored call.';
        COMMENT ON COLUMN ai.replay_bank_items.stored_units IS 'What the gate compares of the stored answer: a stance or a verdict per candidate, or the signals.';

        CREATE TABLE ai.replay_runs (
            id                   BIGSERIAL     PRIMARY KEY,
            run_key              TEXT          NOT NULL CHECK (length(run_key) BETWEEN 1 AND 200),
            bank_version         TEXT          NOT NULL CHECK (bank_version ~ '{BANK_VERSION}'),
            variant              TEXT          NOT NULL CHECK (variant ~ '{VARIANT}'),
            protocol             TEXT          NOT NULL CHECK (protocol ~ '^proto-[a-z0-9-]+-v[1-9][0-9]{{0,2}}$'),
            protocol_fingerprint TEXT          NOT NULL CHECK (protocol_fingerprint ~ '{SHA256}'),
            created_at           TIMESTAMPTZ   NOT NULL,
            items                INTEGER       NOT NULL CHECK (items >= 0),
            asks                 INTEGER       NOT NULL CHECK (asks >= 0),
            repeats              SMALLINT      NOT NULL CHECK (repeats BETWEEN 1 AND 3),
            estimate_usd         NUMERIC(12,6) NOT NULL CHECK (estimate_usd >= 0),
            worst_usd            NUMERIC(12,6) NOT NULL CHECK (worst_usd >= estimate_usd),
            cap_usd              NUMERIC(12,6) NOT NULL CHECK (cap_usd > 0 AND estimate_usd <= cap_usd),
            lab_remaining_usd    NUMERIC(12,6) NOT NULL,
            confirmed_by_owner   BOOLEAN       NOT NULL CHECK (confirmed_by_owner),
            selection            JSONB         NOT NULL CHECK (jsonb_typeof(selection) = 'object')
        );
        CREATE UNIQUE INDEX ai_replay_runs_once ON ai.replay_runs (run_key);
        COMMENT ON TABLE ai.replay_runs IS
          'A run of the replay bank sent to the LAB''s Message Batches route with the owner''s confirmation (IA-047): what it '
          'asked, what it was expected to cost at most, its cap and its protocol. Append-only.';

        CREATE TABLE ai.replay_results (
            id                   BIGSERIAL     PRIMARY KEY,
            bank_item_id         BIGINT        NOT NULL REFERENCES ai.replay_bank_items(id),
            variant              TEXT          NOT NULL CHECK (variant ~ '{VARIANT}'),
            repetition           SMALLINT      NOT NULL CHECK (repetition BETWEEN 1 AND 3),
            batch_item_id        BIGINT        NOT NULL,
            usage_id             BIGINT,
            model                TEXT          CHECK (model IS NULL OR model ~ '{NAME}'),
            collected_at         TIMESTAMPTZ   NOT NULL,
            status               TEXT          NOT NULL CHECK (status IN ('ok', 'abstain', 'invalid')),
            output               JSONB         CHECK (output IS NULL OR jsonb_typeof(output) = 'object'),
            verdict              TEXT          CHECK (verdict IS NULL OR length(verdict) BETWEEN 1 AND 64),
            units                JSONB         NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(units) = 'object'),
            problems             TEXT[]        NOT NULL DEFAULT '{{}}',
            cost_usd             NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            CONSTRAINT replay_results_output CHECK ((status IN ('ok', 'abstain')) = (output IS NOT NULL))
        );
        CREATE UNIQUE INDEX ai_replay_results_once ON ai.replay_results (bank_item_id, variant, repetition);
        COMMENT ON TABLE ai.replay_results IS
          'One answer of a replay of the bank (IA-047), read as the shadow reads its own: the agent''s reader against the rebuilt '
          'slice or view. Append-only; never a run of the shadow, a review, a pick or a state.';
        COMMENT ON COLUMN ai.replay_results.batch_item_id IS 'ai.batch_items.id of the ask (no foreign key: that table is written every 5 minutes).';

        CREATE TABLE ai.replay_assessments (
            id                   BIGSERIAL     PRIMARY KEY,
            at                   TIMESTAMPTZ   NOT NULL,
            bank_version         TEXT          NOT NULL CHECK (bank_version ~ '{BANK_VERSION}'),
            variant              TEXT          NOT NULL CHECK (variant ~ '{VARIANT}'),
            scope                TEXT          NOT NULL CHECK (scope ~ '{SCOPE}'),
            protocol             TEXT          NOT NULL CHECK (protocol ~ '^proto-[a-z0-9-]+-v[1-9][0-9]{{0,2}}$'),
            protocol_fingerprint TEXT          NOT NULL CHECK (protocol_fingerprint ~ '{SHA256}'),
            method               TEXT          NOT NULL CHECK (method ~ '{NAME}'),
            verdict              TEXT          NOT NULL CHECK (verdict IN ('PASA', 'NO PASA', 'INSUFICIENTE')),
            evidence             JSONB         NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
            evidence_hash        TEXT          NOT NULL CHECK (evidence_hash ~ '{SHA256}')
        );
        CREATE INDEX ai_replay_assessments_newest ON ai.replay_assessments (bank_version, variant, scope, at DESC, id DESC);
        COMMENT ON TABLE ai.replay_assessments IS
          'The verdicts of the gate «reproducibilidad suficiente para comparar variantes» (IA-047, replay-measure-v1) per variant '
          'and scope, with the evidence to recompute each one. Append-only: a row is added only when it says something new. '
          'Not a gate of ai.feature_gates: nothing reads it to switch anything.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in TABLES:
        op.execute(f"DROP TABLE ai.{table}")
