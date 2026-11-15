"""The reader's «Avisos»: when a notice was read (plan maestro UX/UI 2026, decision 1; BE-041)

WHY THIS EXISTS
---------------
The owner approved an inbox with a bell: the notices PrediGol already decides to send a reader - the result of what they
saved, the line-ups of their teams, the day's summary, the reminder they asked for, their account - read back in the app,
with the unread ones counted. Those notices are already kept, one row each, in ``customer.push_notices`` (category, title,
body, link, dates; in the reader's export, deleted when the account is anonymised, purged after 90 days). The inbox reads
that table: no second copy of anything personal is made.

WHAT CHANGES
------------
- ``customer.push_notices.read_at`` (NULL: unread): when the reader opened or marked it.
- An index by reader and moment, for the inbox's page (newest first).

Additive only: a nullable column without default (no rewrite) and one index on a small table. Nothing that exists changes;
with FBI_INBOX off (the default) no code reads or writes the column. Downgrade drops both.

Revision ID: 0137
Revises: 0136
"""

from alembic import op

revision = "0137"
down_revision = "0136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE customer.push_notices ADD COLUMN read_at TIMESTAMPTZ;
        COMMENT ON COLUMN customer.push_notices.read_at IS
          'When the reader read it in «Avisos» (NULL: unread). Meaningless while FBI_INBOX is off.';
        CREATE INDEX push_notices_inbox ON customer.push_notices (user_id, not_before DESC, id DESC);
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DROP INDEX customer.push_notices_inbox;
        ALTER TABLE customer.push_notices DROP COLUMN read_at;
    """)
