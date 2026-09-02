"""picks layer: decision, publication, settlement and line value

Source of truth: docs/rebuild/schema_v2/007_picks.sql

DELIBERATE, DOCUMENTED DEVIATION FROM THE SOURCE DDL
----------------------------------------------------
``picks.pick_clv`` becomes ``picks.pick_line_value``, and its ``closing_*``
columns become ``near_close_*``. CLV means "closing line value"; the project has
never validated that the snapshot it compares against IS the closing line.
Naming it CLV would bake an unproven claim into the schema.

  * ``lv_raw`` / ``lv_devigged`` measure value against the near-close snapshot.
  * ``is_validated_close`` (default false) says whether that snapshot was
    empirically shown to be the close. Only then is the number a true CLV.
  * ``near_close_minutes_to_ko`` is stored so every consumer can see how far
    from kickoff the reference price actually was.

No other semantics are changed.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

UPGRADE = """
-- Todos los candidatos evaluados, no solo los elegidos.
CREATE TABLE picks.pick_candidates (
    id               BIGSERIAL PRIMARY KEY,
    run_id           BIGINT       NOT NULL REFERENCES raw.ingestion_runs(id),
    fixture_id       BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    prediction_id    BIGINT       NOT NULL REFERENCES models.predictions(id),
    market_key       TEXT         NOT NULL REFERENCES market.markets(key),
    selection        TEXT         NOT NULL,
    line             NUMERIC(6,2) NOT NULL DEFAULT 0,
    bookmaker_id     INTEGER      REFERENCES market.bookmakers(id),
    market_odds      NUMERIC(9,3),
    p_calibrated     NUMERIC(8,6) NOT NULL,
    p_market_fair    NUMERIC(8,6),
    edge             NUMERIC(8,6),
    price_edge       NUMERIC(8,6),
    ev               NUMERIC(8,6),
    ev_adjusted      NUMERIC(8,6),
    decision         TEXT         NOT NULL CHECK (decision IN ('selected','rejected')),
    rejection_reason TEXT,
    evaluated_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (decision <> 'rejected' OR rejection_reason IS NOT NULL),
    CHECK (decision <> 'selected' OR (market_odds IS NOT NULL AND bookmaker_id IS NOT NULL))
);
COMMENT ON TABLE picks.pick_candidates IS
  'Todos los candidatos evaluados, seleccionados o no, con el motivo del rechazo.
   El ultimo CHECK garantiza que un candidato seleccionado SIEMPRE tiene precio:
   en el legacy los 16 picks del value engine tenian offered_odds NULL.';
CREATE INDEX ON picks.pick_candidates (fixture_id, evaluated_at DESC);
CREATE INDEX ON picks.pick_candidates (decision, evaluated_at DESC);

CREATE TABLE picks.picks (
    id                    BIGSERIAL PRIMARY KEY,
    candidate_id          BIGINT       NOT NULL UNIQUE REFERENCES picks.pick_candidates(id),
    fixture_id            BIGINT       NOT NULL REFERENCES core.fixtures(id),
    market_key            TEXT         NOT NULL REFERENCES market.markets(key),
    selection             TEXT         NOT NULL,
    line                  NUMERIC(6,2) NOT NULL DEFAULT 0,
    model_version_id      BIGINT       NOT NULL REFERENCES models.model_versions(id),
    calibrator_id         BIGINT       NOT NULL REFERENCES models.calibrators(id),
    feature_set_hash      TEXT         NOT NULL,
    data_cutoff_ts        TIMESTAMPTZ  NOT NULL,
    decision_rule_version TEXT         NOT NULL,
    code_version          TEXT         NOT NULL,
    bookmaker_id          INTEGER      NOT NULL REFERENCES market.bookmakers(id),
    market_odds           NUMERIC(9,3) NOT NULL CHECK (market_odds > 1.0),
    odds_captured_at      TIMESTAMPTZ  NOT NULL,
    p_model               NUMERIC(8,6) NOT NULL,
    p_calibrated          NUMERIC(8,6) NOT NULL,
    p_calibrated_lo       NUMERIC(8,6) NOT NULL,
    p_calibrated_hi       NUMERIC(8,6) NOT NULL,
    p_market_fair         NUMERIC(8,6) NOT NULL,
    fair_odds             NUMERIC(9,3) NOT NULL,
    edge                  NUMERIC(8,6) NOT NULL,
    price_edge            NUMERIC(8,6) NOT NULL,
    ev                    NUMERIC(8,6) NOT NULL,
    ev_adjusted           NUMERIC(8,6) NOT NULL,
    kelly_fraction        NUMERIC(8,6) NOT NULL,
    stake_units           NUMERIC(8,4) NOT NULL CHECK (stake_units > 0),
    selection_reason      JSONB        NOT NULL,
    mode                  TEXT         NOT NULL DEFAULT 'shadow'
                          CHECK (mode IN ('shadow','live')),
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    published_at          TIMESTAMPTZ,
    CHECK (p_calibrated_lo <= p_calibrated AND p_calibrated <= p_calibrated_hi),
    CHECK (data_cutoff_ts <= odds_captured_at)
);
CREATE INDEX ON picks.picks (created_at DESC);
CREATE INDEX ON picks.picks (fixture_id);
CREATE INDEX ON picks.picks (mode, created_at DESC);

CREATE TABLE picks.pick_results (
    pick_id        BIGINT PRIMARY KEY REFERENCES picks.picks(id) ON DELETE CASCADE,
    result_status  TEXT   NOT NULL CHECK (result_status IN
                   ('pending','win','loss','push','half_win','half_loss','void')),
    profit_units   NUMERIC(10,4),
    settled_at     TIMESTAMPTZ,
    settled_by     TEXT,
    CHECK (result_status = 'pending' OR (profit_units IS NOT NULL AND settled_at IS NOT NULL))
);
COMMENT ON TABLE picks.pick_results IS
  'Siete estados. El legacy solo tenia win/loss/void, lo que impide liquidar
   correctamente handicaps asiaticos y lineas con medio resultado.';

-- NO se llama pick_clv: ver la nota de cabecera de esta revision.
CREATE TABLE picks.pick_line_value (
    pick_id                  BIGINT PRIMARY KEY REFERENCES picks.picks(id) ON DELETE CASCADE,
    near_close_odds          NUMERIC(9,3) NOT NULL,
    near_close_captured_at   TIMESTAMPTZ  NOT NULL,
    near_close_source        TEXT         NOT NULL CHECK (near_close_source IN ('live','prematch')),
    near_close_minutes_to_ko INTEGER      NOT NULL CHECK (near_close_minutes_to_ko >= 0),
    lv_raw                   NUMERIC(8,6) NOT NULL,
    lv_devigged              NUMERIC(8,6),
    is_validated_close       BOOLEAN      NOT NULL DEFAULT false,
    close_validation_method  TEXT,
    computed_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CHECK (NOT is_validated_close OR close_validation_method IS NOT NULL)
);
COMMENT ON TABLE picks.pick_line_value IS
  'Valor de la cuota tomada frente al ultimo snapshot capturado antes del saque.
   SOLO es CLV (closing line value) cuando is_validated_close = true, es decir
   cuando se ha demostrado que ese snapshot era realmente la linea de cierre.
   Mientras sea false, es valor frente a un snapshot proximo al cierre y nada mas.';
COMMENT ON COLUMN picks.pick_line_value.lv_raw IS
  'odds_tomada / near_close_odds - 1. Sobre cuotas con margen, no desvigadas.';
COMMENT ON COLUMN picks.pick_line_value.near_close_minutes_to_ko IS
  'Distancia real al saque del precio de referencia. Es el dato que permite juzgar
   si la comparacion significa algo.';
"""

DOWNGRADE = """
DROP TABLE IF EXISTS picks.pick_line_value;
DROP TABLE IF EXISTS picks.pick_results;
DROP TABLE IF EXISTS picks.picks;
DROP TABLE IF EXISTS picks.pick_candidates;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
