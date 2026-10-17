"""data truth audit V2: the evidence ledger (E-XXX) and one row per audit run

* ``audit.evidence_ledger`` - one entry per established discrepancy: the claim, what the
  provider said (endpoint, parameters, RAW payload hash, values), what PrediGol holds, what an
  official or corroborating source says, who is at fault, the root cause, the fix and the test
  that pins it. Keyed by a stable ``key`` so a re-run updates ``last_seen_at``/``times_seen``
  instead of duplicating; an entry not reproduced by a later run of the same scope is CLEARED,
  never deleted.
* ``audit.truth_v2_runs`` - every V2 audit command run (standings, team stats, player stats,
  leagues, fixtures, identity, fields, golden): when, how many provider requests (each stored as
  a NEW raw payload under its ingestion run - existing RAW is never modified), the summary and
  the report folder. The admin Data Quality view reads it.

Nothing here changes a fact table: corrections go through audit.data_repairs or a new dataset
version, never a silent UPDATE.

Revision ID: 0056
Revises: 0055
"""

from __future__ import annotations

from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

AREAS = ("baseline", "leagues", "fixtures", "standings", "teams", "team_stats", "team_history", "players",
         "player_stats", "identity", "squads", "injuries", "coaches", "venues", "normalization", "golden", "odds")
ISSUES = ("PROVIDER_STALE", "NORMALIZER_BUG", "MAPPING_ERROR", "MISSING_BACKFILL", "STALE_ENTITY",
          "SEASON_MISMATCH", "STANDINGS_MISMATCH", "PLAYER_STATS_MISMATCH", "TEAM_STATS_MISMATCH",
          "WRONG_SEASON", "MISSING_SEASON", "DUPLICATE_COMPETITION", "WRONG_TYPE", "WRONG_COUNTRY",
          "STALE_CURRENT_SEASON", "REAL_LOW_HISTORY", "PROVIDER_COVERAGE", "IDENTITY_MAPPING_ERROR",
          "SEASON_NOT_MIGRATED", "DROPPED_USEFUL_FIELD", "UNSUPPORTED_FIELD", "INTENTIONALLY_IGNORED",
          "PROVIDER_DEFINED_METRIC", "FIXTURE_MISMATCH", "RESULT_MISMATCH", "PROVIDER_EXTERNAL_MISMATCH",
          "DUPLICATE_ENTITY", "PRODUCT_SCOPE")
KINDS = ("baseline", "leagues", "fixtures", "standings", "team_stats", "team_history", "player_stats", "identity",
         "fields", "golden", "external")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS audit.truth_v2_runs (
            id               BIGSERIAL   PRIMARY KEY,
            kind             TEXT        NOT NULL CHECK (kind IN ({_in(KINDS)})),
            started_at       TIMESTAMPTZ NOT NULL,
            finished_at      TIMESTAMPTZ,
            status           TEXT        NOT NULL DEFAULT 'running'
                             CHECK (status IN ('running', 'completed', 'partial', 'failed')),
            requests         INTEGER     NOT NULL DEFAULT 0 CHECK (requests >= 0),
            ingestion_run_id BIGINT      REFERENCES raw.ingestion_runs (id),
            code_version     TEXT,
            params           JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            summary          JSONB       NOT NULL DEFAULT '{{}}'::jsonb,
            report_dir       TEXT,
            CHECK ((status = 'running') = (finished_at IS NULL))
        );
        CREATE INDEX IF NOT EXISTS truth_v2_runs_kind ON audit.truth_v2_runs (kind, started_at DESC);

        CREATE TABLE IF NOT EXISTS audit.evidence_ledger (
            id                BIGSERIAL   PRIMARY KEY,
            code              TEXT        GENERATED ALWAYS AS
                              ('E-' || CASE WHEN id < 1000 THEN lpad(id::text, 3, '0') ELSE id::text END) STORED,
            key               TEXT        NOT NULL UNIQUE,
            area              TEXT        NOT NULL CHECK (area IN ({_in(AREAS)})),
            issue_type        TEXT        NOT NULL CHECK (issue_type IN ({_in(ISSUES)})),
            severity          TEXT        NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
            at_fault          TEXT        NOT NULL CHECK (at_fault IN ('provider', 'predigol', 'none', 'undetermined')),
            entity            TEXT,
            claim             TEXT        NOT NULL,
            api_evidence      JSONB,
            db_evidence       JSONB,
            external_evidence JSONB,
            root_cause        TEXT,
            fix               TEXT,
            test              TEXT,
            status            TEXT        NOT NULL DEFAULT 'OPEN'
                              CHECK (status IN ('OPEN', 'FIXED', 'ACCEPTED', 'MONITOR', 'CLEARED')),
            first_seen_at     TIMESTAMPTZ NOT NULL,
            last_seen_at      TIMESTAMPTZ NOT NULL,
            times_seen        INTEGER     NOT NULL DEFAULT 1 CHECK (times_seen >= 1),
            cleared_at        TIMESTAMPTZ,
            last_run_id       BIGINT      REFERENCES audit.truth_v2_runs (id),
            CHECK (last_seen_at >= first_seen_at),
            CHECK ((status = 'CLEARED') = (cleared_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS evidence_ledger_code ON audit.evidence_ledger (code);
        CREATE INDEX IF NOT EXISTS evidence_ledger_open ON audit.evidence_ledger (area, status, severity);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.evidence_ledger; DROP TABLE IF EXISTS audit.truth_v2_runs;")
