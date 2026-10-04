"""player profiles and current squads

The truth audit found 58,663 players in a line-up of the last year and four with a
birth date: core.players was only ever written from match payloads, which name a
player and say nothing else, and /players was never normalised. Squads were not
stored at all.

* core.players gains the rest of the provider's profile (birth place and country,
  photo) and ``profile_fetched_at`` - when the profile itself was last read, which
  the freshness engine needs and ``source_fetched_at`` (the last payload that named
  the player) cannot say.
* core.squad_members: who is in a team's current squad, with shirt number, position
  and age, and when each membership was first and last seen. The current squad is
  the members seen at the team's latest squad read (core.teams.squad_checked_at);
  anyone not seen then has left, and stays on record.
* raw.backfill_tasks accepts two more kinds: ``player_profiles`` (a page of 250 of
  /players/profiles) and ``team_squad`` (/players/squads?team=).

Revision ID: 0049
Revises: 0048
"""

from __future__ import annotations

from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

KINDS_BEFORE = ("fixtures_season", "fixture_details", "standings_season", "injuries_season", "teams_season",
                "players_season", "league_coverage")
KINDS_AFTER = (*KINDS_BEFORE, "player_profiles", "team_squad")


def _kinds(kinds: tuple[str, ...]) -> str:
    return ", ".join(f"'{k}'" for k in kinds)


def upgrade() -> None:
    for col in ("birth_place TEXT", "birth_country TEXT", "photo_url TEXT", "profile_fetched_at TIMESTAMPTZ",
                "profile_payload_hash TEXT"):
        op.execute(f"ALTER TABLE core.players ADD COLUMN IF NOT EXISTS {col}")
    op.execute("COMMENT ON COLUMN core.players.profile_fetched_at IS "
               "'When the provider profile (/players/profiles) was last read for this player. NULL: never.'")
    op.execute("ALTER TABLE core.teams ADD COLUMN IF NOT EXISTS squad_checked_at TIMESTAMPTZ")
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.squad_members (
            team_id            BIGINT NOT NULL REFERENCES core.teams(id),
            provider_player_id INTEGER NOT NULL CHECK (provider_player_id > 0),
            player_name        TEXT,
            shirt_number       SMALLINT,
            position           TEXT,
            age                SMALLINT,
            photo_url          TEXT,
            first_seen_at      TIMESTAMPTZ NOT NULL,
            last_seen_at       TIMESTAMPTZ NOT NULL,
            payload_hash       TEXT NOT NULL,
            PRIMARY KEY (team_id, provider_player_id),
            CHECK (last_seen_at >= first_seen_at)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS squad_members_player ON core.squad_members (provider_player_id)")
    op.execute("ALTER TABLE raw.backfill_tasks DROP CONSTRAINT IF EXISTS backfill_tasks_kind_check")
    op.execute(f"ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_kind_check "
               f"CHECK (kind IN ({_kinds(KINDS_AFTER)}))")


def downgrade() -> None:
    op.execute("DELETE FROM raw.backfill_tasks WHERE kind IN ('player_profiles', 'team_squad')")
    op.execute("ALTER TABLE raw.backfill_tasks DROP CONSTRAINT IF EXISTS backfill_tasks_kind_check")
    op.execute(f"ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_kind_check "
               f"CHECK (kind IN ({_kinds(KINDS_BEFORE)}))")
    op.execute("DROP TABLE IF EXISTS core.squad_members")
    op.execute("ALTER TABLE core.teams DROP COLUMN IF EXISTS squad_checked_at")
    for col in ("profile_payload_hash", "profile_fetched_at", "photo_url", "birth_country", "birth_place"):
        op.execute(f"ALTER TABLE core.players DROP COLUMN IF EXISTS {col}")
