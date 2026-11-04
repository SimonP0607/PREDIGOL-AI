"""The weekly summary by e-mail, asked for apart and left in one click (plan UX, B8 and section 33)

WHY THIS EXISTS
---------------
A reader who asks for it in the profile gets one e-mail a week - their picks of the week and how they ended, their teams'
matches of the coming days and what is new in PrediGol - and leaves it in one click from any of them (RFC 8058). It is
commercial mail: it exists only with the consent ``marketing_email`` (the purpose A4 reserved in ``customer.consents``),
it leaves by its own sender, apart from the account's and the security e-mails, and the leaving takes effect at once.

The plan's card said «base de datos: ninguna nueva»; the two lists the database checks did not know commercial mail, and
a check is changed only by a migration.

WHAT CHANGES
------------
- ``customer.messages_outbox.category`` accepts ``marketing``: every summary is a row of the queue like every other e-mail
  (template, language, status, attempts, the provider's id; never its body), the last of the queue's priorities.
- ``customer.consents.source`` accepts ``email``: the leaving from the link of an e-mail is a decision with its own source
  (the version, the sha256 and the sentence of the text, as every decision; append-only, as every decision).

Downgrade: puts both lists back only while no queued e-mail is commercial and no decision came from an e-mail; with them the
code goes back and the lists stay (FBI_DIGEST=0 is the rollback: nothing is queued and nothing queued leaves).
"""

from alembic import op

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None

CATEGORIES_BEFORE = ("account", "security", "membership", "support", "privacy", "legal")
CATEGORIES = (*CATEGORIES_BEFORE, "marketing")
SOURCES_BEFORE = ("gate", "profile", "activation")
SOURCES = (*SOURCES_BEFORE, "email")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE customer.messages_outbox
            DROP CONSTRAINT messages_outbox_category_check,
            ADD CONSTRAINT messages_outbox_category_check CHECK (category IN ({_in(CATEGORIES)}));
        ALTER TABLE customer.consents
            DROP CONSTRAINT consents_source_check,
            ADD CONSTRAINT consents_source_check CHECK (source IN ({_in(SOURCES)}));
        COMMENT ON COLUMN customer.messages_outbox.category IS
            'account, security, membership, support, privacy, legal - and marketing (plan UX, B8): the weekly summary, only '
            'with the consent marketing_email, by its own sender, left in one click';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.messages_outbox WHERE category = 'marketing')
               OR EXISTS (SELECT 1 FROM customer.consents WHERE source = 'email') THEN
                RAISE EXCEPTION 'customer.messages_outbox holds commercial e-mails or customer.consents decisions made from '
                                'an e-mail: the code goes back, the lists stay';
            END IF;
        END $$;
        COMMENT ON COLUMN customer.messages_outbox.category IS NULL;
        ALTER TABLE customer.consents
            DROP CONSTRAINT consents_source_check,
            ADD CONSTRAINT consents_source_check CHECK (source IN ({_in(SOURCES_BEFORE)}));
        ALTER TABLE customer.messages_outbox
            DROP CONSTRAINT messages_outbox_category_check,
            ADD CONSTRAINT messages_outbox_category_check CHECK (category IN ({_in(CATEGORIES_BEFORE)}));
    """)
