"""What each line of a finished match's events IS, and in which period of the match it happened (plan F7, ``events-v1``)

WHY THIS EXISTS
---------------
The provider's list of events (``core.fixture_events``, 3.2 million lines) says things in words: ``Goal / Penalty`` is a converted penalty of
the match and also a converted kick of a shoot-out (the comment ``Penalty Shootout`` tells them apart); an own goal is filed under the team
that GETS the goal; a dismissal for a second yellow is two lines, a ``Yellow Card`` and a ``Red Card`` of the same man at the same minute;
a goal the VAR takes away is removed from the list and its decision stays; a minute above 90 is extra time only in a match that went to
extra time. Four places have been counting these by hand (the post-mortem, the dossier, the tactics, the memory), each with its own idea of
which lines are goals. ``fbi.knowledge.events`` reads them once, with the rules measured on production (see its docstring), and the datasets
that follow (goals by half, cards from events: plan F9) need the answer in the database, not in a Python list.

WHAT IS ADDED
-------------
``core.fixture_event_kinds``  one row per line of ``core.fixture_events`` that has been read: its kind (``goal``, ``own_goal``,
    ``penalty_goal``, ``penalty_missed``, ``shootout_goal``, ``shootout_miss``, ``yellow``, ``second_yellow``, ``red``, ``sub``, ``var_*``...),
    its period (``1H``, ``2H``, ``ET``, ``PEN``), the side it counts for and the side of the man, the line it pairs with (a second yellow), the
    flags it earned, the version of the rules that read it and the ``fetched_at`` of the line it was read from. It is a DERIVED table, like
    ``core.competition_stages``: ``fbi.knowledge.builder`` brings the rows of a match to what its list is (in one transaction, with the
    row of Match Knowledge it belongs to: lines that are gone are deleted, lines that differ are written, the rest is left alone) whenever
    the list or the rules change, so it is not append-only. A match's rows are stale when they are not as many as the lines of its list or
    were read by older rules (``rules_version``): ``builder.coverage`` counts those, and the next build of the match repairs them.
    ``event_fetched_at`` says from which fetch of the list a row was read; the provider fetching the same list again does not make a row stale.

WHY NOT COLUMNS ON ``core.fixture_events`` (the plan's sketch)
---------------------------------------------------------------
Three reasons, all found by looking before building. (1) ``audit.keep_settled_detail`` (revision 0061) is an ``AFTER UPDATE OR DELETE``
trigger on that table: it copies, into ``audit.settled_detail_changes``, every row of a FINISHED match whose values change, whole, as JSON.
Filling two new columns for the 3.2 million lines would copy them all, unless the trigger were changed first - and a change to a trigger
that guards the history of what the provider said is not something to do as a side effect of a classification. (2) The ingestion replaces
the list of a match as a whole (``DELETE`` + ``INSERT``) whenever the provider's list changes, so a column filled at write time would hold
the rules of the day the list was written, and the period of a line depends on the match's final status, which can arrive after the line.
(3) The rules will be improved; a derived table with a version is rebuilt, a provider's table is not rewritten. Nothing about
``core.fixture_events`` changes: no lock on it, no trigger, no column.

Additive and non-blocking: the table is new, refers to nothing (no foreign keys: a foreign key to ``core.fixture_events`` would need a lock
on the table the live follower writes, and the builder keeps the rows in step), and is empty when created. The downgrade drops it (the rows
are derived: ``python -m scripts.match_knowledge build`` writes them again).

Revision ID: 0089
Revises: 0088
"""

from __future__ import annotations

from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new and refers to nothing.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE core.fixture_event_kinds (
            fixture_id        BIGINT      NOT NULL,
            source            TEXT        NOT NULL CHECK (source IN ('api-football')),
            seq               SMALLINT    NOT NULL CHECK (seq >= 0),
            rules_version     TEXT        NOT NULL CHECK (length(btrim(rules_version)) > 0),
            kind              TEXT        NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]{1,40}$'),
            period            TEXT        NOT NULL CHECK (period IN ('1H', '2H', 'ET', 'PEN')),
            side              TEXT        CHECK (side IN ('home', 'away')),
            player_side       TEXT        CHECK (player_side IN ('home', 'away')),
            pair_seq          SMALLINT    CHECK (pair_seq >= 0),
            flags             TEXT[]      NOT NULL DEFAULT '{}',
            event_fetched_at  TIMESTAMPTZ NOT NULL,
            built_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (fixture_id, source, seq)
        )""")
    op.execute("""
        COMMENT ON TABLE core.fixture_event_kinds IS
        'What each line of core.fixture_events IS (kind) and in which period (1H, 2H, ET, PEN) it happened, read by fbi.knowledge.events
         (events-v1). Derived: the rows of a match are rewritten as a whole when its list or the rules change; event_fetched_at is the
         fetched_at of the line a row was read from. side is the side the provider filed the line under (for a goal, the side it counts
         for, also an own goal); player_side is the side of the man. python -m scripts.match_knowledge build.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS core.fixture_event_kinds")
