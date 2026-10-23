"""PrediGol's forecast of a match, kept apart from its value and from any pick (plan F5)

WHY THIS EXISTS
---------------
Until now the only place a model's probability lived for a user was the *candidate*: ``picks.picks`` rows are born from a
selection that already passed the value rule, and ``intel.decisions`` judges only those. A match whose models were
confident but whose price was short (a favourite at 1.30) produced no row at all, so the system had nowhere to say "this is
the likely outcome" without it being, or looking like, a recommendation. ``models.predictions`` holds every model's
numbers, but of every model and every version and every backtest, and the number a decision uses (``p_calibrated``) is the
raw one: the calibrated probability only exists inside a decision, and only where there is a price.

``fbi.predictions.match_forecast`` (``forecast-v1``) states, for every upcoming match that has a model, what PrediGol thinks
will happen in its core markets (1X2, total goals at 2.5, both teams to score) and writes it here. A forecast is a
probability, the interval the model measured around it, and whether it was calibrated. It never carries a price, an edge, a
stake or a state: those are the decision layer's and live in ``intel.decisions`` and ``picks``. Nothing here is read by
either of them, so a forecast cannot become a pick.

WHAT IS ADDED
-------------
``models.match_forecasts``  one row per (match, market, outcome, line) at the instant it was made (``known_at``). Append-only:
    a row is written when a market's forecast is new or moved (see ``MATERIAL_CHANGE`` in the module), and ALL the outcomes
    of the market are written together, so a market always reads as one coherent set that adds up to one. "What did PrediGol
    say about this match at time T" is the newest ``known_at <= T`` of each market.
    ``model_name`` / ``model_version_id`` / ``data_cutoff_ts`` say which model made the number and with what data;
    ``p_model`` is that model's raw probability and ``p`` what PrediGol states: the same number while ``calibration`` is
    UNCALIBRATED, the champion calibrator's output (``calibrator_id``) when CALIBRATED. ``p_market_used`` is the de-vigged
    consensus a calibrator that needs the market took as input (so a calibrated forecast says which market it leaned on).
    ``basis`` is the reason for the calibration status in one word.
``models.refuse_forecast_change()``  the append-only guard (``fbi.models_maintenance = on`` lifts it, for a maintenance
    session that has to remove a match).

Nothing existing is altered: one new table, one function, one trigger. The downgrade drops them. The table is derived (the
inputs are ``models.predictions`` and ``intel.calibrators``), so losing it loses only what was said and when.

Revision ID: 0086
Revises: 0085
"""

from __future__ import annotations

from alembic import op

revision = "0086"
down_revision = "0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new; its foreign keys take
    # a short lock on the tables they point at.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE FUNCTION models.refuse_forecast_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            IF coalesce(current_setting('fbi.models_maintenance', true), '') = 'on' THEN
                RETURN COALESCE(NEW, OLD);
            END IF;
            RAISE EXCEPTION 'models.%: append-only (% refused)', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$""")

    op.execute("""
        CREATE TABLE models.match_forecasts (
            id               BIGSERIAL    PRIMARY KEY,
            version          TEXT         NOT NULL CHECK (length(btrim(version)) > 0),
            known_at         TIMESTAMPTZ  NOT NULL,
            fixture_id       BIGINT       NOT NULL REFERENCES core.fixtures(id),
            family           TEXT         NOT NULL CHECK (family ~ '^[A-Z][A-Z0-9_]*$'),
            market_key       TEXT         NOT NULL REFERENCES market.markets(key),
            selection        TEXT         NOT NULL CHECK (length(btrim(selection)) > 0),
            line             NUMERIC(6,2) NOT NULL DEFAULT 0,
            model_name       TEXT         NOT NULL CHECK (length(btrim(model_name)) > 0),
            model_version_id BIGINT       NOT NULL REFERENCES models.model_versions(id),
            data_cutoff_ts   TIMESTAMPTZ  NOT NULL,
            p_model          NUMERIC(8,6) NOT NULL CHECK (p_model > 0 AND p_model < 1),
            p                NUMERIC(8,6) NOT NULL CHECK (p > 0 AND p < 1),
            p_lo             NUMERIC(8,6) CHECK (p_lo >= 0 AND p_lo <= 1),
            p_hi             NUMERIC(8,6) CHECK (p_hi >= 0 AND p_hi <= 1),
            p_push           NUMERIC(8,6) NOT NULL DEFAULT 0 CHECK (p_push >= 0 AND p_push < 1),
            calibration      TEXT         NOT NULL CHECK (calibration IN ('CALIBRATED', 'UNCALIBRATED')),
            calibrator_id    BIGINT       REFERENCES intel.calibrators(id),
            p_market_used    NUMERIC(8,6) CHECK (p_market_used > 0 AND p_market_used < 1),
            market_as_of     TIMESTAMPTZ,
            basis            TEXT         NOT NULL CHECK (basis IN ('champion', 'no_champion', 'needs_price', 'not_applicable')),
            input_hash       TEXT         NOT NULL CHECK (length(input_hash) > 0),
            code_version     TEXT         NOT NULL,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            CONSTRAINT match_forecasts_interval_pair CHECK ((p_lo IS NULL) = (p_hi IS NULL)),
            CONSTRAINT match_forecasts_interval_holds_p CHECK (p_lo IS NULL OR (p_lo <= p AND p <= p_hi)),
            CONSTRAINT match_forecasts_calibrated_iff_calibrator
                CHECK ((calibration = 'CALIBRATED') = (calibrator_id IS NOT NULL)),
            CONSTRAINT match_forecasts_basis_says_calibration
                CHECK ((calibration = 'CALIBRATED') = (basis = 'champion')),
            CONSTRAINT match_forecasts_once UNIQUE (fixture_id, version, market_key, line, selection, known_at)
        )""")
    op.execute("CREATE INDEX match_forecasts_read ON models.match_forecasts "
               "(fixture_id, version, market_key, line, known_at DESC)")
    op.execute("CREATE INDEX match_forecasts_known_at ON models.match_forecasts (known_at)")
    op.execute("""
        COMMENT ON TABLE models.match_forecasts IS
        'PrediGol''s forecast of a match (plan F5): per match, market and outcome, the probability it states, the interval the
         model measured and whether it was calibrated. Never a price, an edge or a pick: those are intel.decisions and
         picks.* and nothing there reads this table. Append-only; all the outcomes of a market are written together at one
         known_at. fbi.predictions.match_forecast (version) writes it from models.predictions and the champion calibrators.'""")
    op.execute("""
        COMMENT ON COLUMN models.match_forecasts.p IS
        'The probability PrediGol states: p_model while calibration is UNCALIBRATED; the champion calibrator''s output,
         scaled so the outcomes of the market add up to one, when CALIBRATED.'""")
    op.execute("""
        COMMENT ON COLUMN models.match_forecasts.basis IS
        'Why the calibration status is what it is: champion (a champion calibrator was applied), no_champion (the market
         has none for this model), needs_price (the champion uses the market''s probability and there was no recent one),
         not_applicable (the calibrator could not be applied to this probability).'""")
    op.execute("CREATE TRIGGER match_forecasts_append_only BEFORE UPDATE OR DELETE ON models.match_forecasts "
               "FOR EACH ROW EXECUTE FUNCTION models.refuse_forecast_change()")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS models.match_forecasts")
    op.execute("DROP FUNCTION IF EXISTS models.refuse_forecast_change()")
