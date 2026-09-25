"""historical migration: every unit of the paid backfill, resumable and priced in advance

raw.backfill_tasks held one kind of unit - a competition-season of fixtures,
one request each. A paid backfill needs more: the detail of each fixture
(events, lineups, statistics and player statistics come together, twenty
fixtures per request through /fixtures?ids=), standings, injuries, teams,
paginated player seasons and the provider's coverage flags. This widens the
same table rather than adding a second queue, so the worker's existing
resumable loop - and its live-capture reserve - drives all of it.

A unit now records the endpoint and parameters it will call, the page or the
batch of fixture ids, its tier, when it started, whether a failure is worth
retrying, the rows it wrote and the requests it spent. 'running' marks a unit
in flight: a unit left 'running' by a process that died is picked up again.

raw.migration_plans keeps each plan as computed - what it would cost before a
single request was made - so the estimate can be compared with what the
backfill actually spent.

Revision ID: 0023
Revises: 0022
"""

from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE raw.migration_plans (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT        NOT NULL,
    plan_hash     TEXT        NOT NULL UNIQUE,
    config        JSONB       NOT NULL,
    summary       JSONB       NOT NULL,
    code_version  TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE raw.migration_plans IS
  'A historical-migration plan as computed before spending: units, requests, days per plan, storage. Immutable.';

ALTER TABLE raw.backfill_tasks DROP CONSTRAINT backfill_tasks_kind_check;
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_kind_check CHECK (kind IN (
    'fixtures_season', 'fixture_details', 'standings_season', 'injuries_season',
    'teams_season', 'players_season', 'league_coverage'));
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT backfill_tasks_status_check;
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_status_check CHECK (status IN (
    'pending', 'running', 'done', 'refused', 'failed'));
ALTER TABLE raw.backfill_tasks
    ADD COLUMN endpoint        TEXT,
    ADD COLUMN params          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN page            INTEGER     CHECK (page >= 1),
    ADD COLUMN batch_key       TEXT,
    ADD COLUMN tier            SMALLINT    CHECK (tier BETWEEN 1 AND 9),
    ADD COLUMN plan_id         BIGINT      REFERENCES raw.migration_plans(id),
    ADD COLUMN started_at      TIMESTAMPTZ,
    ADD COLUMN retryable       BOOLEAN     NOT NULL DEFAULT true,
    ADD COLUMN rows_written    INTEGER     CHECK (rows_written >= 0),
    ADD COLUMN requests_spent  INTEGER     NOT NULL DEFAULT 0 CHECK (requests_spent >= 0);
UPDATE raw.backfill_tasks SET endpoint = '/fixtures',
       params = jsonb_build_object('league', provider_league_id, 'season', season)
 WHERE kind = 'fixtures_season';
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT backfill_tasks_provider_kind_provider_league_id_season_key;
CREATE UNIQUE INDEX backfill_tasks_unit_key ON raw.backfill_tasks
    (provider, kind, provider_league_id, season, COALESCE(page, 0), COALESCE(batch_key, ''));
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_running_has_start
    CHECK (status <> 'running' OR started_at IS NOT NULL);
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_details_have_batch
    CHECK (kind <> 'fixture_details' OR batch_key IS NOT NULL);
DROP INDEX IF EXISTS raw.backfill_tasks_pending_idx;
CREATE INDEX backfill_tasks_pending_idx ON raw.backfill_tasks (tier, priority, id)
    WHERE status IN ('pending', 'failed', 'running');
COMMENT ON COLUMN raw.backfill_tasks.batch_key IS
  'fixture_details: the provider fixture ids of the batch, joined by "-" (at most 20, the documented maximum).';
COMMENT ON COLUMN raw.backfill_tasks.retryable IS
  'false when retrying cannot help (the plan refuses the season, the competition is not catalogued).';
"""

DOWNGRADE = """
DELETE FROM raw.backfill_tasks WHERE kind <> 'fixtures_season';
UPDATE raw.backfill_tasks SET status = 'pending', started_at = NULL WHERE status = 'running';
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT IF EXISTS backfill_details_have_batch;
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT IF EXISTS backfill_running_has_start;
DROP INDEX IF EXISTS raw.backfill_tasks_pending_idx;
DROP INDEX IF EXISTS raw.backfill_tasks_unit_key;
ALTER TABLE raw.backfill_tasks
    DROP COLUMN requests_spent, DROP COLUMN rows_written, DROP COLUMN retryable, DROP COLUMN started_at,
    DROP COLUMN plan_id, DROP COLUMN tier, DROP COLUMN batch_key, DROP COLUMN page, DROP COLUMN params,
    DROP COLUMN endpoint;
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_provider_kind_provider_league_id_season_key
    UNIQUE (provider, kind, provider_league_id, season);
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT backfill_tasks_status_check;
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_status_check
    CHECK (status IN ('pending', 'done', 'refused', 'failed'));
ALTER TABLE raw.backfill_tasks DROP CONSTRAINT backfill_tasks_kind_check;
ALTER TABLE raw.backfill_tasks ADD CONSTRAINT backfill_tasks_kind_check CHECK (kind IN ('fixtures_season'));
CREATE INDEX backfill_tasks_pending_idx ON raw.backfill_tasks (priority, id) WHERE status IN ('pending','failed');
DROP TABLE IF EXISTS raw.migration_plans;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
