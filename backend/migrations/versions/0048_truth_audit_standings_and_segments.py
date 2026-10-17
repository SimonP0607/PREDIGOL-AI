"""the truth audit's ledger, the whole league table, and the segments of football

Three things the data-truth gate needs a place for.

1. ``audit.truth_runs`` / ``audit.truth_findings``: each run of the API-vs-database
   audit (``scripts/truth_audit.py``), its sample, its per-dataset summary and every
   disagreement it kept, so the Admin Console can show the last audit and the next
   one can be compared with it.

2. ``core.standings`` kept rank, points and the all-matches totals, and dropped the
   rest of each row: goal difference, the provider's zone description
   ("Promotion - Champions League"), its up/down marker, the home and away split and
   the provider's own ``update`` time. They are stored from now on. And the key had no
   group, so a team listed in two tables of one season at the same instant (a
   conference and an overall table) kept only the first: ``group_key`` joins the key.

3. ``core.competitions.gender`` and ``age_group``, generated from the name with the
   patterns in ``fbi.catalog.segments`` - the provider has neither field, and a
   women's league or a U21 tournament pooled with the Premier League describes none
   of them.

Revision ID: 0048
Revises: 0047
"""

from __future__ import annotations

from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

WOMEN = (r"(women|woman|femin|fémin|frauen|damen|ladies|\mwsl\M|damallsvenskan|nwsl|"
         r"femenil|femenina|feminino|kvinner|naiset|\mliga f\M)")
YOUTH = r"(\mu-?(1[3-9]|2[0-3])\M|youth|junior|primavera|juvenil|\msub-?(1[3-9]|2[0-3])\M)"

SIDES = ("home", "away")
SPLIT = ("played", "wins", "draws", "losses", "goals_for", "goals_against")


def upgrade() -> None:
    # 1. the audit's ledger
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.truth_runs (
            id           BIGSERIAL PRIMARY KEY,
            started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at  TIMESTAMPTZ,
            status       TEXT NOT NULL DEFAULT 'running'
                         CHECK (status IN ('running', 'completed', 'partial', 'failed', 'interrupted')),
            requests     INTEGER NOT NULL DEFAULT 0 CHECK (requests >= 0),
            ingestion_run_id BIGINT REFERENCES raw.ingestion_runs(id),
            seed         DOUBLE PRECISION,
            sample       JSONB NOT NULL DEFAULT '{}'::jsonb,
            summary      JSONB NOT NULL DEFAULT '{}'::jsonb,
            report_dir   TEXT,
            code_version TEXT,
            notes        TEXT
        )""")
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.truth_findings (
            id        BIGSERIAL PRIMARY KEY,
            run_id    BIGINT NOT NULL REFERENCES audit.truth_runs(id) ON DELETE CASCADE,
            dataset   TEXT NOT NULL,
            entity    TEXT NOT NULL,
            field     TEXT NOT NULL,
            kind      TEXT NOT NULL CHECK (kind IN ('mismatch', 'missing_in_db', 'missing_in_api', 'not_stored',
                                                    'stale', 'provider_lag', 'inconsistent')),
            severity  TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
            api_value TEXT,
            db_value  TEXT,
            note      TEXT NOT NULL DEFAULT ''
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS truth_findings_run ON audit.truth_findings (run_id, dataset, severity)")

    # 2. the whole league-table row
    cols = ["goals_diff SMALLINT", "zone_status TEXT", "description TEXT", "provider_updated_at TIMESTAMPTZ",
            "payload_hash TEXT"]
    cols += [f"{side}_{name} SMALLINT" for side in SIDES for name in SPLIT]
    for col in cols:
        op.execute(f"ALTER TABLE core.standings ADD COLUMN IF NOT EXISTS {col}")
    op.execute("ALTER TABLE core.standings ADD COLUMN IF NOT EXISTS group_key TEXT "
               "GENERATED ALWAYS AS (COALESCE(\"group\", '')) STORED")
    op.execute("ALTER TABLE core.standings DROP CONSTRAINT IF EXISTS standings_pkey")
    op.execute("ALTER TABLE core.standings ADD CONSTRAINT standings_pkey "
               "PRIMARY KEY (competition_season_id, team_id, snapshot_at, group_key)")
    op.execute("COMMENT ON COLUMN core.standings.provider_updated_at IS "
               "'The provider''s own update stamp for the row (it states a date, at midnight UTC).'")
    op.execute("COMMENT ON COLUMN core.standings.zone_status IS "
               "'The provider''s movement marker: same, up or down.'")

    # 2b. when each season's context was last asked for, whatever the answer was. An
    # unchanged table hashes to the payload already stored, so no new snapshot row is
    # written and the snapshot time alone cannot tell "asked an hour ago, nothing new"
    # from "not asked for a week".
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.context_checks (
            competition_season_id BIGINT NOT NULL REFERENCES core.competition_seasons(id),
            dataset      TEXT NOT NULL CHECK (dataset IN ('standings', 'injuries', 'teams', 'squads', 'players')),
            checked_at   TIMESTAMPTZ NOT NULL,
            payload_hash TEXT,
            rows_seen    INTEGER,
            rows_skipped INTEGER NOT NULL DEFAULT 0,
            changed_at   TIMESTAMPTZ,
            PRIMARY KEY (competition_season_id, dataset)
        )""")
    op.execute("COMMENT ON TABLE core.context_checks IS "
               "'Last time each dataset of a competition-season was requested, and when its content last changed.'")

    # 3. the segments of football
    op.execute(f"ALTER TABLE core.competitions ADD COLUMN IF NOT EXISTS gender TEXT "
               f"GENERATED ALWAYS AS (CASE WHEN name ~* '{WOMEN}' THEN 'women' ELSE 'men' END) STORED")
    op.execute(f"ALTER TABLE core.competitions ADD COLUMN IF NOT EXISTS age_group TEXT "
               f"GENERATED ALWAYS AS (CASE WHEN name ~* '{YOUTH}' THEN 'youth' ELSE 'senior' END) STORED")


def downgrade() -> None:
    op.execute("ALTER TABLE core.competitions DROP COLUMN IF EXISTS age_group")
    op.execute("ALTER TABLE core.competitions DROP COLUMN IF EXISTS gender")
    op.execute("ALTER TABLE core.standings DROP CONSTRAINT IF EXISTS standings_pkey")
    # Rows that differ only by group cannot share the old key; keep the first of each.
    op.execute("""DELETE FROM core.standings s USING core.standings t
                   WHERE s.competition_season_id = t.competition_season_id AND s.team_id = t.team_id
                     AND s.snapshot_at = t.snapshot_at AND s.group_key > t.group_key""")
    op.execute("ALTER TABLE core.standings DROP COLUMN IF EXISTS group_key")
    op.execute("ALTER TABLE core.standings ADD CONSTRAINT standings_pkey "
               "PRIMARY KEY (competition_season_id, team_id, snapshot_at)")
    for side in SIDES:
        for name in SPLIT:
            op.execute(f"ALTER TABLE core.standings DROP COLUMN IF EXISTS {side}_{name}")
    for col in ("payload_hash", "provider_updated_at", "description", "zone_status", "goals_diff"):
        op.execute(f"ALTER TABLE core.standings DROP COLUMN IF EXISTS {col}")
    op.execute("DROP TABLE IF EXISTS core.context_checks")
    op.execute("DROP TABLE IF EXISTS audit.truth_findings")
    op.execute("DROP TABLE IF EXISTS audit.truth_runs")
