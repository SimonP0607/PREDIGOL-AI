"""The registry of models accepts the family of counts (plan F10)

WHY THIS EXISTS
---------------
F10 adds models of a different kind from the ones the platform has: they do not price the goals of the match from one score matrix, they
forecast a COUNT - the goals of each half, the corners, the cards - with a negative binomial per team (``fbi.families``). A forecast of
the platform is stored in ``models.match_forecasts`` (F5), and every row there names the model version that made it
(``model_version_id``, NOT NULL, a foreign key to ``models.model_versions``). A version belongs to a model of ``models.model_registry``,
and the registry only knew five families (``baseline``, ``rating``, ``goals``, ``ml``, ``ensemble``): a model of corners is none of them,
and calling it ``goals`` or ``ml`` would put it among models it has nothing in common with in every page that groups by family.

WHAT CHANGES
------------
One CHECK constraint of one small table: ``models.model_registry.family`` also accepts ``counts``. No row is written; the five models
that run today keep their family and their versions. The models of counts are registered at run time by ``fbi.families.versioning``,
in the registry and with a version keyed by the fingerprint of the code of ``fbi.families`` (a change there is a new version, the way
``mc...`` does it for the goal models), and they are stored in the forecast table under a version of their own, which the page of
the forecast of a match does not read: they are research, in SHADOW, until the gate of the plan says otherwise.

Downgrade: removes what the new family holds - its forecasts (the table is append-only; the guard is lifted for this session, the way
a maintenance session does), its versions and its registry rows - and restores the old constraint. Nothing else can depend on them: the
models of counts write nowhere else.
"""

from alembic import op

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

OLD = "'baseline', 'rating', 'goals', 'ml', 'ensemble'"
NEW = "'baseline', 'rating', 'goals', 'ml', 'ensemble', 'counts'"


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The registry has a dozen rows.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE models.model_registry DROP CONSTRAINT model_registry_family_check")
    op.execute(f"ALTER TABLE models.model_registry ADD CONSTRAINT model_registry_family_check CHECK (family IN ({NEW}))")
    op.execute("""
        COMMENT ON COLUMN models.model_registry.family IS
        'What kind of model: baseline (no skill reference), rating (Elo), goals (a score matrix), ml, ensemble, counts (a negative
         binomial per team for a count: the goals of a half, corners, cards - plan F10).'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("SET LOCAL fbi.models_maintenance = 'on'")  # the forecasts are append-only; this lifts the guard for this transaction
    op.execute("""
        DELETE FROM models.match_forecasts WHERE model_version_id IN (
            SELECT v.id FROM models.model_versions v JOIN models.model_registry r ON r.id = v.model_id WHERE r.family = 'counts')""")
    op.execute("DELETE FROM models.model_versions WHERE model_id IN (SELECT id FROM models.model_registry WHERE family = 'counts')")
    op.execute("DELETE FROM models.model_registry WHERE family = 'counts'")
    op.execute("ALTER TABLE models.model_registry DROP CONSTRAINT model_registry_family_check")
    op.execute(f"ALTER TABLE models.model_registry ADD CONSTRAINT model_registry_family_check CHECK (family IN ({OLD}))")
    op.execute("COMMENT ON COLUMN models.model_registry.family IS NULL")
