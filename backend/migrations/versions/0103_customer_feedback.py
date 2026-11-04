"""What readers think of PrediGol: the monthly survey and «¿Te sirvió?» (plan UX, B6 and section 40)

WHY THIS EXISTS
---------------
With few readers, one question a month and a «¿Te sirvió?» in the right place say more than any panel: whether PrediGol
is useful to them, and which reading, narrative or explanation helped. Until now there was no channel for an opinion.
The opinion improves the product and never enters the models: nothing of PrediGol Intelligence reads this table (the
worker cannot: db/grants.sql treats ``customer`` as ``auth``).

WHAT CHANGES
------------
- ``customer.feedback``: one row per answer, of three kinds:
    ``csat``          the monthly survey answered - «¿Qué tan útil te resultó PrediGol este mes?», 1 to 5 - with, if the
                      reader wrote one, the answer to «¿Qué faltó?» (1-3) or «¿Qué fue lo más útil?» (4-5);
    ``csat_skipped``  the survey closed without an answer: it does not come back for 30 days either;
    ``helpful``       «¿Te sirvió?» yes or no on a reading, a narrative, an explanation or an «Explícame» answer - one
                      row per reader and thing read; changing the answer updates it.
  Every row keeps where it was asked (``context``: the trigger and the page, never a form's content) and when. The rule
  of the survey - once every 30 days, never after an error - lives in ``fbi.customer.feedback`` and the page; the
  checks here keep each kind's fields coherent and a comment bounded. Never an amount, a bankroll or a contact detail:
  the comment does not ask for personal data, and the service removes an address or a number that looks like a phone
  or a document before storing it.

The foreign key to ``auth.users`` is ON DELETE RESTRICT: an account is anonymised, never deleted (A7) - and its feedback
is deleted then, with the rest of what the reader keeps. Retention: 24 months (the messenger deletes older rows once
the owner switches the purge on, FBI_EVENTS_PURGE, like the product analytics of A6).

Downgrade: drops the table only while it is empty. With readers' answers the code goes back and the table stays
(FBI_FEEDBACK=0 is the rollback: no survey, no vote; the answers stay).
"""

from alembic import op

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE customer.feedback (
            id          BIGSERIAL   PRIMARY KEY,
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind        TEXT        NOT NULL CHECK (kind IN ('csat', 'csat_skipped', 'helpful')),
            score       SMALLINT    CHECK (score BETWEEN 1 AND 5),
            comment     TEXT        CHECK (comment IS NULL OR char_length(comment) BETWEEN 1 AND 1000),
            subject     TEXT        CHECK (subject IN ('reading', 'narrative', 'explanation', 'explain')),
            subject_id  BIGINT      CHECK (subject_id > 0),
            helpful     BOOLEAN,
            context     JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(context) = 'object'),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CHECK ((kind = 'csat') = (score IS NOT NULL)),
            CHECK (kind = 'csat' OR comment IS NULL),
            CHECK ((kind = 'helpful') = (subject IS NOT NULL AND subject_id IS NOT NULL AND helpful IS NOT NULL))
        );
        -- one «¿Te sirvió?» per reader and thing read: a new answer replaces the previous one
        CREATE UNIQUE INDEX feedback_helpful_once ON customer.feedback (user_id, subject, subject_id) WHERE kind = 'helpful';
        -- the survey's rule reads a reader's last answer or skip
        CREATE INDEX feedback_survey_by_reader ON customer.feedback (user_id, created_at DESC)
            WHERE kind IN ('csat', 'csat_skipped');
        -- the owner's view and the retention read by date
        CREATE INDEX feedback_by_date ON customer.feedback (created_at);
        COMMENT ON TABLE customer.feedback IS
          'What readers think of PrediGol (plan UX, B6): the monthly survey (csat, 1-5, with an optional comment; '
          'csat_skipped when closed) and «¿Te sirvió?» (helpful, one per reader and thing read). Never read by PrediGol '
          'Intelligence. Deleted when the account is anonymised (A7); kept 24 months.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.feedback) THEN
                RAISE EXCEPTION 'customer.feedback holds readers'' answers: the code goes back, the table stays';
            END IF;
        END $$;
        DROP TABLE customer.feedback;
    """)
