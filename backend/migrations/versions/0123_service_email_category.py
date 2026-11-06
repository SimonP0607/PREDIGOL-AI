"""The e-mail category «servicio»: what the service says about itself, which a reader can switch off (plan de cierre UX, 4.1)

WHY THIS EXISTS
---------------
The account's e-mails had six categories (A5): the account, its security, the reader's privacy requests and a material
change of the legal texts (always sent) and the membership's reminders and the answers to support questions (a reader
may switch them off). The closing plan (4.1) adds the messages that speak of the service itself - a scheduled
maintenance, an incident that is over, an important change - and says they are a category of their own that can be
switched off, except what is critical. The two lists the database checks did not know it, and a check is changed only
by a migration.

WHAT CHANGES
------------
- ``customer.messages_outbox.category`` accepts ``service``: every such message is a row of the queue like every other
  e-mail (template, language, status, attempts, the provider's id; never its body), after the membership's in the
  queue's priorities and before commercial mail. It has its own daily cap inside the provider's (the free plan sends 100
  a day; the account's and security mail go first and are never held back by it).
- ``customer.preferences.email_off`` accepts ``service``: the reader's choice to stop receiving them. The one template
  that is critical (an important change) ignores the choice; the code says so (``Template.critical``), the database
  only keeps the choice.

Nothing is written by this revision, no row changes and no column is added. The checks are replaced under
``lock_timeout = '10s'`` (the rule of 0111, 0112, 0115, 0119, 0120 and 0122): a wait longer than that for the lock fails
the revision whole. Both tables are small (a row per reader and a queue pruned after 90 days).

Downgrade: only while the queue holds no ``service`` e-mail and no reader has switched the category off. With them the
code goes back and the lists stay (FBI_EMAIL_SENDING=0 is the rollback: nothing queued leaves).
"""

from alembic import op

revision = "0123"
down_revision = "0122"
branch_labels = None
depends_on = None

OPTIONAL_BEFORE = ("membership", "support")
OPTIONAL = (*OPTIONAL_BEFORE, "service")
"""The categories a reader may switch off (fbi.messaging.templates.MANDATORY are the others)."""
CATEGORIES_BEFORE = ("account", "security", "membership", "support", "privacy", "legal", "marketing")
CATEGORIES = ("account", "security", "membership", "support", "privacy", "legal", "service", "marketing")
"""What the queue holds: the account's categories, the service's and commercial mail (plan UX, B8)."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE customer.preferences
            DROP CONSTRAINT preferences_email_off_check,
            ADD CONSTRAINT preferences_email_off_check CHECK (email_off <@ ARRAY[{_in(OPTIONAL)}]::text[]);
        ALTER TABLE customer.messages_outbox
            DROP CONSTRAINT messages_outbox_category_check,
            ADD CONSTRAINT messages_outbox_category_check CHECK (category IN ({_in(CATEGORIES)}));
        COMMENT ON COLUMN customer.messages_outbox.category IS
            'account, security, membership, support, privacy, legal - service (plan UX, 4.1: maintenance, an incident that '
            'is over, an important change; a reader can switch it off, what is critical aside) - and marketing (plan UX, '
            'B8): the weekly summary, only with the consent marketing_email, by its own sender, left in one click';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.messages_outbox WHERE category = 'service')
               OR EXISTS (SELECT 1 FROM customer.preferences WHERE 'service' = ANY (email_off)) THEN
                RAISE EXCEPTION 'customer.messages_outbox holds service e-mails or customer.preferences holds readers who '
                                'switched the category off: the code goes back, the lists stay';
            END IF;
        END $$;
        ALTER TABLE customer.messages_outbox
            DROP CONSTRAINT messages_outbox_category_check,
            ADD CONSTRAINT messages_outbox_category_check CHECK (category IN ({_in(CATEGORIES_BEFORE)}));
        ALTER TABLE customer.preferences
            DROP CONSTRAINT preferences_email_off_check,
            ADD CONSTRAINT preferences_email_off_check CHECK (email_off <@ ARRAY[{_in(OPTIONAL_BEFORE)}]::text[]);
        COMMENT ON COLUMN customer.messages_outbox.category IS
            'account, security, membership, support, privacy, legal - and marketing (plan UX, B8): the weekly summary, only '
            'with the consent marketing_email, by its own sender, left in one click';
    """)
