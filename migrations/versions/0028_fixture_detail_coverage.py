"""per-fixture detail coverage: what the provider actually delivered

THE RULE BEING ENFORCED
-----------------------
    "fixture exists" is NOT proof that "fixture details exist"

and the corollary the planner got wrong for months: a ``fixtures_season`` unit
marked done is not proof that any detail unit ever ran. 1,893 played fixtures had
no detail of any kind while every task row said the season was complete.

There were three separate holes, and only a per-dataset record closes them:

1. ``seed_plan`` only expanded detail batches when the fixtures unit was NEWLY
   created. A season whose fixtures a previous plan had already stored took the
   other branch and never got detail units at all.
2. ``expand_detail_batches`` read "covered" from the batch keys of
   ``raw.backfill_tasks`` regardless of their STATUS, so a batch that was pending,
   failed or refused still counted as covered and was never regenerated.
3. Nothing recorded what a detail payload actually CARRIED. ``/fixtures?ids=``
   returns events, line-ups, statistics and player statistics inline, but a
   league-season without ``lineups`` coverage simply has no line-ups block. An
   empty table then meant either "the provider does not publish this", "we never
   asked", or "we asked and it failed" - three very different things that looked
   identical.

WHAT THIS TABLE IS
------------------
``core.fixture_detail_coverage``: one row per fixture, source and dataset,
recording whether the payload carried the block at all and how many rows came
out of it, with the payload hash and the instant.

That turns the planner's question from a guess into a query:

  * no row for (fixture, dataset)        -> never fetched, REQUEST IT
  * row with block_present = false       -> the provider did not publish it.
                                            Do NOT ask again; it is a fact about
                                            their data, recorded as MISSING_DETAIL.
  * row with rows_written = 0 but present -> the block came empty. Also a fact.

Quota matters here: without the distinction, "regenerate what is missing" would
re-request every fixture the provider does not cover, for ever.

Revision ID: 0028
Revises: 0027
"""

from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

UPGRADE = """
CREATE TABLE core.fixture_detail_coverage (
    fixture_id    BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
    source        TEXT        NOT NULL CHECK (source IN ('api-football')),
    dataset       TEXT        NOT NULL CHECK (dataset IN
                  ('events','lineups','team_statistics','player_statistics')),
    block_present BOOLEAN     NOT NULL,
    rows_written  INTEGER     NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
    payload_hash  TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
    fetched_at    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (fixture_id, source, dataset),
    CONSTRAINT detail_coverage_absent_block_has_no_rows
        CHECK (block_present OR rows_written = 0)
);
COMMENT ON TABLE core.fixture_detail_coverage IS
  'Lo que el payload de detalle TRAJO de verdad, por fixture y dataset. Sin esto,
   una tabla vacia significaba indistintamente "el proveedor no lo publica", "no
   lo hemos pedido nunca" y "lo pedimos y fallo".';
COMMENT ON COLUMN core.fixture_detail_coverage.block_present IS
  'false = el payload no traia el bloque. Es un hecho sobre los datos del
   proveedor: se registra como MISSING_DETAIL y NO se vuelve a pedir, porque
   reintentarlo gastaria cuota indefinidamente.';
COMMENT ON COLUMN core.fixture_detail_coverage.rows_written IS
  'Filas normalizadas de ese bloque para este partido. 0 con block_present=true
   significa que el bloque llego vacio, que tampoco es lo mismo que no llegar.';

CREATE INDEX fixture_detail_coverage_dataset
    ON core.fixture_detail_coverage (dataset, block_present, rows_written);

-- Lo que falta, por competicion, temporada y dataset, con el denominador a la vista.
CREATE VIEW core.detail_completeness AS
SELECT c.provider_league_id,
       cs.season,
       c.tier,
       d.dataset,
       count(*)                                                        AS played,
       count(cov.fixture_id)                                           AS fetched,
       count(*) FILTER (WHERE cov.block_present)                       AS delivered,
       count(*) FILTER (WHERE cov.block_present AND cov.rows_written > 0) AS with_rows,
       count(*) FILTER (WHERE cov.fixture_id IS NULL)                  AS never_fetched,
       count(*) FILTER (WHERE cov.fixture_id IS NOT NULL AND NOT cov.block_present) AS not_published,
       lc.events, lc.lineups, lc.statistics_fixtures, lc.statistics_players
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 CROSS JOIN (VALUES ('events'),('lineups'),('team_statistics'),('player_statistics')) AS d(dataset)
  LEFT JOIN core.fixture_detail_coverage cov
         ON cov.fixture_id = f.id AND cov.dataset = d.dataset AND cov.source = 'api-football'
  LEFT JOIN raw.league_coverage lc
         ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE f.status_group = 'finished'
 GROUP BY c.provider_league_id, cs.season, c.tier, d.dataset,
          lc.events, lc.lineups, lc.statistics_fixtures, lc.statistics_players;
COMMENT ON VIEW core.detail_completeness IS
  'played es el denominador: partidos jugados. Si played = 0 no hay porcentaje
   que calcular, y la vista no inventa uno. never_fetched es lo unico que el
   planner debe pedir; not_published es un hecho del proveedor.';
"""

DOWNGRADE = """
DROP VIEW IF EXISTS core.detail_completeness;
DROP TABLE IF EXISTS core.fixture_detail_coverage;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
