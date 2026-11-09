"""The post-match review of the chronicle (IA-022): what a match's chronicle said, against what happened

WHY THIS EXISTS
---------------
The owner's single flow of analysis (``claude/PLAN_FLUJO_UNICO_ANALISIS.md``) ends with the post-match: what the chronicle anticipated
and what the match showed. Nothing recorded it: the post-mortems read numbers, never the text a reader was shown.

WHAT CHANGES
------------
- ``ai.chronicle_reviews``: one row per chronicle (``narrative_id``) and version of the review. Its ``items`` are the sentences of the
  chronicle with each reference judged (an absence or a doubt against who played; a news item against who played), its ``summary`` the
  counts, its ``outcome`` the score, its ``picks`` what the post-mortems say of the selections of the match. It records what was
  checked and what could not be checked; it states no cause, it changes no model and no threshold.

Append-only (``ai.refuse_change()``). No foreign key to a table the worker writes all the time (``core.fixtures``, ``ai.user_narratives``):
creating one locks the referenced table, and this migration enters a live database (the lesson of 0076, 0100 and 0110). The ids are
kept by the code that writes them. Nothing that exists changes.

Downgrade: drops the table; the next run writes the reviews again from the chronicles, which are never deleted.
"""

from alembic import op

revision = "0131"
down_revision = "0130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE ai.chronicle_reviews (
            id                BIGSERIAL    PRIMARY KEY,
            fixture_id        BIGINT       NOT NULL,
            narrative_id      BIGINT       NOT NULL,
            version           TEXT         NOT NULL CHECK (version ~ '^chronicle-review-v[0-9]+$'),
            created_at        TIMESTAMPTZ  NOT NULL,
            narrative_version TEXT         NOT NULL CHECK (narrative_version ~ '^user-narrative-v[0-9]+$'),
            packet_id         BIGINT       NOT NULL,
            trace_id          UUID         NOT NULL,
            status            TEXT         NOT NULL CHECK (status IN ('reviewed', 'facts_unavailable')),
            outcome           JSONB        NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
            items             JSONB        NOT NULL CHECK (jsonb_typeof(items) = 'array'),
            summary           JSONB        NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
            picks             JSONB        NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(picks) = 'array')
        );
        CREATE UNIQUE INDEX ai_chronicle_reviews_once ON ai.chronicle_reviews (narrative_id, version);
        CREATE INDEX ai_chronicle_reviews_fixture ON ai.chronicle_reviews (fixture_id, created_at DESC, id DESC);
        COMMENT ON TABLE ai.chronicle_reviews IS
          'The post-match review of a match''s chronicle (IA-022): each sentence''s references judged against who played and the '
          'result; what could not be checked is said so. Owner-only. It states no cause and changes no model.';
        CREATE TRIGGER chronicle_reviews_append_only BEFORE UPDATE OR DELETE ON ai.chronicle_reviews
            FOR EACH ROW EXECUTE FUNCTION ai.refuse_change();
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE ai.chronicle_reviews")
