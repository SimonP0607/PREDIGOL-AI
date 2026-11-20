"""The market's margin and dispersion by competition, market and day (plan PM, PM-05-07)

WHY THIS EXISTS
---------------
PrediGol keeps the last pre-match price of every house (``market.final_prematch_odds``, read after kick-off: 4,626 matches since
4-Oct-2026) and nothing sums it up: nobody can say which competitions have tight, consistent prices and which have wide margins or
houses that disagree. A nightly batch (PM-05-07, the code after this revision, behind a switch that is born off) measures, for each
competition, market and UTC day of kick-off, the margin of each house's book and how far the houses' fair probabilities lie apart, and
writes one row here. A measure, not a forecast: nothing reads it to price, pick or decide.

market.league_daily_stats
-------------------------
One row per UTC day of kick-off, competition (``core.competitions.id``), market and line (``1X2`` and ``BTTS`` at 0, ``OU`` at 2.50):

* ``n_fixtures`` the finished matches of that day priced in that market by at least one complete book; ``n_books`` the complete books
  (house x match) measured; ``books_median`` the median of houses per match;
* ``margin_*`` over the complete books: margin = sum of 1/price over the selections - 1 (a book without a margin - a stale or broken
  quote - is left out, as ``fbi.market.consensus`` does); mean, median, 10th and 90th percentiles;
* ``dispersion_*`` over the matches with two or more complete books: the population standard deviation across houses of each
  selection's proportional fair probability, averaged over the selections (the definition of ``market.market_consensus.dispersion``);
  median and mean, and ``n_dispersion`` the matches it was measured on;
* ``source`` where the prices came from (``final_prematch``), ``method_version`` the version of the rules, ``measured_at``.

Additive only: one new table, no foreign key (no lock on ``core.competitions``; a measure outlives nothing it refers to), no change to an
existing table, no row written. Privileges: ``deploy/vps/db/grants.sql`` - the worker writes and rewrites its rows (INSERT, UPDATE; never
DELETE: a day is measured again while late prices arrive, never removed); the API reads it. Downgrade drops it only while it is empty:
it never deletes a measure.

Revision ID: 0170
Revises: 0169
"""

from __future__ import annotations

from alembic import op

revision = "0170"
down_revision = "0169"
branch_labels = None
depends_on = None

TABLE = "market.league_daily_stats"

_VERSION = r"~ '^[a-z][a-z0-9-]{1,40}-v[0-9]+$'"
_MARGIN = "NUMERIC(7,5)  NOT NULL CHECK ({col} > 0 AND {col} < 1)"
_M_MEAN, _M_MEDIAN, _M_P10, _M_P90 = (_MARGIN.format(col=c) for c in ("margin_mean", "margin_median", "margin_p10", "margin_p90"))


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE {TABLE} (
            day                    DATE          NOT NULL,
            competition_id         BIGINT        NOT NULL,
            market_key             TEXT          NOT NULL CHECK (market_key ~ '^[A-Za-z0-9][A-Za-z0-9_.]{{0,63}}$'),
            line                   NUMERIC(6,2)  NOT NULL DEFAULT 0,
            n_fixtures             INTEGER       NOT NULL CHECK (n_fixtures >= 1),
            n_books                INTEGER       NOT NULL CHECK (n_books >= n_fixtures),
            books_median           NUMERIC(5,1)  NOT NULL CHECK (books_median >= 1),
            margin_mean            {_M_MEAN},
            margin_median          {_M_MEDIAN},
            margin_p10             {_M_P10},
            margin_p90             {_M_P90},
            dispersion_median      NUMERIC(8,6)  CHECK (dispersion_median >= 0 AND dispersion_median <= 1),
            dispersion_mean        NUMERIC(8,6)  CHECK (dispersion_mean >= 0 AND dispersion_mean <= 1),
            n_dispersion           INTEGER       NOT NULL DEFAULT 0 CHECK (n_dispersion >= 0 AND n_dispersion <= n_fixtures),
            source                 TEXT          NOT NULL CHECK (source IN ('final_prematch')),
            method_version         TEXT          NOT NULL CHECK (method_version {_VERSION}),
            measured_at            TIMESTAMPTZ   NOT NULL,
            first_measured_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            PRIMARY KEY (day, competition_id, market_key, line),
            CHECK (margin_p10 <= margin_median AND margin_median <= margin_p90),
            CHECK ((n_dispersion = 0) = (dispersion_median IS NULL) AND (dispersion_median IS NULL) = (dispersion_mean IS NULL))
        );
        CREATE INDEX league_daily_stats_competition ON {TABLE} (competition_id, day);
        COMMENT ON TABLE {TABLE} IS
          'PM-05-07: by UTC day of kick-off, competition, market and line, the margin of each house''s complete book (sum of 1/price - 1) '
          'and the dispersion across houses of the proportional fair probability, from market.final_prematch_odds. A measure written '
          'by the nightly batch; nothing reads it to price, pick or decide.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a measure: an empty table (a test database, a deploy rolled back the same minute) is dropped; one with rows stops
    # the downgrade. Nested: PL/pgSQL plans the inner query only when it runs, so a table already gone is no error.
    op.execute(
        "DO $refuse$\nBEGIN\n"
        f"  IF to_regclass('{TABLE}') IS NOT NULL THEN\n"
        f"    IF EXISTS (SELECT 1 FROM {TABLE}) THEN\n"
        f"      RAISE EXCEPTION '0170 downgrade refused: {TABLE} holds measures (PM-05-07); they are never deleted';\n"
        "    END IF;\n"
        "  END IF;\n"
        "END\n$refuse$"
    )
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
