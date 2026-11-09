"""A reader can follow any market of the catalogue, not only the five classic ones (plan CUOTAS, phase 6; BE-025)

WHY THIS EXISTS
---------------
Since 3.1 a reader follows up to five markets - 1X2, over/under, both teams to score, handicap and double chance - the keys
of ``market.markets``. The catalogue of a match («Mercados») prices many more: corners, cards, shots, the halves. A reader
who reads corners every week had nothing to follow. This revision lets a reader follow a market of the catalogue by the
key the catalogue itself gives it (``corners_over_under.FT.match``: code, period, subject).

WHAT CHANGES
------------
- ``customer.favorites`` takes a new kind, ``catalog``, with its own column ``catalog_key`` (text, no foreign key: the
  catalogue's keys are computed from the taxonomy, they are not rows of ``market.markets``). The classic ``market`` rows and
  their column are untouched: the five keep working exactly as before, and the older code ignores the new kind.
- The shape CHECK (``favorites_kind_shape``) says what each kind carries - its own column and no other. It is replaced by
  the same CHECK plus the new kind.
- The unique index over one row per reader and favourite also counts ``catalog_key`` (a ``catalog`` row has no ``ref_id`` and
  no ``market_key``).
- The limit (10 catalogue markets to start with) lives in ``fbi.customer.favorites`` and widens without a migration. What
  keys are valid is decided by the code against the taxonomy, so a market the taxonomy later drops does not need a migration.

Never a betting profile: a market is followed for its name, never for what the reader stakes on it. Following orders what
the reader sees; it never changes a pick, a probability, a state or a price.

On a live database the table is altered under ``lock_timeout = '10s'`` (the rule of 0111, 0112, 0115, 0119, 0120 and 0122):
a wait longer than that for its lock fails the revision whole. It holds readers' favourites, a few rows each.

Downgrade: only while no reader follows a catalogue market. With them the code goes back and the column stays (the older code
reads the other kinds and ignores this one).
"""

from alembic import op

revision = "0132"
down_revision = "0131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        ALTER TABLE customer.favorites ADD COLUMN catalog_key TEXT;

        ALTER TABLE customer.favorites DROP CONSTRAINT favorites_kind_shape;
        ALTER TABLE customer.favorites ADD CONSTRAINT favorites_kind_shape CHECK (
            (kind = 'league' AND league_id IS NOT NULL AND team_id IS NULL AND player_id IS NULL
                AND market_key IS NULL AND catalog_key IS NULL AND ref_id = league_id)
         OR (kind = 'team' AND team_id IS NOT NULL AND league_id IS NULL AND player_id IS NULL
                AND market_key IS NULL AND catalog_key IS NULL AND ref_id = team_id)
         OR (kind = 'player' AND player_id IS NOT NULL AND league_id IS NULL AND team_id IS NULL
                AND market_key IS NULL AND catalog_key IS NULL AND ref_id = player_id)
         OR (kind = 'market' AND market_key IS NOT NULL AND league_id IS NULL AND team_id IS NULL
                AND player_id IS NULL AND catalog_key IS NULL AND ref_id IS NULL)
         OR (kind = 'catalog' AND catalog_key IS NOT NULL AND length(catalog_key) BETWEEN 3 AND 80
                AND league_id IS NULL AND team_id IS NULL AND player_id IS NULL AND market_key IS NULL
                AND ref_id IS NULL)
        );

        DROP INDEX customer.favorites_one_per_reader;
        CREATE UNIQUE INDEX favorites_one_per_reader
            ON customer.favorites (user_id, kind, COALESCE(ref_id::text, market_key, catalog_key));

        COMMENT ON TABLE customer.favorites IS
          'What a reader follows (plan UX, A13, 3.1 and CUOTAS BE-025): leagues, teams, players, the five classic markets '
          'and markets of the catalogue. They order and filter what the reader is shown, never a pick, a probability, a '
          'state or a price. The limits live in fbi.customer.favorites. Deleted when the account is anonymised (A7).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.favorites WHERE kind = 'catalog') THEN
                RAISE EXCEPTION 'customer.favorites holds readers'' catalogue markets: the code goes back, the column stays';
            END IF;
        END $$;

        DROP INDEX customer.favorites_one_per_reader;
        CREATE UNIQUE INDEX favorites_one_per_reader
            ON customer.favorites (user_id, kind, COALESCE(ref_id::text, market_key));

        ALTER TABLE customer.favorites DROP CONSTRAINT favorites_kind_shape;
        ALTER TABLE customer.favorites ADD CONSTRAINT favorites_kind_shape CHECK (
            (kind = 'league' AND league_id IS NOT NULL AND team_id IS NULL AND player_id IS NULL
                AND market_key IS NULL AND ref_id = league_id)
         OR (kind = 'team' AND team_id IS NOT NULL AND league_id IS NULL AND player_id IS NULL
                AND market_key IS NULL AND ref_id = team_id)
         OR (kind = 'player' AND player_id IS NOT NULL AND league_id IS NULL AND team_id IS NULL
                AND market_key IS NULL AND ref_id = player_id)
         OR (kind = 'market' AND market_key IS NOT NULL AND league_id IS NULL AND team_id IS NULL
                AND player_id IS NULL AND ref_id IS NULL)
        );
        ALTER TABLE customer.favorites DROP COLUMN catalog_key;

        COMMENT ON TABLE customer.favorites IS
          'What a reader follows (plan UX, A13 and 3.1): leagues, teams, players and markets. They order and filter what '
          'the reader is shown, never a pick, a probability, a state or a price. The limits live in '
          'fbi.customer.favorites. Deleted when the account is anonymised (A7).';
    """)
