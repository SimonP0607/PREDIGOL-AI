"""Each customer's state of the day, with its reasons (plan UX, B11 and section 23)

WHY THIS EXISTS
---------------
Without states nobody knows in time who is cooling off. U8 built the membership and U6 the daily activity; this keeps, once a
day and for every reader, where they stand - invited, activated, habitual, at risk, about to expire, renewed or expired - and
WHY, in codes a person can read ("no activity for 7 days", "the last survey was 2", "a ticket waiting for 72 hours"). The
support, the owner's morning list, the console's columns and the metrics read it. It is never used for campaigns: the only
automatic messages to readers stay the membership's four notices and the security ones.

WHAT CHANGES
------------
- ``customer.lifecycle_snapshots``: one row per reader and Bogota day (``state``, ``reasons``), append-only (the table's own
  trigger refuses an edit or a delete; the maintenance switch ``fbi.customer_maintenance`` is for the two documented
  deletions: the account's anonymisation and the 24 months' retention). A reason is a short code, never a word the reader
  wrote, an amount or an address.
- ``audit.notifications`` learns the kind ``lifecycle_daily``: the owner's morning count (customers about to expire, at risk and
  invited without activating - counts and a link, never names), drafted by the messenger like the membership's.

Nothing of PrediGol Intelligence reads or writes it (the worker has no access to ``customer``).

Downgrade: drops the table only while it is empty. With the history written, the code goes back (``FBI_LIFECYCLE=0`` stops the
calculation) and the table stays.

Chain: written on 0105 (UX B8); at the integration with the main line it hangs after the IA plan's and the security plan's
migrations like the rest of the UX chain.
"""

from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None

STATES = ("invited", "activated", "habitual", "at_risk", "expiring", "renewed", "expired")
KINDS_BEFORE = ("shadow_pick", "pick_settled", "first_capture", "capture_failed", "worker_down", "run_recovered",
                "job_failing", "ai_budget", "outbox_failing", "membership_due", "ticket_new", "privacy_due",
                "synthetic_failed", "ai_user_budget")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE customer.lifecycle_snapshots (
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            day         DATE        NOT NULL,
            state       TEXT        NOT NULL CHECK (state IN ({_in(STATES)})),
            reasons     TEXT[]      NOT NULL CHECK (cardinality(reasons) BETWEEN 1 AND 8
                                        AND array_to_string(reasons, ',') ~ '^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$'
                                        AND length(array_to_string(reasons, ',')) <= 200),
            computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, day)
        );
        CREATE INDEX lifecycle_snapshots_day ON customer.lifecycle_snapshots (day, state);
        CREATE TRIGGER lifecycle_snapshots_append_only BEFORE UPDATE OR DELETE ON customer.lifecycle_snapshots
            FOR EACH ROW EXECUTE FUNCTION customer.refuse_change();
        COMMENT ON TABLE customer.lifecycle_snapshots IS
          'Where each reader stands on each Bogota day and why (plan UX, B11): invited, activated, habitual, at risk, '
          'expiring, renewed or expired, with reason codes - never a reader''s words. Append-only. For support, the owner '
          'and the metrics: never for campaigns. Kept 24 months; deleted when the account is anonymised (A7).';

        ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({_in((*KINDS_BEFORE, "lifecycle_daily"))}));
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.lifecycle_snapshots) THEN
                RAISE EXCEPTION 'customer.lifecycle_snapshots holds the customers'' history: the code goes back '
                                '(FBI_LIFECYCLE=0), the table stays';
            END IF;
        END
        $guard$;
        DROP TABLE customer.lifecycle_snapshots;
        ALTER TABLE audit.notifications DROP CONSTRAINT IF EXISTS notifications_kind_check;
        ALTER TABLE audit.notifications ADD CONSTRAINT notifications_kind_check
            CHECK (kind IN ({_in(KINDS_BEFORE)})) NOT VALID;
    """)
