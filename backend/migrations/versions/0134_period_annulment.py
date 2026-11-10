"""A period the owner annuls (UX-090): a new kind of membership event, nothing else.

An approval of a payment request that was a mistake (the payment never arrived, the amount was another) cannot be
undone by editing or deleting - periods and payments are append-only, tax records. It is undone by a fact that is
added: the event ``period_annulled`` (with the period, the reason and the actor). A period with that event stops
counting for the membership's state; the period, its payment and the event stay forever.

Revision ID: 0134
Revises: 0133

Downgrade: only while no period was annulled; otherwise the code goes back and the schema stays.
"""

from alembic import op

revision = "0134"
down_revision = "0133"
branch_labels = None
depends_on = None

EVENTS_BEFORE = (
    "trial_planned", "trial_started", "payment_recorded", "courtesy_granted", "suspended", "suspension_lifted",
    "will_not_renew", "will_renew", "notice", "payment_requested", "payment_request_approved",
    "payment_request_rejected", "payment_request_cancelled",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        ALTER TABLE customer.membership_events DROP CONSTRAINT membership_events_kind_check;
        ALTER TABLE customer.membership_events ADD CONSTRAINT membership_events_kind_check
            CHECK (kind IN ({_in((*EVENTS_BEFORE, "period_annulled"))}));
        ALTER TABLE customer.membership_events ADD CONSTRAINT membership_events_annulment_check
            CHECK (kind <> 'period_annulled' OR (reason IS NOT NULL AND period_id IS NOT NULL));
        CREATE UNIQUE INDEX membership_events_one_annulment ON customer.membership_events (period_id)
            WHERE kind = 'period_annulled';

        CREATE VIEW customer.live_membership_periods AS
            SELECT p.* FROM customer.membership_periods p
             WHERE NOT EXISTS (SELECT 1 FROM customer.membership_events e
                                WHERE e.kind = 'period_annulled' AND e.period_id = p.id);
        COMMENT ON VIEW customer.live_membership_periods IS
          'The periods that count: every one except those with a period_annulled event. The membership''s state and '
          'its notices read this; the history and the export read the table.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.membership_events WHERE kind = 'period_annulled') THEN
                RAISE EXCEPTION 'periods were annulled: the code goes back, the schema stays';
            END IF;
        END
        $guard$;
        DROP VIEW customer.live_membership_periods;
        DROP INDEX customer.membership_events_one_annulment;
        ALTER TABLE customer.membership_events DROP CONSTRAINT membership_events_annulment_check;
        ALTER TABLE customer.membership_events DROP CONSTRAINT membership_events_kind_check;
        ALTER TABLE customer.membership_events ADD CONSTRAINT membership_events_kind_check
            CHECK (kind IN ({_in(EVENTS_BEFORE)}));
    """)
