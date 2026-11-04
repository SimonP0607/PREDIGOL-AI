"""What a family learns from its own decisions: a post-mortem for each and a memory over them (plan F11)

WHY THIS EXISTS
---------------
The plan asks that a family complete the cycle in SHADOW before anyone talks about promoting it: a decision (``intel.decisions`` under
``decision-fam-v1``), its settlement (``intel.decision_outcomes`` under ``outcome-fam-v1``), a POST-MORTEM that says what became of it and why,
and a MEMORY that adds the post-mortems up. The first two exist in code since F11.8 and F11.9; this revision gives the last two a place to be
written.

They are NOT written to the tables the pipeline learns in (``intel.postmortems``, ``intel.entity_memory``, F8's one post-mortem and memory-v4),
on purpose:

* what the pipeline learned from its selections is read by things that act on the pipeline: the daily report, the patterns that become
  hypotheses, the lessons the AI is handed. A family is a research layer in shadow, with forecasts that are NOT calibrated: its hundreds of
  decisions would be mixed into the sample sizes, the verdicts and the confidence of a layer they say nothing about;
* a row of the pipeline's post-mortem is about a selection some part of the system looked at (a pick, a leg, a review). A family's decision
  has none of that: it has a count, a line, a model that was never calibrated, a referee, a price against the close. The questions it is asked
  are not the pipeline's ten, and the causes it looks for (cards against what the referee usually shows, a red card) are the ones a count
  can turn on;
* a memory of the families can be rebuilt from scratch every night, because it is a small sum over rows that are kept; the pipeline's memory
  is incremental, with a state it continues. Putting the two in one table would give it two ways of being right.

What a family learns obeys the rule the pipeline's lessons do (``tests/unit/test_postmortem_isolation.py``, which names these tables too): it is
the future of the match it describes and it is derived, so NOTHING that is said before a kick-off reads it. It is not an input of any forecast,
decision, packet or pick; it feeds a console and the owner's decisions.

WHAT IS ADDED
-------------
``intel.family_postmortems``  one row for the decision of a family that STOOD at the kick-off (the last one of each model, market and match: the
    hourly passes revise a decision as the prices move, and the revisions are the same bet seen again, settled but not studied) once it has an
    outcome, per version (``pm-fam-v1``): what it said (the
    model's probability and the books' at the decision), what happened (the result and the count against the line), what it was worth (the
    price against the close: ``clv``, ``clv-v1``, the only definition), the verdict of luck against decision (the pipeline's: MERECIDO,
    VARIANZA, SUERTE, ERROR, NULO, SIN_DATOS), the causes the model could not see and the questions answered from stored numbers. Built by
    rules, at no cost, no language model. Constraints tie the verdict to the result and the quality of the price, the quality to the closing
    value, the profit to the result and the price taken, and the row to the time after the match, so a row cannot contradict the rule or
    predate what it describes. Append-only.
``intel.family_memory``  the sum of the post-mortems by family, market, competition and referee, as of a Bogotá day, per version
    (``memory-fam-v1``): the record (how many, how many won, what the model claimed and what happened, the value against the close, the profit
    at flat stakes, the verdicts) over everything and over the recent weeks, the difference between the two, and a confidence from 0 to 1
    (how much of it rests on enough recent evidence). Append-only; ``intel.family_memory_latest`` is the newest snapshot of each entity.

Nothing existing is altered: no table, column, view or row. Two new tables and a view, empty. The only foreign key is to ``intel.decisions``
(a small append-only table); there is none to ``core.fixtures`` (revision 0090: a lock on a table ``fixtures_sync`` keeps in a write transaction
of ~27 minutes every six hours), and a lock that cannot be had within 10 s fails the migration whole (transactional DDL).

Downgrade: drops the view and the two tables. They hold derived rows only: the nightly pass writes them again from the decisions and the
outcomes, which stay.

Revision ID: 0118
Revises: 0117
"""

from __future__ import annotations

from alembic import op

revision = "0118"
down_revision = "0117"
branch_labels = None
depends_on = None

VERDICTS = "'MERECIDO', 'VARIANZA', 'SUERTE', 'ERROR', 'NULO', 'SIN_DATOS'"
RESULTS = "'win', 'loss', 'push', 'void', 'half_win', 'half_loss'"
QUALITIES = "'GOOD', 'NEUTRAL', 'BAD', 'UNKNOWN'"
GOOD = "0.01"
"""The closing-line value above which a price is GOOD and below minus which it is BAD (``fbi.market.closing_value.GOOD``, clv-v1): written here as
a constant of pm-fam-v1, because a row of that version must not change meaning if the code does. A test holds the two equal."""


def _quoted(text: str) -> str:
    """The text as the inside of an SQL string: an apostrophe is written twice."""
    return text.replace("'", "''")


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The tables are new and refer only to intel.decisions.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(f"""
        CREATE TABLE intel.family_postmortems (
            id             BIGSERIAL    PRIMARY KEY,
            decision_id    BIGINT       NOT NULL REFERENCES intel.decisions(id),
            version        TEXT         NOT NULL CHECK (length(btrim(version)) > 0),
            created_at     TIMESTAMPTZ  NOT NULL,
            fixture_id     BIGINT       NOT NULL,
            kickoff_at     TIMESTAMPTZ  NOT NULL,
            family         TEXT         NOT NULL CHECK (family ~ '^[A-Z][A-Z0-9_]*$'),
            model_name     TEXT         NOT NULL CHECK (length(btrim(model_name)) > 0),
            market_key     TEXT         NOT NULL CHECK (length(btrim(market_key)) > 0),
            selection      TEXT         NOT NULL CHECK (length(btrim(selection)) > 0),
            line           NUMERIC(6,2) NOT NULL,
            competition_id BIGINT,
            referee_id     BIGINT,
            result         TEXT         NOT NULL CHECK (result IN ({RESULTS})),
            quality        TEXT         NOT NULL CHECK (quality IN ({QUALITIES})),
            verdict        TEXT         NOT NULL CHECK (verdict IN ({VERDICTS})),
            odds           NUMERIC(9,3) NOT NULL CHECK (odds > 1),
            p_model        NUMERIC(8,6) NOT NULL CHECK (p_model > 0 AND p_model < 1),
            p_decision     NUMERIC(8,6) CHECK (p_decision > 0 AND p_decision < 1),
            p_close        NUMERIC(8,6) CHECK (p_close > 0 AND p_close < 1),
            clv            NUMERIC(10,6),
            profit_flat    NUMERIC(10,4) NOT NULL,
            actual         NUMERIC(8,2),
            margin         NUMERIC(8,2),
            causes         JSONB        NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(causes) = 'array'),
            answers        JSONB        NOT NULL CHECK (jsonb_typeof(answers) = 'object'),
            evidence       JSONB        NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
            CONSTRAINT family_postmortems_once UNIQUE (decision_id, version),
            CONSTRAINT family_postmortems_after_the_match CHECK (created_at > kickoff_at),
            CONSTRAINT family_postmortems_a_close_has_both CHECK ((clv IS NULL) = (p_close IS NULL)),
            CONSTRAINT family_postmortems_margin_needs_actual CHECK (margin IS NULL OR actual IS NOT NULL),
            CONSTRAINT family_postmortems_profit_follows_result CHECK (version <> 'pm-fam-v1' OR profit_flat = CASE result
                WHEN 'win' THEN odds - 1 WHEN 'half_win' THEN (odds - 1) / 2 WHEN 'loss' THEN -1 WHEN 'half_loss' THEN -0.5 ELSE 0 END),
            CONSTRAINT family_postmortems_quality_follows_clv CHECK (version <> 'pm-fam-v1' OR quality = CASE
                WHEN clv IS NULL THEN 'UNKNOWN' WHEN clv > {GOOD} THEN 'GOOD' WHEN clv < -{GOOD} THEN 'BAD' ELSE 'NEUTRAL' END),
            CONSTRAINT family_postmortems_verdict_follows_the_rule CHECK (version <> 'pm-fam-v1' OR verdict = CASE
                WHEN result IN ('push', 'void') THEN 'NULO'
                WHEN quality = 'UNKNOWN' THEN 'SIN_DATOS'
                WHEN result IN ('win', 'half_win') THEN CASE WHEN quality = 'BAD' THEN 'SUERTE' ELSE 'MERECIDO' END
                ELSE CASE WHEN quality = 'BAD' THEN 'ERROR' ELSE 'VARIANZA' END END)
        )""")
    op.execute("CREATE INDEX family_postmortems_fixture ON intel.family_postmortems (fixture_id)")
    op.execute("CREATE INDEX family_postmortems_kickoff ON intel.family_postmortems (kickoff_at)")
    for column, text in (
        ("decision_id", "The decision of a family (intel.decisions, decision-fam-v1) this post-mortem is about: the one that stood at the kick-off, "
                       "one per version."),
        ("created_at", "The moment of the pass that wrote it. The match was over, its outcome settled and the statistics of the cards in."),
        ("competition_id", "The competition of the match (no foreign key, see revision 0090). The memory sums by it."),
        ("referee_id", "The referee the identity layer placed in the match, or NULL (no foreign key). The memory sums by it."),
        ("result", "What the selection settled as, from intel.decision_outcomes (outcome-fam-v1): the same word."),
        ("quality", "The price against the close by clv-v1: GOOD above +1 %, BAD below -1 %, NEUTRAL between, UNKNOWN without a close. "
                    "Never the result: this is the decision."),
        ("verdict", "Luck against decision, the pipeline's rule (a constraint): won with a GOOD or NEUTRAL price MERECIDO, with a BAD one SUERTE; "
                    "lost with a GOOD or NEUTRAL price VARIANZA, with a BAD one ERROR; push or void NULO; no close SIN_DATOS."),
        ("odds", "The price the decision was taken at (the best of the complete books at the moment of the decision)."),
        ("profit_flat", "What one unit staked at that price made: the outcome of the decision. A constraint ties it to the result and the price "
                        "(win: odds - 1, half win: half of it, push or void: 0, half loss: -1/2, loss: -1)."),
        ("p_model", "What the family said of the selection (its forecast, NOT calibrated: the families have no champion calibrator)."),
        ("p_decision", "The fair probability of the books at the moment of the decision (intel.decisions.p_market)."),
        ("p_close", "The fair probability of the books at the kick-off, built the way the decision priced (outcome-fam-v1)."),
        ("clv", "clv-v1: the price taken at the closing fair probability, odds x p_close - 1 (fbi.market.closing_value). The only CLV."),
        ("actual", "The count the line was graded on (the corners of the match, the goals of a half): NULL for a bet that reads two numbers "
                   "(1X2 of the corners, HT/FT)."),
        ("margin", "The count minus the line: positive is over it, negative under it. NULL when there is no single count."),
        ("causes", "What happened in the match that the model could not see (a red card, an early goal, cards against what the referee usually "
                   "shows), from the events and the statistics: the pipeline's function, so the codes are the same."),
        ("answers", "The questions of the post-mortem, in Spanish, from stored numbers only. One result changes nothing: it goes to the memory."),
        ("evidence", "What the row rests on: the forecast the decision cited, the counts read, the outcome and the close."),
    ):
        op.execute(f"COMMENT ON COLUMN intel.family_postmortems.{column} IS '{_quoted(text)}'")
    op.execute("""
        COMMENT ON TABLE intel.family_postmortems IS
        'The post-mortem of a decision of a family in shadow (plan F11, pm-fam-v1): what it said, what happened, what the price was worth
         against the close and whether the result was luck or the decision. Built by rules from stored facts, no language model. Kept apart
         from intel.postmortems (the pipeline''s one) so that a research layer does not move the pipeline''s lessons. Nothing said before a
         kick-off reads it. Append-only.'""")
    op.execute("CREATE TRIGGER family_postmortems_append_only BEFORE UPDATE OR DELETE ON intel.family_postmortems "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")

    op.execute("""
        CREATE TABLE intel.family_memory (
            id           BIGSERIAL    PRIMARY KEY,
            version      TEXT         NOT NULL CHECK (length(btrim(version)) > 0),
            as_of_day    DATE         NOT NULL,
            built_at     TIMESTAMPTZ  NOT NULL,
            entity_type  TEXT         NOT NULL CHECK (entity_type IN ('family', 'market', 'competition', 'referee')),
            entity_key   TEXT         NOT NULL CHECK (length(btrim(entity_key)) > 0),
            entity_name  TEXT,
            stats        JSONB        NOT NULL CHECK (jsonb_typeof(stats) = 'object'),
            delta        JSONB        NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(delta) = 'object'),
            confidence   NUMERIC(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
            evidence_ref JSONB        NOT NULL CHECK (jsonb_typeof(evidence_ref) = 'object'),
            CONSTRAINT family_memory_once UNIQUE (version, as_of_day, entity_type, entity_key)
        )""")
    op.execute("CREATE INDEX family_memory_entity ON intel.family_memory (entity_type, entity_key, as_of_day DESC)")
    op.execute("COMMENT ON COLUMN intel.family_memory.as_of_day IS "
               "'The Bogotá day the snapshot is as of: the post-mortems written by the pass of that day are in it, none after.'")
    op.execute("COMMENT ON COLUMN intel.family_memory.stats IS "
               "'The record over everything (all) and over the recent weeks (recent): decisions, results, the hit rate against what the model "
               "claimed, the closing-line value, the profit at flat stakes and the verdicts.'")
    op.execute("COMMENT ON COLUMN intel.family_memory.confidence IS "
               "'0 to 1: how much of this memory rests on enough RECENT evidence (the effective sample, discounted by age, over itself plus a "
               "constant).'")
    op.execute("COMMENT ON COLUMN intel.family_memory.evidence_ref IS "
               "'What the row rests on: the number of post-mortems, the newest one included (through) and a sample of the newest.'")
    op.execute("""
        COMMENT ON TABLE intel.family_memory IS
        'What the families have learned from their own decisions (plan F11, memory-fam-v1): the sum of intel.family_postmortems by family,
         market, competition and referee, as of a Bogotá day, with a confidence. Rebuilt every night from the post-mortems, which are kept;
         a day with nothing new writes nothing. Nothing said before a kick-off reads it. Append-only.'""")
    op.execute("CREATE TRIGGER family_memory_append_only BEFORE UPDATE OR DELETE ON intel.family_memory "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")

    op.execute("""
        CREATE VIEW intel.family_memory_latest AS
        SELECT DISTINCT ON (entity_type, entity_key)
               id, version, as_of_day, built_at, entity_type, entity_key, entity_name, stats, delta, confidence, evidence_ref
          FROM intel.family_memory
         ORDER BY entity_type, entity_key, as_of_day DESC,
                  NULLIF(regexp_replace(version, '[^0-9]', '', 'g'), '')::int DESC NULLS LAST, id DESC""")
    op.execute("COMMENT ON VIEW intel.family_memory_latest IS "
               "'The newest snapshot of each family, market, competition and referee: what the families know of themselves today.'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS intel.family_memory_latest")
    op.execute("DROP TABLE IF EXISTS intel.family_memory")
    op.execute("DROP TABLE IF EXISTS intel.family_postmortems")
