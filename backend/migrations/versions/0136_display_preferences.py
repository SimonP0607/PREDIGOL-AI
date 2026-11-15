"""How a reader wants PrediGol shown, and a bell per followed team (plan maestro UX/UI 2026, decision 8; BE-039)

WHY THIS EXISTS
---------------
The owner approved five settings in the profile: the clock (24 h or 12 h), how a price is written (decimal, American or
fractional), fewer animations, whether Inicio opens on «Para ti», and a bell per followed team. They are how the page is
drawn and which notices of a team a reader wants - never what is stored, computed or sent as a price (prices stay decimal).

WHAT CHANGES
------------
- ``customer.preferences`` takes four columns, each with the value that leaves everything as it is today:
  ``time_format`` (''24h''), ``odds_format`` (''decimal''), ``reduce_motion`` (false: as the device says) and
  ``home_default`` (NULL: «Para ti» for a reader who follows something, «Todo» otherwise - the rule the owner approved).
- ``customer.favorites`` takes ``notify`` (true): for a followed team, false stops its line-up notices and keeps its matches
  out of the day's summary. It means nothing for the other kinds.

Additive only: constant defaults (no table rewrite), no index, no data touched. A reader without a preferences row keeps the
defaults, as before. Downgrade drops the five columns (the settings go back to the defaults; nothing else depended on them).

Revision ID: 0136
Revises: 0135
"""

from alembic import op

revision = "0136"
down_revision = "0135"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE customer.preferences
            ADD COLUMN time_format   TEXT    NOT NULL DEFAULT '24h' CHECK (time_format IN ('24h', '12h')),
            ADD COLUMN odds_format   TEXT    NOT NULL DEFAULT 'decimal'
                CHECK (odds_format IN ('decimal', 'american', 'fractional')),
            ADD COLUMN reduce_motion BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN home_default  TEXT    CHECK (home_default IN ('mine', 'all'));
        COMMENT ON COLUMN customer.preferences.time_format IS 'How a time is written for this reader: 24h or 12h.';
        COMMENT ON COLUMN customer.preferences.odds_format IS
          'How a price is WRITTEN for this reader. What is stored, computed and sent stays decimal.';
        COMMENT ON COLUMN customer.preferences.reduce_motion IS
          'True: fewer animations whatever the device says. False: as the device says.';
        COMMENT ON COLUMN customer.preferences.home_default IS
          'The view Inicio opens on: mine («Para ti») or all («Todo»). NULL: mine for a reader who follows something.';

        ALTER TABLE customer.favorites ADD COLUMN notify BOOLEAN NOT NULL DEFAULT TRUE;
        COMMENT ON COLUMN customer.favorites.notify IS
          'A followed team''s bell: false stops its line-up notices and keeps its matches out of the day''s summary. '
          'Meaningless for the other kinds.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        ALTER TABLE customer.favorites DROP COLUMN notify;
        ALTER TABLE customer.preferences
            DROP COLUMN home_default, DROP COLUMN reduce_motion, DROP COLUMN odds_format, DROP COLUMN time_format;
    """)
