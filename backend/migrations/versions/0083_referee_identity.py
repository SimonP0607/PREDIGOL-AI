"""A referee is a row with a stable id, the spellings the provider wrote for him, and who refereed each match (plan F3)

WHY THIS EXISTS
---------------
The provider gives no referee id. ``core.fixture_facts.referee`` is a string per match - ``M. Oliver``, ``Michael Oliver,
England``, ``Brooks, John, England`` - and on 22 Oct 2026 the 199,890 matches that carry one held 9,510 distinct spellings
for what is about six thousand people. Everything that wants "what does this referee do" (the dossier, the post-mortem, the
memory aspect, the cards and fouls models of F10) grouped by that text, so the same man was several referees with a few
matches each, and two different men with the same initial and surname were one.

``fbi.people.referee_identity`` (``refid-v1``) reads the spellings and decides who is who; ``fbi.people.referees`` writes what it
decides here. The rules are conservative: a doubt goes to a queue (``core.referee_candidates``) for a person, and two people
who referee at the same time are never joined.

WHAT IS ADDED
-------------
``core.referees``          one row per person: the name he is shown with, his country, and whether a person set the name.
``core.referee_aliases``   one row per SPELLING IN A SCOPE (a normalised name and the country the string names, or else the
    country of the domestic competition it was written in, or ``?``), pointing at the referee it belongs to and saying why
    (``basis``) and who placed it (``rules`` or a person). A merge or a split is a MOVE of aliases between referees: nothing
    else changes, so it is reversible (``core.referee_events`` keeps what moved).
``core.fixture_officials`` who refereed each match, as the history of what the provider said: one row per CHANGE of the
    spelling of a match (change-only, like ``core.fixture_facts``, which it mirrors through ``observed_at``), pointing at the
    ALIAS and not at the referee, so a merge never touches it. ``alias_id`` NULL means the provider took the referee off the
    match. "Who refereed at moment T" is the newest row with ``observed_at <= T``.
``core.fixture_referees``  the view of the newest row per match, with the referee: what the readers use.
``core.referee_candidates`` the queue: pairs of referees the rules could not decide and a person can (reason, score, the two
    spellings that suggested it, and the matches of the smaller side as ``impact``). Open ones are derived and re-derived on
    every pass; the rejected ones are decisions and are kept so that the pair is never suggested again.
``core.referee_events``    what a person (or the rules) changed after the first placement: merge, undo, split, reject, reopen,
    rename. A merge records the aliases it moved, which is what the undo needs.

Nothing here changes a model, a forecast, a pick or a settlement. ``core.fixture_facts`` is not touched: the raw string stays
where it is, and a referee that cannot be placed leaves the readers on the text they read before.

Additive: five new tables and one view, nothing existing is altered. The downgrade drops them (they are derived from
``fixture_facts``: ``python -m scripts.referee_identity build`` rebuilds the rules' part; the people's decisions are the only
thing that would be lost, so take the usual backup first).

Revision ID: 0083
Revises: 0082
"""

from __future__ import annotations

from alembic import op

revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). All the tables are new; the foreign
    # keys take a short lock on core.fixtures.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE core.referees (
            id          BIGSERIAL   PRIMARY KEY,
            name        TEXT        NOT NULL CHECK (length(btrim(name)) > 0),
            name_key    TEXT        NOT NULL CHECK (length(btrim(name_key)) > 0),
            country_key TEXT,
            name_locked BOOLEAN     NOT NULL DEFAULT false,
            status      TEXT        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
            merged_into BIGINT      REFERENCES core.referees(id),
            origin      TEXT        NOT NULL CHECK (origin IN ('rules', 'manual')),
            version     TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT referees_merged_iff_target CHECK ((status = 'merged') = (merged_into IS NOT NULL)),
            CONSTRAINT referees_not_into_itself CHECK (merged_into IS NULL OR merged_into <> id)
        )""")
    op.execute("CREATE INDEX referees_status ON core.referees (status)")
    op.execute("CREATE INDEX referees_name_key ON core.referees (name_key)")
    op.execute("""
        COMMENT ON TABLE core.referees IS
        'A referee (plan F3): a person with a stable id. The provider gives none, so the id is ours: fbi.people.referee_identity
         (version) groups the spellings the provider wrote and fbi.people.referees writes the groups. name is what he is shown
         with (the longest, most used spelling; a person can set it, then name_locked keeps it), country_key the country he
         referees from (a key of fbi.people.countries; NULL when no scope is known). A referee merged into another keeps his
         row (status merged, merged_into) so that old links and decisions still point somewhere; an undo reactivates him.'""")
    op.execute("COMMENT ON COLUMN core.referees.origin IS "
               "'rules: made by the identity rules; manual: made by a person (a split).'")

    op.execute("""
        CREATE TABLE core.referee_aliases (
            id         BIGSERIAL   PRIMARY KEY,
            referee_id BIGINT      NOT NULL REFERENCES core.referees(id),
            name_key   TEXT        NOT NULL CHECK (length(btrim(name_key)) > 0),
            scope      TEXT        NOT NULL CHECK (length(btrim(scope)) > 0),
            display    TEXT        NOT NULL CHECK (length(btrim(display)) > 0),
            basis      TEXT        NOT NULL CHECK (basis IN ('identity', 'extension', 'initial', 'foreign', 'unscoped', 'manual')),
            placed_by  TEXT        NOT NULL CHECK (placed_by IN ('rules', 'manual')),
            version    TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            placed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT referee_aliases_spelling_key UNIQUE (name_key, scope)
        )""")
    op.execute("CREATE INDEX referee_aliases_referee ON core.referee_aliases (referee_id)")
    op.execute("""
        COMMENT ON TABLE core.referee_aliases IS
        'The spellings of referees, each in a scope (plan F3): name_key is the provider''s string without accents, case or
         punctuation, given names first (a surname-first string is put back in order); scope is the country the string names, or
         else the country of the domestic competition it was written in, or ? for a continental or international one. One
         spelling in one scope belongs to one referee. basis says why it is where it is (identity: it anchors its group;
         extension: a name with a middle name or without one; initial: an initial and a surname beside the one full name it
         could be; foreign: a referee abroad joined his home; unscoped: a spelling with no scope joined the only scoped one it
         could be; manual: a person put it there). A merge or a split moves aliases between referees and nothing else.'""")

    op.execute("""
        CREATE TABLE core.fixture_officials (
            fixture_id  BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            role        TEXT        NOT NULL DEFAULT 'referee' CHECK (role IN ('referee')),
            observed_at TIMESTAMPTZ NOT NULL,
            alias_id    BIGINT      REFERENCES core.referee_aliases(id),
            PRIMARY KEY (fixture_id, role, observed_at)
        )""")
    op.execute("CREATE INDEX fixture_officials_alias ON core.fixture_officials (alias_id, fixture_id) WHERE alias_id IS NOT NULL")
    op.execute("""
        COMMENT ON TABLE core.fixture_officials IS
        'Who officiated a match, as the history of what the provider said (plan F3): one row per change of the referee spelling
         of a fixture, mirroring core.fixture_facts through observed_at, pointing at the ALIAS (not at the referee: a merge never
         touches this table). alias_id NULL: the provider took the referee off the match. The referee at a moment T is the newest
         row with observed_at <= T. Written only by fbi.people.referees; nothing is updated or deleted.'""")

    op.execute("""
        CREATE VIEW core.fixture_referees AS
        SELECT o.fixture_id, o.observed_at, o.alias_id, a.referee_id
          FROM core.fixture_officials o
          JOIN core.referee_aliases a ON a.id = o.alias_id
         WHERE o.role = 'referee'
           AND NOT EXISTS (SELECT 1 FROM core.fixture_officials n
                            WHERE n.fixture_id = o.fixture_id AND n.role = o.role AND n.observed_at > o.observed_at)""")
    op.execute("""
        COMMENT ON VIEW core.fixture_referees IS
        'The referee of each match as of now: the newest core.fixture_officials row per match, through its alias. A match whose
         newest row has no alias (the provider took the referee off) is not here. For "as of a moment" read fixture_officials
         with observed_at <= that moment.'""")

    op.execute("""
        CREATE TABLE core.referee_candidates (
            id         BIGSERIAL   PRIMARY KEY,
            referee_a  BIGINT      NOT NULL REFERENCES core.referees(id),
            referee_b  BIGINT      NOT NULL REFERENCES core.referees(id),
            reason     TEXT        NOT NULL
                       CHECK (reason IN ('same_name_other_scope', 'longer_name', 'initial_and_full', 'spelling_variant', 'manual')),
            score      REAL        NOT NULL CHECK (score >= 0),
            impact     INTEGER     NOT NULL DEFAULT 0 CHECK (impact >= 0),
            evidence   JSONB       NOT NULL DEFAULT '{}'::jsonb,
            status     TEXT        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'merged', 'rejected')),
            decided_by TEXT,
            decided_at TIMESTAMPTZ,
            version    TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT referee_candidates_ordered CHECK (referee_a < referee_b),
            CONSTRAINT referee_candidates_pair UNIQUE (referee_a, referee_b),
            CONSTRAINT referee_candidates_decided CHECK ((status = 'open') = (decided_at IS NULL))
        )""")
    op.execute("CREATE INDEX referee_candidates_open ON core.referee_candidates (impact DESC, score DESC) WHERE status = 'open'")
    op.execute("""
        COMMENT ON TABLE core.referee_candidates IS
        'The merge queue (plan F3): pairs of referees whose names could be one person and that no rule joined (reason: the
         same name written in another scope, a name and the same name with a middle name that two longer names also fit, an
         initial beside several full names, a typing variant; manual: a row made by the decision of a person for a pair the rules never suggested). score ranks the suggestion, impact is the matches of the smaller
         side, evidence the two spellings that raised it. Open rows are derived and re-derived on every pass; a rejected row is a
         decision and keeps the pair from being suggested again; a pair of referees who kick off at the same time is never here.'""")

    op.execute("""
        CREATE TABLE core.referee_events (
            id         BIGSERIAL   PRIMARY KEY,
            at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor      TEXT        NOT NULL CHECK (length(btrim(actor)) > 0),
            action     TEXT        NOT NULL CHECK (action IN ('merge', 'undo', 'split', 'reject', 'reopen', 'rename')),
            referee_id BIGINT      REFERENCES core.referees(id),
            other_id   BIGINT      REFERENCES core.referees(id),
            alias_ids  BIGINT[]    NOT NULL DEFAULT '{}',
            undone_by  BIGINT      REFERENCES core.referee_events(id),
            detail     JSONB       NOT NULL DEFAULT '{}'::jsonb
        )""")
    op.execute("CREATE INDEX referee_events_referee ON core.referee_events (referee_id, at DESC)")
    op.execute("""
        COMMENT ON TABLE core.referee_events IS
        'What was changed in the referees after the first placement (plan F3): merge (referee_id keeps, other_id was merged
         into it, alias_ids are the aliases that moved), undo (reverses the merge event named in detail), split (alias_ids went
         from referee_id to the new other_id), reject / reopen (a candidate decision), rename. actor is who did it (admin:<user>
         or script:<name>). Append-only, except undone_by on a merge that was undone.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS core.referee_events")
    op.execute("DROP TABLE IF EXISTS core.referee_candidates")
    op.execute("DROP VIEW IF EXISTS core.fixture_referees")
    op.execute("DROP TABLE IF EXISTS core.fixture_officials")
    op.execute("DROP TABLE IF EXISTS core.referee_aliases")
    op.execute("DROP TABLE IF EXISTS core.referees")
