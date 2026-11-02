"""An index on the squad sheets by player, built without blocking the writers (plan F3)

``core.fixture_lineup_players`` is keyed by match first: (fixture_id, team_side, source, provider_player_id). Everything about a match
reads it through that key; nothing could read it by PLAYER, so "in which matches was he in the squad" meant a scan of the table. The
history of a player's clubs (``fbi.people.player_history``) reads the matches of a batch of players, and the national-team record in
the dossier reads one man's, so the table gets the index it was missing.

It is built CONCURRENTLY: the worker writes squad sheets all day, and a plain ``CREATE INDEX`` would hold every one of those writes
for as long as the build takes (minutes on the production table). That statement cannot run inside a transaction, so the revision
leaves alembic's for the build and comes back (``autocommit_block``). A build that was interrupted leaves an INVALID index of the same
name; the revision drops it first, so running it again is safe.

Revision ID: 0085
Revises: 0084
"""

from __future__ import annotations

from alembic import op

revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None

INDEX = "fixture_lineup_players_player"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '10s'")
        # an index left INVALID by a build that was interrupted is not used and blocks the name
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
                             JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = 'core' AND c.relname = '{INDEX}' AND NOT i.indisvalid) THEN
                    DROP INDEX core.{INDEX};
                END IF;
            END $$""")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON core.fixture_lineup_players (provider_player_id, fixture_id)")
        op.execute("RESET lock_timeout")
    op.execute(f"COMMENT ON INDEX core.{INDEX} IS "
               "'The matches of a player (plan F3): the table is keyed by match, this reads it by player. Built concurrently (0085).'")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS core.{INDEX}")
