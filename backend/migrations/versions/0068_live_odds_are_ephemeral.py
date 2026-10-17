"""in-play odds are the present, not a history: two bounded UNLOGGED tables, and a record of every cleanup

Owner's decision of 6 Oct 2026 (docs/owner/LIVE_ODDS_STORAGE_2026-10-06.md). Measured over 94 complete matches,
the change-only in-play series kept 15,851 rows per match - 4.86 MB in PostgreSQL with its four indexes, plus
1.25 MB of RAW - about 125 GB a year at 133 leagues, ~72 % of all growth. No model, feature, pick, parlay,
backtest, settlement, consensus or CLV reads it: PrediGol publishes pre-match picks only. The live page and the
Match Center show the CURRENT in-play price; nothing shows its history.

So the in-play book is kept as it stands now and nothing else:

* market.live_fixture_current - one row per fixture the provider is pricing in play: minute, score, whether the
  book is stopped or blocked, how much it offers, when the odds feed last saw it.
* market.live_odds_current - one row per (fixture, provider bet, selection, line) quoted right now, with the price
  it replaced and when, at what minute and score, it last changed. A key that stops being quoted is DELETED; a
  fixture that leaves the live book is purged (``fbi.odds.live_repository.STALE_AFTER``). Bounded by what is in
  play at one instant: tens of thousands of rows at the busiest moment, zero when nothing is played.

Both are UNLOGGED: no WAL for ~1,500 row changes every 30 s (and nothing of it in a PITR archive), and after a
crash PostgreSQL empties them - which is right, because the next tick refills them from /odds/live within 30 s and
the provider keeps no history anyway. payload_hash has no foreign key: the in-play payload is no longer kept in the
RAW store unless it carries evidence of an anomaly (``fbi.odds.live_capture``).

audit.storage_cleanups records every cleanup of stored data: what, how many rows and bytes, the archive and its
checksum, the backup taken before, and whether the archive was read back and verified. Revision 0069 refuses to
drop the in-play history unless its tables are empty or a verified archive with the same row counts is recorded
here.

The pre-match series is not touched: market.odds_snapshots, market.final_prematch_odds, market.near_close_snapshots,
market.market_consensus and market.historical_odds keep every row, timestamp, bookmaker, market and RAW link.

Revision ID: 0068
Revises: 0067
"""

from __future__ import annotations

from alembic import op

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE UNLOGGED TABLE market.live_fixture_current (
    fixture_id          BIGINT      PRIMARY KEY REFERENCES core.fixtures(id) ON DELETE CASCADE,
    first_seen_at       TIMESTAMPTZ NOT NULL,
    captured_at         TIMESTAMPTZ NOT NULL,
    elapsed_minute      SMALLINT    CHECK (elapsed_minute >= 0),
    elapsed_seconds     TEXT,
    score_home          SMALLINT    CHECK (score_home >= 0),
    score_away          SMALLINT    CHECK (score_away >= 0),
    status_long         TEXT,
    is_stopped          BOOLEAN,
    is_blocked          BOOLEAN,
    is_finished         BOOLEAN,
    markets_offered     INTEGER     NOT NULL DEFAULT 0,
    values_offered      INTEGER     NOT NULL DEFAULT 0,
    values_suspended    INTEGER     NOT NULL DEFAULT 0,
    provider_updated_at TIMESTAMPTZ,
    payload_hash        TEXT        NOT NULL,
    CHECK (captured_at >= first_seen_at)
) WITH (fillfactor = 70);

COMMENT ON TABLE market.live_fixture_current IS
  'The fixtures the provider is pricing in play NOW, one row each, as the last /odds/live tick saw them. '
  'Ephemeral (UNLOGGED, purged when the fixture leaves the live book): not a history and not a model input.';
COMMENT ON COLUMN market.live_fixture_current.payload_hash IS
  'The hash of the /odds/live body this state came from. No foreign key: in-play payloads are kept in the RAW '
  'store only when they carry evidence of an anomaly.';

CREATE UNLOGGED TABLE market.live_odds_current (
    fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    provider_bet_id     INTEGER      NOT NULL,
    market_key          TEXT         REFERENCES market.markets(key),
    selection           TEXT         NOT NULL,
    line                NUMERIC(6,2) NOT NULL,
    odds_decimal        NUMERIC(10,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
    is_suspended        BOOLEAN      NOT NULL DEFAULT false,
    is_main_line        BOOLEAN,
    previous_odds       NUMERIC(10,3),
    previous_suspended  BOOLEAN,
    change_kind         TEXT         NOT NULL CHECK (change_kind IN ('offered', 'moved', 'suspended', 'available')),
    changed_at          TIMESTAMPTZ  NOT NULL,
    changed_minute      SMALLINT,
    changed_score_home  SMALLINT,
    changed_score_away  SMALLINT,
    first_seen_at       TIMESTAMPTZ  NOT NULL,
    PRIMARY KEY (fixture_id, provider_bet_id, selection, line),
    CHECK (changed_at >= first_seen_at),
    CHECK ((change_kind = 'offered') = (previous_odds IS NULL AND previous_suspended IS NULL))
) WITH (fillfactor = 70);

COMMENT ON TABLE market.live_odds_current IS
  'The in-play book as it stands NOW: one row per fixture, provider bet, selection and line being quoted, '
  'with the price it replaced. Updated in place (only when the price or its suspension changes), deleted when '
  'the provider stops quoting it, purged with its fixture. Ephemeral (UNLOGGED); never a model, pick or '
  'backtest input. line is 0 when the market has no line, as in market.odds_snapshots.';
COMMENT ON COLUMN market.live_odds_current.change_kind IS
  'What the last change was: offered (first quoted, or quoted again after being withdrawn), moved (the price '
  'changed), suspended or available (the suspension flipped).';

CREATE TABLE audit.storage_cleanups (
    id              BIGSERIAL   PRIMARY KEY,
    kind            TEXT        NOT NULL CHECK (kind IN ('inplay_archive', 'inplay_drop', 'inplay_raw_purge')),
    subject         TEXT        NOT NULL,
    rows            BIGINT      CHECK (rows >= 0),
    bytes           BIGINT      CHECK (bytes >= 0),
    archive_path    TEXT,
    archive_sha256  TEXT,
    backup_label    TEXT,
    verified        BOOLEAN     NOT NULL DEFAULT false,
    details         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    code_version    TEXT        NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE audit.storage_cleanups IS
  'Every cleanup of stored data, with its evidence: what was archived, dropped or purged, how many rows and '
  'bytes, where the archive is and its SHA-256, the backup taken before, and whether the archive was read back '
  'and verified. Append only.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS audit.storage_cleanups;
DROP TABLE IF EXISTS market.live_odds_current;
DROP TABLE IF EXISTS market.live_fixture_current;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
