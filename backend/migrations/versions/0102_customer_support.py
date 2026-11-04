"""A support ticket's category, its context and the reader's effort; where a message was said (plan UX, A14)

WHY THIS EXISTS
---------------
A4 created ``customer.support_tickets`` and ``customer.ticket_messages`` for the privacy requests (0095), with a
fourth kind, ``support``, that nothing wrote yet. A14 opens it to the readers' own questions, and the plan (section 32)
needs, for each one: its category - which sets its priority and how soon it is answered -, the context the web
attaches so the owner does not have to ask, where each message was said (a talk on WhatsApp or an e-mail the owner
notes in the thread so it stays whole) and the optional question on how easy it was, asked at the close. The card of
A14 says «no new table»: there is none - four columns, nothing dropped, nothing rewritten.

WHAT CHANGES
------------
- ``customer.support_tickets.category``: access | account | technical | wrong_data | suggestion | complaint | privacy.
  A privacy request is ``privacy`` and only a privacy request is (CHECK). The rows before A14 get theirs here; a row
  the code before A14 writes (it does not know the column) gets it from a trigger - a privacy kind: ``privacy``,
  ``support``: ``technical`` -, so going back to that code keeps working.
- ``.context``: what the web attached when the ticket was opened (the screen's route, the request id of the last
  error, the web's version, the device's class, the installed app or a tab, the match): a JSON object of at most
  2 KB whose keys the API checks; never a password, a token, an address or what a form held. Support tickets only.
- ``.effort``: 1 to 5, the reader's answer to «¿Qué tan fácil fue resolverlo?»; once, on a closed support ticket.
- ``customer.ticket_messages.channel``: web | email | whatsapp (every message before A14 was written in PrediGol).
- ``customer.ticket_guard()``: the category and the context are fixed like who, what and when; the effort is set
  once. The status, the one extension and the closing change as before.

Downgrade: refuses while a support ticket or a message noted from WhatsApp or an e-mail exists (dropping the columns
would lose what readers said and what they were told); otherwise drops the columns and the trigger and puts the
guard of 0095 back.
"""

from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None

CATEGORIES = ("access", "account", "technical", "wrong_data", "suggestion", "complaint", "privacy")

GUARD_0095 = """
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
"""


def upgrade() -> None:
    allowed = ", ".join(f"'{c}'" for c in CATEGORIES)
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE customer.support_tickets
            ADD COLUMN category TEXT,
            ADD COLUMN context  JSONB,
            ADD COLUMN effort   SMALLINT;

        -- The rows before A14 (still under the guard of 0095, which does not know the column).
        UPDATE customer.support_tickets SET category = CASE WHEN kind = 'support' THEN 'technical' ELSE 'privacy' END;

        ALTER TABLE customer.support_tickets
            ALTER COLUMN category SET NOT NULL,
            ADD CONSTRAINT support_tickets_category CHECK (category IN ({allowed})),
            ADD CONSTRAINT support_tickets_privacy_category CHECK ((kind = 'support') = (category <> 'privacy')),
            ADD CONSTRAINT support_tickets_context CHECK (
                context IS NULL OR (kind = 'support' AND jsonb_typeof(context) = 'object'
                                    AND octet_length(context::text) <= 2048)),
            ADD CONSTRAINT support_tickets_effort CHECK (
                effort IS NULL OR (effort BETWEEN 1 AND 5 AND kind = 'support' AND status = 'closed'));

        COMMENT ON COLUMN customer.support_tickets.category IS
          'Plan UX, section 32: access (urgent), account, technical, complaint (high), wrong_data (medium), suggestion '
          '(low) - a support ticket; privacy - a privacy request (its legal deadline in due_on). Fixed once written.';
        COMMENT ON COLUMN customer.support_tickets.context IS
          'What the web attached (route, request id of the last error, web version, device class, installed app, '
          'match). At most 2 KB; never a password, a token, an address or a form''s contents. Fixed once written.';
        COMMENT ON COLUMN customer.support_tickets.effort IS
          'The reader''s answer, 1 (very hard) to 5 (very easy), to how easy it was; once, on a closed support ticket.';

        -- A row written by the code before A14, which does not know the category: it gets the one the backfill gives.
        CREATE OR REPLACE FUNCTION customer.ticket_defaults() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF NEW.category IS NULL THEN
                NEW.category := CASE WHEN NEW.kind = 'support' THEN 'technical' ELSE 'privacy' END;
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER support_tickets_defaults BEFORE INSERT ON customer.support_tickets
            FOR EACH ROW EXECUTE FUNCTION customer.ticket_defaults();

        CREATE OR REPLACE FUNCTION customer.ticket_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN NEW;
            END IF;
            IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.kind <> OLD.kind
               OR NEW.opened_at <> OLD.opened_at OR NEW.due_on IS DISTINCT FROM OLD.due_on
               OR (OLD.extended_to IS NOT NULL AND NEW.extended_to IS DISTINCT FROM OLD.extended_to)
               OR NEW.category IS DISTINCT FROM OLD.category OR NEW.context IS DISTINCT FROM OLD.context
               OR (OLD.effort IS NOT NULL AND NEW.effort IS DISTINCT FROM OLD.effort) THEN
                RAISE EXCEPTION 'customer.support_tickets: only the status, the one extension, the closing and the '
                                'effort (once) change'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;

        ALTER TABLE customer.ticket_messages
            ADD COLUMN channel TEXT NOT NULL DEFAULT 'web' CHECK (channel IN ('web', 'email', 'whatsapp'));
        COMMENT ON COLUMN customer.ticket_messages.channel IS
          'Where it was said: web (written in PrediGol, by the reader or the owner), email or whatsapp (the owner noted '
          'in the thread what was said there).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.support_tickets WHERE kind = 'support')
               OR EXISTS (SELECT 1 FROM customer.ticket_messages WHERE channel <> 'web') THEN
                RAISE EXCEPTION 'customer holds support tickets or messages noted from WhatsApp or e-mail (what readers '
                                'said and were told): the code goes back, the columns stay';
            END IF;
        END
        $guard$;
        DROP TRIGGER IF EXISTS support_tickets_defaults ON customer.support_tickets;
        DROP FUNCTION IF EXISTS customer.ticket_defaults();
        {GUARD_0095}
        ALTER TABLE customer.ticket_messages DROP COLUMN channel;
        ALTER TABLE customer.support_tickets
            DROP CONSTRAINT support_tickets_effort,
            DROP CONSTRAINT support_tickets_context,
            DROP CONSTRAINT support_tickets_privacy_category,
            DROP CONSTRAINT support_tickets_category,
            DROP COLUMN effort,
            DROP COLUMN context,
            DROP COLUMN category;
    """)
