"""The own texts and the moderation of the news (IA-101 / IA-102, plan pieces AD-G04 and AD-G05): two append-only tables of ``news``

WHY THIS EXISTS
---------------
``news.stories`` (0146) keeps a story's own headline and summary and its moderation state as versions, but not the two records the plan asks
for beside them: every ATTEMPT to write a story's own text with what the verifiers said of it (the text is written only when the anti-copy,
support and health checks pass - the attempts that fail must still be counted to show that they are refused), and the REGISTER of every
moderation act - a rule that sent a story to the private queue, a request of withdrawal and who made it, the owner's withdrawal, approval or
putting back. A withdrawal hides the story (a new version ``retirada``); the register says why and at whose request; nothing is deleted.

WHAT CHANGES
------------
- ``news.story_texts``: one row per attempt of ``news-text-v1`` on a story - the version of the story, the hash of its input, the facts it
  cited, the outcome (``accepted``, ``rejected`` and the provider's codes), the closed reasons, the measures of the anti-copy verifier, the cost
  and the ledger row; the text itself ONLY when accepted (a refused text is not kept: it may be a copy of a third party).
- ``news.moderation_log``: one row per act - ``flag`` (a rule of the system), ``request`` (a withdrawal asked for, recorded by the owner),
  ``withdraw``, ``restore``, ``approve`` (the owner's), ``dismiss`` (a request the owner turned down) - with the rule or the reason, who asked
  (a kind: the holder of the rights, a person named, a club, an outlet, the owner, other) and a reference (never a person's contact), and the
  version of the story the act produced.

Both append-only (``ai.refuse_change()``, the static test of IA-059). The API writes ``news.moderation_log`` and ``news.stories`` from the
owner's console (``deploy/vps/db/grants.sql``); the worker writes both tables from the pipeline in shadow.

Downgrade: drops the two tables (the versions of the stories stay in ``news.stories``; what the register said is lost with it).

Revision ID: 0154
Revises: 0149 (provisional: the head of this branch; the merge re-chains it)
"""

from __future__ import annotations

from alembic import op

revision = "0154"
down_revision = "0152"
branch_labels = None
depends_on = None

SHA256 = "^[0-9a-f]{64}$"
WRITER = "^[a-z0-9][a-z0-9._:+-]{1,79}$"
STORY_KEY = "^st-[a-z0-9][a-z0-9-]{3,62}$"
OUTCOMES = ("accepted", "rejected", "invalid_output", "over_budget", "not_configured", "failed", "timeout", "refused", "unavailable",
            "rate_limited", "piece_cap")
ACTIONS = ("flag", "request", "withdraw", "restore", "approve", "dismiss")
REQUESTERS = ("sistema", "titular_derechos", "persona_mencionada", "club", "medio", "dueno", "otro")
TABLES = ("story_texts", "moderation_log")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE news.story_texts (
            id                BIGSERIAL      PRIMARY KEY,
            story_id          BIGINT         NOT NULL,
            story_key         TEXT           NOT NULL CHECK (story_key ~ '{STORY_KEY}'),
            at                TIMESTAMPTZ    NOT NULL,
            mode              TEXT           NOT NULL CHECK (mode IN ('shadow')),
            prompt_version    TEXT           NOT NULL CHECK (prompt_version ~ '{WRITER}'),
            verify_version    TEXT           NOT NULL CHECK (verify_version ~ '{WRITER}'),
            anticopy_version  TEXT           NOT NULL CHECK (anticopy_version ~ '{WRITER}'),
            input_hash        TEXT           NOT NULL CHECK (input_hash ~ '{SHA256}'),
            fact_ids          JSONB          NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(fact_ids) = 'array'),
            outcome           TEXT           NOT NULL CHECK (outcome IN ({_in(OUTCOMES)})),
            problems          JSONB          NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(problems) = 'array'),
            metrics           JSONB          NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(metrics) = 'object'),
            headline_es       TEXT           CHECK (length(btrim(headline_es)) BETWEEN 5 AND 120),
            headline_en       TEXT           CHECK (length(btrim(headline_en)) BETWEEN 5 AND 120),
            summary_es        TEXT           CHECK (length(btrim(summary_es)) BETWEEN 10 AND 600),
            summary_en        TEXT           CHECK (length(btrim(summary_en)) BETWEEN 10 AND 600),
            model             TEXT           CHECK (length(model) BETWEEN 1 AND 100),
            usage_id          BIGINT,
            cost_usd          NUMERIC(10,6)  NOT NULL DEFAULT 0 CHECK (cost_usd >= 0),
            written_by        TEXT           NOT NULL CHECK (written_by ~ '{WRITER}'),
            FOREIGN KEY (story_id, story_key) REFERENCES news.stories(id, story_key),
            CONSTRAINT story_texts_text_only_when_accepted CHECK (
                (outcome = 'accepted') = (num_nonnulls(headline_es, headline_en, summary_es, summary_en) = 4)
                AND (outcome = 'accepted' OR num_nonnulls(headline_es, headline_en, summary_es, summary_en) = 0))
        );
        CREATE INDEX news_story_texts_story ON news.story_texts (story_key, id DESC);
        CREATE INDEX news_story_texts_at ON news.story_texts (at);
        COMMENT ON TABLE news.story_texts IS
          'IA-101 (AD-G04): every attempt to write a story''s own headline and summary (news-text-v1) and what the verifiers said: support, '
          'health, anti-copy (thresholds preregistered, anticopy-v1). The text is kept only when accepted; an accepted text is also a new '
          'version of news.stories. Append-only.';

        CREATE TABLE news.moderation_log (
            id              BIGSERIAL    PRIMARY KEY,
            story_key       TEXT         NOT NULL CHECK (story_key ~ '{STORY_KEY}'),
            story_id        BIGINT       REFERENCES news.stories(id),
            at              TIMESTAMPTZ  NOT NULL,
            action          TEXT         NOT NULL CHECK (action IN ({_in(ACTIONS)})),
            rule            TEXT         CHECK (rule ~ '^[a-z][a-z0-9_]{{2,59}}$'),
            reason          TEXT         NOT NULL CHECK (length(btrim(reason)) BETWEEN 3 AND 500),
            requested_by    TEXT         NOT NULL CHECK (requested_by IN ({_in(REQUESTERS)})),
            reference       TEXT         CHECK (length(btrim(reference)) BETWEEN 1 AND 200),
            decided_by      TEXT         NOT NULL CHECK (decided_by IN ('system', 'owner')),
            actor_user_id   BIGINT,
            written_by      TEXT         NOT NULL CHECK (written_by ~ '{WRITER}'),
            CHECK ((action = 'flag') = (decided_by = 'system')),
            CHECK (action <> 'flag' OR (rule IS NOT NULL AND requested_by = 'sistema'))
        );
        CREATE INDEX news_moderation_log_story ON news.moderation_log (story_key, id DESC);
        CREATE INDEX news_moderation_log_at ON news.moderation_log (at);
        COMMENT ON TABLE news.moderation_log IS
          'IA-102 (AD-G05): the register of moderation - a rule that sent a story to the private queue (flag), a request of withdrawal '
          'recorded by the owner (request; who asked is a kind, the reference never a person''s contact), the owner''s withdraw, restore, '
          'approve or dismiss, and the version of news.stories the act produced. A withdrawal hides; nothing is deleted. Append-only.';
    """)
    for table in TABLES:
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON news.{table} "
                   f"FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS news.{table}")
