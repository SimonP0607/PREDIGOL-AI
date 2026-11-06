"""Coupons and discounts of the membership (plan UX, UX-005)

WHY THIS EXISTS
---------------
The owner decided (5 Nov 2026) that a reader can hold a coupon the owner creates when he wants one, and that a reader
who has paid for more than two months gets 20% off from then on, for loyalty. Nothing is charged by PrediGol (no
gateway): the owner records the payment in the console, so the discount is a number the console proposes and the payment
keeps. This revision adds the two tables a coupon needs and the three columns a discounted payment keeps.

WHAT CHANGES
------------
- ``customer.coupons``: a code the owner creates (3 to 32 letters, digits, - or _, stored in capitals), the percentage it
  takes off (1 to 100), an optional note for himself, an optional last day and an optional ceiling of redemptions.
  A coupon is never deleted and nothing about it is edited except that it is DISABLED (``disabled_at``, once): the
  trigger refuses the rest, so a payment that used a coupon always finds it as it was.
- ``customer.coupon_redemptions``: a reader holding a coupon, once per coupon and reader. Append-only. The coupon is
  USED when a payment records it (``payments.coupon_id``): nothing is edited to say so.
- ``customer.payments``: ``discount_percent``, ``discount_kind`` (``coupon`` or ``loyalty``) and ``coupon_id``, all NULL
  for a payment without a discount (every payment before this revision), and all set together for one with it.

Both new tables follow the rest of the membership: every foreign key is ON DELETE RESTRICT (an account is anonymised,
never deleted, A7), the worker of PrediGol Intelligence cannot read them (``customer`` is treated as ``auth`` by
db/grants.sql) and the API's role gets only the verbs they need there.

On a live database: ``customer.payments`` is altered FIRST and a wait longer than 10 s for its lock fails the revision
whole (the rule of 0111, 0112, 0115, 0119 and 0120). It holds the owner's manual payments - a handful of rows, none
read by the decision layer.

Downgrade (production goes back by deploying the code that ran before, which works on this schema because every change
here only adds): the columns and the two tables go only while no coupon, redemption or discounted payment exists. With
any, the code goes back and the tables stay.

Revision ID: 0121
Revises: 0120
"""

from __future__ import annotations

from alembic import op

revision = "0121"
down_revision = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE customer.payments
            ADD COLUMN discount_percent SMALLINT CHECK (discount_percent BETWEEN 1 AND 100),
            ADD COLUMN discount_kind    TEXT     CHECK (discount_kind IN ('coupon', 'loyalty')),
            ADD COLUMN coupon_id        BIGINT;
    """)
    op.execute(r"""
        CREATE TABLE customer.coupons (
            id              BIGSERIAL   PRIMARY KEY,
            code            TEXT        NOT NULL UNIQUE CHECK (code ~ '^[A-Z0-9_-]{3,32}$'),
            percent         SMALLINT    NOT NULL CHECK (percent BETWEEN 1 AND 100),
            note            TEXT        CHECK (note IS NULL OR length(btrim(note)) BETWEEN 3 AND 120),
            valid_until     TIMESTAMPTZ,
            max_redemptions INTEGER     CHECK (max_redemptions IS NULL OR max_redemptions BETWEEN 1 AND 100000),
            created_by      BIGINT      REFERENCES auth.users(id) ON DELETE RESTRICT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            disabled_at     TIMESTAMPTZ,
            disabled_by     BIGINT      REFERENCES auth.users(id) ON DELETE RESTRICT,
            CHECK (disabled_by IS NULL OR disabled_at IS NOT NULL)
        );
        COMMENT ON TABLE customer.coupons IS
          'A coupon the owner creates: its code, the percentage it takes off, an optional note, last day and ceiling of '
          'redemptions. Never deleted; the only change is disabling it, once (customer.coupons_guard).';

        CREATE OR REPLACE FUNCTION customer.coupons_guard() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.customer_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'customer.coupons: a coupon is disabled, never deleted'
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.disabled_at IS NOT NULL
               OR (NEW.id, NEW.code, NEW.percent, NEW.note, NEW.valid_until, NEW.max_redemptions,
                   NEW.created_by, NEW.created_at)
                  IS DISTINCT FROM
                  (OLD.id, OLD.code, OLD.percent, OLD.note, OLD.valid_until, OLD.max_redemptions,
                   OLD.created_by, OLD.created_at) THEN
                RAISE EXCEPTION 'customer.coupons: only disabling an enabled coupon is allowed'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $fn$;
        CREATE TRIGGER coupons_guard BEFORE UPDATE OR DELETE ON customer.coupons
            FOR EACH ROW EXECUTE FUNCTION customer.coupons_guard();

        CREATE TABLE customer.coupon_redemptions (
            id          BIGSERIAL   PRIMARY KEY,
            coupon_id   BIGINT      NOT NULL REFERENCES customer.coupons(id) ON DELETE RESTRICT,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            redeemed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (coupon_id, user_id)
        );
        CREATE INDEX coupon_redemptions_user ON customer.coupon_redemptions (user_id, redeemed_at DESC);
        CREATE TRIGGER coupon_redemptions_append_only BEFORE UPDATE OR DELETE ON customer.coupon_redemptions
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.coupon_redemptions IS
          'A reader holding a coupon, once per coupon and reader. The coupon is used when a payment records it '
          '(payments.coupon_id). Append-only.';

        ALTER TABLE customer.payments
            ADD CONSTRAINT payments_coupon_fk FOREIGN KEY (coupon_id) REFERENCES customer.coupons(id) ON DELETE RESTRICT,
            ADD CONSTRAINT payments_discount_together
                CHECK ((discount_percent IS NULL) = (discount_kind IS NULL)),
            ADD CONSTRAINT payments_coupon_with_its_kind
                CHECK ((discount_kind = 'coupon') = (coupon_id IS NOT NULL));
        CREATE UNIQUE INDEX payments_one_use_per_coupon ON customer.payments (user_id, coupon_id)
            WHERE coupon_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.coupons) OR EXISTS (SELECT 1 FROM customer.coupon_redemptions)
               OR EXISTS (SELECT 1 FROM customer.payments WHERE discount_kind IS NOT NULL) THEN
                RAISE EXCEPTION 'customer holds coupons or discounted payments: the code goes back, the tables stay';
            END IF;
        END
        $guard$;
        DROP INDEX customer.payments_one_use_per_coupon;
        ALTER TABLE customer.payments
            DROP CONSTRAINT payments_coupon_with_its_kind,
            DROP CONSTRAINT payments_discount_together,
            DROP CONSTRAINT payments_coupon_fk,
            DROP COLUMN coupon_id,
            DROP COLUMN discount_kind,
            DROP COLUMN discount_percent;
        DROP TABLE customer.coupon_redemptions;
        DROP TRIGGER coupons_guard ON customer.coupons;
        DROP TABLE customer.coupons;
        DROP FUNCTION customer.coupons_guard();
    """)
