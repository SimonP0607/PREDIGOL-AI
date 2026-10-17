"""market catalog: what the provider offers vs what our models may use

WHY THIS EXISTS
---------------
``market.markets`` was doing two jobs at once and therefore neither well. It
held the five keys our own schema references (picks, predictions, consensus all
FK to it) and was seeded from a four-entry Python enum. The consequence was
measured, not theoretical: API-Football returns 338 pre-match bet types, our
normalizer already mapped bet 4 to ``AH``, and every Asian-Handicap price we
captured was silently dropped at ``OddsRepository.write_snapshots`` because no
row with key ``AH`` existed. The provider had answered; we threw the answer away
and counted it as "unknown market".

This revision separates the two concerns:

``market.provider_markets``  every bet type the provider is known to offer, per
                             scope, whether or not we model it. Pre-match and
                             in-play bet ids are DIFFERENT namespaces in
                             API-Football (bet 4 is not the same bet in both),
                             so ``scope`` is part of the primary key. A row may
                             map to one of our markets, or to none - "known but
                             not modelled" is the normal case, and recording it
                             is how an unmapped bet stops being invisible.
``market.markets``           the markets WE can represent, now with the two
                             flags that were implicit before:
                             ``is_tracked``      we store prices for it,
                             ``is_model_enabled`` our models and the decision
                                                  rule may use it.

ASIAN HANDICAP
--------------
``AH`` is added as a tracked market, NOT model-enabled: we keep the prices from
now on, and no model consumes them until one is built and backtested.

Its line is SIGNED, which is new, so the meaning is pinned down here as well as
in the domain: ``line`` is the handicap applied to the selection stored beside
it. ``AH / Away / +0.75`` is a complete statement. The provider sends the home
handicap on both rows of a pair ("Home -0.25" @1.92 / "Away -0.25" @1.88); the
boundary negates the away row. Reading it any other way makes the pair devig to
0.47 instead of the 1.090 every sampled pair actually shows.

``is_exclusive`` is false for AH: on a whole-number handicap a bet can push, so
the two sides do not exhaust the outcome space and their fair probabilities do
not sum to 1. Devigging it as if they did would invent value out of the push.

LINE INVARIANTS
---------------
One trigger function, three tables, and ``market.markets`` as the only source of
truth for what a line may be:

  * a line is always a multiple of 0.25 - no bookmaker quotes anything else, so
    such a value is a parsing failure, not a price;
  * a market with ``has_line = false`` may only carry the sentinel 0;
  * a negative line is accepted only where ``line_is_signed`` says so.

Enforcing it in the schema rather than only in Python means a future writer -
a backfill script, a manual fix, a new service - cannot store a handicap whose
sign has been lost.

Revision ID: 0025
Revises: 0024
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

UPGRADE = """
-- ── what our models may use ────────────────────────────────────────────────
ALTER TABLE market.markets
    ADD COLUMN is_model_enabled BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN line_is_signed   BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN market.markets.is_tracked IS
  'Guardamos precios de este mercado. Independiente de que lo modelemos.';
COMMENT ON COLUMN market.markets.is_model_enabled IS
  'Nuestros modelos y la regla de decision pueden usar este mercado. Capturar
   no es modelar: AH se captura y NO se modela hasta que exista un modelo
   backtesteado para el.';
COMMENT ON COLUMN market.markets.line_is_signed IS
  'true cuando una linea negativa tiene sentido (handicap asiatico). La linea
   almacenada es la que se aplica a la seleccion guardada a su lado.';

ALTER TABLE market.markets
    ADD CONSTRAINT markets_model_requires_tracking
        CHECK (NOT is_model_enabled OR is_tracked),
    ADD CONSTRAINT markets_signed_requires_line
        CHECK (NOT line_is_signed OR has_line);

-- Los cinco mercados que el esquema referencia por clave ajena. Hasta ahora
-- llegaban de un import de parquets legacy, asi que una base recien migrada no
-- tenia ninguno y el FK apuntaba a la nada. Se siembran aqui, con las banderas
-- reales: AH se captura y NO se modela; DC se captura y tampoco se modela (la
-- regla de decision RULE_V1 cubre 1X2, OU y BTTS y nada mas).
INSERT INTO market.markets
    (key, name, n_outcomes, has_line, is_exclusive, provider_bet_id, is_tracked,
     is_model_enabled, line_is_signed)
VALUES
    ('1X2', 'Match Winner',      3, false, true,  1,  true, true,  false),
    ('OU',  'Goals Over/Under',  2, true,  true,  5,  true, true,  false),
    ('BTTS','Both Teams Score',  2, false, true,  8,  true, true,  false),
    ('DC',  'Double Chance',     3, false, false, 12, true, false, false),
    ('AH',  'Asian Handicap',    2, true,  false, 4,  true, false, true)
ON CONFLICT (key) DO UPDATE SET
    name = EXCLUDED.name, n_outcomes = EXCLUDED.n_outcomes, has_line = EXCLUDED.has_line,
    is_exclusive = EXCLUDED.is_exclusive, provider_bet_id = EXCLUDED.provider_bet_id,
    is_tracked = EXCLUDED.is_tracked, is_model_enabled = EXCLUDED.is_model_enabled,
    line_is_signed = EXCLUDED.line_is_signed;

-- ── el catalogo del proveedor ──────────────────────────────────────────────
CREATE TABLE market.provider_markets (
    provider         TEXT        NOT NULL,
    scope            TEXT        NOT NULL CHECK (scope IN ('prematch','inplay')),
    provider_bet_id  INTEGER     NOT NULL,
    name             TEXT        NOT NULL,
    market_key       TEXT        REFERENCES market.markets(key),
    source           TEXT        NOT NULL CHECK (source IN ('catalogue','observed')),
    provider_version TEXT,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (provider, scope, provider_bet_id),
    CHECK (last_seen_at >= first_seen_at)
);
COMMENT ON TABLE market.provider_markets IS
  'Todo lo que el proveedor ofrece, este mapeado o no. 338 bets prematch y 266
   in-play en API-Football v3.9.3. market_key NULL = conocido y no modelado,
   que es el caso normal y la razon de que esta tabla exista.';
COMMENT ON COLUMN market.provider_markets.scope IS
  'prematch e inplay son espacios de ids DISTINTOS en API-Football: el bet 4 de
   uno no es el bet 4 del otro. Por eso forma parte de la clave.';
COMMENT ON COLUMN market.provider_markets.source IS
  'catalogue = lo dijo /odds/bets. observed = aparecio dentro de un payload
   real. Un observed que no esta en catalogue es una senal de cambio del
   proveedor, no un error nuestro.';

-- Un bet del proveedor mapea a un unico mercado nuestro, y un mercado nuestro
-- se alimenta de un unico bet por scope.
CREATE UNIQUE INDEX provider_markets_one_bet_per_market
    ON market.provider_markets (provider, scope, market_key)
    WHERE market_key IS NOT NULL;
CREATE INDEX provider_markets_unmapped
    ON market.provider_markets (provider, scope) WHERE market_key IS NULL;

INSERT INTO market.provider_markets
    (provider, scope, provider_bet_id, name, market_key, source, provider_version)
VALUES
    ('api-football','prematch', 1,'Match Winner',      '1X2', 'catalogue','v3.9.3'),
    ('api-football','prematch', 4,'Asian Handicap',    'AH',  'catalogue','v3.9.3'),
    ('api-football','prematch', 5,'Goals Over/Under',  'OU',  'catalogue','v3.9.3'),
    ('api-football','prematch', 8,'Both Teams Score',  'BTTS','catalogue','v3.9.3'),
    ('api-football','prematch',12,'Double Chance',     'DC',  'catalogue','v3.9.3')
ON CONFLICT (provider, scope, provider_bet_id) DO NOTHING;

-- ── invariantes de linea ───────────────────────────────────────────────────
CREATE FUNCTION market.assert_line_is_valid() RETURNS trigger
LANGUAGE plpgsql AS $fn$
DECLARE
    m RECORD;
BEGIN
    SELECT has_line, line_is_signed INTO m FROM market.markets WHERE key = NEW.market_key;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'market % is not in market.markets', NEW.market_key
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF (NEW.line * 4) <> trunc(NEW.line * 4) THEN
        RAISE EXCEPTION 'line % of market % is not a multiple of 0.25', NEW.line, NEW.market_key
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT m.has_line AND NEW.line <> 0 THEN
        RAISE EXCEPTION 'market % has no line, but a line of % was offered', NEW.market_key, NEW.line
            USING ERRCODE = 'check_violation';
    END IF;
    IF NOT m.line_is_signed AND NEW.line < 0 THEN
        RAISE EXCEPTION 'market % does not take a negative line, got %', NEW.market_key, NEW.line
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$fn$;
COMMENT ON FUNCTION market.assert_line_is_valid() IS
  'Unica fuente de verdad sobre lo que puede ser una linea: lee has_line y
   line_is_signed de market.markets. Un escritor futuro no puede guardar un
   handicap sin signo ni una linea que no sea multiplo de 0.25.';

CREATE TRIGGER odds_snapshots_line_is_valid
    BEFORE INSERT OR UPDATE ON market.odds_snapshots
    FOR EACH ROW EXECUTE FUNCTION market.assert_line_is_valid();
CREATE TRIGGER near_close_snapshots_line_is_valid
    BEFORE INSERT OR UPDATE ON market.near_close_snapshots
    FOR EACH ROW EXECUTE FUNCTION market.assert_line_is_valid();
CREATE TRIGGER market_consensus_line_is_valid
    BEFORE INSERT OR UPDATE ON market.market_consensus
    FOR EACH ROW EXECUTE FUNCTION market.assert_line_is_valid();
"""

DOWNGRADE = """
DROP TRIGGER IF EXISTS market_consensus_line_is_valid ON market.market_consensus;
DROP TRIGGER IF EXISTS near_close_snapshots_line_is_valid ON market.near_close_snapshots;
DROP TRIGGER IF EXISTS odds_snapshots_line_is_valid ON market.odds_snapshots;
DROP FUNCTION IF EXISTS market.assert_line_is_valid();
DROP TABLE IF EXISTS market.provider_markets;
ALTER TABLE market.markets
    DROP CONSTRAINT IF EXISTS markets_signed_requires_line,
    DROP CONSTRAINT IF EXISTS markets_model_requires_tracking;
ALTER TABLE market.markets
    DROP COLUMN IF EXISTS line_is_signed,
    DROP COLUMN IF EXISTS is_model_enabled;
-- La fila AH se conserva: hay precios reales que la referencian.
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
