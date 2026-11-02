"""A match at a neutral venue is recognised from evidence and stored with its reason; the models read it only after a backtest justifies it (plan F0, defect 1)

WHY THIS EXISTS
---------------
``core.fixtures.is_neutral`` and ``core.competitions.neutral_venue`` are read by the Elo, the goal models and the ordered
logit, and by the AI packet's travel context - and nothing ever wrote either of them. Every ingestion path inserts a
fixture with ``is_neutral = false`` and no competition ever had ``neutral_venue`` set, so a Champions League final, a Copa
del Rey final, an FA Cup semi-final at Wembley, a World Cup match in a third country were all modelled as if the nominal
home side played in front of its own crowd (a home-advantage term in the Elo and the goal models, a home intercept in the
ordered logit).

Deciding which matches are neutral is not a flag to flip: the provider says nothing about it, the venue id it gives is
stale or shared (a club's id is kept for a home match played abroad; one id names different grounds), and a wrong
"neutral" takes a real home advantage away from a real home match. So the decision is made by a rule that needs positive
evidence (``fbi.catalog.neutral``, rule ``neutral-v1``), the verdict is stored with the evidence it was made from, and
the models read it only when a person switches it on after a before/after backtest (the project's rule: no model changes
without a test).

WHAT IS ADDED
-------------
``core.fixture_venue_class``  one row per (fixture, rule version): neutral or not, the basis (a short code: why), the
    evidence (the ground, its country and how it was found, each side's presence at it, the round) and when it was last
    decided. Domestic league matches have no row (never neutral by rule). A DERIVED table: ``classify`` rewrites a row
    when the facts change (a venue named later, a round renamed) and the ingestion does it when it writes a fixture; it
    is not history, so it is not append-only.
``analytics.neutral_rule_runs``  the before/after backtests: for a rule version, the fingerprint of the verdicts the run
    is about, the parameters (thresholds fixed before the run), the metrics of both arms, and a verdict computed by
    arithmetic (justified / not_justified / inconclusive). Append-only.
``analytics.neutral_rule_promotion``  the switch, as a history: the newest row names the rule the models read, or none
    (a retirement). EMPTY after this migration, which is rule OFF: deploying changes no probability. A promotion must
    cite a run whose verdict is ``justified``; rolling back is a retirement row. Append-only.

Nothing here changes a model, a forecast or a stored prediction. ``fbi.features.data.load_matches`` ORs the verdict in
only for the rule the newest promotion names.

Additive. The downgrade drops the three tables (the two analytics tables are a record of decisions: export them first if
the revision is being undone on a database that has had a promotion). It leaves ``analytics.refuse_change()`` (revision
0079's) alone.

Revision ID: 0081
Revises: 0080
"""

from __future__ import annotations

from alembic import op

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). Every table here is new; the
    # foreign keys take a short lock on core.fixtures / the runs table.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE core.fixture_venue_class (
            fixture_id    BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            rule_version  TEXT        NOT NULL CHECK (length(btrim(rule_version)) > 0),
            neutral       BOOLEAN     NOT NULL,
            basis         TEXT        NOT NULL CHECK (length(btrim(basis)) > 0),
            evidence      JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
            classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (fixture_id, rule_version)
        )""")
    op.execute("CREATE INDEX fixture_venue_class_neutral ON core.fixture_venue_class (rule_version, fixture_id) "
               "WHERE neutral")
    op.execute("""
        COMMENT ON TABLE core.fixture_venue_class IS
        'Whether a fixture is played at a neutral venue (neither side at home), by the rule rule_version
         (fbi.catalog.neutral, plan F0 defect 1): the verdict, its basis code and the evidence it was made from (the
         ground the payload names, its country and how it was found, each side''s presence at it, the round). Domestic
         league matches have no row: never neutral. Derived and rewritten when the facts change; the models read
         neutral only for the rule the newest analytics.neutral_rule_promotion row names (none after this migration).'""")
    op.execute("COMMENT ON COLUMN core.fixture_venue_class.basis IS "
               "'Why: third_country, decider_ground, semi_pair_ground, shared_ground (neutral) or league, no_venue, kind_unknown, "
               "mixed_sides, country_unknown, venue_country_unknown, home_country, away_country, home_ground, "
               "away_ground, no_evidence (not neutral). No evidence is never read as neutral.'")

    op.execute("""
        CREATE TABLE analytics.neutral_rule_runs (
            id           BIGSERIAL   PRIMARY KEY,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            rule_version TEXT        NOT NULL CHECK (length(btrim(rule_version)) > 0),
            protocol     TEXT        NOT NULL CHECK (length(btrim(protocol)) > 0),
            verdict      TEXT        NOT NULL CHECK (verdict IN ('justified', 'not_justified', 'inconclusive')),
            labels       JSONB       NOT NULL CHECK (jsonb_typeof(labels) = 'object'),
            params       JSONB       NOT NULL CHECK (jsonb_typeof(params) = 'object'),
            result       JSONB       NOT NULL CHECK (jsonb_typeof(result) = 'object'),
            code_version TEXT,
            dataset_hash TEXT
        )""")
    op.execute("""
        COMMENT ON TABLE analytics.neutral_rule_runs IS
        'A before/after backtest of a neutral-venue rule (fbi.backtesting.neutral_ab): the models as they are (before) and
         with the rule''s verdicts (after) over the same matches, walk-forward. labels fingerprints the verdicts the run is
         about (a promotion is refused if they changed), params holds the thresholds fixed BEFORE the run, result both
         arms'' metrics, and verdict is arithmetic over them: justified (not worse where the rule changes a match, not
         worse elsewhere), not_justified, or inconclusive (too few neutral matches to say). Append-only.'""")
    op.execute("CREATE TRIGGER neutral_rule_runs_append_only BEFORE UPDATE OR DELETE "
               "ON analytics.neutral_rule_runs FOR EACH ROW EXECUTE FUNCTION analytics.refuse_change()")

    op.execute("""
        CREATE TABLE analytics.neutral_rule_promotion (
            id           BIGSERIAL   PRIMARY KEY,
            promoted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            promoted_by  TEXT        NOT NULL CHECK (promoted_by IN ('owner', 'system')),
            action       TEXT        NOT NULL CHECK (action IN ('promote', 'retire')),
            rule_version TEXT,
            reason       TEXT        NOT NULL CHECK (length(btrim(reason)) >= 10),
            run_id       BIGINT      REFERENCES analytics.neutral_rule_runs(id) ON DELETE RESTRICT,
            previous_id  BIGINT      REFERENCES analytics.neutral_rule_promotion(id),
            evidence     JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence) = 'object'),
            CHECK ((action = 'promote') = (rule_version IS NOT NULL AND run_id IS NOT NULL)),
            CHECK (action = 'promote' OR (rule_version IS NULL AND run_id IS NULL))
        )""")
    op.execute("""
        COMMENT ON TABLE analytics.neutral_rule_promotion IS
        'The switch that lets the models read neutral-venue verdicts, as a history of explicit decisions: the newest row
         names the rule in force, or none (action retire). EMPTY = OFF, which is where this migration leaves it. A promote
         row cites the backtest run that justified it (fbi.catalog.neutral_store.promote refuses any other); rolling back
         is a retire row. Append-only. python -m scripts.neutral_rule show.'""")
    op.execute("CREATE TRIGGER neutral_rule_promotion_append_only BEFORE UPDATE OR DELETE "
               "ON analytics.neutral_rule_promotion FOR EACH ROW EXECUTE FUNCTION analytics.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS analytics.neutral_rule_promotion")
    op.execute("DROP TABLE IF EXISTS analytics.neutral_rule_runs")
    op.execute("DROP TABLE IF EXISTS core.fixture_venue_class")
