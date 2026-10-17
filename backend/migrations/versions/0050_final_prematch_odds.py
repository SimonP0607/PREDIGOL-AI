"""final pre-match odds, read after kick-off

The bookmaker coverage report found 182 of 675 played matches priced: the worker did not
run on 26-28 September and 2 October (the machine was off), and a pre-match window that
passes unobserved is gone for the capture. The provider, however, keeps pre-match odds for
7 days (measured 4 Oct 2026: a match 5 days old answered with 9 bookmakers, stamped 30
minutes before kick-off; one 8 days old answered with nothing).

* market.final_prematch_odds: the provider's LAST pre-match price per bookmaker, market,
  selection and line, read after the match. ``provider_update_at`` is the provider's own
  ``update`` stamp and must precede kick-off (checked before a row is written); a stamp at or after
  kick-off could be an in-play price and is refused before it gets here. This is not a
  capture: it did not exist for us before kick-off, so no pick may ever read it. It is the
  near-closing line the platform has lacked since Pinnacle's public API closed (CLV of
  picks, the market benchmark in research, coverage).
* market.final_prematch_checks: one row per fixture asked, with the outcome, so a match is
  asked once and "asked after the match, the provider had nothing" is a stored fact.

Revision ID: 0050
Revises: 0049
"""

from __future__ import annotations

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.final_prematch_odds (
            fixture_id         BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            bookmaker_id       INTEGER      NOT NULL REFERENCES market.bookmakers(id),
            market_key         TEXT         NOT NULL REFERENCES market.markets(key),
            selection          TEXT         NOT NULL,
            line               NUMERIC(6,2) NOT NULL DEFAULT 0,
            odds_decimal       NUMERIC(9,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
            provider_update_at TIMESTAMPTZ  NOT NULL,
            minutes_to_ko      INTEGER      NOT NULL CHECK (minutes_to_ko >= 0),
            fetched_at         TIMESTAMPTZ  NOT NULL,
            payload_hash       TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
            PRIMARY KEY (fixture_id, bookmaker_id, market_key, selection, line),
            CHECK (fetched_at > provider_update_at)
        )""")
    op.execute("""
        COMMENT ON TABLE market.final_prematch_odds IS
          'The provider''s last pre-match price, read after kick-off (it keeps pre-match odds 7 days).
           provider_update_at is the provider''s own stamp and precedes kick-off. Not a capture: no
           pick may read it. Uses: closing-line benchmark (CLV), coverage, research.'""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS market.final_prematch_checks (
            fixture_id         BIGINT      PRIMARY KEY REFERENCES core.fixtures(id) ON DELETE CASCADE,
            checked_at         TIMESTAMPTZ NOT NULL,
            outcome            TEXT        NOT NULL CHECK (outcome IN ('priced', 'empty', 'after_kickoff')),
            provider_update_at TIMESTAMPTZ,
            bookmakers         SMALLINT    NOT NULL DEFAULT 0 CHECK (bookmakers >= 0),
            quotes             INTEGER     NOT NULL DEFAULT 0 CHECK (quotes >= 0),
            payload_hash       TEXT        REFERENCES raw.ingestion_payloads(hash),
            CHECK ((outcome = 'priced') = (quotes > 0))
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.final_prematch_checks")
    op.execute("DROP TABLE IF EXISTS market.final_prematch_odds")
