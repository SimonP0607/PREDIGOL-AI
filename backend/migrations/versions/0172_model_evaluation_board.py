"""The private evaluation of the models by competition and coverage level, and the weekly board (plan PM, PM-12-06 and PM-12-01)

WHY THIS EXISTS
---------------
The models are judged on the backtest as a whole, never by competition (H-EST-01), and the leagues added lately have little history of
their own. A weekly batch (PM-12-06, the code after this revision, behind a switch that is born off) scores the forecasts already stored
(``models.match_forecasts``, ``models.predictions``, ``analytics.backtest_samples``) against the results, by competition and by the
matrix's coverage level, and says for each competition whether its own sample is enough to authorise a probability there. The weekly
board of PM-12-01 (reliability and resolution apart, model against market and provider) keeps its report next to it. Reads predictions
and results; changes no pick, model, threshold or forecast.

analytics.evaluation_reports
----------------------------
One row per computed report: ``kind`` (``segments`` PM-12-06, ``weekly`` PM-12-01), the rules' ``version``, the period of kick-offs
it covers (``period_from``, ``period_to``, Bogotá days), when it was computed, the code that computed it and its ``body`` (what the
owner's board shows: counts, intervals, the reproduction checks). Append-only; the same kind, version and last day once.

analytics.evaluation_segments
-----------------------------
One row per report, source (``forecast`` = what a reader is shown, ``prediction`` = each model's own figure, ``backtest`` = a LAB
session), model, market and line, and segment (``global``, ``competition`` with the competition's id, ``level`` with the summary level
of the matrix): the matches ``n`` and days, the mean log loss with its 95 % interval (whole days resampled), Brier, RPS (1X2), the skill
against the segment's own frequencies (log loss difference, negative is better) with its interval, and the verdict
(``apta``, ``sin_habilidad``, ``insuficiente``). Append-only.

Additive only: two new tables, no foreign key outside them (no lock on any existing table), no row written. Privileges:
``deploy/vps/db/grants.sql`` - the worker appends (INSERT; never UPDATE or DELETE), the API reads. Downgrade drops them only while they
are empty: it never deletes a measure.

Revision ID: 0172
Revises: 0171
"""

from __future__ import annotations

from alembic import op

revision = "0172"
down_revision = "0171"
branch_labels = None
depends_on = None

REPORTS = "analytics.evaluation_reports"
SEGMENTS = "analytics.evaluation_segments"
_VERSION = r"~ '^[a-z][a-z0-9-]{1,40}-v[0-9]+$'"
_SCORE = "NUMERIC(10,6)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(rf"""
        CREATE TABLE {REPORTS} (
            id             BIGSERIAL     PRIMARY KEY,
            kind           TEXT          NOT NULL CHECK (kind IN ('segments', 'weekly')),
            version        TEXT          NOT NULL CHECK (version {_VERSION}),
            period_from    DATE          NOT NULL,
            period_to      DATE          NOT NULL,
            computed_at    TIMESTAMPTZ   NOT NULL,
            code_version   TEXT          NOT NULL CHECK (char_length(code_version) BETWEEN 1 AND 64),
            body           JSONB         NOT NULL,
            UNIQUE (kind, version, period_to),
            CHECK (period_from <= period_to)
        );
        COMMENT ON TABLE {REPORTS} IS
          'PM-12-06 and PM-12-01: one computed evaluation report (segments by competition and coverage level; the weekly board). '
          'Append-only, written by the weekly batch; read by the owner''s private board. It changes no pick, model or forecast.';

        CREATE TABLE {SEGMENTS} (
            id             BIGSERIAL     PRIMARY KEY,
            report_id      BIGINT        NOT NULL REFERENCES {REPORTS}(id),
            source         TEXT          NOT NULL CHECK (source IN ('forecast', 'prediction', 'backtest')),
            model_name     TEXT          NOT NULL CHECK (char_length(model_name) BETWEEN 1 AND 80),
            market_key     TEXT          NOT NULL CHECK (market_key ~ '^[A-Za-z0-9][A-Za-z0-9_.]{{0,63}}$'),
            line           NUMERIC(6,2)  NOT NULL DEFAULT 0,
            segment_kind   TEXT          NOT NULL CHECK (segment_kind IN ('global', 'competition', 'level')),
            segment_key    TEXT          NOT NULL CHECK (char_length(segment_key) BETWEEN 1 AND 40),
            n              INTEGER       NOT NULL CHECK (n >= 1),
            days           INTEGER       NOT NULL CHECK (days >= 1 AND days <= n),
            log_loss       {_SCORE}      NOT NULL CHECK (log_loss >= 0),
            log_loss_low   {_SCORE},
            log_loss_high  {_SCORE},
            brier          {_SCORE}      NOT NULL CHECK (brier >= 0 AND brier <= 2),
            rps            {_SCORE}      CHECK (rps >= 0 AND rps <= 1),
            skill          {_SCORE}      NOT NULL,
            skill_low      {_SCORE},
            skill_high     {_SCORE},
            verdict        TEXT          NOT NULL CHECK (verdict IN ('apta', 'sin_habilidad', 'insuficiente')),
            UNIQUE (report_id, source, model_name, market_key, line, segment_kind, segment_key),
            CHECK ((log_loss_low IS NULL) = (log_loss_high IS NULL) AND (skill_low IS NULL) = (skill_high IS NULL)),
            CHECK (verdict <> 'apta' OR (skill_high IS NOT NULL AND skill_high < 0))
        );
        CREATE INDEX evaluation_segments_lookup ON {SEGMENTS} (segment_kind, segment_key, source, report_id);
        COMMENT ON TABLE {SEGMENTS} IS
          'PM-12-06: the scores of a report by source, model, market and segment (global, competition, coverage level), with the '
          'sample, 95 % intervals over whole days and the verdict of the competition''s own sample (segments-v1). Append-only.';
    """)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # Never deletes a measure: empty tables (a test database, a deploy rolled back the same minute) are dropped; rows stop the downgrade.
    for table in (SEGMENTS, REPORTS):
        op.execute(
            "DO $refuse$\nBEGIN\n"
            f"  IF to_regclass('{table}') IS NOT NULL THEN\n"
            f"    IF EXISTS (SELECT 1 FROM {table}) THEN\n"
            f"      RAISE EXCEPTION '0172 downgrade refused: {table} holds measures (PM-12-06); they are never deleted';\n"
            "    END IF;\n"
            "  END IF;\n"
            "END\n$refuse$"
        )
    op.execute(f"DROP TABLE IF EXISTS {SEGMENTS}")
    op.execute(f"DROP TABLE IF EXISTS {REPORTS}")
