"""the 90-minute score is read from the provider, not reconstructed by subtraction

WHAT WAS WRONG
--------------
Four columns settle the core markets, and all four derived the 90-minute score
the same way::

    goals - COALESCE(et_goals, 0)

``goals`` is the final score with extra time included and penalties excluded, so
subtracting what was scored in extra time looks like it must give the score at
90 minutes. It does - as long as ``extratime`` means "goals scored during extra
time". Measured across the 1,645 AET/PEN fixtures in the raw store that carry a
non-null extratime:

    goals == fulltime + extratime      1,557   extratime is the increment
    goals == extratime                    82   extratime is the RUNNING TOTAL
    neither                                4

In those 82 the subtraction yields 0, so a tie that stood 2-1 after ninety
minutes was stored as ``reg_goals 0-0`` and ``outcome_1x2 'Draw'``. **78 stored
results were wrong in the database**, along with their total_goals and btts.

The guard in the normaliser was written for this and missed it: it rejected
``et > goals`` but not ``et == goals``, which is the corruption's actual
signature. Separately, a ``PEN`` fixture with a null extratime - a tie that went
from ninety minutes straight to penalties, which the provider records by leaving
extratime null - was skipped entirely, so 6 Champions League ties had no result
row at all.

WHAT CHANGES
------------
The provider states the 90-minute score in ``score.fulltime``. It does not have
to be derived, and a value that is read cannot be wrong about the semantics of a
different field.

``ft_goals_home``   ``score.fulltime``, the 90-minute score as the provider gives
``ft_goals_away``   it. Nullable, because a payload from before this migration
                    does not carry it until it is reprocessed from the raw store.

The four generated columns now read::

    COALESCE(ft_goals, goals - COALESCE(et_goals, 0))

so a row with the stated score uses it, and a row without one keeps exactly the
behaviour it had. Nothing is invented: where neither is available the row is not
written at all, which is what the normaliser already did.

``fixture_results_ft_within_final`` is the invariant that would have caught this
class of fault in the first place: the score at ninety minutes cannot exceed the
final score.

The raw payloads are untouched. This corrects a DERIVED table from bytes already
on disk - no provider request, and no snapshot rewritten.

Revision ID: 0031
Revises: 0030
"""

from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

# One expression, named once. Four columns repeating a subtraction is how three of
# them stayed wrong after anyone thought about the fourth.
REG_HOME = "COALESCE(ft_goals_home, goals_home - COALESCE(et_goals_home, 0))"
REG_AWAY = "COALESCE(ft_goals_away, goals_away - COALESCE(et_goals_away, 0))"

UPGRADE = f"""
ALTER TABLE core.fixture_results
    ADD COLUMN ft_goals_home SMALLINT,
    ADD COLUMN ft_goals_away SMALLINT;

COMMENT ON COLUMN core.fixture_results.ft_goals_home IS
  'The provider''s score.fulltime: the score after 90 minutes, as stated rather than '
  'derived. NULL on a row whose payload predates this column and has not been reprocessed.';

ALTER TABLE core.fixture_results
    ADD CONSTRAINT fixture_results_ft_within_final CHECK (
        (ft_goals_home IS NULL OR ft_goals_home <= goals_home)
        AND (ft_goals_away IS NULL OR ft_goals_away <= goals_away));

ALTER TABLE core.fixture_results
    DROP COLUMN reg_goals_home, DROP COLUMN reg_goals_away,
    DROP COLUMN outcome_1x2, DROP COLUMN total_goals, DROP COLUMN btts;

ALTER TABLE core.fixture_results
    ADD COLUMN reg_goals_home SMALLINT GENERATED ALWAYS AS ({REG_HOME}) STORED,
    ADD COLUMN reg_goals_away SMALLINT GENERATED ALWAYS AS ({REG_AWAY}) STORED,
    ADD COLUMN outcome_1x2 TEXT GENERATED ALWAYS AS (
        CASE WHEN {REG_HOME} > {REG_AWAY} THEN 'Home'
             WHEN {REG_HOME} = {REG_AWAY} THEN 'Draw'
             ELSE 'Away' END) STORED,
    ADD COLUMN total_goals SMALLINT GENERATED ALWAYS AS ({REG_HOME} + {REG_AWAY}) STORED,
    ADD COLUMN btts BOOLEAN GENERATED ALWAYS AS ({REG_HOME} > 0 AND {REG_AWAY} > 0) STORED;

COMMENT ON COLUMN core.fixture_results.reg_goals_home IS
  'Regulation (90 minutes + stoppage) score: what 1X2, Over/Under and BTTS settle on. '
  'Reads the provider''s stated fulltime when present, and only falls back to '
  'goals - extratime when it is absent - because extratime is the running total rather '
  'than the increment on about 5% of the provider''s extra-time fixtures.';
"""

DOWNGRADE = """
ALTER TABLE core.fixture_results
    DROP COLUMN reg_goals_home, DROP COLUMN reg_goals_away,
    DROP COLUMN outcome_1x2, DROP COLUMN total_goals, DROP COLUMN btts;

ALTER TABLE core.fixture_results
    ADD COLUMN reg_goals_home SMALLINT GENERATED ALWAYS AS (goals_home - COALESCE(et_goals_home, 0)) STORED,
    ADD COLUMN reg_goals_away SMALLINT GENERATED ALWAYS AS (goals_away - COALESCE(et_goals_away, 0)) STORED,
    ADD COLUMN outcome_1x2 TEXT GENERATED ALWAYS AS (
        CASE WHEN goals_home - COALESCE(et_goals_home, 0) > goals_away - COALESCE(et_goals_away, 0) THEN 'Home'
             WHEN goals_home - COALESCE(et_goals_home, 0) = goals_away - COALESCE(et_goals_away, 0) THEN 'Draw'
             ELSE 'Away' END) STORED,
    ADD COLUMN total_goals SMALLINT GENERATED ALWAYS AS (
        goals_home - COALESCE(et_goals_home, 0) + goals_away - COALESCE(et_goals_away, 0)) STORED,
    ADD COLUMN btts BOOLEAN GENERATED ALWAYS AS (
        goals_home - COALESCE(et_goals_home, 0) > 0 AND goals_away - COALESCE(et_goals_away, 0) > 0) STORED;

ALTER TABLE core.fixture_results DROP CONSTRAINT fixture_results_ft_within_final;
ALTER TABLE core.fixture_results DROP COLUMN ft_goals_home, DROP COLUMN ft_goals_away;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
