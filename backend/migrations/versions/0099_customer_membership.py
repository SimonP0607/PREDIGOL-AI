"""Membership: periods, payments and their events (plan UX, A8)

WHY THIS EXISTS
---------------
A reader's account is active or disabled, nothing else: no trial, no expiry, no grace, no record of a payment. The
plan's membership (section 22) is one full plan with a 14-day trial, seven states computed from dates, notices before
and after the expiry, and a manual renewal the owner records in under a minute - charged outside PrediGol, recorded
here, in a shape a payment gateway (C4) can write later without changing anything.

WHAT CHANGES
------------
- ``customer.payments``: a payment the owner recorded - amount, currency, method, a reference in words - with the
  provider (``manual`` today) and an idempotency key, so a click repeated, or a gateway's webhook delivered twice,
  records one payment. Never an account or card number: the reference refuses any run of ten digits or more, spaces,
  dots and dashes ignored (the API refuses it first, with a clear message). Append-only.
- ``customer.membership_periods``: what covers an account and until when - a trial (one per account), a paid period
  (tied to its payment) or a courtesy (with its reason). A new period starts at the end of the one in force, or now if
  that one has ended. Append-only: the state is computed from the periods and the events, never stored.
- ``customer.membership_events``: what happened besides periods - the trial the owner chose at the invitation, the
  trial started, a payment recorded, a courtesy granted, a suspension and its lifting (with the reason), «will not
  renew» and its withdrawal (with the reason), and each notice sent for a period's end (one per period and milestone:
  the unique index makes the messenger's notices idempotent). Append-only.

Every foreign key to ``auth.users`` is ON DELETE RESTRICT: an account is anonymised, never deleted (A7), and the
payments stay linked to it (tax records). The worker of PrediGol Intelligence cannot read any of the three
(db/grants.sql treats ``customer`` as ``auth``); the API's role inserts and never edits or deletes.

Downgrade: drops the three tables only while they are empty. With real periods or payments the code goes back and the
tables stay (FBI_MEMBERSHIP_ENFORCE=0 is the rollback: everybody keeps full access).
"""

from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE customer.payments (
            id              BIGSERIAL     PRIMARY KEY,
            user_id         BIGINT        NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            provider        TEXT          NOT NULL DEFAULT 'manual' CHECK (provider IN ('manual')),
            amount          NUMERIC(12,2) NOT NULL CHECK (amount > 0),
            currency        TEXT          NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
            method          TEXT          NOT NULL
                            CHECK (method IN ('transfer', 'nequi', 'daviplata', 'cash', 'card', 'paypal', 'other')),
            reference       TEXT          NOT NULL DEFAULT ''
                            CHECK (length(reference) <= 120
                                   AND regexp_replace(reference, '[[:space:].-]', '', 'g') !~ '[0-9]{10}'),
            external_ref    TEXT          CHECK (external_ref IS NULL OR length(external_ref) BETWEEN 1 AND 120),
            idempotency_key TEXT          NOT NULL UNIQUE CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{8,80}$'),
            recorded_by     BIGINT        REFERENCES auth.users(id) ON DELETE RESTRICT,
            recorded_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        CREATE INDEX payments_user ON customer.payments (user_id, recorded_at DESC);
        CREATE TRIGGER payments_append_only BEFORE UPDATE OR DELETE ON customer.payments
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.payments IS
          'A payment recorded by the owner (provider manual) or, later, a gateway: amount, currency, method and a '
          'reference in words - never an account or card number. One per idempotency key. Append-only.';

        CREATE TABLE customer.membership_periods (
            id          BIGSERIAL   PRIMARY KEY,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind        TEXT        NOT NULL CHECK (kind IN ('trial', 'paid', 'courtesy')),
            starts_at   TIMESTAMPTZ NOT NULL,
            ends_at     TIMESTAMPTZ NOT NULL,
            payment_id  BIGINT      UNIQUE REFERENCES customer.payments(id) ON DELETE RESTRICT,
            reason      TEXT        CHECK (reason IS NULL OR length(btrim(reason)) BETWEEN 3 AND 200),
            created_by  BIGINT      REFERENCES auth.users(id) ON DELETE RESTRICT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK (ends_at > starts_at),
            CHECK ((kind = 'paid') = (payment_id IS NOT NULL)),
            CHECK (kind <> 'courtesy' OR reason IS NOT NULL)
        );
        CREATE INDEX membership_periods_user ON customer.membership_periods (user_id, ends_at DESC);
        CREATE UNIQUE INDEX membership_periods_one_trial ON customer.membership_periods (user_id)
            WHERE kind = 'trial';
        CREATE TRIGGER membership_periods_append_only BEFORE UPDATE OR DELETE ON customer.membership_periods
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.membership_periods IS
          'What covers an account and until when: a trial (one per account), a paid period (its payment) or a '
          'courtesy (its reason). The membership''s state is computed from these and the events, never stored.';

        CREATE TABLE customer.membership_events (
            id            BIGSERIAL   PRIMARY KEY,
            user_id       BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind          TEXT        NOT NULL CHECK (kind IN (
                              'trial_planned', 'trial_started', 'payment_recorded', 'courtesy_granted',
                              'suspended', 'suspension_lifted', 'will_not_renew', 'will_renew', 'notice')),
            period_id     BIGINT      REFERENCES customer.membership_periods(id) ON DELETE RESTRICT,
            milestone     TEXT        CHECK (milestone IS NULL OR milestone IN ('before', 'due', 'grace_end')),
            reason        TEXT        CHECK (reason IS NULL OR length(btrim(reason)) BETWEEN 3 AND 200),
            detail        JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
            actor_user_id BIGINT      REFERENCES auth.users(id) ON DELETE RESTRICT,
            at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((kind = 'notice') = (milestone IS NOT NULL)),
            CHECK (kind <> 'notice' OR period_id IS NOT NULL),
            CHECK (kind NOT IN ('suspended', 'suspension_lifted', 'will_not_renew') OR reason IS NOT NULL)
        );
        CREATE INDEX membership_events_user ON customer.membership_events (user_id, at DESC, id DESC);
        CREATE UNIQUE INDEX membership_events_one_notice ON customer.membership_events (period_id, milestone)
            WHERE kind = 'notice';
        CREATE TRIGGER membership_events_append_only BEFORE UPDATE OR DELETE ON customer.membership_events
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.membership_events IS
          'What happened to a membership besides its periods: the trial chosen at the invitation, the trial started, '
          'payments, courtesies, suspensions, «will not renew», and the notices of a period''s end (one per period '
          'and milestone). Append-only.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.membership_periods) OR EXISTS (SELECT 1 FROM customer.payments)
               OR EXISTS (SELECT 1 FROM customer.membership_events) THEN
                RAISE EXCEPTION 'customer holds memberships or payments: the code goes back, the tables stay';
            END IF;
        END
        $guard$;
        DROP TABLE customer.membership_events;
        DROP TABLE customer.membership_periods;
        DROP TABLE customer.payments;
    """)
