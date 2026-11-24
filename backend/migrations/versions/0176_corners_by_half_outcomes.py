"""market.fixture_outcomes learns the corners of each half (plan PM, PM-05-03, OP-06)

WHY THIS EXISTS
---------------
The settlement rules ``corners_1h@v1`` and ``corners_2h@v1`` were written as «not available»: the provider was believed to give corners only
as a total of the match. It gives them by half (``GET /fixtures/statistics?half=true``, the probe of PM-01-05), and PM-05-01 keeps them in
``core.fixture_team_stats_period``. A rule is never edited, so the new reading is a new version of the same two measures
(``corners_1h@v2``, ``corners_2h@v2``, ``fbi.market.rules``), and the columns it reads are born here, in the view every rule reads.

WHAT CHANGES
------------
Four columns are appended to the view, after every existing one (``CREATE OR REPLACE VIEW`` keeps the columns, their order, the grants and the
views that read it): ``corners_1h_home``, ``corners_1h_away``, ``corners_2h_home``, ``corners_2h_away``. A figure is KNOWN only when

* the match was asked and the four corner figures came (both teams, both halves: ``core.fixture_period_asks.filled`` has ``corners``), and
* the halves add up to the match total for corners (``sums_ok``): a half is never graded on a figure that contradicts the match's own, and
* for the second half, the match did not go to extra time (the provider does not say whether its second half includes the extra half hour).

Otherwise NULL, which means «not known», never zero - the rule of the whole view. The first half is not touched by extra time.

The view is rebuilt from the definition the database holds now (``pg_get_viewdef``) wrapped as a subquery, so no column of the original is retyped
here and none can be changed by accident. The statement is skipped when the columns already exist (it can be run twice). Additive: no table
changes, no row is written, ``lock_timeout`` 10 s. Downgrade does nothing: the extra columns are harmless to the code before this one, and
dropping them would need the view rebuilt without them.

Revision ID: 0176
Revises: 0175
"""

from __future__ import annotations

from alembic import op

revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None

VIEW = "market.fixture_outcomes"

HALVES = """
CREATE OR REPLACE VIEW market.fixture_outcomes AS
SELECT o.*,
       CASE WHEN c.known THEN c.c1h_home END AS corners_1h_home,
       CASE WHEN c.known THEN c.c1h_away END AS corners_1h_away,
       CASE WHEN c.known AND NOT o.extra_time THEN c.c2h_home END AS corners_2h_home,
       CASE WHEN c.known AND NOT o.extra_time THEN c.c2h_away END AS corners_2h_away
  FROM ({base}) o
  LEFT JOIN LATERAL (
        SELECT (count(p.corners) = 4 AND bool_or(a.fixture_id IS NOT NULL AND 'corners' = ANY(a.sums_ok))) AS known,
               max(p.corners) FILTER (WHERE p.period = '1h' AND p.team_side = 'home') AS c1h_home,
               max(p.corners) FILTER (WHERE p.period = '1h' AND p.team_side = 'away') AS c1h_away,
               max(p.corners) FILTER (WHERE p.period = '2h' AND p.team_side = 'home') AS c2h_home,
               max(p.corners) FILTER (WHERE p.period = '2h' AND p.team_side = 'away') AS c2h_away
          FROM core.fixture_team_stats_period p
          LEFT JOIN core.fixture_period_asks a ON a.fixture_id = p.fixture_id
         WHERE p.fixture_id = o.fixture_id AND p.source = 'api-football') c ON true
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    conn = op.get_bind()
    done = conn.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'market' AND table_name = 'fixture_outcomes' "
        "AND column_name = 'corners_1h_home'").first()
    if done is not None:
        return
    base = conn.exec_driver_sql(f"SELECT pg_get_viewdef('{VIEW}'::regclass, true)").scalar_one()
    conn.exec_driver_sql(HALVES.replace("{base}", str(base).strip().rstrip(";")))
    op.execute("""
        COMMENT ON VIEW market.fixture_outcomes IS
        'One row per finished match: every figure a settlement rule can read (market.settlement_rules.columns).
         Goals are the 90-minute score (core.fixture_results), halves from the half-time score (NULL when it is missing or
         impossible). Statistics are NULL after extra time. Cards by period come from core.fixture_event_kinds (events-v1); the
         match total falls back on the team statistics. Corners by half (PM-05-03) come from core.fixture_team_stats_period and are
         known only when the four figures came and the halves add up to the match total (the second half also not after extra
         time). NULL means not known, never zero. A view: no storage, never stale.'""")


def downgrade() -> None:
    """Nothing: the four columns are harmless to the code before this revision (see the module's docstring)."""
