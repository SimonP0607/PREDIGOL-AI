"""The factual review of the single chronicle (IA-118, plan piece AD-F06): ``ai.chronicle_reviews`` also keeps ``chronicle-review-v2``

WHY THIS EXISTS
---------------
The plan's piece says «usa ai.chronicle_reviews con versión nueva», and the table could not take it: it was made for the readers' chronicle
only (revision 0132) - ``narrative_id`` NOT NULL (an id of ``ai.user_narratives``) and ``narrative_version`` CHECKed to ``user-narrative-vN``.
The single chronicle (``chronicle-v4``, ``ai.chronicles``, revision 0155) is another table and another version, so a review of it had nowhere
to go without writing a lie in those columns.

WHAT CHANGES
------------
- ``ai.chronicle_reviews.chronicle_id`` (new, nullable): the ``ai.chronicles`` row a ``chronicle-review-v2`` judged.
- ``narrative_id`` may be NULL; a row names EXACTLY ONE text (``chronicle_reviews_one_text``), and which one follows its version: a review of
  ``user-narrative-vN`` names ``narrative_id``, a review of ``chronicle-vN`` names ``chronicle_id`` (``chronicle_reviews_text_of_version``).
- ``narrative_version`` accepts ``chronicle-vN`` besides ``user-narrative-vN`` (the CHECK of 0132 replaced by the same name).
- ``ai_chronicle_reviews_chronicle_once``: one review per chronicle and version (the twin of ``ai_chronicle_reviews_once``).

Every existing row (``chronicle-review-v1``) already satisfies the new checks: it has its ``narrative_id`` and a ``user-narrative`` version.
Nothing is rewritten or deleted; the append-only trigger stays. The table is small (about 300 rows on 16 Nov 2026) and written once an hour:
the brief ACCESS EXCLUSIVE of the ALTERs waits at most ``lock_timeout``.

Downgrade: drops the index, the two checks and the column, and restores 0132's checks - which FAILS while a ``chronicle-review-v2`` row
exists (on purpose: a downgrade never deletes a review).

Revision ID: 0159
Revises: 0158
"""

from __future__ import annotations

from alembic import op

revision = "0159"
down_revision = "0158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        ALTER TABLE ai.chronicle_reviews ADD COLUMN chronicle_id BIGINT;
        ALTER TABLE ai.chronicle_reviews ALTER COLUMN narrative_id DROP NOT NULL;
        ALTER TABLE ai.chronicle_reviews DROP CONSTRAINT chronicle_reviews_narrative_version_check;
        ALTER TABLE ai.chronicle_reviews ADD CONSTRAINT chronicle_reviews_narrative_version_check
            CHECK (narrative_version ~ '^(user-narrative|chronicle)-v[0-9]+$');
        ALTER TABLE ai.chronicle_reviews ADD CONSTRAINT chronicle_reviews_one_text
            CHECK (num_nonnulls(narrative_id, chronicle_id) = 1);
        ALTER TABLE ai.chronicle_reviews ADD CONSTRAINT chronicle_reviews_text_of_version
            CHECK ((chronicle_id IS NOT NULL) = (narrative_version ~ '^chronicle-v[0-9]+$'));
        CREATE UNIQUE INDEX ai_chronicle_reviews_chronicle_once ON ai.chronicle_reviews (chronicle_id, version)
            WHERE chronicle_id IS NOT NULL;
        COMMENT ON COLUMN ai.chronicle_reviews.chronicle_id IS
          'IA-118: the ai.chronicles row (chronicle-v4) a chronicle-review-v2 judged on its cited facts; NULL for a review of the readers'' '
          'chronicle (narrative_id). Exactly one of the two.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DROP INDEX IF EXISTS ai.ai_chronicle_reviews_chronicle_once;
        ALTER TABLE ai.chronicle_reviews DROP CONSTRAINT IF EXISTS chronicle_reviews_text_of_version;
        ALTER TABLE ai.chronicle_reviews DROP CONSTRAINT IF EXISTS chronicle_reviews_one_text;
        ALTER TABLE ai.chronicle_reviews DROP CONSTRAINT chronicle_reviews_narrative_version_check;
        ALTER TABLE ai.chronicle_reviews ADD CONSTRAINT chronicle_reviews_narrative_version_check
            CHECK (narrative_version ~ '^user-narrative-v[0-9]+$');
        ALTER TABLE ai.chronicle_reviews ALTER COLUMN narrative_id SET NOT NULL;
        ALTER TABLE ai.chronicle_reviews DROP COLUMN chronicle_id;
    """)
