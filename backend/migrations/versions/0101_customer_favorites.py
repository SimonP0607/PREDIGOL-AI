"""A reader's favourite leagues and teams (plan UX, A13)

WHY THIS EXISTS
---------------
A new account lands on Home with the leagues suggested for Colombia (A9) and nothing of its own: the plan's onboarding
(section 20) asks the reader, once, for the leagues and teams they follow - with the country's ones already ticked - and
Home opens on «Hoy en tus ligas». The favourites order and filter what the reader is shown; they never change a pick, a
probability, a state or a price (section 38): those are the same for every reader.

WHAT CHANGES
------------
- ``customer.favorites``: one row per reader and favourite - a league (``core.competitions``) or a team
  (``core.teams``) - with when it was chosen. The limits (10 leagues and 20 teams to start with) live in
  ``fbi.customer.favorites`` and widen without a migration. A favourite whose league or team row disappears goes with it.
  Never a betting profile: no amounts, no bankroll, no appetite for risk - only what the reader follows.

``customer.preferences`` already keeps ``onboarded_at`` and ``hints_seen`` (A5's 0096 laid them down for this phase).

The foreign key to ``auth.users`` is ON DELETE RESTRICT: an account is anonymised, never deleted (A7) - and its favourites
are deleted then, with the rest of what the reader keeps. The worker of PrediGol Intelligence cannot read the table
(db/grants.sql treats ``customer`` as ``auth``); the API's role inserts and deletes (a favourite is chosen or removed, never
edited).

Downgrade: drops the table only while it is empty. With readers' favourites the code goes back and the table stays
(FBI_ONBOARDING=0 and FBI_PERSONALIZATION=0 are the rollback: Home without the welcome, and the common view).
"""

from alembic import op

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(r"""
        CREATE TABLE customer.favorites (
            user_id     BIGINT      NOT NULL REFERENCES auth.users(id) ON DELETE RESTRICT,
            kind        TEXT        NOT NULL CHECK (kind IN ('league', 'team')),
            ref_id      BIGINT      NOT NULL,
            league_id   BIGINT      REFERENCES core.competitions(id) ON DELETE CASCADE,
            team_id     BIGINT      REFERENCES core.teams(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, kind, ref_id),
            CHECK ((kind = 'league') = (league_id IS NOT NULL AND team_id IS NULL AND league_id = ref_id)),
            CHECK ((kind = 'team') = (team_id IS NOT NULL AND league_id IS NULL AND team_id = ref_id))
        );
        COMMENT ON TABLE customer.favorites IS
          'The leagues and teams a reader follows (plan UX, A13): they order and filter what the reader is shown, never a '
          'pick, a probability, a state or a price. The limits live in fbi.customer.favorites. Deleted when the account is '
          'anonymised (A7).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM customer.favorites) THEN
                RAISE EXCEPTION 'customer.favorites holds readers'' favourites: the code goes back, the table stays';
            END IF;
        END $$;
        DROP TABLE customer.favorites;
    """)
