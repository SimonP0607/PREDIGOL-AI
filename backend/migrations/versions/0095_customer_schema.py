"""The customer's own schema: consents and privacy requests (plan UX, A4)

WHY THIS EXISTS
---------------
Charging a reader needs a legal basis: the terms, the data-processing policy and the reader's consents, each one tied
to the exact text that was shown (its version and its sha256), and a way to exercise the rights the law gives - see,
correct, delete - with its deadline in business days. And the reader's data needs a border of its own: a schema the
worker of PrediGol Intelligence cannot read (db/grants.sql treats ``customer`` as it treats ``auth``).

WHAT CHANGES
------------
- ``customer``: a new schema. Nothing that exists is touched; the code before A4 never reads it.
- ``customer.refuse_change()``: the append-only guard. Consents and the messages of a ticket are legal evidence: they
  are corrected with a new row (``replaces_id``), never edited or deleted. A documented retention job may lift the
  guard inside one transaction (``SET LOCAL fbi.customer_maintenance = 'on'``), the first time dry and with the
  owner's OK (plan UX, section 41).
- ``customer.consents``: one row per decision (granted or withdrawn) on a purpose - the terms, the processing of the
  data, the +18 declaration, the reading of the risk notice (the four the reader must give), and the two optional
  ones later phases offer (commercial e-mail, B8; a separate box for product analytics, only if the lawyer asks for
  one) - with the document's version, its sha256 in the language it was read, and the statement the reader ticked.
  No IP, no device.
- ``customer.support_tickets`` / ``customer.ticket_messages``: a privacy request (a query, a claim, a deletion) or a
  support question, with its legal deadline (``due_on``; the law allows one extension, ``extended_to``) and its
  messages. A ticket's status changes and nothing else does (``customer.ticket_guard()``: who, what, when and the
  deadline are fixed, the extension is set once); it is never deleted, and its messages are append-only.

Every foreign key to ``auth.users`` is ON DELETE RESTRICT: an account is anonymised, never deleted while it has
legal evidence (plan UX, A7). A consent's ``replaces_id`` is checked at the end of the statement, so the documented
retention job can remove a whole chain at once and never one link of it.

Downgrade: drops the schema only while it holds no row. With real consents or tickets the code goes back and the
tables stay (plan UX, section 44: dropping them would delete legal evidence).

Chain: written on 0094 (UX A1); the IA plan's releases reached production first - ia-p01 (0110 to 0113), ia-p02 (0114
and 0115) and ia-p03 (0116) - and then the security plan's sec-s3 (0117, the incident register), so this migration hangs
from 0119 (ia-p03b, the shadow arms) and the UX chain 0095 to 0106 follows it unchanged - the same move 0110 made when A1 went first. Its revision
number stays: production never ran it, and every UX test and guide names it.
"""

from alembic import op

revision = "0095"
down_revision = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE SCHEMA IF NOT EXISTS customer;
        COMMENT ON SCHEMA customer IS
          'The customer''s own data (plan UX): consents, privacy requests and support. The worker has no access '
          '(db/grants.sql). No IP, no payment numbers, no tokens, no article text in any column.';

        CREATE OR REPLACE FUNCTION customer.refuse_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'customer.%: append-only (% refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$;

        CREATE TABLE customer.consents (
            id          BIGSERIAL   PRIMARY KEY,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind        TEXT        NOT NULL
                        CHECK (kind IN ('terms', 'privacy', 'age_18', 'risk_notice', 'marketing_email', 'analytics')),
            granted     BOOLEAN     NOT NULL,
            document    TEXT        NOT NULL CHECK (document IN ('terms', 'privacy', 'responsible_gaming')),
            version     TEXT        NOT NULL CHECK (version ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[a-z0-9.-]{0,24}$'),
            sha256      TEXT        NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
            locale      TEXT        NOT NULL CHECK (locale IN ('es', 'en')),
            statement   TEXT        NOT NULL CHECK (length(btrim(statement)) BETWEEN 1 AND 500),
            source      TEXT        NOT NULL CHECK (source IN ('gate', 'profile', 'activation')),
            replaces_id BIGINT      REFERENCES customer.consents(id),
            at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX consents_user_kind ON customer.consents (user_id, kind, at DESC, id DESC);
        CREATE TRIGGER consents_append_only BEFORE UPDATE OR DELETE ON customer.consents
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.consents IS
          'Every decision of a reader on a purpose, granted or withdrawn, with the version and the sha256 of the '
          'text read and the statement ticked. Append-only: the latest row of a kind is the reader''s answer.';

        CREATE TABLE customer.support_tickets (
            id          BIGSERIAL   PRIMARY KEY,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind        TEXT        NOT NULL
                        CHECK (kind IN ('privacy_query', 'privacy_claim', 'privacy_deletion', 'support')),
            status      TEXT        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered', 'closed')),
            opened_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            due_on      DATE,
            extended_to DATE,
            closed_at   TIMESTAMPTZ,
            CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
            CHECK (kind = 'support' OR due_on IS NOT NULL),
            CHECK (extended_to IS NULL OR (due_on IS NOT NULL AND extended_to > due_on))
        );
        CREATE INDEX support_tickets_user ON customer.support_tickets (user_id, opened_at DESC);
        CREATE INDEX support_tickets_open ON customer.support_tickets (due_on) WHERE status <> 'closed';
        CREATE TRIGGER support_tickets_never_deleted BEFORE DELETE ON customer.support_tickets
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();

        CREATE OR REPLACE FUNCTION customer.ticket_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN NEW;
            END IF;
            IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.kind <> OLD.kind
               OR NEW.opened_at <> OLD.opened_at OR NEW.due_on IS DISTINCT FROM OLD.due_on
               OR (OLD.extended_to IS NOT NULL AND NEW.extended_to IS DISTINCT FROM OLD.extended_to) THEN
                RAISE EXCEPTION 'customer.support_tickets: only the status, the one extension and the closing change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER support_tickets_guard BEFORE UPDATE ON customer.support_tickets
            FOR EACH ROW EXECUTE FUNCTION customer.ticket_guard();
        COMMENT ON COLUMN customer.support_tickets.due_on IS
          'The legal deadline in Colombian business days (Ley 1581 de 2012: a query 10, a claim 15); '
          'extended_to the one extension the law allows (5 / 8 more), said to the reader in a message.';

        CREATE TABLE customer.ticket_messages (
            id         BIGSERIAL   PRIMARY KEY,
            ticket_id  BIGINT      NOT NULL REFERENCES customer.support_tickets(id) ON DELETE RESTRICT,
            author     TEXT        NOT NULL CHECK (author IN ('customer', 'owner', 'system')),
            body       TEXT        NOT NULL CHECK (length(btrim(body)) BETWEEN 1 AND 4000),
            at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ticket_messages_ticket ON customer.ticket_messages (ticket_id, at, id);
        CREATE TRIGGER ticket_messages_append_only BEFORE UPDATE OR DELETE ON customer.ticket_messages
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.consents) OR EXISTS (SELECT 1 FROM customer.support_tickets) THEN
                RAISE EXCEPTION 'customer holds consents or tickets (legal evidence): the code goes back, the tables stay';
            END IF;
        END
        $guard$;
        DROP SCHEMA IF EXISTS customer CASCADE;
    """)
