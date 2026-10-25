"""The messenger's queue and the reader's notification preferences (plan UX, A5)

WHY THIS EXISTS
---------------
PrediGol has no e-mail: no invitation, no recovery, no answer to a privacy request reaches a reader. A5 adds one queue
for every message to a reader (e-mail now, push in B7), a process of its own that sends it (the messenger, with the
API's role and the backend's image - never the worker of PrediGol Intelligence), and the reader's choice of what they
want to receive.

WHAT CHANGES
------------
- ``customer.messages_outbox``: one row per message - the template, the language, the parameters the template needs
  (never a secret, a token, the reader's name or the address: they are read when sending), the deduplication key, the
  status, the attempts, the next attempt, the provider's id and the last error's class. Never the body (plan UX,
  section 33). What was asked never changes and a row is never deleted (``customer.messages_outbox_guard()`` and
  ``customer.refuse_change()``); the status, the attempts and the provider's answer do.
- ``customer.preferences``: one row per reader, written the first time they choose or their address bounces - the
  optional e-mail categories they switched off, the deliverability of their address (a hard bounce or a complaint
  stops the e-mail), and the fields later phases use (quiet hours, hints seen, onboarding).
- ``audit.notifications``: the owner's six new kinds (the queue failing, a membership due, a new ticket, a privacy
  request near its deadline, the synthetic journey failing, the readers' AI budget); counts and a link, never a
  reader's address, alias or words.

Both tables follow ``customer``'s rules: the worker cannot read them (db/grants.sql), and every foreign key to
``auth.users`` is ON DELETE RESTRICT (an account is anonymised, never deleted).

Downgrade: drops the two tables only while the queue holds no row (a sent message is a record of what was sent);
the notification kinds stay accepted for the rows already written (NOT VALID on the older CHECK).
"""

from alembic import op

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None

KINDS_BEFORE = ("shadow_pick", "pick_settled", "first_capture", "capture_failed", "worker_down", "run_recovered",
                "job_failing", "ai_budget")
KINDS_NEW = ("outbox_failing", "membership_due", "ticket_new", "privacy_due", "synthetic_failed", "ai_user_budget")
CATEGORIES = ("account", "security", "membership", "support", "privacy", "legal")
OPTIONAL = ("membership", "support")
"""The categories a reader may switch off (fbi.messaging.templates.MANDATORY are the others)."""


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE customer.preferences (
            user_id          BIGINT      PRIMARY KEY REFERENCES auth.users(id) ON DELETE RESTRICT,
            email_off        TEXT[]      NOT NULL DEFAULT '{{}}' CHECK (email_off <@ ARRAY[{_in(OPTIONAL)}]::text[]),
            email_status     TEXT        NOT NULL DEFAULT 'ok' CHECK (email_status IN ('ok', 'bounced', 'complained')),
            email_status_at  TIMESTAMPTZ,
            quiet_from       SMALLINT    CHECK (quiet_from BETWEEN 0 AND 23),
            quiet_to         SMALLINT    CHECK (quiet_to BETWEEN 0 AND 23),
            hints_seen       TEXT[]      NOT NULL DEFAULT '{{}}',
            onboarded_at     TIMESTAMPTZ,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((email_status = 'ok') = (email_status_at IS NULL)),
            CHECK ((quiet_from IS NULL) = (quiet_to IS NULL))
        );
        COMMENT ON TABLE customer.preferences IS
          'What a reader wants to receive and whether their address can receive it. email_off: the optional e-mail '
          'categories they switched off (an account, security, privacy or legal message is never optional). '
          'email_status: a hard bounce or a complaint stops the e-mail until the address is fixed. No row: the defaults.';

        CREATE TABLE customer.messages_outbox (
            id              BIGSERIAL   PRIMARY KEY,
            user_id         BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            channel         TEXT        NOT NULL DEFAULT 'email' CHECK (channel IN ('email')),
            category        TEXT        NOT NULL CHECK (category IN ({_in(CATEGORIES)})),
            template        TEXT        NOT NULL CHECK (template ~ '^[a-z][a-z0-9_]{{2,63}}$'),
            locale          TEXT        NOT NULL CHECK (locale IN ('es', 'en')),
            params          JSONB       NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(params) = 'object'),
            dedup_key       TEXT        NOT NULL UNIQUE CHECK (length(dedup_key) BETWEEN 8 AND 200),
            status          TEXT        NOT NULL DEFAULT 'queued'
                            CHECK (status IN ('queued', 'sent', 'failed', 'bounced', 'complained', 'suppressed')),
            attempts        INTEGER     NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 20),
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            provider_id     TEXT        CHECK (provider_id IS NULL OR length(provider_id) BETWEEN 1 AND 100),
            last_error      TEXT        CHECK (last_error IS NULL OR length(last_error) <= 200),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at         TIMESTAMPTZ,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            -- accepted by the provider <=> its id and the moment; delivered, bounced and complained only after that
            CHECK ((sent_at IS NULL) = (provider_id IS NULL)),
            CHECK (status NOT IN ('sent', 'bounced', 'complained') OR sent_at IS NOT NULL),
            CHECK (status <> 'queued' OR sent_at IS NULL)
        );
        CREATE INDEX messages_outbox_due ON customer.messages_outbox (next_attempt_at) WHERE status = 'queued';
        CREATE INDEX messages_outbox_user ON customer.messages_outbox (user_id, created_at DESC);
        CREATE INDEX messages_outbox_recent ON customer.messages_outbox (created_at DESC);
        CREATE UNIQUE INDEX messages_outbox_provider ON customer.messages_outbox (provider_id)
            WHERE provider_id IS NOT NULL;
        COMMENT ON TABLE customer.messages_outbox IS
          'Every message to a reader and its fate, without its body, the reader''s name or the address (read when '
          'sending). params never holds a secret, a token or a password (fbi.messaging.templates refuses them). '
          'Retention: 12 months (the purge is a documented job run with the owner''s OK, never automatic).';

        CREATE OR REPLACE FUNCTION customer.messages_outbox_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN NEW;
            END IF;
            IF NEW.id <> OLD.id OR NEW.user_id <> OLD.user_id OR NEW.channel <> OLD.channel
               OR NEW.category <> OLD.category OR NEW.template <> OLD.template OR NEW.locale <> OLD.locale
               OR NEW.params <> OLD.params OR NEW.dedup_key <> OLD.dedup_key OR NEW.created_at <> OLD.created_at
               OR (OLD.provider_id IS NOT NULL AND NEW.provider_id IS DISTINCT FROM OLD.provider_id) THEN
                RAISE EXCEPTION 'customer.messages_outbox: what was asked is fixed; only its fate changes'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER messages_outbox_guard BEFORE UPDATE ON customer.messages_outbox
            FOR EACH ROW EXECUTE FUNCTION customer.messages_outbox_guard();
        CREATE TRIGGER messages_outbox_never_deleted BEFORE DELETE ON customer.messages_outbox
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();

        ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({_in(KINDS_BEFORE + KINDS_NEW)}));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.messages_outbox) OR EXISTS (SELECT 1 FROM customer.preferences) THEN
                RAISE EXCEPTION 'customer.messages_outbox or customer.preferences hold rows (what was sent, what readers '
                                'chose): the code goes back, the tables stay';
            END IF;
        END
        $guard$;
        DROP TABLE customer.messages_outbox;
        DROP FUNCTION customer.messages_outbox_guard();
        DROP TABLE customer.preferences;
        ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({_in(KINDS_BEFORE)})) NOT VALID;
    """)
