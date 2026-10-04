"""persistent daily picks and parlays, and the user's own picks and parlays

Until now the product recomputed its picks and parlays on every request from the picks
whose matches were still ahead, so a pick vanished at kick-off and nothing could be
settled, counted or shown in a history. GATE D makes them records:

* picks.daily_sets / picks.daily_set_items: up to five picks per product day (America/
  Bogota), chosen progressively as each match reaches T-24h, T-12h, T-6h and T-3h, with the
  inputs frozen at selection (price, bookmaker, probabilities, expected value, model
  version, rule). An item is never removed or edited; it is settled after the match.
  ``source`` keeps the qualified set (what a user sees) apart from the evaluation set built
  from shadow picks (the owner's preview, labelled evaluation mode).
* picks.parlays / picks.parlay_legs: the daily and multi-day parlays, legs frozen when added,
  with the lifecycle BUILDING -> READY -> ACTIVE -> WON / LOST / VOID / PARTIAL_VOID.
* picks.user_picks: a selection a user saved, with a snapshot of what we showed at that
  moment (and, optionally, the price the user says they got), settled like any pick.
* picks.user_parlays / picks.user_parlay_legs: a parlay a user assembled, validated
  (one leg per match, no team twice) and settled.

Revision ID: 0053
Revises: 0052
"""

from __future__ import annotations

from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

RESULT = "'PENDING', 'WIN', 'LOSS', 'PUSH', 'VOID', 'HALF_WIN', 'HALF_LOSS'"
PARLAY = "'BUILDING', 'READY', 'ACTIVE', 'WON', 'LOST', 'VOID', 'PARTIAL_VOID'"


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS picks.daily_sets (
            id           BIGSERIAL PRIMARY KEY,
            day          DATE        NOT NULL,
            timezone     TEXT        NOT NULL,
            source       TEXT        NOT NULL CHECK (source IN ('qualified', 'evaluation')),
            rule_version TEXT        NOT NULL,
            status       TEXT        NOT NULL DEFAULT 'BUILDING' CHECK (status IN ('BUILDING', 'COMPLETE', 'SETTLED')),
            created_at   TIMESTAMPTZ NOT NULL,
            updated_at   TIMESTAMPTZ NOT NULL,
            UNIQUE (day, source)
        );
        CREATE TABLE IF NOT EXISTS picks.daily_set_items (
            set_id           BIGINT       NOT NULL REFERENCES picks.daily_sets(id) ON DELETE CASCADE,
            rank             SMALLINT     NOT NULL CHECK (rank BETWEEN 1 AND 5),
            pick_id          BIGINT       NOT NULL REFERENCES picks.picks(id),
            fixture_id       BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key       TEXT         NOT NULL,
            selection        TEXT         NOT NULL,
            line             NUMERIC(6,2) NOT NULL DEFAULT 0,
            stage            TEXT         NOT NULL CHECK (stage IN ('T-24h', 'T-12h', 'T-6h', 'T-3h')),
            selected_at      TIMESTAMPTZ  NOT NULL,
            odds             NUMERIC(9,3) NOT NULL CHECK (odds > 1),
            bookmaker_id     INTEGER      REFERENCES market.bookmakers(id),
            price_at         TIMESTAMPTZ  NOT NULL,
            p_model          NUMERIC(8,6) NOT NULL,
            p_low            NUMERIC(8,6) NOT NULL,
            p_push           NUMERIC(8,6) NOT NULL DEFAULT 0,
            p_market         NUMERIC(8,6) NOT NULL,
            ev               NUMERIC(10,6) NOT NULL,
            model_version_id BIGINT       NOT NULL REFERENCES models.model_versions(id),
            inputs           JSONB        NOT NULL,
            status           TEXT         NOT NULL DEFAULT 'PENDING' CHECK (status IN ({RESULT})),
            profit_units     NUMERIC(10,4),
            settled_at       TIMESTAMPTZ,
            PRIMARY KEY (set_id, rank),
            UNIQUE (set_id, fixture_id),
            CHECK (price_at <= selected_at),
            CHECK ((status = 'PENDING') = (settled_at IS NULL))
        );
        CREATE INDEX IF NOT EXISTS daily_set_items_fixture ON picks.daily_set_items (fixture_id);

        CREATE TABLE IF NOT EXISTS picks.parlays (
            id                  BIGSERIAL PRIMARY KEY,
            kind                TEXT        NOT NULL CHECK (kind IN ('daily', 'multiday')),
            day                 DATE        NOT NULL,
            source              TEXT        NOT NULL CHECK (source IN ('qualified', 'evaluation')),
            rule_version        TEXT        NOT NULL,
            status              TEXT        NOT NULL DEFAULT 'BUILDING' CHECK (status IN ({PARLAY})),
            min_legs            SMALLINT    NOT NULL,
            max_legs            SMALLINT    NOT NULL,
            window_from         TIMESTAMPTZ NOT NULL,
            window_to           TIMESTAMPTZ NOT NULL,
            combined_odds       NUMERIC(12,3),
            p_all_low           NUMERIC(10,8),
            expected_log_growth NUMERIC(12,8),
            created_at          TIMESTAMPTZ NOT NULL,
            ready_at            TIMESTAMPTZ,
            settled_at          TIMESTAMPTZ,
            profit_units        NUMERIC(12,4),
            UNIQUE (kind, day, source),
            CHECK (min_legs BETWEEN 2 AND max_legs)
        );
        CREATE TABLE IF NOT EXISTS picks.parlay_legs (
            parlay_id        BIGINT       NOT NULL REFERENCES picks.parlays(id) ON DELETE CASCADE,
            leg_no           SMALLINT     NOT NULL CHECK (leg_no >= 1),
            pick_id          BIGINT       NOT NULL REFERENCES picks.picks(id),
            fixture_id       BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key       TEXT         NOT NULL,
            selection        TEXT         NOT NULL,
            line             NUMERIC(6,2) NOT NULL DEFAULT 0,
            added_at         TIMESTAMPTZ  NOT NULL,
            odds             NUMERIC(9,3) NOT NULL CHECK (odds > 1),
            bookmaker_id     INTEGER      REFERENCES market.bookmakers(id),
            price_at         TIMESTAMPTZ  NOT NULL,
            p_model          NUMERIC(8,6) NOT NULL,
            p_low            NUMERIC(8,6) NOT NULL,
            p_push           NUMERIC(8,6) NOT NULL DEFAULT 0,
            p_market         NUMERIC(8,6) NOT NULL,
            ev               NUMERIC(10,6) NOT NULL,
            inputs           JSONB        NOT NULL,
            status           TEXT         NOT NULL DEFAULT 'PENDING' CHECK (status IN ({RESULT})),
            settled_at       TIMESTAMPTZ,
            PRIMARY KEY (parlay_id, leg_no),
            UNIQUE (parlay_id, fixture_id),
            CHECK ((status = 'PENDING') = (settled_at IS NULL))
        );

        CREATE TABLE IF NOT EXISTS picks.user_picks (
            id           BIGSERIAL PRIMARY KEY,
            user_id      BIGINT       NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            fixture_id   BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key   TEXT         NOT NULL,
            selection    TEXT         NOT NULL,
            line         NUMERIC(6,2) NOT NULL DEFAULT 0,
            origin       TEXT         NOT NULL CHECK (origin IN ('predigol_pick', 'market')),
            pick_id      BIGINT       REFERENCES picks.picks(id),
            odds         NUMERIC(9,3) CHECK (odds IS NULL OR odds > 1),
            bookmaker    TEXT,
            price_at     TIMESTAMPTZ,
            user_odds    NUMERIC(9,3) CHECK (user_odds IS NULL OR user_odds > 1),
            snapshot     JSONB        NOT NULL,
            saved_at     TIMESTAMPTZ  NOT NULL,
            status       TEXT         NOT NULL DEFAULT 'PENDING' CHECK (status IN ({RESULT})),
            profit_units NUMERIC(10,4),
            settled_at   TIMESTAMPTZ,
            UNIQUE (user_id, fixture_id, market_key, selection, line),
            CHECK ((origin = 'predigol_pick') = (pick_id IS NOT NULL)),
            CHECK ((status = 'PENDING') = (settled_at IS NULL))
        );
        CREATE INDEX IF NOT EXISTS user_picks_user ON picks.user_picks (user_id, saved_at DESC);

        CREATE TABLE IF NOT EXISTS picks.user_parlays (
            id            BIGSERIAL PRIMARY KEY,
            user_id       BIGINT       NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
            name          TEXT         CHECK (name IS NULL OR length(btrim(name)) BETWEEN 1 AND 80),
            created_at    TIMESTAMPTZ  NOT NULL,
            combined_odds NUMERIC(12,3),
            validation    JSONB        NOT NULL,
            status        TEXT         NOT NULL DEFAULT 'READY' CHECK (status IN ({PARLAY})),
            profit_units  NUMERIC(12,4),
            settled_at    TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS user_parlays_user ON picks.user_parlays (user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS picks.user_parlay_legs (
            user_parlay_id BIGINT       NOT NULL REFERENCES picks.user_parlays(id) ON DELETE CASCADE,
            leg_no         SMALLINT     NOT NULL CHECK (leg_no >= 1),
            fixture_id     BIGINT       NOT NULL REFERENCES core.fixtures(id),
            market_key     TEXT         NOT NULL,
            selection      TEXT         NOT NULL,
            line           NUMERIC(6,2) NOT NULL DEFAULT 0,
            odds           NUMERIC(9,3) CHECK (odds IS NULL OR odds > 1),
            snapshot       JSONB        NOT NULL,
            status         TEXT         NOT NULL DEFAULT 'PENDING' CHECK (status IN ({RESULT})),
            settled_at     TIMESTAMPTZ,
            PRIMARY KEY (user_parlay_id, leg_no),
            UNIQUE (user_parlay_id, fixture_id),
            CHECK ((status = 'PENDING') = (settled_at IS NULL))
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS picks.user_parlay_legs;
        DROP TABLE IF EXISTS picks.user_parlays;
        DROP TABLE IF EXISTS picks.user_picks;
        DROP TABLE IF EXISTS picks.parlay_legs;
        DROP TABLE IF EXISTS picks.parlays;
        DROP TABLE IF EXISTS picks.daily_set_items;
        DROP TABLE IF EXISTS picks.daily_sets;
    """)
