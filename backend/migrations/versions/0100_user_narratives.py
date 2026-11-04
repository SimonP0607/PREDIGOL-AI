"""The readers' narrative and its own spend (plan UX, A11)

WHY THIS EXISTS
---------------
A reader sees the structured reading of a match (A9): facts written from templates, the same words every time. A11 adds
a narrative in Spanish and English, written by a language model from the very facts the reader is shown and from the
match's verified news, and shown only once the server has checked every sentence against them (``fbi.ai.user_narrative``).
Its money is not PrediGol Intelligence's: the readers' AI has its own monthly budget (``FBI_AI_USER_MONTHLY_BUDGET_USD``,
the owner's P8), recorded apart, so it can never take a cent from what Intelligence may spend.

WHAT CHANGES
------------
- ``ai.user_usage``: one row per model call of the readers' layer - tokens, cost, how it ended - the mirror of
  ``ai.usage``. ``fbi.ai.usage.SPENT_SQL`` sums ``ai.usage`` and ``analytics.ai_runs`` only, so nothing here counts against
  Intelligence's budget. No prompt and no key is stored.
- ``ai.user_narratives``: every narrative the job wrote or tried to write - the validated text (``status = ok``, Spanish and
  English, each sentence with its references) or why it was not shown (``rejected``, ``invalid_output``, ``failed``), the packet
  and the hash of the structured reading it was written from (the API shows it only while the reading is still the same), its
  calls and its cost.
- ``ai.evidence_translations``: the own headline (up to 80 characters) and, in English, the claim of a news item of
  ``ai.evidence``, written in the same call and checked one by one. Keyed by the item's ``content_hash``: the content of an item
  never changes, so neither does its translation.

All three are append-only (``ai.refuse_change()``, the AI layer's trigger since 0072). None has a foreign key to a table the
worker writes all the time (``core.fixtures``, ``ai.match_packets``, ``ai.evidence``): creating one locks the referenced table,
and this migration enters a live database (the lesson of 0076 and of the AI plan's 0110). The ids are kept by the code that
writes them. Nothing that exists changes; the worker reads and writes the three with the default privileges of the ``ai``
schema (append-only all the same), the API reads them. Never a reader's data: the model is given the match's facts only.

Downgrade: drops the three tables - the narratives and the translations are written again by the next passes - but refuses
while ``ai.user_usage`` records real spend: those rows are the month's account of the readers' budget, and dropping them
would let the job spend the month again. With spend recorded, the rollback is the switch (``FBI_USER_NARRATIVE=0``).
"""

from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE ai.user_usage (
            id             BIGSERIAL     PRIMARY KEY,
            at             TIMESTAMPTZ   NOT NULL,
            purpose        TEXT          NOT NULL CHECK (purpose IN ('user_narrative')),
            tier           TEXT          NOT NULL CHECK (tier IN ('bulk', 'analysis', 'final')),
            provider       TEXT          NOT NULL,
            model          TEXT          NOT NULL,
            prompt_version TEXT,
            fixture_id     BIGINT,
            input_tokens   INTEGER       NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
            output_tokens  INTEGER       NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
            cached_tokens  INTEGER       NOT NULL DEFAULT 0 CHECK (cached_tokens >= 0),
            searches       INTEGER       NOT NULL DEFAULT 0 CHECK (searches = 0),
            vision_items   INTEGER       NOT NULL DEFAULT 0 CHECK (vision_items = 0),
            cost_usd       NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            latency_ms     INTEGER       CHECK (latency_ms IS NULL OR latency_ms >= 0),
            status         TEXT          NOT NULL CHECK (status IN ('ok', 'failed', 'timeout', 'refused',
                                         'invalid_output')),
            error          TEXT          CHECK (error IS NULL OR length(error) <= 300),
            input_hash     TEXT,
            request_id     TEXT
        );
        CREATE INDEX ai_user_usage_at ON ai.user_usage (at);
        COMMENT ON TABLE ai.user_usage IS
          'The readers'' AI (plan UX, A11): one row per model call, with its own monthly budget '
          '(FBI_AI_USER_MONTHLY_BUDGET_USD) - never counted in PrediGol Intelligence''s (ai.usage). No prompt, no key.';

        CREATE TABLE ai.user_narratives (
            id           BIGSERIAL     PRIMARY KEY,
            fixture_id   BIGINT        NOT NULL,
            created_at   TIMESTAMPTZ   NOT NULL,
            version      TEXT          NOT NULL CHECK (version ~ '^user-narrative-v[0-9]+$'),
            packet_id    BIGINT        NOT NULL,
            data_at      TIMESTAMPTZ   NOT NULL,
            reading_hash TEXT          NOT NULL CHECK (reading_hash ~ '^[0-9a-f]{64}$'),
            input_hash   TEXT          NOT NULL CHECK (input_hash ~ '^[0-9a-f]{64}$'),
            status       TEXT          NOT NULL CHECK (status IN ('ok', 'rejected', 'invalid_output', 'failed')),
            content      JSONB,
            rejected     JSONB         NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(rejected) = 'array'),
            provider     TEXT,
            model        TEXT,
            attempts     SMALLINT      NOT NULL DEFAULT 1 CHECK (attempts BETWEEN 1 AND 3),
            usage_ids    BIGINT[]      NOT NULL DEFAULT '{}',
            cost_usd     NUMERIC(12,6) NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            error        TEXT          CHECK (error IS NULL OR length(error) <= 300),
            CHECK ((status = 'ok') = (content IS NOT NULL)),
            CHECK (content IS NULL OR (jsonb_typeof(content) = 'object' AND content ? 'es' AND content ? 'en')),
            CHECK (data_at <= created_at)
        );
        CREATE INDEX ai_user_narratives_fixture ON ai.user_narratives (fixture_id, created_at DESC, id DESC);
        CREATE INDEX ai_user_narratives_input ON ai.user_narratives (input_hash);
        COMMENT ON TABLE ai.user_narratives IS
          'The readers'' narrative of a match (plan UX, A11), Spanish and English, written from the facts of the structured '
          'reading and the verified news and shown only when every sentence passed the server''s checks (status ok); '
          'otherwise why not. The API shows it only while the reading has the same packet and the same reading_hash.';

        CREATE TABLE ai.evidence_translations (
            id           BIGSERIAL     PRIMARY KEY,
            evidence_id  BIGINT        NOT NULL,
            content_hash TEXT          NOT NULL,
            lang         TEXT          NOT NULL CHECK (lang IN ('es', 'en')),
            headline     TEXT          CHECK (headline IS NULL OR length(btrim(headline)) BETWEEN 3 AND 80),
            claim        TEXT          CHECK (claim IS NULL OR length(btrim(claim)) BETWEEN 5 AND 600),
            version      TEXT          NOT NULL CHECK (version ~ '^user-narrative-v[0-9]+$'),
            narrative_id BIGINT        NOT NULL REFERENCES ai.user_narratives(id) ON DELETE CASCADE,
            created_at   TIMESTAMPTZ   NOT NULL,
            CHECK (headline IS NOT NULL OR claim IS NOT NULL),
            CHECK (lang = 'en' OR claim IS NULL)
        );
        CREATE UNIQUE INDEX ai_evidence_translations_once
            ON ai.evidence_translations (evidence_id, content_hash, lang, version);
        CREATE INDEX ai_evidence_translations_evidence ON ai.evidence_translations (evidence_id, created_at DESC, id DESC);
        COMMENT ON TABLE ai.evidence_translations IS
          'A news item of ai.evidence in the reader''s other language (plan UX, A11): its own headline (up to 80 characters; '
          'Spanish and English) and, in English, its claim - checked one by one against the Spanish claim. Never an '
          'article''s text or title.';
    """)
    for table in ("user_usage", "user_narratives", "evidence_translations"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON ai.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $refuse$
        BEGIN
            IF EXISTS (SELECT 1 FROM ai.user_usage WHERE cost_usd > 0) THEN
                RAISE EXCEPTION 'ai.user_usage records the readers'' AI spend: going back would forget it and let the '
                                'narrative spend the month again. The rollback is FBI_USER_NARRATIVE=0.'
                    USING ERRCODE = 'check_violation';
            END IF;
        END
        $refuse$;
        DROP TABLE ai.evidence_translations;
        DROP TABLE ai.user_narratives;
        DROP TABLE ai.user_usage;
    """)
