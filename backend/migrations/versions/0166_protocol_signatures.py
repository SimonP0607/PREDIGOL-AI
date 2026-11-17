"""The owner's signature of a preregistered protocol (IA-143, plan piece AD-K07): ``ai.protocol_signatures``, append-only

WHY THIS EXISTS
---------------
Every LAB protocol of ``fbi.research.protocol`` and the chronicle's own protocols (AD-F04, AD-F05, AD-F06) are registered with a fingerprint
before their data is looked at, and every one says «the owner signs it». There was no way to record that signature: the readers wrote
``signed_by_owner: False`` by hand. This table is that record.

WHAT CHANGES
------------
* ``ai.protocol_signatures``: one row per signature - ONE protocol (``protocol_key``, ``protocol_version``, its ``framework``) in ONE
  fingerprint (the sha256 the owner signed), the owner's reason (10 to 600 characters), ``decided_by = 'owner'`` (the only value the database
  takes), the hour and the code version. The same protocol is signed once per fingerprint (``protocol_signatures_once``). A protocol that
  changed has a new fingerprint and needs a new row; the old one stays as it was, and the readers (``fbi.protosign.store``) count only the
  row whose fingerprint is the one the code has now.

Nothing reads this table to switch, promote or re-threshold anything: a signature records that the protocol is the one the owner approved
before the data was looked at, nothing more.

Append-only (``ai.refuse_change()``). Downgrade: drops the table (the signatures are lost; nothing else changes).

Revision ID: 0166
Revises: 0165
"""

from __future__ import annotations

from alembic import op

revision = "0166"
down_revision = "0165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE ai.protocol_signatures (
            id                BIGSERIAL    PRIMARY KEY,
            protocol_key      TEXT         NOT NULL CHECK (protocol_key ~ '^(INT|AD)-[A-Z][0-9]{2}$'),
            protocol_version  TEXT         NOT NULL CHECK (protocol_version ~ '^[a-z][a-z0-9.-]{1,79}$'),
            framework         TEXT         NOT NULL CHECK (framework IN ('lab-protocol-v1', 'own-record-v1')),
            fingerprint       TEXT         NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
            reason            TEXT         NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 600),
            decided_by        TEXT         NOT NULL DEFAULT 'owner' CHECK (decided_by = 'owner'),
            signed_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
            code_version      TEXT,
            CONSTRAINT protocol_signatures_once UNIQUE (protocol_key, fingerprint)
        );
        CREATE INDEX protocol_signatures_key ON ai.protocol_signatures (protocol_key, id);
        COMMENT ON TABLE ai.protocol_signatures IS
          'IA-143 (AD-K07): the owner''s signature of ONE preregistered protocol in ONE fingerprint; append-only. It counts only while the '
          'fingerprint is the one the code has; a changed protocol needs a new row. A signature turns nothing on.';
    """)
    op.execute("CREATE TRIGGER protocol_signatures_append_only BEFORE UPDATE OR DELETE ON ai.protocol_signatures "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS ai.protocol_signatures")
