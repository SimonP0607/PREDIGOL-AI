"""historical odds from a second source, team aliases, and the market baseline

Live snapshots are prices WE observed, at an instant we recorded. Historical
odds from Football-Data.co.uk are prices another source reports, with its own
semantics: 'closing' columns and 'pre-closing' columns collected, per its
notes, on Friday afternoons for weekend games and Tuesday afternoons for
midweek ones - never an exact timestamp. They must not be written into
market.odds_snapshots, where captured_at is part of the identity: that would
mean inventing an instant. They get their own table, labelled with the
source's own words.

Joining two sources needs team names to agree ("Man United" is not
"Manchester United" as a string). core.team_aliases records every accepted
mapping with how it was established; a row is matched to a fixture only when
the date, both teams AND the score agree, so a wrong alias cannot silently
attach odds to the wrong match.

analytics.market_baseline stores the de-vigged probabilities per fixture,
source, price kind and method: the reference every model is judged against.

Revision ID: 0018
Revises: 0017
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE core.team_aliases (
    source      TEXT        NOT NULL,
    alias       TEXT        NOT NULL,
    team_id     BIGINT      NOT NULL REFERENCES core.teams(id),
    method      TEXT        NOT NULL CHECK (method IN ('exact','normalised','fixture_and_score','manual')),
    evidence    INTEGER     NOT NULL DEFAULT 0 CHECK (evidence >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (source, alias)
);
COMMENT ON COLUMN core.team_aliases.evidence IS
  'How many fixtures confirmed the mapping (date, both teams and the score agreeing).';

CREATE TABLE market.historical_odds (
    fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    source              TEXT         NOT NULL,
    bookmaker_code      TEXT         NOT NULL,
    market_key          TEXT         NOT NULL,
    selection           TEXT         NOT NULL,
    line                NUMERIC(6,2) NOT NULL DEFAULT 0,
    price_kind          TEXT         NOT NULL CHECK (price_kind IN ('closing','pre_closing')),
    odds_decimal        NUMERIC(9,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
    source_payload_hash TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
    PRIMARY KEY (fixture_id, source, bookmaker_code, market_key, selection, line, price_kind)
);
CREATE INDEX historical_odds_fixture_idx ON market.historical_odds (fixture_id);
COMMENT ON TABLE market.historical_odds IS
  'Prices reported by another source, with its own semantics and no capture
   instant. Never mixed into market.odds_snapshots, whose rows are prices we
   observed at a recorded time.';
COMMENT ON COLUMN market.historical_odds.price_kind IS
  'closing: the source''s closing columns (e.g. PSCH, AvgCH), as the source
   reports them - not validated by us. pre_closing: collected by the source on
   Friday afternoon (weekend games) or Tuesday afternoon (midweek).';

CREATE TABLE analytics.market_baseline (
    fixture_id      BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    source          TEXT         NOT NULL,
    bookmaker_code  TEXT         NOT NULL,
    price_kind      TEXT         NOT NULL CHECK (price_kind IN ('closing','pre_closing','snapshot')),
    market_key      TEXT         NOT NULL,
    devig_method    TEXT         NOT NULL CHECK (devig_method IN ('proportional','shin','power')),
    p_home          NUMERIC(8,6) NOT NULL CHECK (p_home BETWEEN 0 AND 1),
    p_draw          NUMERIC(8,6) NOT NULL CHECK (p_draw BETWEEN 0 AND 1),
    p_away          NUMERIC(8,6) NOT NULL CHECK (p_away BETWEEN 0 AND 1),
    overround       NUMERIC(7,5) NOT NULL CHECK (overround > 1),
    computed_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (fixture_id, source, bookmaker_code, price_kind, market_key, devig_method),
    CONSTRAINT market_baseline_sums_to_one CHECK (abs(p_home + p_draw + p_away - 1) < 0.0005)
);
COMMENT ON TABLE analytics.market_baseline IS
  'De-vigged market probabilities: the reference every model is compared with.
   One row per fixture, source, bookmaker (or AVG), price kind and method.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS analytics.market_baseline;
DROP TABLE IF EXISTS market.historical_odds;
DROP TABLE IF EXISTS core.team_aliases;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
