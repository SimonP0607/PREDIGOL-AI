"""The single chronicle and its content plan (IA-103 / IA-104, plan pieces AD-F01 and AD-F02): one append-only table, ``ai.chronicles``

WHY THIS EXISTS
---------------
Six texts are written of a match today; the plan replaces them by ONE chronicle, ``chronicle-v4``, written from a content plan made by code
(``content-plan-v1``: the facts that must and may be told, the abstentions, the classes of claim each fact authorises) and checked sentence by
sentence (``chronicle-verify-v1``: a sentence the plan does not support is dropped, not the whole text). Both are new versions beside
``user-narrative-v3``, which keeps its own table and goes on as it is. This table keeps every plan and every attempt so that the coverage of
the plan, the support of every sentence and the cost can be measured before anything reaches a reader.

WHAT CHANGES
------------
- ``ai.chronicles``: one row per attempt of a match - the plan as JSON (facts by reference: no text of the internet), its hash and versions,
  the outcome (``ok``, ``partial``, ``rejected``, ``abstained``, ``invalid_output``, ``failed``), the abstention's code when there is no text
  (``SIN_PLAN``, ``SIN_DATOS``, ``VERIFICACION_VACIA``), the sentences that stood (ONLY when some did), the ones dropped with why, the measures,
  the route (``batch``, ``realtime`` or ``none``), the model, the ledger row and the cost. Append-only: ``ai.refuse_change()`` refuses UPDATE
  and DELETE. One row per answer of a batch (``custom_id`` unique).

Nothing reads it to decide, price or publish; no reader sees it (``FBI_MATCH_INTELLIGENCE`` is off and C-01's second delivery is another
piece). The worker writes it only under ``FBI_CHRONICLE_V4=shadow`` (off by default). No data is written by the migration.

Downgrade: drops the table.

Revision ID: 0155
Revises: 0154
"""

from __future__ import annotations

from alembic import op

revision = "0155"
down_revision = "0154"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
STATUSES = ("ok", "partial", "rejected", "abstained", "invalid_output", "failed")
ABSTENTIONS = ("SIN_PLAN", "SIN_DATOS", "VERIFICACION_VACIA")
ROUTES = ("batch", "realtime", "none")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE ai.chronicles (
            id               BIGSERIAL      PRIMARY KEY,
            fixture_id       BIGINT         NOT NULL REFERENCES core.fixtures(id),
            created_at       TIMESTAMPTZ    NOT NULL,
            plan_at          TIMESTAMPTZ    NOT NULL,
            version          TEXT           NOT NULL CHECK (version ~ '^chronicle-v[0-9]+$'),
            plan_version     TEXT           NOT NULL CHECK (plan_version ~ '^content-plan-v[0-9]+$'),
            classes_version  TEXT           NOT NULL CHECK (classes_version ~ '^claim-classes-v[0-9]+$'),
            verify_version   TEXT           NOT NULL CHECK (verify_version ~ '^chronicle-verify-v[0-9]+$'),
            figure_version   TEXT           CHECK (figure_version IS NULL OR figure_version ~ '^forecast-v[0-9]+$'),
            packet_id        BIGINT,
            plan_hash        TEXT           NOT NULL CHECK (plan_hash ~ '{SHA256}'),
            input_hash       TEXT           CHECK (input_hash IS NULL OR input_hash ~ '{SHA256}'),
            plan             JSONB          NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
            status           TEXT           NOT NULL CHECK (status IN ({_in(STATUSES)})),
            abstention       TEXT           CHECK (abstention IS NULL OR abstention IN ({_in(ABSTENTIONS)})),
            content          JSONB          CHECK (content IS NULL OR jsonb_typeof(content) = 'object'),
            dropped          JSONB          NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(dropped) = 'array'),
            metrics          JSONB          NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
            route            TEXT           NOT NULL CHECK (route IN ({_in(ROUTES)})),
            provider         TEXT,
            model            TEXT,
            usage_id         BIGINT,
            custom_id        TEXT,
            cost_usd         NUMERIC(12, 6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            error            TEXT           CHECK (error IS NULL OR length(error) <= 300),
            code_version     TEXT,
            CHECK ((status IN ('ok', 'partial')) = (content IS NOT NULL)),
            CHECK ((status IN ('abstained', 'rejected')) = (abstention IS NOT NULL)),
            CHECK (status <> 'abstained' OR (route = 'none' AND cost_usd = 0)),
            CHECK (plan_at <= created_at)
        );
        CREATE INDEX ai_chronicles_fixture ON ai.chronicles (fixture_id, id DESC);
        CREATE INDEX ai_chronicles_created ON ai.chronicles (created_at DESC);
        CREATE UNIQUE INDEX ai_chronicles_custom_id ON ai.chronicles (custom_id) WHERE custom_id IS NOT NULL;
        COMMENT ON TABLE ai.chronicles IS
          'IA-103/IA-104: the single chronicle chronicle-v4 and its content plan content-plan-v1 (facts by reference), one row per attempt, '
          'checked sentence by sentence (chronicle-verify-v1). Shadow only (FBI_CHRONICLE_V4); append-only; no reader reads it.';
    """)
    op.execute("CREATE TRIGGER chronicles_append_only BEFORE UPDATE OR DELETE ON ai.chronicles "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS ai.chronicles")
