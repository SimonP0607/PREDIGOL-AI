"""One post-mortem and a memory with a confidence (plan F8)

WHY THIS EXISTS
---------------
After a match PrediGol wrote down what it had learned in THREE places that did not agree: ``ai.postmortems`` (pm-v1: the match, with the
AI's evidence checked against the line-ups), ``ai.pick_postmortems`` (pm-v2: each selection the AI studied, with ten questions and the
class of a loss) and ``intel.postmortems`` (pm-v3 to pm-v5: each decision of the decision layer, luck against the quality of the price).
Measured in production on 23 Oct 2026: 1,139 match rows, 2,487 selection rows and 78 decision rows; only 20 selections were in two of them.
Every reader chose one, so the screens, the daily lessons and the patterns each counted a different thing - and the picks users actually
see were in pm-v2 only. The plan asks for ONE post-mortem. This revision makes ``intel.postmortems`` that one: a row is a SELECTION
(fixture, market, selection, line) - with the decision it came from, when there is one - so that the selections the AI studied (the
picks of the day, the legs of the parlays, every selection a review looked at) and the decisions of the decision layer are the same kind
of row, judged by the same rules (``pm-v6``): the verdict of luck against the quality of the price (MERECIDO, VARIANZA, SUERTE, ERROR,
NULO, SIN_DATOS, from the one closing-line value of ``fbi.market.closing_value``), the verdict of the review (approved and won, rejected
and would have won, ...) beside it and never mixed with it, the class of a loss, and the ten questions answered from stored numbers.

WHAT IS ADDED
-------------
``intel.postmortems``  keeps every column and every row it has (the rows of pm-v3 to pm-v5 - 78 when this was measured, 104 by the night
    of the 23rd - stay as they were written: the table is append-only
    and this revision rewrites none) and gains NULLABLE columns that pm-v6 fills: the key of the selection (``market_key``, ``selection``,
    ``line``), why it was studied (``roles``), the review it met (``review_id``, ``review_decision``, ``review_verdict``), the class of a
    loss (``loss_class``), the prices (``odds``, ``close_odds``, ``p_model``, ``p_market``, ``p_close``), the price move of the same book
    (``price_move``, which is NOT the CLV) and the closing-line value (``clv``, clv-v1). ``decision_id`` becomes optional: a selection
    may have no decision. A selection has ONE row per version (a partial unique index), and a row is about a decision or a selection
    (a check). Rows written before pm-v6 have no key and are read as what they are, per decision.
``intel.selection_postmortems``  the newest row of each selection among the rows that have a key (pm-v6 and later): what the system
    concluded about each selection today. The readers that wanted "the post-mortem of a selection" read this.
``intel.match_postmortems``  the match as a whole, once per version (pm-v6): the score, the AI's evidence checked against the line-ups
    (a player reported out who started, a regular starter missing without a report) and the model's 1X2 forecast against the closing
    market. It is what ``ai.postmortems`` held, kept apart from the selections because it is about the match, not about a price.
    Append-only. No foreign key to ``core.fixtures`` (see revision 0090: it would need a lock on a table that ``fixtures_sync`` keeps in
    a write transaction of ~27 minutes every six hours).
``ai.postmortem_narratives``  the short narrative a language model writes for the losses that matter most, one per post-mortem and
    version, apart from the post-mortem so that the post-mortem is built by rules at no cost and a narrative is optional and paid for.
    Append-only.
``intel.entity_memory``  gains ``confidence`` (0 to 1: how much of this memory rests on enough recent evidence) and ``evidence_ref`` (what
    it rests on, by kind: fixtures, decisions, post-mortems). Both NULL in every row written before memory-v4.

``intel.entity_memory_latest``  the row of the newest memory version for each entity, aspect and day: a memory is rebuilt under a new version
    (memory-v4 from 13 October) and the old rows stay as history, so every reader asks the view and the rule "the newest version wins" lives in
    one place.

Nothing existing is altered in what it says: ``ai.postmortems``, ``ai.pick_postmortems`` and ``ai.memory_events`` stay, readable and
frozen in the sense that PrediGol stops adding to the first two (a switch brings them back); no model, Elo, calibrator, forecast, price,
pick, settlement or filter reads any of it.

Additive and non-blocking: new nullable columns and new tables are metadata-only changes; the only tables altered are ``intel.postmortems``
(about a hundred rows) and ``intel.entity_memory`` (a few thousand), neither read by anything that holds a lock on a big table; there is no foreign key to
a big table, and a lock that cannot be had within 10 s fails the migration whole (transactional DDL).

DOWNGRADE: drops the view, the narratives (paid text - export them first if a person has quoted them), the match table and the new
columns, and removes the rows pm-v6 wrote (they are rebuilt by ``python -m scripts.postmortems build`` from facts that are kept) and the
rows memory-v4 wrote (rebuilt by ``python -m scripts.memory rebuild``), each with the append-only trigger lifted for that one statement;
the rows of before are untouched and ``decision_id`` is required again. The memory rows go out because the code this returns to
(memory-v3) continues "the latest row of ANY version": left behind, a memory-v4 row would be read as the state it continues, and it would
write its own rows from a state it does not understand (figures that version does not produce, a weighted sample it never carried).

Revision ID: 0091
Revises: 0090
"""

from __future__ import annotations

from alembic import op

revision = "0091"
down_revision = "0090"
branch_labels = None
depends_on = None

REVIEW_VERDICTS = ("'approved_won', 'approved_lost', 'caution_won', 'caution_lost', 'rejected_would_have_won', 'rejected_correctly', "
                   "'unreviewed_won', 'unreviewed_lost', 'push'")
LOSS_CLASSES = "'MODEL_ERROR', 'CONTEXT_ERROR', 'DATA_ERROR', 'MARKET_ERROR', 'EXECUTION_ERROR', 'NORMAL_VARIANCE', 'UNKNOWN'"


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("ALTER TABLE intel.postmortems ALTER COLUMN decision_id DROP NOT NULL")
    op.execute(f"""
        ALTER TABLE intel.postmortems
            ADD COLUMN market_key      TEXT,
            ADD COLUMN selection       TEXT,
            ADD COLUMN line            NUMERIC(6,2),
            ADD COLUMN roles           TEXT[],
            ADD COLUMN review_id       BIGINT,
            ADD COLUMN review_decision TEXT CHECK (review_decision IN ('APPROVE', 'DOWNGRADE', 'REJECT', 'ABSTAIN')),
            ADD COLUMN review_verdict  TEXT CHECK (review_verdict IN ({REVIEW_VERDICTS})),
            ADD COLUMN loss_class      TEXT CHECK (loss_class IN ({LOSS_CLASSES})),
            ADD COLUMN odds            NUMERIC(9,3),
            ADD COLUMN close_odds      NUMERIC(9,3),
            ADD COLUMN p_model         NUMERIC(8,6),
            ADD COLUMN p_market        NUMERIC(8,6),
            ADD COLUMN p_close         NUMERIC(8,6),
            ADD COLUMN price_move      NUMERIC(9,4),
            ADD COLUMN clv             NUMERIC(9,4),
            ADD CONSTRAINT postmortems_key_whole CHECK (
                (market_key IS NULL) = (selection IS NULL) AND (selection IS NULL) = (line IS NULL) AND (line IS NULL) = (roles IS NULL)),
            ADD CONSTRAINT postmortems_about_something CHECK (decision_id IS NOT NULL OR market_key IS NOT NULL)""")
    op.execute("CREATE UNIQUE INDEX postmortems_selection_version ON intel.postmortems (fixture_id, market_key, selection, line, version) "
               "WHERE market_key IS NOT NULL")
    op.execute("CREATE INDEX postmortems_fixture ON intel.postmortems (fixture_id)")
    for column, text in (
        ("market_key", "The selection this post-mortem is about (pm-v6 and later; NULL in the rows judged per decision before)."),
        ("roles", "Why the selection was studied: decision (the decision layer), daily_pick, parlay_leg, reviewed, llm, rejected."),
        ("review_id", "The newest combined review of the selection before kick-off (ai.pick_reviews.id; no foreign key, see revision 0090)."),
        ("review_verdict", "What the review decided against how the selection ended (approved and won, rejected and would have won...): "
                           "never the same thing as verdict, which judges the price."),
        ("loss_class", "The class of a loss, the first that applies: data, execution, context, market, model, normal variance, unknown."),
        ("price_move", "The price taken against the SAME bookmaker closing price, margin in both. NOT the CLV."),
        ("clv", "clv-v1: the price taken at the closing fair probability, odds x p_close - 1 (fbi.market.closing_value). The only CLV."),
    ):
        op.execute(f"COMMENT ON COLUMN intel.postmortems.{column} IS '{text}'")
    op.execute("""
        COMMENT ON TABLE intel.postmortems IS
        'THE post-mortem (plan F8): one row per selection and version (pm-v6 and later; the key columns), or per decision before it. Built
         by rules from stored facts, at no cost; verdict judges the price, review_verdict what the review decided. Append-only.'""")

    op.execute("""
        CREATE VIEW intel.selection_postmortems AS
        SELECT DISTINCT ON (pm.fixture_id, pm.market_key, pm.selection, pm.line)
               pm.id, pm.fixture_id, pm.market_key, pm.selection, pm.line, pm.decision_id, pm.created_at, pm.version, pm.roles,
               pm.review_id, pm.review_decision, pm.review_verdict, pm.outcome,
               CASE pm.outcome WHEN 'won' THEN 'win' WHEN 'lost' THEN 'loss' WHEN 'half_won' THEN 'half_win'
                               WHEN 'half_lost' THEN 'half_loss' ELSE pm.outcome END AS settled,
               pm.decision_quality, pm.verdict, pm.loss_class, pm.odds, pm.close_odds, pm.p_model, pm.p_market, pm.p_close,
               pm.price_move, pm.clv, pm.causes, pm.answers, pm.evidence
          FROM intel.postmortems pm
         WHERE pm.market_key IS NOT NULL
         ORDER BY pm.fixture_id, pm.market_key, pm.selection, pm.line, pm.created_at DESC, pm.id DESC""")
    op.execute("COMMENT ON VIEW intel.selection_postmortems IS "
               "'The newest post-mortem of each selection (pm-v6 and later): what the system concludes about it today.'")

    op.execute("""
        CREATE TABLE intel.match_postmortems (
            id          BIGSERIAL   PRIMARY KEY,
            fixture_id  BIGINT      NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL,
            version     TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            outcome     JSONB       NOT NULL CHECK (jsonb_typeof(outcome) = 'object'),
            findings    JSONB       NOT NULL CHECK (jsonb_typeof(findings) = 'object'),
            CONSTRAINT match_postmortems_once UNIQUE (fixture_id, version)
        )""")
    op.execute("""
        COMMENT ON TABLE intel.match_postmortems IS
        'The match as a whole after it ended (pm-v6): the score, the AI evidence checked against the line-ups and the model 1X2 forecast
         against the closing market. What ai.postmortems held; about the match, not about a price. Append-only.'""")
    op.execute("CREATE TRIGGER match_postmortems_append_only BEFORE UPDATE OR DELETE ON intel.match_postmortems "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")

    op.execute("""
        CREATE TABLE ai.postmortem_narratives (
            id             BIGSERIAL   PRIMARY KEY,
            postmortem_id  BIGINT      NOT NULL REFERENCES intel.postmortems(id),
            created_at     TIMESTAMPTZ NOT NULL,
            version        TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            narrative      TEXT        NOT NULL CHECK (length(btrim(narrative)) > 0),
            usage_ids      BIGINT[]    NOT NULL DEFAULT '{}',
            CONSTRAINT postmortem_narratives_once UNIQUE (postmortem_id, version)
        )""")
    op.execute("COMMENT ON TABLE ai.postmortem_narratives IS "
               "'The short narrative a language model wrote for a post-mortem that mattered (a loss of a pick of the day...), apart from "
               "the post-mortem, which is built by rules at no cost. Append-only.'")
    op.execute("CREATE TRIGGER postmortem_narratives_append_only BEFORE UPDATE OR DELETE ON ai.postmortem_narratives "
               "FOR EACH ROW EXECUTE FUNCTION ai.refuse_change()")

    op.execute("""
        ALTER TABLE intel.entity_memory
            ADD COLUMN confidence   NUMERIC(5,4) CHECK (confidence BETWEEN 0 AND 1),
            ADD COLUMN evidence_ref JSONB CHECK (evidence_ref IS NULL OR jsonb_typeof(evidence_ref) = 'object')""")
    op.execute("COMMENT ON COLUMN intel.entity_memory.confidence IS "
               "'0 to 1: how much of this memory rests on enough RECENT evidence (the effective sample, discounted by age, over itself plus a "
               "constant). NULL in the rows written before memory-v4.'")
    op.execute("COMMENT ON COLUMN intel.entity_memory.evidence_ref IS "
               "'What the row rests on, by kind: {fixtures: [...], decisions: [...], postmortems: [...]} (a sample, newest first). NULL "
               "before memory-v4.'")

    op.execute("""
        CREATE VIEW intel.entity_memory_latest AS
        SELECT DISTINCT ON (entity_type, entity_id, aspect, as_of_day)
               id, entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources, confidence, evidence_ref
          FROM intel.entity_memory
         ORDER BY entity_type, entity_id, aspect, as_of_day,
                  NULLIF(regexp_replace(version, '[^0-9]', '', 'g'), '')::int DESC NULLS LAST, id DESC""")
    op.execute("COMMENT ON VIEW intel.entity_memory_latest IS "
               "'One row per entity, aspect and day: the one of the newest memory version (memory-v4 over memory-v3 over memory-v1). "
               "The older rows stay in intel.entity_memory as history.'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS intel.entity_memory_latest")
    # the rows memory-v4 wrote are rebuilt from the data (``python -m scripts.memory rebuild``); the code this returns to continues the
    # latest row of ANY version, so none may be left for it to take as the state it continues
    op.execute("ALTER TABLE intel.entity_memory DISABLE TRIGGER entity_memory_append_only")
    op.execute("DELETE FROM intel.entity_memory WHERE version = 'memory-v4'")
    op.execute("ALTER TABLE intel.entity_memory ENABLE TRIGGER entity_memory_append_only")
    op.execute("ALTER TABLE intel.entity_memory DROP COLUMN IF EXISTS evidence_ref, DROP COLUMN IF EXISTS confidence")
    op.execute("DROP TABLE IF EXISTS ai.postmortem_narratives")
    op.execute("DROP TABLE IF EXISTS intel.match_postmortems")
    op.execute("DROP VIEW IF EXISTS intel.selection_postmortems")
    # the rows pm-v6 wrote are rebuilt from facts that are kept; the trigger that keeps the table append-only is lifted for this statement only
    op.execute("ALTER TABLE intel.postmortems DISABLE TRIGGER postmortems_append_only")
    op.execute("DELETE FROM intel.postmortems WHERE market_key IS NOT NULL OR decision_id IS NULL")
    op.execute("ALTER TABLE intel.postmortems ENABLE TRIGGER postmortems_append_only")
    op.execute("DROP INDEX IF EXISTS intel.postmortems_fixture")
    op.execute("DROP INDEX IF EXISTS intel.postmortems_selection_version")
    op.execute("""
        ALTER TABLE intel.postmortems
            DROP CONSTRAINT IF EXISTS postmortems_about_something,
            DROP CONSTRAINT IF EXISTS postmortems_key_whole,
            DROP COLUMN IF EXISTS clv, DROP COLUMN IF EXISTS price_move, DROP COLUMN IF EXISTS p_close, DROP COLUMN IF EXISTS p_market,
            DROP COLUMN IF EXISTS p_model, DROP COLUMN IF EXISTS close_odds, DROP COLUMN IF EXISTS odds, DROP COLUMN IF EXISTS loss_class,
            DROP COLUMN IF EXISTS review_verdict, DROP COLUMN IF EXISTS review_decision, DROP COLUMN IF EXISTS review_id,
            DROP COLUMN IF EXISTS roles, DROP COLUMN IF EXISTS line, DROP COLUMN IF EXISTS selection, DROP COLUMN IF EXISTS market_key""")
    op.execute("ALTER TABLE intel.postmortems ALTER COLUMN decision_id SET NOT NULL")
    op.execute("COMMENT ON TABLE intel.postmortems IS NULL")
