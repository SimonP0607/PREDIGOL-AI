"""the match as it is being played: score, minute and status over time

core.fixtures holds a status and core.fixture_results a FINAL score; neither
says what the score was in the 63rd minute, and the fixture row kept saying
'NS' for matches two halves in, because only the six-hourly results sync moved
it. The Live page and the Match Center need the match state AS IT HAPPENED.

market.live_fixture_states already holds a minute and a score, but it is a
by-product of /odds/live and exists only for fixtures the provider prices in
play - a third of what we track on a Saturday. This table is fed by the
fixture feed itself (/fixtures?ids=, which also carries events, statistics and
line-ups), so every tracked match in play has a state whether or not anyone
quotes it. The two sources stay separate on purpose: they disagree sometimes,
and which one said what must stay visible.

Append-only, one row per CHANGE (status, minute, added time or score), keyed
on the instant the payload was fetched.

Revision ID: 0041
Revises: 0040
"""

from __future__ import annotations

from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE core.fixture_live_states (
            fixture_id     bigint      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            observed_at    timestamptz NOT NULL,
            status_short   text        NOT NULL,
            elapsed        smallint,
            extra          smallint,
            goals_home     smallint,
            goals_away     smallint,
            payload_hash   text        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            PRIMARY KEY (fixture_id, observed_at),
            CONSTRAINT live_state_minute_is_possible CHECK (elapsed IS NULL OR elapsed BETWEEN 0 AND 200),
            CONSTRAINT live_state_goals_are_possible CHECK (
                (goals_home IS NULL OR goals_home >= 0) AND (goals_away IS NULL OR goals_away >= 0))
        );
        CREATE INDEX fixture_live_states_observed_idx ON core.fixture_live_states (observed_at DESC);
        COMMENT ON TABLE core.fixture_live_states IS
            'Match state from the fixture feed (/fixtures?ids=), one row per change. '
            'Not the odds feed: see market.live_fixture_states for that.';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE core.fixture_live_states")
