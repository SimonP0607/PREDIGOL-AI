"""A reader can also follow players and markets (plan de cierre UX, 3.1)

WHY THIS EXISTS
---------------
A reader follows leagues and teams since A13. The closing plan (3.1) adds what a reader asks for next: the players they
care about (seen in a line-up or searched by name) and the markets they read most (followed from the Mercados tab). They
order and filter what the reader is shown - «Para ti» in Home, 3.2 - and never change a pick, a probability, a state or a
price: those are the same for every reader.

WHAT CHANGES
------------
- ``customer.favorites`` takes two new kinds, ``player`` (a row of ``core.players``) and ``market`` (a key of
  ``market.markets``), with two new columns for them (``player_id``, ``market_key``). The league and team rows are untouched.
- ``ref_id`` stays the id of a league, team or player and is NULL for a market (a market has a text key, not a number).
  The primary key (``user_id, kind, ref_id``) cannot hold a NULL, so it is replaced by a unique index over the same three
  things with the market key standing for a missing id: still one row per reader and favourite.
- One CHECK says what each kind carries - its own column and no other, and ``ref_id`` equal to it - so a row never points
  at two things. The kind CHECK and the two older table CHECKs are dropped by what they say, not by a name they never had.
- The limits (20 players and 5 markets to start with) live in ``fbi.customer.favorites`` and widen without a migration. A
  player or market row that disappears takes the favourite with it.

Never a betting profile: no amounts, no bankroll, no appetite for risk - the markets are only the ones the reader reads.

Nothing else changes: the API's role already inserts and deletes on the table (db/grants.sql), the worker of PrediGol
Intelligence still cannot read it, and an account's anonymisation (A7) deletes by ``user_id``, whatever the kind.

On a live database the table is altered under ``lock_timeout = '10s'`` (the rule of 0111, 0112, 0115, 0119 and 0120): a
wait longer than that for its lock fails the revision whole. It holds readers' favourites, a few rows each.

Downgrade: only while no reader follows a player or a market. With them the code goes back and the columns stay (the
older code reads leagues and teams alone and ignores the rest).
"""

from alembic import op

revision = "0122"
down_revision = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DO $$
        DECLARE c record;
        BEGIN
            FOR c IN SELECT conname FROM pg_constraint
                      WHERE conrelid = 'customer.favorites'::regclass AND contype IN ('c', 'p')
            LOOP
                EXECUTE format('ALTER TABLE customer.favorites DROP CONSTRAINT %I', c.conname);
            END LOOP;
        END $$;

        ALTER TABLE customer.favorites
            ALTER COLUMN ref_id DROP NOT NULL,
            ADD COLUMN player_id  BIGINT REFERENCES core.players(id)    ON DELETE CASCADE,
            ADD COLUMN market_key TEXT   REFERENCES market.markets(key) ON DELETE CASCADE;

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

        CREATE UNIQUE INDEX favorites_one_per_reader
            ON customer.favorites (user_id, kind, COALESCE(ref_id::text, market_key));

        COMMENT ON TABLE customer.favorites IS
          'What a reader follows (plan UX, A13 and 3.1): leagues, teams, players and markets. They order and filter what '
          'the reader is shown, never a pick, a probability, a state or a price. The limits live in '
          'fbi.customer.favorites. Deleted when the account is anonymised (A7).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.favorites WHERE kind IN ('player', 'market')) THEN
                RAISE EXCEPTION 'customer.favorites holds readers'' players or markets: the code goes back, the columns stay';
            END IF;
        END $$;

        DROP INDEX customer.favorites_one_per_reader;
        ALTER TABLE customer.favorites DROP CONSTRAINT favorites_kind_shape;
        ALTER TABLE customer.favorites
            DROP COLUMN player_id,
            DROP COLUMN market_key,
            ALTER COLUMN ref_id SET NOT NULL,
            ADD PRIMARY KEY (user_id, kind, ref_id),
            ADD CONSTRAINT favorites_kind_check CHECK (kind IN ('league', 'team')),
            ADD CONSTRAINT favorites_league_shape CHECK
                ((kind = 'league') = (league_id IS NOT NULL AND team_id IS NULL AND league_id = ref_id)),
            ADD CONSTRAINT favorites_team_shape CHECK
                ((kind = 'team') = (team_id IS NOT NULL AND league_id IS NULL AND team_id = ref_id));

        COMMENT ON TABLE customer.favorites IS
          'The leagues and teams a reader follows (plan UX, A13): they order and filter what the reader is shown, never a '
          'pick, a probability, a state or a price. The limits live in fbi.customer.favorites. Deleted when the account is '
          'anonymised (A7).';
    """)
