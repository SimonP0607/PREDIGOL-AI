"""odds asks: every pre-match /odds request, answered or empty, so a window asked is a window done.

The RAW index (raw.ingestion_payloads) keeps one row per DISTINCT answer: an empty answer for the same fixture is
the same bytes every time, so asking again left no trace. The capture planner read "when was this fixture last
asked" from that index and "which windows are done" from the prices stored, so a fixture the provider does not price
was asked again on every 5-minute tick: 25-33 requests a tick, ~8,600 a day, 0 rows written (measured 5 Oct 2026).

Revision ID: 0064
Revises: 0063
"""

from __future__ import annotations

from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.odds_asks (
            provider_fixture_id BIGINT      NOT NULL,
            asked_at            TIMESTAMPTZ NOT NULL,
            minutes_to_ko       INTEGER     NOT NULL,
            window_minutes      INTEGER,
            results             INTEGER     NOT NULL CHECK (results >= 0),
            quotes              INTEGER     NOT NULL DEFAULT 0 CHECK (quotes >= 0),
            payload_hash        TEXT        REFERENCES raw.ingestion_payloads(hash),
            run_id              BIGINT      REFERENCES raw.ingestion_runs(id),
            PRIMARY KEY (provider_fixture_id, asked_at)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS odds_asks_asked_at ON market.odds_asks (asked_at)")
    op.execute("COMMENT ON TABLE market.odds_asks IS 'Every pre-match /odds request of the capture, answered or "
               "empty (results = response entries, quotes = prices parsed). A window asked in its band is done even "
               "when the provider had nothing; the RAW index alone cannot say so, because an identical answer is "
               "stored once.'")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.odds_asks")
