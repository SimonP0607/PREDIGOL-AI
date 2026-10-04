"""a fixture's kick-off changes are kept

Friendlies especially are published with a placeholder time and corrected later, sometimes
only after they were played: a club friendly stood at 12:00 in every fixture payload from 29
September to 1 October and was played at 08:30 on 2 October. The capture plans its windows
from the stored kick-off, so a moved kick-off moves every window, and the coverage report
could only call the resulting miss "missed while the worker was running".

core.fixture_kickoff_changes keeps every change the fixture sync applies (before, after, when
it was observed, from which payload), so a capture miss can be attributed to a moved
kick-off and the planner's history can be read back.

Revision ID: 0051
Revises: 0050
"""

from __future__ import annotations

from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.fixture_kickoff_changes (
            fixture_id     BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            observed_at    TIMESTAMPTZ NOT NULL,
            before_kickoff TIMESTAMPTZ NOT NULL,
            after_kickoff  TIMESTAMPTZ NOT NULL,
            payload_hash   TEXT,
            PRIMARY KEY (fixture_id, observed_at),
            CHECK (before_kickoff <> after_kickoff)
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.fixture_kickoff_changes")
