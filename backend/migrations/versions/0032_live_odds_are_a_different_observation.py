"""live odds are a different observation, and get a table of their own

WHAT /odds/live ACTUALLY RETURNS, MEASURED 2026-10-01
----------------------------------------------------
One unfiltered call returns every fixture the provider is pricing live. Eight fixtures,
seven competitions, elapsed 12 to 78 minutes. Per fixture: ``fixture``, ``league``,
``teams`` (with live goals), ``status`` (stopped / blocked / finished), ``update`` (the
provider''s own last-change time) and ``odds`` - a flat list of markets, each with values
carrying ``value``, ``odd``, ``handicap``, ``main`` and ``suspended``.

**There is no bookmaker dimension.** Not one of the eight fixtures carried a
``bookmakers`` key. A live price here is the provider''s single aggregated number for a
market, selection and line - which is a different kind of observation from a pre-match
price quoted BY a named book, and the reason this is a separate table rather than more
rows in market.odds_snapshots.

The bet ids differ from pre-match for the same concept, which is the second reason:

    concept             pre-match                live
    1X2                 1  Match Winner          59 Fulltime Result
    Asian Handicap      4                        33
    Over/Under          5  Goals Over/Under      36 Over/Under Line
    Both teams to score 8                        69
    Double Chance       12                       72

Mapping one onto the other by id would silently file live prices under the wrong market.
72 distinct bet types were observed live, of the 266 the in-play catalogue lists; most are
in-play only (Match Corners, Race to the 9th corner, Last Team to Score) and have no
pre-match equivalent at all.

WHY market_key IS NULLABLE HERE
-------------------------------
Pre-match rows must name a market we model. Live rows must not be thrown away for lacking
one: 67 of the 72 observed bet types have no normalised key, and they are exactly the
in-play markets the live intelligence will be built on. The provider bet id is always
recorded, so an unmapped series stays usable and can be normalised later without re-fetching
anything that no longer exists - /odds/live keeps NO history.

Revision ID: 0032
Revises: 0031
"""

from __future__ import annotations

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE market.live_odds_snapshots (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    provider_bet_id     INTEGER     NOT NULL,
    market_key          TEXT        REFERENCES market.markets(key),
    selection           TEXT        NOT NULL,
    line                NUMERIC(6,2) NOT NULL,
    odds_decimal        NUMERIC(10,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
    is_suspended        BOOLEAN     NOT NULL DEFAULT false,
    is_main_line        BOOLEAN,
    elapsed_minute      SMALLINT    CHECK (elapsed_minute >= 0),
    elapsed_seconds     TEXT,
    score_home          SMALLINT    CHECK (score_home >= 0),
    score_away          SMALLINT    CHECK (score_away >= 0),
    status_long         TEXT,
    is_stopped          BOOLEAN,
    is_blocked          BOOLEAN,
    provider_updated_at TIMESTAMPTZ,
    captured_at         TIMESTAMPTZ NOT NULL,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    PRIMARY KEY (fixture_id, provider_bet_id, selection, line, captured_at)
) PARTITION BY RANGE (captured_at);

COMMENT ON TABLE market.live_odds_snapshots IS
  'In-play prices, one row per market/selection/line/instant. No bookmaker column: '
  '/odds/live was measured to return a single aggregated price with no bookmaker '
  'dimension. Append only - a price is never overwritten, so the series is complete.';
COMMENT ON COLUMN market.live_odds_snapshots.market_key IS
  'NULL when the provider bet has no normalised equivalent, which is most of them. The '
  'provider_bet_id is always kept so an unmapped series stays usable: /odds/live holds no '
  'history, so what is not stored now cannot be recovered.';
COMMENT ON COLUMN market.live_odds_snapshots.provider_updated_at IS
  'The provider''s own ``update`` field for the fixture. Two captures sharing it saw the '
  'same state, which is how a real price change is told from a re-read.';
COMMENT ON COLUMN market.live_odds_snapshots.line IS
  '0 when the market has no line, matching market.odds_snapshots, so the two read alike.';

CREATE TABLE market.live_odds_snapshots_default PARTITION OF market.live_odds_snapshots DEFAULT;

CREATE INDEX live_odds_fixture_captured_idx
    ON market.live_odds_snapshots (fixture_id, captured_at DESC);
CREATE INDEX live_odds_market_idx
    ON market.live_odds_snapshots (provider_bet_id, captured_at DESC);
CREATE INDEX live_odds_mapped_idx
    ON market.live_odds_snapshots (market_key, fixture_id, captured_at DESC)
    WHERE market_key IS NOT NULL;

-- Which fixtures were seen in play, and when. One row per fixture per capture run, so the
-- live state is queryable without unpacking prices, and a fixture that was live with no
-- market at all still leaves a trace.
CREATE TABLE market.live_fixture_states (
    fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    captured_at         TIMESTAMPTZ NOT NULL,
    elapsed_minute      SMALLINT,
    elapsed_seconds     TEXT,
    score_home          SMALLINT,
    score_away          SMALLINT,
    status_long         TEXT,
    is_stopped          BOOLEAN,
    is_blocked          BOOLEAN,
    is_finished         BOOLEAN,
    markets_offered     INTEGER     NOT NULL DEFAULT 0,
    values_offered      INTEGER     NOT NULL DEFAULT 0,
    values_suspended    INTEGER     NOT NULL DEFAULT 0,
    provider_updated_at TIMESTAMPTZ,
    payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    PRIMARY KEY (fixture_id, captured_at)
);

COMMENT ON TABLE market.live_fixture_states IS
  'The match state each live capture observed: minute, score, whether the provider had '
  'stopped or blocked the book, and how much it was pricing. Kept apart from the prices '
  'so "what was happening" can be asked without reading every quote.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS market.live_fixture_states;
DROP TABLE IF EXISTS market.live_odds_snapshots;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
