"""The availability matrix: coverage cells by competition season, phase and datum, markets by competition season, the facts of each
match, the history of their levels and the shadow comparison's discrepancies (plan PM, section 4; PM-02-02)

WHY THIS EXISTS
---------------
Whether a competition season records a datum (corners, cards, line-ups ...) or prices a market is computed today on the fly
(``fbi.market.settle_coverage``, one query per rule and answer) or lives in JSON files committed by hand (``stats_coverage.json``,
``market_states.json``): photos with no history. The rules ``coverage-levels-v1`` (``fbi.coverage.levels``, PM-02-01) grade each
cell A, B, C, D or MI; a nightly batch (PM-02-03) measures and writes them here, the resolver of a match (PM-02-04) and the contract
C-16 «Disponibilidad» (PM-02-05) read them, and the shadow comparison (PM-02-06) records where a module shows something the matrix
would not (or the other way round).

analytics.coverage_cells
------------------------
One row per competition season, phase and datum (``fbi.coverage.levels.DATA``): the finished matches measured, how many carry the
datum (filled for both teams), the share, the level published and the level this recalculation measured (rule 4: a level goes
down only after two recalculations in a row miss it - ``missed`` keeps the first miss), ``provisional`` (a B below 30 matches, or a
season short of sample that took the level of the season before), the reason in the code's vocabulary, how many editions were
pooled (rule 3: one-match competitions pool their last five), the provider's declared flag (rule 5: only its «no» is used), the
rules' version and when it was measured. ``phase_key`` is ``todas`` until PM-02-07 splits the cups by phase.

analytics.market_availability
-----------------------------
One row per competition season and market (``fbi.coverage.levels.MARKETS``): over the finished matches of the odds window, how many
were priced and the median of houses; over the finished matches of the season, how many carry what the market settles on; the
level, as above, and the catalogue's state of the market when there is one.

analytics.coverage_fixture_facts
--------------------------------
One row per finished match measured: which data it carries (filled for both teams), how many houses priced each market (only for a
match inside the odds window) and which markets its stored result settles. Facts, not states: a match's prices do not change after
it is played, so the nightly batch measures each match once (and its data again on Sundays, when late statistics may have arrived)
and the cells are counted from here, not from the 29 million rows of ``market.odds_quotes`` every night. A fifth table, not in the
plan's list: without it the incremental pass would read every quote of every match of a season each night.

analytics.coverage_changes
--------------------------
Append-only: one row each time a published level changes (or a cell is graded for the first time), with the level before and after
and why. History and the owner's notices.

analytics.availability_discrepancies
------------------------------------
Append-only: one row per day, match, module and subject where what the module shows differs from what the matrix would say, both
read at the same instant (PM-02-06). Not in the plan's list of three either: the shadow's daily record needs a home and a
second migration for it would be a second chance of a clash of revision numbers (it happened three times).

Additive only: five new tables, no foreign key (no lock on ``core.competition_seasons`` or ``core.fixtures``; a cell outlives
nothing it refers to, seasons are never deleted), no change to an existing table, no row written. Privileges:
``deploy/vps/db/grants.sql`` - the worker writes the cells, markets and facts (INSERT, UPDATE; never DELETE) and only appends the changes
and discrepancies; the API reads the five. Downgrade drops them only while they are empty: it never deletes a measure.

Revision ID: 0169
Revises: 0168
"""

from __future__ import annotations

from alembic import op

revision = "0169"
down_revision = "0168"
branch_labels = None
depends_on = None

TABLES = ("analytics.coverage_cells", "analytics.market_availability", "analytics.coverage_fixture_facts",
          "analytics.coverage_changes", "analytics.availability_discrepancies")

_LEVEL = "IN ('A', 'B', 'C', 'D', 'MI')"
_VERSION = r"~ '^[a-z][a-z0-9-]{1,40}-v[0-9]+$'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE SCHEMA IF NOT EXISTS analytics;

        CREATE TABLE analytics.coverage_cells (
            competition_season_id  BIGINT        NOT NULL,
            phase_key              TEXT          NOT NULL CHECK (phase_key ~ '^[a-z][a-z0-9_]{{0,31}}$'),
            datum                  TEXT          NOT NULL CHECK (datum ~ '^[a-z][a-z0-9_]{{0,31}}$'),
            n_finished             INTEGER       NOT NULL CHECK (n_finished >= 0),
            n_with_data            INTEGER       NOT NULL CHECK (n_with_data >= 0 AND n_with_data <= n_finished),
            share                  NUMERIC(5,4)  CHECK (share BETWEEN 0 AND 1),
            level                  TEXT          NOT NULL CHECK (level {_LEVEL}),
            measured_level         TEXT          NOT NULL CHECK (measured_level {_LEVEL}),
            missed                 BOOLEAN       NOT NULL DEFAULT false,
            provisional            BOOLEAN       NOT NULL DEFAULT false,
            reason                 TEXT          CHECK (char_length(reason) BETWEEN 1 AND 40),
            pooled_seasons         SMALLINT      NOT NULL DEFAULT 1 CHECK (pooled_seasons BETWEEN 1 AND 5),
            declared_flag          BOOLEAN,
            rules_version          TEXT          NOT NULL CHECK (rules_version {_VERSION}),
            measured_at            TIMESTAMPTZ   NOT NULL,
            first_measured_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            PRIMARY KEY (competition_season_id, phase_key, datum)
        );
        COMMENT ON TABLE analytics.coverage_cells IS
          'PM-02-02 (C-16, states 1 and 2): the level (coverage-levels-v1, fbi.coverage.levels) of a datum in a competition season and '
          'phase, from its finished matches: a datum counts when filled for both teams. level is the published one (rule 4: down only '
          'after two recalculations in a row miss it; missed keeps the first miss), measured_level what this recalculation measured. '
          'Written by the nightly batch (PM-02-03); read by the resolver and C-16. phase_key todas until PM-02-07.';

        CREATE TABLE analytics.market_availability (
            competition_season_id  BIGINT        NOT NULL,
            market_key             TEXT          NOT NULL CHECK (market_key ~ '^[A-Za-z0-9][A-Za-z0-9_.]{{0,63}}$'),
            window_start           DATE          NOT NULL,
            window_days            INTEGER       NOT NULL CHECK (window_days >= 0),
            n_window               INTEGER       NOT NULL CHECK (n_window >= 0),
            n_priced               INTEGER       NOT NULL CHECK (n_priced >= 0 AND n_priced <= n_window),
            priced_share           NUMERIC(5,4)  CHECK (priced_share BETWEEN 0 AND 1),
            median_books           NUMERIC(5,1)  CHECK (median_books >= 0),
            n_settle_finished      INTEGER       CHECK (n_settle_finished >= 0),
            n_settleable           INTEGER       CHECK (n_settleable >= 0 AND n_settleable <= n_settle_finished),
            settle_share           NUMERIC(5,4)  CHECK (settle_share BETWEEN 0 AND 1),
            level                  TEXT          NOT NULL CHECK (level {_LEVEL}),
            measured_level         TEXT          NOT NULL CHECK (measured_level {_LEVEL}),
            missed                 BOOLEAN       NOT NULL DEFAULT false,
            provisional            BOOLEAN       NOT NULL DEFAULT false,
            reason                 TEXT          CHECK (char_length(reason) BETWEEN 1 AND 40),
            catalogue_state        TEXT          CHECK (char_length(catalogue_state) BETWEEN 1 AND 40),
            rules_version          TEXT          NOT NULL CHECK (rules_version {_VERSION}),
            measured_at            TIMESTAMPTZ   NOT NULL,
            first_measured_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
            PRIMARY KEY (competition_season_id, market_key)
        );
        COMMENT ON TABLE analytics.market_availability IS
          'PM-02-02 (C-16, states 2, 3 and 6 by competition season): over the finished matches of the odds window, the share priced and '
          'the median of houses; over the finished matches of the season, the share carrying what the market settles on; the level '
          '(coverage-levels-v1) as in analytics.coverage_cells. Written by the nightly batch (PM-02-03).';

        CREATE TABLE analytics.coverage_fixture_facts (
            fixture_id             BIGINT        PRIMARY KEY,
            competition_season_id  BIGINT        NOT NULL,
            kickoff_at             TIMESTAMPTZ   NOT NULL,
            present                TEXT[]        NOT NULL DEFAULT '{{}}',
            books                  JSONB         CHECK (books IS NULL OR jsonb_typeof(books) = 'object'),
            settles                TEXT[]        NOT NULL DEFAULT '{{}}',
            rules_version          TEXT          NOT NULL CHECK (rules_version {_VERSION}),
            measured_at            TIMESTAMPTZ   NOT NULL,
            odds_measured_at       TIMESTAMPTZ
        );
        CREATE INDEX coverage_fixture_facts_season ON analytics.coverage_fixture_facts (competition_season_id, kickoff_at);
        COMMENT ON TABLE analytics.coverage_fixture_facts IS
          'PM-02-03: what a finished match carries - present: the data filled for both teams; books: houses per market (NULL outside '
          'the odds window); settles: the markets its stored result settles. Measured once by the nightly batch (data again on '
          'Sundays); the cells of analytics.coverage_cells and analytics.market_availability are counted from here.';

        CREATE TABLE analytics.coverage_changes (
            id                     BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            competition_season_id  BIGINT        NOT NULL,
            phase_key              TEXT          NOT NULL CHECK (phase_key ~ '^[a-z][a-z0-9_]{{0,31}}$'),
            kind                   TEXT          NOT NULL CHECK (kind IN ('datum', 'market')),
            subject                TEXT          NOT NULL CHECK (subject ~ '^[A-Za-z0-9][A-Za-z0-9_.]{{0,63}}$'),
            old_level              TEXT          CHECK (old_level {_LEVEL}),
            new_level              TEXT          NOT NULL CHECK (new_level {_LEVEL}),
            reason                 TEXT          NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 40),
            n_finished             INTEGER       CHECK (n_finished >= 0),
            share                  NUMERIC(5,4)  CHECK (share BETWEEN 0 AND 1),
            rules_version          TEXT          NOT NULL CHECK (rules_version {_VERSION}),
            changed_at             TIMESTAMPTZ   NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE analytics.coverage_changes IS
          'PM-02-02: append-only history of the published levels of analytics.coverage_cells (kind datum) and '
          'analytics.market_availability (kind market): before, after and why (reason: primera_medida, sube, baja ...).';

        CREATE TABLE analytics.availability_discrepancies (
            id                     BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            day                    DATE          NOT NULL,
            fixture_id             BIGINT        NOT NULL,
            module                 TEXT          NOT NULL CHECK (module ~ '^[a-z][a-z0-9_]{{0,31}}$'),
            subject                TEXT          NOT NULL CHECK (subject ~ '^[A-Za-z0-9][A-Za-z0-9_.:]{{0,95}}$'),
            shown                  BOOLEAN       NOT NULL,
            matrix                 BOOLEAN       NOT NULL,
            reason                 TEXT          NOT NULL CHECK (char_length(reason) BETWEEN 1 AND 60),
            detail                 JSONB         NOT NULL DEFAULT '{{}}'::jsonb CHECK (jsonb_typeof(detail) = 'object'),
            observed_at            TIMESTAMPTZ   NOT NULL,
            rules_version          TEXT          NOT NULL CHECK (rules_version {_VERSION}),
            code_version           TEXT          CHECK (char_length(code_version) <= 64),
            UNIQUE (day, fixture_id, module, subject)
        );
        COMMENT ON TABLE analytics.availability_discrepancies IS
          'PM-02-06: append-only, one row per UTC day, match, module and subject where what the module shows (shown) differs from what '
          'the availability matrix would say (matrix), both read at the same instant (observed_at). Nothing a reader sees.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a measure: the history of the levels cannot be measured again. Empty tables (a test database, a deploy rolled back
    # the same minute) are dropped; anything else stops the downgrade and says which table.
    checks = "\n".join(
        # nested: PL/pgSQL plans the inner query only when it runs, so a table already gone is no error
        f"  IF to_regclass('{t}') IS NOT NULL THEN\n"
        f"    IF EXISTS (SELECT 1 FROM {t}) THEN\n"
        f"      RAISE EXCEPTION '0169 downgrade refused: {t} holds measures (PM-02-02); they are never deleted';\n"
        f"    END IF;\n"
        f"  END IF;"
        for t in TABLES
    )
    op.execute(f"DO $refuse$\nBEGIN\n{checks}\nEND\n$refuse$")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
