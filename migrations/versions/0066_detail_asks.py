"""detail asks: every post-match /fixtures?ids= re-read, per fixture and stage, so a stage asked is a stage done.

A finished match's detail is read once more after it settles (kick-off + 150 min). The truth audits of 5 Oct 2026
found the provider still revising statistics and line-ups after that read (team statistics 92-102 of 120 sides
agreeing; players identified, line-ups published, passes corrected hours later), so a second, late read follows at
kick-off + 26 h. Whether a stage was read cannot come from the RAW index or the coverage rows: an identical answer
is stored once and keeps its first fetch time, so a re-read that changed nothing would be asked again on every tick.
This table says it was asked.

Revision ID: 0066
Revises: 0065
"""

from __future__ import annotations

from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.detail_asks (
            fixture_id    BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            stage         TEXT        NOT NULL CHECK (stage IN ('settled', 'late')),
            asked_at      TIMESTAMPTZ NOT NULL,
            payload_hash  TEXT        REFERENCES raw.ingestion_payloads(hash),
            run_id        BIGINT      REFERENCES raw.ingestion_runs(id),
            PRIMARY KEY (fixture_id, stage)
        )""")
    op.execute("COMMENT ON TABLE core.detail_asks IS 'Each post-match re-read of a finished match, by stage (settled: "
               "kick-off + 150 min; late: kick-off + 26 h). A stage asked is done even when the answer was identical: "
               "the RAW index stores an identical answer once.'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS core.detail_asks")
