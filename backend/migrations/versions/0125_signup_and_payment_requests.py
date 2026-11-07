"""The ground for a reader who registers by themselves and asks for access: their data, a unique nickname and the payment request (plan del flujo de usuario, tramo 1, UX-027)

WHY THIS EXISTS
---------------
Until now an account was born in the owner's hands: invited from the console (A7) or created by the owner. The first
stretch of the user's flow (registration, e-mail check, a request for access paid by Nequi/Bre-B, the owner's approval)
needs an account that a person opens by themselves and that is NOT a member until the owner says so. This revision only
prepares the ground, additively. Nothing here is read or written by any screen yet, and no switch changes: the code
before it keeps working on the new schema (every new column is nullable or has a default, every widened CHECK only
admits more values).

Four things stay apart, and the schema keeps them apart: registered (an ``auth.users`` row), e-mail verified
(``email_verified_at``), payment requested (``customer.payment_requests``, ``submitted``) and payment verified, which
is the owner's act (the request ``approved`` and a ``customer.payments`` row with its ``membership_periods``).

WHAT CHANGES
------------
- ``auth.users``: ``first_name``, ``last_name``, ``phone_e164`` (E.164, kept for the owner's own records: no SMS is
  ever sent to it), ``email_verified_at`` and ``origin`` (``admin``, ``invite`` or ``signup``; existing accounts are
  ``invite`` when an invitation token of theirs exists and ``admin`` otherwise). Status ``pending`` (registered, e-mail
  not yet verified). A ``signup`` account must carry its three personal fields while it exists (an anonymised one has
  none).
- The nickname (``display_name``) is unique, ignoring case and surrounding spaces, among the accounts that are not
  deleted. Nicknames that already repeat are made distinct by this revision - the oldest account keeps its own, the
  others get ``-<id>`` appended - so the index can be built; none is lost or merged.
- ``auth.account_tokens``: the purpose ``verify`` (the link that proves the e-mail).
- ``customer.consents``: the source ``signup`` (the four boxes ticked on the registration form).
- ``customer.payment_requests``: one row per «ya pagué». The amount expected (with its discount), what the reader
  declares, the reference as its last four characters and an HMAC (never the full number: a reference of 10 or more
  digits is refused everywhere, like in ``customer.payments``), an optional payer name and note, the version and
  sha256 of the purchase conditions accepted, and the decision (who, when, a closed code, a note, the payment it
  produced). One open request per reader. Once decided it cannot change (a trigger refuses it); the only thing that may
  still be done is to blank the payer's name and the note when the account is anonymised. Never deleted.
- ``customer.membership_events`` learns the four events of a request, ``audit.notifications`` learns
  ``payment_request_new`` and ``customer.lifecycle_snapshots`` learns the states ``registered`` and
  ``payment_pending``.

Nothing is written by this revision beyond the nickname repair and the ``origin`` backfill above. ``customer`` is the
API's schema (the worker cannot read it); the grants are db/grants.sql.

Downgrade: only while nothing of the flow exists (no pending or self-registered account, no request, no ``verify`` token
or ``signup`` consent: consents are append-only). Otherwise the code goes back and the schema stays.
"""

from alembic import op

revision = "0125"
down_revision = "0124"
branch_labels = None
depends_on = None

NOTIFY_BEFORE = (
    "shadow_pick", "pick_settled", "first_capture", "capture_failed", "worker_down", "run_recovered", "job_failing",
    "ai_budget", "outbox_failing", "membership_due", "ticket_new", "privacy_due", "synthetic_failed",
    "ai_user_budget", "lifecycle_daily",
)
EVENTS_BEFORE = (
    "trial_planned", "trial_started", "payment_recorded", "courtesy_granted", "suspended", "suspension_lifted",
    "will_not_renew", "will_renew", "notice",
)
EVENTS_NEW = ("payment_requested", "payment_request_approved", "payment_request_rejected",
              "payment_request_cancelled")
STATES_BEFORE = ("invited", "activated", "habitual", "at_risk", "expiring", "renewed", "expired")
STATES_NEW = ("registered", "payment_pending")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # 1. The nickname repair has to come before the unique index; it touches only a repeated nickname.
    op.execute(r"""
        WITH ranked AS (
            SELECT id, row_number() OVER (PARTITION BY lower(btrim(display_name)) ORDER BY id) AS n
              FROM auth.users WHERE status <> 'deleted'
        )
        UPDATE auth.users u
           SET display_name = left(btrim(u.display_name), 70) || '-' || u.id::text
          FROM ranked r
         WHERE r.id = u.id AND r.n > 1;

        ALTER TABLE auth.users
            ADD COLUMN first_name        TEXT CHECK (first_name IS NULL OR length(btrim(first_name)) BETWEEN 1 AND 80),
            ADD COLUMN last_name         TEXT CHECK (last_name IS NULL OR length(btrim(last_name)) BETWEEN 1 AND 80),
            ADD COLUMN phone_e164        TEXT CHECK (phone_e164 IS NULL OR phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
            ADD COLUMN email_verified_at TIMESTAMPTZ,
            ADD COLUMN origin            TEXT NOT NULL DEFAULT 'admin' CHECK (origin IN ('admin', 'invite', 'signup'));

        UPDATE auth.users u SET origin = 'invite'
         WHERE EXISTS (SELECT 1 FROM auth.account_tokens t WHERE t.user_id = u.id AND t.purpose = 'invite');

        ALTER TABLE auth.users DROP CONSTRAINT users_status_check;
        ALTER TABLE auth.users ADD CONSTRAINT users_status_check
            CHECK (status IN ('active', 'disabled', 'invited', 'deleted', 'pending'));
        ALTER TABLE auth.users ADD CONSTRAINT users_signup_has_its_data
            CHECK (origin <> 'signup' OR status = 'deleted'
                   OR (first_name IS NOT NULL AND last_name IS NOT NULL AND phone_e164 IS NOT NULL));
        ALTER TABLE auth.users ADD CONSTRAINT users_pending_is_signup
            CHECK (status <> 'pending' OR origin = 'signup');

        CREATE UNIQUE INDEX users_display_name_ci_key ON auth.users (lower(btrim(display_name)))
            WHERE status <> 'deleted';

        COMMENT ON COLUMN auth.users.phone_e164 IS
          'The reader''s mobile in E.164, for the owner''s own records. No SMS or text message is ever sent to it.';
        COMMENT ON COLUMN auth.users.origin IS
          'How the account was born: the owner created it (admin), the owner invited it (invite) or the person '
          'registered by themselves (signup).';
        COMMENT ON COLUMN auth.users.email_verified_at IS
          'When the person proved the address with the link we sent. NULL for accounts of the owner''s making: the '
          'invitation link already proves the address when they activate.';

        ALTER TABLE auth.account_tokens DROP CONSTRAINT account_tokens_purpose_check;
        ALTER TABLE auth.account_tokens ADD CONSTRAINT account_tokens_purpose_check
            CHECK (purpose IN ('invite', 'reset', 'unlock', 'verify'));

        ALTER TABLE customer.consents DROP CONSTRAINT consents_source_check;
        ALTER TABLE customer.consents ADD CONSTRAINT consents_source_check
            CHECK (source IN ('gate', 'profile', 'activation', 'email', 'signup'));
    """)

    # 2. The payment request.
    op.execute(r"""
        CREATE TABLE customer.payment_requests (
            id                BIGSERIAL     PRIMARY KEY,
            user_id           BIGINT        NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            status            TEXT          NOT NULL DEFAULT 'submitted'
                                            CHECK (status IN ('submitted', 'approved', 'rejected', 'cancelled')),
            expected_amount   NUMERIC(12,2) NOT NULL CHECK (expected_amount > 0),
            currency          TEXT          NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            coupon_id         BIGINT        REFERENCES customer.coupons(id) ON DELETE RESTRICT,
            discount_percent  SMALLINT      CHECK (discount_percent BETWEEN 1 AND 100),
            declared_amount   NUMERIC(12,2) NOT NULL CHECK (declared_amount > 0),
            declared_paid_on  DATE          NOT NULL,
            method            TEXT          NOT NULL CHECK (method IN ('nequi', 'transfer', 'other')),
            reference_last4   TEXT          CHECK (reference_last4 IS NULL OR reference_last4 ~ '^[A-Za-z0-9]{1,4}$'),
            reference_hmac    TEXT          CHECK (reference_hmac IS NULL OR reference_hmac ~ '^[0-9a-f]{64}$'),
            payer_name        TEXT          CHECK (payer_name IS NULL OR length(btrim(payer_name)) BETWEEN 1 AND 80),
            note              TEXT          CHECK (note IS NULL OR length(btrim(note)) BETWEEN 1 AND 300),
            terms_version     TEXT          NOT NULL CHECK (terms_version ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[a-z0-9.-]{0,24}$'),
            terms_sha256      TEXT          NOT NULL CHECK (terms_sha256 ~ '^[0-9a-f]{64}$'),
            accepted_at       TIMESTAMPTZ   NOT NULL,
            created_at        TIMESTAMPTZ   NOT NULL DEFAULT now(),
            decided_at        TIMESTAMPTZ,
            decided_by        BIGINT        REFERENCES auth.users(id) ON DELETE RESTRICT,
            decision_code     TEXT          CHECK (decision_code IN ('amount_mismatch', 'not_received', 'duplicate',
                                                                     'unreadable', 'other')),
            decision_note     TEXT          CHECK (decision_note IS NULL OR length(btrim(decision_note)) BETWEEN 3 AND 200),
            payment_id        BIGINT        REFERENCES customer.payments(id) ON DELETE RESTRICT,
            CHECK ((coupon_id IS NULL) = (discount_percent IS NULL)),
            CHECK ((reference_last4 IS NULL) = (reference_hmac IS NULL)),
            CHECK ((status = 'submitted') = (decided_at IS NULL)),
            CHECK ((status = 'approved') = (payment_id IS NOT NULL)),
            CHECK (status NOT IN ('approved', 'rejected') OR decided_by IS NOT NULL),
            CHECK (status <> 'cancelled' OR decided_by IS NULL),
            CHECK ((status = 'rejected') = (decision_code IS NOT NULL)),
            CHECK (decision_note IS NULL OR status IN ('approved', 'rejected'))
        );
        CREATE UNIQUE INDEX payment_requests_one_open ON customer.payment_requests (user_id)
            WHERE status = 'submitted';
        CREATE INDEX payment_requests_user ON customer.payment_requests (user_id, created_at DESC, id DESC);
        CREATE INDEX payment_requests_queue ON customer.payment_requests (created_at, id) WHERE status = 'submitted';

        CREATE OR REPLACE FUNCTION customer.payment_requests_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            fixed_new jsonb;
            fixed_old jsonb;
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'customer.payment_requests: never deleted' USING ERRCODE = 'check_violation';
            END IF;
            -- What the reader declared and accepted never changes; the payer's name and the note may only be blanked
            -- (the anonymisation of the account does it).
            fixed_new := to_jsonb(NEW) - 'status' - 'decided_at' - 'decided_by' - 'decision_code' - 'decision_note'
                         - 'payment_id' - 'payer_name' - 'note';
            fixed_old := to_jsonb(OLD) - 'status' - 'decided_at' - 'decided_by' - 'decision_code' - 'decision_note'
                         - 'payment_id' - 'payer_name' - 'note';
            IF fixed_new <> fixed_old THEN
                RAISE EXCEPTION 'customer.payment_requests: what the reader declared cannot change'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF (NEW.payer_name IS NOT NULL AND NEW.payer_name IS DISTINCT FROM OLD.payer_name)
               OR (NEW.note IS NOT NULL AND NEW.note IS DISTINCT FROM OLD.note) THEN
                RAISE EXCEPTION 'customer.payment_requests: the payer''s name and the note can only be blanked'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.status <> 'submitted'
               AND (to_jsonb(NEW) - 'payer_name' - 'note') <> (to_jsonb(OLD) - 'payer_name' - 'note') THEN
                RAISE EXCEPTION 'customer.payment_requests: a decided request is not edited'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER payment_requests_guard BEFORE UPDATE OR DELETE ON customer.payment_requests
            FOR EACH ROW EXECUTE FUNCTION customer.payment_requests_guard();

        COMMENT ON TABLE customer.payment_requests IS
          'A reader''s «ya pagué»: what they declare about a Nequi/Bre-B payment, the purchase conditions they accepted '
          '(version and sha256) and the owner''s decision. One open request per reader; never edited once decided, '
          'never deleted. It confirms nothing by itself: only the owner''s approval creates the payment and the period. '
          'No IP, no account numbers, no full reference.';
    """)

    # 3. Closed lists that learn the flow's events, notice and states.
    op.execute(f"""
        ALTER TABLE customer.membership_events DROP CONSTRAINT membership_events_kind_check;
        ALTER TABLE customer.membership_events ADD CONSTRAINT membership_events_kind_check
            CHECK (kind IN ({_in((*EVENTS_BEFORE, *EVENTS_NEW))}));

        ALTER TABLE audit.notifications DROP CONSTRAINT notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({_in((*NOTIFY_BEFORE, "payment_request_new"))}));

        ALTER TABLE customer.lifecycle_snapshots DROP CONSTRAINT lifecycle_snapshots_state_check;
        ALTER TABLE customer.lifecycle_snapshots ADD CONSTRAINT lifecycle_snapshots_state_check
            CHECK (state IN ({_in((*STATES_BEFORE, *STATES_NEW))}));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.payment_requests)
               OR EXISTS (SELECT 1 FROM auth.users WHERE status = 'pending' OR origin = 'signup')
               OR EXISTS (SELECT 1 FROM auth.account_tokens WHERE purpose = 'verify')
               OR EXISTS (SELECT 1 FROM customer.consents WHERE source = 'signup')
               OR EXISTS (SELECT 1 FROM customer.membership_events WHERE kind LIKE 'payment_request%')
               OR EXISTS (SELECT 1 FROM audit.notifications WHERE kind = 'payment_request_new')
               OR EXISTS (SELECT 1 FROM customer.lifecycle_snapshots WHERE state IN ('registered', 'payment_pending'))
            THEN
                RAISE EXCEPTION 'readers registered by themselves or payment requests exist: the code goes back, the schema stays';
            END IF;
        END
        $guard$;
    """)
    op.execute(f"""
        ALTER TABLE customer.lifecycle_snapshots DROP CONSTRAINT lifecycle_snapshots_state_check;
        ALTER TABLE customer.lifecycle_snapshots ADD CONSTRAINT lifecycle_snapshots_state_check
            CHECK (state IN ({_in(STATES_BEFORE)}));
        ALTER TABLE audit.notifications DROP CONSTRAINT notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check CHECK (kind IN ({_in(NOTIFY_BEFORE)}));
        ALTER TABLE customer.membership_events DROP CONSTRAINT membership_events_kind_check;
        ALTER TABLE customer.membership_events ADD CONSTRAINT membership_events_kind_check
            CHECK (kind IN ({_in(EVENTS_BEFORE)}));

        DROP TRIGGER payment_requests_guard ON customer.payment_requests;
        DROP FUNCTION customer.payment_requests_guard();
        DROP TABLE customer.payment_requests;

        ALTER TABLE customer.consents DROP CONSTRAINT consents_source_check;
        ALTER TABLE customer.consents ADD CONSTRAINT consents_source_check
            CHECK (source IN ('gate', 'profile', 'activation', 'email'));
        ALTER TABLE auth.account_tokens DROP CONSTRAINT account_tokens_purpose_check;
        ALTER TABLE auth.account_tokens ADD CONSTRAINT account_tokens_purpose_check
            CHECK (purpose IN ('invite', 'reset', 'unlock'));

        DROP INDEX auth.users_display_name_ci_key;
        ALTER TABLE auth.users DROP CONSTRAINT users_pending_is_signup;
        ALTER TABLE auth.users DROP CONSTRAINT users_signup_has_its_data;
        ALTER TABLE auth.users DROP CONSTRAINT users_status_check;
        ALTER TABLE auth.users ADD CONSTRAINT users_status_check
            CHECK (status IN ('active', 'disabled', 'invited', 'deleted'));
        ALTER TABLE auth.users
            DROP COLUMN origin, DROP COLUMN email_verified_at, DROP COLUMN phone_e164,
            DROP COLUMN last_name, DROP COLUMN first_name;
    """)
