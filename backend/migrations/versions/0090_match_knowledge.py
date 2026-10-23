"""Match Knowledge: a finished match as one object, in layers, each with the moment it was known (plan F7)

WHY THIS EXISTS
---------------
When a match ends, what PrediGol knows about it is spread over a dozen tables written by different jobs at different moments: the result
and its corrections, the statistics, the events, the squad sheets and what each man did, the prices from the opening to the close, the
decisions and picks and how they ended, the post-mortem. Nothing puts them side by side, so every reader that wants "what happened in this
match" (the post-match screen, the post-mortem, the memory of a team, a referee or a market, the next dossier) assembles it again with its
own rules. The plan asks for ONE object per finished match, built by rules (no AI, no cost), from facts already stored.

WHAT IS ADDED
-------------
``intel.match_knowledge``  the history of what each finished match turned out to be, one row per build. A row holds the nine layers of
    the plan as JSON (``layers``: the result and its corrections, the statistics, the events by period, the players, the observable tactics,
    the market from open to close, the external context - off by default -, PrediGol's picks and decisions, the post-mortem), and for each
    layer its status (``ok``, ``partial``, ``missing``, ``off``), the sources it was read from and the moment its newest input was known
    (``known_at``): a layer says what it is made of and how fresh. ``quality`` states what could not be said (a list of events that does
    not give the score, a squad sheet the provider crossed...). A match is built when it is over and settled (26 hours after kick-off, the
    time of the provider's last re-read) and again, as a NEW row, only if an input changed since (``inputs_hash``); a rebuild that finds
    the same content as the newest row adds nothing (the builder compares ``content_hash``; ``UNIQUE (fixture_id, version, inputs_hash,
    content_hash)`` stops two builders adding the very same row at once, and still lets a match go A, then B, then A again: the third
    row is a fact - the provider changed its mind twice - and its inputs are not those of the first). Append-only
    (``intel.refuse_change``), versioned (``version``: ``mk-v1``): a new version of the rules adds rows beside the old ones.
``intel.match_knowledge_latest``  the newest row of each (fixture, version).

Match Knowledge is knowledge of a match that is OVER. No reader of a pre-match moment may read it - not the dossier, the AI packet, the
models, the forecast, the decision layer - and a test keeps them away (``tests/unit/test_knowledge_isolation.py``). It changes no model, no
forecast, no pick and no settlement; nothing reads it until F8 (the single post-mortem and the memory) and the post-match screen.

Additive and non-blocking: the table is new and refers to nothing (no foreign keys: one to ``core.fixtures`` would need a lock on a table
that ``fixtures_sync`` keeps in a write transaction of ~27 minutes every six hours - revisions 0085 and 0086 waited on it), and it is
empty when created. The downgrade drops the view and the table (rows are rebuilt by ``python -m scripts.match_knowledge build``, from
facts that are kept; export them first only if a person has quoted them). It leaves ``intel.refuse_change()`` (revision 0076's) alone.

Revision ID: 0090
Revises: 0089
"""

from __future__ import annotations

from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new and refers to nothing.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE intel.match_knowledge (
            id            BIGSERIAL   PRIMARY KEY,
            fixture_id    BIGINT      NOT NULL,
            version       TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            built_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            known_at      TIMESTAMPTZ NOT NULL,
            inputs_hash   TEXT        NOT NULL CHECK (length(inputs_hash) = 64),
            content_hash  TEXT        NOT NULL CHECK (length(content_hash) = 64),
            completeness  TEXT        NOT NULL CHECK (completeness IN ('complete', 'partial', 'minimal')),
            layers        JSONB       NOT NULL CHECK (jsonb_typeof(layers) = 'object'),
            quality       JSONB       NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(quality) = 'object'),
            UNIQUE (fixture_id, version, inputs_hash, content_hash)
        )""")
    op.execute("CREATE INDEX match_knowledge_fixture ON intel.match_knowledge (fixture_id, version, id DESC)")
    op.execute("""
        COMMENT ON TABLE intel.match_knowledge IS
        'A finished match as one object in layers (result, statistics, events, players, tactics, market, external context, picks, post-mortem),
         each layer with its status, sources and known_at. Built by rules from stored facts when the match is over and settled (kick-off +
         26 h) and again, as a new row, only when an input changed (inputs_hash) and the content differs from the newest row''s. Append-only, versioned.
         Knowledge of a match that is OVER: no pre-match reader may read it. python -m scripts.match_knowledge.'""")
    op.execute("COMMENT ON COLUMN intel.match_knowledge.known_at IS "
               "'The newest moment any input of any layer was known to PrediGol (the layers carry their own).'")
    op.execute("COMMENT ON COLUMN intel.match_knowledge.inputs_hash IS "
               "'Hash of the signature of the inputs the build read (newest fetched_at / count of each source): the cheap test of whether a rebuild is due.'")
    op.execute("""
        CREATE VIEW intel.match_knowledge_latest AS
        SELECT DISTINCT ON (fixture_id, version) id, fixture_id, version, built_at, known_at, inputs_hash, content_hash, completeness,
               layers, quality
          FROM intel.match_knowledge
         ORDER BY fixture_id, version, id DESC""")
    op.execute("COMMENT ON VIEW intel.match_knowledge_latest IS "
               "'The newest build of each (fixture, version) of intel.match_knowledge: what each finished match is today.'")
    op.execute("CREATE TRIGGER match_knowledge_append_only BEFORE UPDATE OR DELETE ON intel.match_knowledge "
               "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS intel.match_knowledge_latest")
    op.execute("DROP TABLE IF EXISTS intel.match_knowledge")
