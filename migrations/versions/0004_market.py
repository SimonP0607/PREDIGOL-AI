"""market layer: the odds time series

Source of truth: docs/rebuild/schema_v2/004_market.sql

DELIBERATE, DOCUMENTED DEVIATION FROM THE SOURCE DDL
----------------------------------------------------
The source file named the materialised pre-kickoff price table
``market.closing_lines``. That name asserts an empirical claim the project has
never validated: that the last snapshot we captured IS the closing line. It is
not - it is the last snapshot we happened to take, at whatever distance from
kickoff our cadence allowed.

The table is therefore named ``market.near_close_snapshots``, and the claim is
made structurally unprovable-by-accident:

  * ``minutes_to_ko`` records how close to kickoff the snapshot actually is.
  * ``is_validated_close`` defaults to false.
  * ``CHECK (NOT is_validated_close OR close_validation_method IS NOT NULL)``
    makes it impossible to assert "this is the closing line" without recording
    HOW that was established.

No other semantics are changed. Column types, constraints, keys and behaviour
are identical to the validated DDL.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE market.bookmakers (
    id                     SERIAL PRIMARY KEY,
    provider_bookmaker_id  INTEGER NOT NULL UNIQUE,
    name                   TEXT    NOT NULL,
    is_sharp               BOOLEAN NOT NULL DEFAULT false,
    consensus_weight       NUMERIC(4,2) NOT NULL DEFAULT 1.00,
    is_active              BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON COLUMN market.bookmakers.consensus_weight IS
  'Peso en el consenso de mercado. Las casas sharp pesan mas que las blandas.';

CREATE TABLE market.markets (
    key            TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    n_outcomes     SMALLINT NOT NULL,
    has_line       BOOLEAN NOT NULL DEFAULT false,
    is_exclusive   BOOLEAN NOT NULL DEFAULT true,
    provider_bet_id INTEGER,
    is_tracked     BOOLEAN NOT NULL DEFAULT true
);
COMMENT ON COLUMN market.markets.is_exclusive IS
  'false para Doble Oportunidad: sus selecciones NO son mutuamente excluyentes.';

-- La tabla central del sistema.
CREATE TABLE market.odds_snapshots (
    fixture_id     BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    bookmaker_id   INTEGER      NOT NULL REFERENCES market.bookmakers(id),
    market_key     TEXT         NOT NULL REFERENCES market.markets(key),
    selection      TEXT         NOT NULL,
    line           NUMERIC(6,2) NOT NULL DEFAULT 0,
    odds_decimal   NUMERIC(9,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
    captured_at    TIMESTAMPTZ  NOT NULL,
    minutes_to_ko  INTEGER      NOT NULL,
    source         TEXT         NOT NULL CHECK (source IN ('prematch','live')),
    payload_hash   TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
    PRIMARY KEY (fixture_id, bookmaker_id, market_key, selection, line, captured_at)
) PARTITION BY RANGE (captured_at);
COMMENT ON TABLE market.odds_snapshots IS
  'Serie temporal. captured_at forma parte de la PK: una cuota NUNCA se sobrescribe.';
COMMENT ON COLUMN market.odds_snapshots.line IS
  '0 para mercados sin linea (1X2, BTTS). NOT NULL para que la PK sea fiable.';

-- Ultimo snapshot conocido antes del saque inicial, materializado.
-- NO se llama "closing line": ver la nota de cabecera de esta revision.
CREATE TABLE market.near_close_snapshots (
    fixture_id     BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    bookmaker_id   INTEGER      NOT NULL REFERENCES market.bookmakers(id),
    market_key     TEXT         NOT NULL REFERENCES market.markets(key),
    selection      TEXT         NOT NULL,
    line           NUMERIC(6,2) NOT NULL DEFAULT 0,
    odds_decimal   NUMERIC(9,3) NOT NULL,
    captured_at    TIMESTAMPTZ  NOT NULL,
    minutes_to_ko  INTEGER      NOT NULL CHECK (minutes_to_ko >= 0),
    source         TEXT         NOT NULL CHECK (source IN ('prematch','live')),
    is_validated_close      BOOLEAN NOT NULL DEFAULT false,
    close_validation_method TEXT,
    PRIMARY KEY (fixture_id, bookmaker_id, market_key, selection, line),
    CHECK (NOT is_validated_close OR close_validation_method IS NOT NULL)
);
COMMENT ON TABLE market.near_close_snapshots IS
  'El ultimo snapshot que CONSEGUIMOS capturar antes del saque inicial. NO es,
   por defecto, la linea de cierre: es el snapshot mas proximo al cierre que
   nuestra cadencia permitio. Se puebla desde /odds/live cuando esta disponible
   y, en su defecto, desde el ultimo /odds prematch.';
COMMENT ON COLUMN market.near_close_snapshots.minutes_to_ko IS
  'Distancia real al saque inicial. Es la medida honesta de cuanto se parece
   este snapshot a un cierre. Valores altos = el "cierre" es una ficcion.';
COMMENT ON COLUMN market.near_close_snapshots.is_validated_close IS
  'Solo true cuando se ha demostrado empiricamente que este snapshot coincide
   con la linea de cierre real. Requiere close_validation_method por CHECK.';

-- Consenso desvigado por metodo. Se recalcula, no es fuente de verdad.
CREATE TABLE market.market_consensus (
    fixture_id     BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    market_key     TEXT         NOT NULL REFERENCES market.markets(key),
    selection      TEXT         NOT NULL,
    line           NUMERIC(6,2) NOT NULL DEFAULT 0,
    as_of          TIMESTAMPTZ  NOT NULL,
    devig_method   TEXT         NOT NULL CHECK (devig_method IN
                   ('proportional','shin','power','logarithmic')),
    p_fair         NUMERIC(8,6) NOT NULL CHECK (p_fair BETWEEN 0 AND 1),
    n_bookmakers   SMALLINT     NOT NULL CHECK (n_bookmakers >= 1),
    overround      NUMERIC(7,5) NOT NULL,
    best_odds      NUMERIC(9,3) NOT NULL,
    best_bookmaker_id INTEGER   NOT NULL REFERENCES market.bookmakers(id),
    dispersion     NUMERIC(8,6),
    PRIMARY KEY (fixture_id, market_key, selection, line, as_of, devig_method)
);
"""

DOWNGRADE = """
DROP TABLE IF EXISTS market.market_consensus;
DROP TABLE IF EXISTS market.near_close_snapshots;
DROP TABLE IF EXISTS market.odds_snapshots;
DROP TABLE IF EXISTS market.markets;
DROP TABLE IF EXISTS market.bookmakers;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
