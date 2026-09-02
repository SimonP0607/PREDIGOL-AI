"""partitions, indexes and convenience view for the odds time series

Source of truth: docs/rebuild/schema_v2/010_partitions_and_indexes.sql
The index on market.closing_lines becomes an index on
market.near_close_snapshots (see revision 0004).

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

UPGRADE = """
-- Particion por defecto: recoge cualquier fecha sin particion explicita.
CREATE TABLE market.odds_snapshots_default PARTITION OF market.odds_snapshots DEFAULT;

CREATE INDEX ON market.odds_snapshots USING BRIN (captured_at);
CREATE INDEX ON market.odds_snapshots (fixture_id, market_key, selection, captured_at DESC);
CREATE INDEX ON market.odds_snapshots (minutes_to_ko) WHERE source = 'live';

CREATE INDEX ON market.near_close_snapshots (fixture_id);
CREATE INDEX ON market.market_consensus (fixture_id, as_of DESC);

-- Vista de conveniencia: ultima cuota conocida por seleccion.
CREATE OR REPLACE VIEW market.v_latest_odds AS
SELECT DISTINCT ON (fixture_id, bookmaker_id, market_key, selection, line)
       fixture_id, bookmaker_id, market_key, selection, line,
       odds_decimal, captured_at, minutes_to_ko, source
FROM   market.odds_snapshots
ORDER  BY fixture_id, bookmaker_id, market_key, selection, line, captured_at DESC;

COMMENT ON VIEW market.v_latest_odds IS
  'Conveniencia para la UI. NUNCA usar en backtesting: para eso hay que filtrar
   explicitamente por captured_at <= data_cutoff_ts.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS market.v_latest_odds;
DROP TABLE IF EXISTS market.odds_snapshots_default;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
