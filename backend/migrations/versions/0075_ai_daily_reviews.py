"""CIERRE DEL DÍA: the day's review, written at 23:59 Bogotá and revised until nothing of it is left open

``ai.daily_reviews``: one row per revision of a Bogotá day (``fbi.ai.daily_review``). Revision 1 is the close at
23:59 (``kind = 'close'``; written later, with its real ``built_at``, if the worker was down then); every later
revision (``'update'``) exists because something of THAT day changed - a late match settled, a post-mortem or the
morning's learning written about it. ``complete`` when no match of the day is left to play or to settle;
``pending_fixtures`` lists the ones that are. Append-only like the rest of the ``ai`` schema.

Revision ID: 0075
Revises: 0074
"""

from __future__ import annotations

from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ai.daily_reviews (
            id               BIGSERIAL   PRIMARY KEY,
            day              DATE        NOT NULL,
            revision         SMALLINT    NOT NULL CHECK (revision >= 1),
            kind             TEXT        NOT NULL CHECK (kind IN ('close', 'update')),
            built_at         TIMESTAMPTZ NOT NULL,
            complete         BOOLEAN     NOT NULL,
            pending_fixtures BIGINT[]    NOT NULL DEFAULT '{}',
            content          JSONB       NOT NULL,
            content_hash     TEXT        NOT NULL,
            version          TEXT        NOT NULL,
            UNIQUE (day, revision),
            CHECK ((revision = 1) = (kind = 'close')),
            CHECK (complete = (cardinality(pending_fixtures) = 0))
        );
        CREATE INDEX ai_daily_reviews_day ON ai.daily_reviews (day DESC, revision DESC);
        COMMENT ON TABLE ai.daily_reviews IS
          'CIERRE DEL DÍA: a Bogotá day written down at 23:59 and revised while anything of it changes. Append-only.';
        CREATE TRIGGER daily_reviews_append_only BEFORE UPDATE OR DELETE ON ai.daily_reviews
            FOR EACH ROW EXECUTE FUNCTION ai.refuse_change();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai.daily_reviews")
