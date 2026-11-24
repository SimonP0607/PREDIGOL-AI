"""Team statistics by half and the register of what was asked for them (plan PM, PM-05-01, OP-06)

WHY THIS EXISTS
---------------
``core.fixture_team_stats`` holds the statistics of the whole match: it has no period. The provider answers ``GET /fixtures/statistics
?fixture=&half=true`` with, for each team, the match block (``statistics``) and two more, ``statistics_1h`` and ``statistics_2h``.
The one-week probe of PM-01-05 (``scripts.coverage_probe half``: finished matches of twelve competitions asked between
20 Oct and 24 Nov 2026) found both halves in every answer it got and, by type, corners, shots, cards, possession, saves and expected goals in both halves
for most competitions; fouls and red cards come empty in several (never as a zero). Which competitions and statistics are built is that
probe's decision (decision DM-13: at least 90 % of the matches asked carry the figure in both halves, with at least 5 asked).

core.fixture_team_stats_period
------------------------------
One row per match, side, half (``1h`` or ``2h``) and source: the same columns as ``core.fixture_team_stats`` (less ``goals_prevented``,
which the provider does not give by half). **NULL means the provider did not send the figure, never zero** (the same rule as the match
table); a negative count is the provider's error and is dropped, named in ``dropped_fields``. Four rows per match at most. Written with
the payload they came from (``payload_hash``) and replaced only by a payload fetched at the same instant or later (newest wins), as the
match table is. Nothing reads the table until ``FBI_STATS_BY_PERIOD`` (the writer, ``fbi.ingestion.period_stats``) and the readers the
plan adds behind their own switches are on.

core.fixture_period_asks
------------------------
One row per match asked: when, by which channel (``closing``: the worker's pass after the final whistle; ``backfill``: the night-time fill of
2024-2026, PM-05-02; ``probe``: the answers of PM-01-05 read back from RAW without a new request), what came back (``with_halves``:
every team with both halves; ``without_halves``: the answer lacks a half; ``empty``: no team), which statistics came filled for both
teams in both halves (``filled``) and which counted ones add up (first half + second half = match: ``sums_ok``) or not (``sums_off``).
Without it a match that answered nothing would be asked again forever, and the share of matches that carry a statistic by competition -
what decides which competitions and statistics are built (PM-05-01) and which corners of a half may be settled (PM-05-03) - would have to
be re-read from the RAW files.

Additive only: two new tables. The foreign keys are to ``core.fixtures`` and ``raw.ingestion_payloads`` (the match table's own), taken
under ``lock_timeout`` 10 s; no existing table changes and no row is written. Privileges: ``deploy/vps/db/grants.sql`` - the worker
inserts and updates (a match asked again is updated), never deletes; the API reads. Downgrade drops the tables only while they are empty:
a measure is never deleted.

Revision ID: 0175
Revises: 0174
"""

from __future__ import annotations

from alembic import op

revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None

PERIOD = "core.fixture_team_stats_period"
ASKS = "core.fixture_period_asks"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE {PERIOD} (
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            team_side           TEXT         NOT NULL CHECK (team_side IN ('home', 'away')),
            period              TEXT         NOT NULL CHECK (period IN ('1h', '2h')),
            source              TEXT         NOT NULL CHECK (source IN ('api-football')),
            shots               SMALLINT     CHECK (shots >= 0),
            shots_on_target     SMALLINT     CHECK (shots_on_target >= 0),
            shots_off_target    SMALLINT     CHECK (shots_off_target >= 0),
            shots_blocked       SMALLINT     CHECK (shots_blocked >= 0),
            shots_inside_box    SMALLINT     CHECK (shots_inside_box >= 0),
            shots_outside_box   SMALLINT     CHECK (shots_outside_box >= 0),
            corners             SMALLINT     CHECK (corners >= 0),
            fouls               SMALLINT     CHECK (fouls >= 0),
            offsides            SMALLINT     CHECK (offsides >= 0),
            yellow_cards        SMALLINT     CHECK (yellow_cards >= 0),
            red_cards           SMALLINT     CHECK (red_cards >= 0),
            saves               SMALLINT     CHECK (saves >= 0),
            possession_pct      NUMERIC(5,2) CHECK (possession_pct BETWEEN 0 AND 100),
            passes              SMALLINT     CHECK (passes >= 0),
            passes_accurate     SMALLINT     CHECK (passes_accurate >= 0),
            expected_goals      NUMERIC(6,3) CHECK (expected_goals >= 0),
            payload_hash        TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
            fetched_at          TIMESTAMPTZ  NOT NULL,
            dropped_fields      TEXT[]       NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (fixture_id, team_side, period, source),
            CHECK (shots_on_target IS NULL OR shots IS NULL OR shots_on_target <= shots),
            CHECK (passes_accurate IS NULL OR passes IS NULL OR passes_accurate <= passes)
        );
        COMMENT ON TABLE {PERIOD} IS
          'PM-05-01: team statistics of one half of a match (period 1h or 2h), from GET /fixtures/statistics?half=true. NULL means the '
          'provider did not send the figure - never zero. A negative count is dropped (dropped_fields). Written with the payload it '
          'came from; a payload fetched later replaces the row. Which competitions and statistics are published is decided by the '
          'share of matches asked that carry them (fbi.ingestion.period_stats, rule 90 percent and 5 matches); nothing reads this '
          'table behind a switch that is off.';

        CREATE TABLE {ASKS} (
            fixture_id    BIGINT       PRIMARY KEY REFERENCES core.fixtures(id) ON DELETE CASCADE,
            channel       TEXT         NOT NULL CHECK (channel IN ('closing', 'backfill', 'probe')),
            asked_at      TIMESTAMPTZ  NOT NULL,
            outcome       TEXT         NOT NULL CHECK (outcome IN ('with_halves', 'without_halves', 'empty')),
            filled        TEXT[]       NOT NULL DEFAULT '{{}}',
            sums_ok       TEXT[]       NOT NULL DEFAULT '{{}}',
            sums_off      TEXT[]       NOT NULL DEFAULT '{{}}',
            payload_hash  TEXT         REFERENCES raw.ingestion_payloads(hash),
            run_id        BIGINT
        );
        CREATE INDEX fixture_period_asks_when ON {ASKS} (asked_at);
        COMMENT ON TABLE {ASKS} IS
          'PM-05-01 and PM-05-02: each match whose halves were asked of the provider, once (asking again updates the row): by which '
          'channel (closing, backfill, probe = the PM-01-05 answers read back from RAW), what came back, which statistics came filled '
          'for both teams in both halves (filled) and which counted ones add up to the match total (sums_ok) or do not (sums_off). '
          'The share of matches asked by competition decides what is built (DM-13).';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a measure: empty tables (a test database, a deploy rolled back the same minute) are dropped; rows stop the downgrade.
    for table in (ASKS, PERIOD):
        op.execute(
            "DO $refuse$\nBEGIN\n"
            f"  IF to_regclass('{table}') IS NOT NULL THEN\n"
            f"    IF EXISTS (SELECT 1 FROM {table}) THEN\n"
            f"      RAISE EXCEPTION '0175 downgrade refused: {table} holds measures (PM-05-01); they are never deleted';\n"
            "    END IF;\n"
            "  END IF;\n"
            "END\n$refuse$"
        )
    op.execute(f"DROP TABLE IF EXISTS {ASKS}")
    op.execute(f"DROP TABLE IF EXISTS {PERIOD}")
