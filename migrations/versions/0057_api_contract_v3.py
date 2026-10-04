"""API-Football v3 data contract: audit kinds for phases, the API contract and field coverage, and dataset versions

* ``audit.truth_v2_runs.kind`` and ``audit.evidence_ledger.area`` / ``issue_type`` accept the new
  audits: competition phases (a season's tables mapped to its stages; the Match Center once mixed
  Apertura and Clausura rows), the API contract (every documented endpoint, parameter and field
  against what PrediGol requests and stores) and field coverage (API -> RAW -> normalizer -> DB ->
  product -> model, each field classed STORED_AND_USED ... BUG_DROPPED_FIELD).
* ``audit.dataset_versions`` - a named version of the analytical dataset: the one the models were
  trained on before the data-truth audits (``PRE_DATA_TRUTH_AUDIT``, kept as it is) and each new
  version rebuilt from RAW (``DATASET_V2`` ...), with what it was built from, its counts, its gates
  and whether models may read it (``model_ready``). Only a version declared MODEL_READY may feed a
  model; none is, until the audits close.

Nothing here changes a fact table.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

AREAS_0056 = ("baseline", "leagues", "fixtures", "standings", "teams", "team_stats", "team_history", "players",
              "player_stats", "identity", "squads", "injuries", "coaches", "venues", "normalization", "golden", "odds")
AREAS = (*AREAS_0056, "phases", "api_contract", "field_coverage", "predictions", "transfers", "trophies", "sidelined",
         "h2h", "media", "datasets")
ISSUES_0056 = ("PROVIDER_STALE", "NORMALIZER_BUG", "MAPPING_ERROR", "MISSING_BACKFILL", "STALE_ENTITY",
               "SEASON_MISMATCH", "STANDINGS_MISMATCH", "PLAYER_STATS_MISMATCH", "TEAM_STATS_MISMATCH",
               "WRONG_SEASON", "MISSING_SEASON", "DUPLICATE_COMPETITION", "WRONG_TYPE", "WRONG_COUNTRY",
               "STALE_CURRENT_SEASON", "REAL_LOW_HISTORY", "PROVIDER_COVERAGE", "IDENTITY_MAPPING_ERROR",
               "SEASON_NOT_MIGRATED", "DROPPED_USEFUL_FIELD", "UNSUPPORTED_FIELD", "INTENTIONALLY_IGNORED",
               "PROVIDER_DEFINED_METRIC", "FIXTURE_MISMATCH", "RESULT_MISMATCH", "PROVIDER_EXTERNAL_MISMATCH",
               "DUPLICATE_ENTITY", "PRODUCT_SCOPE")
ISSUES = (*ISSUES_0056, "PHASE_TABLE_MIXED", "PHASE_TABLE_UNMAPPED", "BUG_DROPPED_FIELD", "STORED_NOT_USED",
          "API_CONTRACT_GAP", "MISSING_ENDPOINT")
KINDS_0056 = ("baseline", "leagues", "fixtures", "standings", "team_stats", "team_history", "player_stats", "identity",
              "fields", "golden", "external")
KINDS = (*KINDS_0056, "phases", "api_contract", "field_coverage", "teams", "players", "data_truth", "datasets")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _checks(kinds: tuple[str, ...], areas: tuple[str, ...], issues: tuple[str, ...]) -> None:
    op.execute(f"""
        ALTER TABLE audit.truth_v2_runs DROP CONSTRAINT IF EXISTS truth_v2_runs_kind_check;
        ALTER TABLE audit.truth_v2_runs ADD CONSTRAINT truth_v2_runs_kind_check CHECK (kind IN ({_in(kinds)}));
        ALTER TABLE audit.evidence_ledger DROP CONSTRAINT IF EXISTS evidence_ledger_area_check;
        ALTER TABLE audit.evidence_ledger ADD CONSTRAINT evidence_ledger_area_check CHECK (area IN ({_in(areas)}));
        ALTER TABLE audit.evidence_ledger DROP CONSTRAINT IF EXISTS evidence_ledger_issue_type_check;
        ALTER TABLE audit.evidence_ledger ADD CONSTRAINT evidence_ledger_issue_type_check
            CHECK (issue_type IN ({_in(issues)}));
    """)


def upgrade() -> None:
    _checks(KINDS, AREAS, ISSUES)
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.dataset_versions (
            name          TEXT        PRIMARY KEY CHECK (name ~ '^[A-Z][A-Z0-9_]{2,63}$'),
            status        TEXT        NOT NULL
                          CHECK (status IN ('LEGACY', 'BUILDING', 'CANDIDATE', 'VALIDATED', 'MODEL_READY', 'REJECTED')),
            model_ready   BOOLEAN     NOT NULL DEFAULT false,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            built_from    TEXT        NOT NULL,
            code_version  TEXT,
            counts        JSONB       NOT NULL DEFAULT '{}'::jsonb,
            gates         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            notes         TEXT        NOT NULL DEFAULT '',
            promoted_at   TIMESTAMPTZ,
            CHECK (model_ready = (status = 'MODEL_READY')),
            CHECK ((status = 'MODEL_READY') = (promoted_at IS NOT NULL))
        )""")
    op.execute("""
        INSERT INTO audit.dataset_versions (name, status, model_ready, built_from, notes)
        VALUES ('PRE_DATA_TRUTH_AUDIT', 'LEGACY', false,
                'core.* and analytics.* as normalized before the data-truth audits (backup pre-api-contract-v3, '
                '4 Oct 2026); the models in models.model_versions were trained on it',
                'Kept unchanged as the reference. Known defects are in the evidence ledger (audit.evidence_ledger) '
                'and audit.data_repairs; corrections go to a new version rebuilt from RAW, never into this one.')
        ON CONFLICT (name) DO NOTHING""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.dataset_versions")
    _checks(KINDS_0056, AREAS_0056, ISSUES_0056)
