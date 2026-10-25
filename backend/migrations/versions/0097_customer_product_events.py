"""Product analytics: the readers' events of a closed catalog and their daily aggregate (plan UX, A6)

WHY THIS EXISTS
---------------
Without data no one knows whether the product serves, nor when the triggers of block C are met (plan UX, section 39).
A6 records the events of a closed catalog of 35 (fbi/customer/events_catalog.json), each tied to a product decision,
in PostgreSQL - no third party, no session recording, no IP.

WHAT CHANGES
------------
- ``customer.product_events``: one row per event - the reader's pseudonym (an HMAC of the account's id under its own
  key: the table cannot be joined to the accounts without it), the event's name, the catalog's properties (no free
  text) and the moment. Raw events are kept 90 days (the messenger's purge, born dry: the owner says when it deletes).
- ``customer.activity_daily``: per reader's pseudonym and Bogotá day, the number of events and the count per event;
  recomputed from the raw events, kept 13 months.

The owner (SUPER_ADMIN) and the synthetic journey's account are never recorded. The worker cannot read either table
(db/grants.sql, as for all of ``customer``); nothing here reaches a model, the decision layer or the AI's package.

Downgrade: drops both tables only while they are empty.
"""

from alembic import op

revision = "0097"
down_revision = "0096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE customer.product_events (
            id       BIGSERIAL   PRIMARY KEY,
            subject  TEXT        NOT NULL CHECK (subject ~ '^[0-9a-f]{20}$'),
            name     TEXT        NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{2,40}$'),
            props    JSONB       NOT NULL DEFAULT '{}'::jsonb
                     CHECK (jsonb_typeof(props) = 'object' AND length(props::text) <= 600),
            at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX product_events_at ON customer.product_events (at);
        CREATE INDEX product_events_subject ON customer.product_events (subject, at);
        COMMENT ON TABLE customer.product_events IS
          'A reader''s product events of the closed catalog (fbi/customer/events_catalog.json): a pseudonym, never an '
          'account id, an address, an IP or free text. Raw rows are kept 90 days (the messenger''s purge).';

        CREATE TABLE customer.activity_daily (
            day       DATE        NOT NULL,
            subject   TEXT        NOT NULL CHECK (subject ~ '^[0-9a-f]{20}$'),
            events    INTEGER     NOT NULL CHECK (events > 0),
            counts    JSONB       NOT NULL CHECK (jsonb_typeof(counts) = 'object'),
            first_at  TIMESTAMPTZ NOT NULL,
            last_at   TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (day, subject),
            CHECK (last_at >= first_at)
        );
        CREATE INDEX activity_daily_subject ON customer.activity_daily (subject, day);
        COMMENT ON TABLE customer.activity_daily IS
          'Per pseudonym and Bogota day: the events and their count by name, recomputed from the raw events (it always '
          'equals them for the days they still hold). Kept 13 months.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $guard$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.product_events) OR EXISTS (SELECT 1 FROM customer.activity_daily) THEN
                RAISE EXCEPTION 'customer.product_events or customer.activity_daily hold rows: the code goes back, the '
                                'tables stay (deleting them is the owner''s decision)';
            END IF;
        END
        $guard$;
        DROP TABLE customer.activity_daily;
        DROP TABLE customer.product_events;
    """)
