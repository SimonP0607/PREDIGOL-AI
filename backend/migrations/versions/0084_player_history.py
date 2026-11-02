"""A player's clubs and national team over time, and the coaches' careers tied to people and teams (plan F3)

WHY THIS EXISTS
---------------
The dossier of a national-team match needs to say where each called-up player plays his football and how he is doing there, as of
the day of the match; a club match needs the same for a man who was transferred. Until now the system had the pieces and no
history: the transfers the provider lists (``core.player_transfers``, snapshots), the squad lists (``core.squad_members``, first and
last sighting), the squad sheets of the matches (``core.fixture_lineup_players``) and the statistics (``core.fixture_player_stats``).
Nothing said "from this day to that day he was at this club", and nothing counted his caps: a national-team match was one more
match of a player whose club it did not know.

``fbi.people.spells`` (``spells-v1``) folds the pieces into streaks and ``fbi.people.caps`` (``caps-v1``) classifies his matches for
a senior national side; ``fbi.people.player_history`` writes what they say here. Everything below is DERIVED from the facts that are
already stored (a pass is idempotent and rebuilds it), nothing is asked of the provider, and no model, forecast or pick reads it
yet except the dossier of a match.

WHAT IS ADDED
-------------
``core.player_spells``         one row per STREAK of a player at a club (a player who goes A, B, A has three): the provider's
    club id and the name it was written with, ``valid_from`` (first day he is there, NULL when nobody says since when) and
    ``valid_to`` (first day he is NOT there, NULL while he still is as far as we know), how the streak began to be known
    (transfer, lineup, squad), the matches of his matchday squad the streak holds and the last day something confirms it.
    "Where was he on day D" is ``valid_from <= D < valid_to``.
``core.player_national_caps``  one row per (player, finished match of a SENIOR national side whose squad sheet carries him):
    starter or bench, whether he played (NULL until the statistics arrive) and his minutes. Youth and Olympic sides are not caps.
``core.coach_careers``         two nullable columns: ``coach_id`` (the person, ``core.coaches``) and ``team_id`` (the club,
    ``core.teams``) of each snapshot row, filled by the linking pass (``fbi.people.coach_links``) that also creates the person
    when only his profile exists. ``core.coach_spells`` is the view of the newest snapshot of each career with both links.

Additive: two new tables, one view and two nullable columns without a default (instant on a live table; the foreign keys are added
NOT VALID and validated in the same revision, as in 0082). Nothing existing changes meaning. The downgrade drops them: the two
tables are rebuilt by ``python -m scripts.player_history build --apply``; the links of the careers are rebuilt by the same pass.

Revision ID: 0084
Revises: 0083
"""

from __future__ import annotations

from alembic import op

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE core.player_spells (
            provider_player_id INTEGER     NOT NULL,
            ordinal            SMALLINT    NOT NULL,
            provider_team_id   INTEGER     NOT NULL,
            team_name          TEXT,
            valid_from         DATE,
            valid_to           DATE,
            source             TEXT        NOT NULL,
            matches            INTEGER     NOT NULL DEFAULT 0,
            last_evidence      DATE        NOT NULL,
            via                TEXT,
            version            TEXT        NOT NULL,
            built_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT player_spells_pkey PRIMARY KEY (provider_player_id, ordinal),
            CONSTRAINT player_spells_player_check CHECK (provider_player_id > 0),
            CONSTRAINT player_spells_ordinal_check CHECK (ordinal >= 0),
            CONSTRAINT player_spells_source_check CHECK (source IN ('transfer', 'lineup', 'squad')),
            CONSTRAINT player_spells_matches_check CHECK (matches >= 0),
            CONSTRAINT player_spells_version_check CHECK (length(btrim(version)) > 0),
            CONSTRAINT player_spells_in_order CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to),
            CONSTRAINT player_spells_start_known CHECK (ordinal = 0 OR valid_from IS NOT NULL)
        )""")
    op.execute("CREATE INDEX player_spells_club ON core.player_spells (provider_team_id, valid_from)")
    op.execute("""
        COMMENT ON TABLE core.player_spells IS
        'The streaks of a player at his clubs (plan F3): one row per streak, in order (ordinal 0 is the oldest). A player who goes
         A, B, A has three rows. fbi.people.spells (version) folds the transfers, the squad sheets of the matches and the squad
         lists into them. valid_from is the first day he is there (NULL: nobody says since when, only the first streak can be
         so), valid_to the first day he is NOT (NULL: still there as far as we know), so that where he was on day D is
         valid_from <= D < valid_to. Derived and rebuilt by python -m scripts.player_history build; never edited by hand.'""")
    op.execute("COMMENT ON COLUMN core.player_spells.provider_team_id IS "
               "'The provider''s id of the club (core.teams.provider_team_id when the club is one we hold; a national team is never here).'")
    op.execute("COMMENT ON COLUMN core.player_spells.team_name IS "
               "'The club as we call it (core.teams.name), else as the transfer that named it wrote it.'")
    op.execute("COMMENT ON COLUMN core.player_spells.source IS "
               "'How the streak began to be known: transfer (a transfer dated it), lineup (a match put him there), squad (only a squad list carried him).'")
    op.execute("COMMENT ON COLUMN core.player_spells.matches IS "
               "'Matches of the club in whose matchday squad he was during the streak (starter or bench).'")
    op.execute("COMMENT ON COLUMN core.player_spells.last_evidence IS "
               "'The latest day something says he was there: the freshness of the streak (an open one with an old day is probably over).'")
    op.execute("COMMENT ON COLUMN core.player_spells.via IS "
               "'The provider''s wording of the move that opened the streak (Loan, Free, a fee, Return from loan), when a transfer did.'")

    op.execute("""
        CREATE TABLE core.player_national_caps (
            provider_player_id INTEGER     NOT NULL,
            fixture_id         BIGINT      NOT NULL,
            team_id            BIGINT      NOT NULL,
            is_starter         BOOLEAN     NOT NULL,
            appeared           BOOLEAN,
            minutes            SMALLINT,
            version            TEXT        NOT NULL,
            built_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT player_national_caps_pkey PRIMARY KEY (provider_player_id, fixture_id),
            CONSTRAINT player_national_caps_fixture_fk FOREIGN KEY (fixture_id) REFERENCES core.fixtures(id) ON DELETE CASCADE,
            CONSTRAINT player_national_caps_team_fk FOREIGN KEY (team_id) REFERENCES core.teams(id),
            CONSTRAINT player_national_caps_player_check CHECK (provider_player_id > 0),
            CONSTRAINT player_national_caps_minutes_check CHECK (minutes IS NULL OR minutes >= 0),
            CONSTRAINT player_national_caps_minutes_iff_played CHECK (minutes IS NULL OR appeared IS TRUE),
            CONSTRAINT player_national_caps_version_check CHECK (length(btrim(version)) > 0)
        )""")
    op.execute("CREATE INDEX player_national_caps_fixture ON core.player_national_caps (fixture_id)")
    op.execute("CREATE INDEX player_national_caps_open ON core.player_national_caps (fixture_id) WHERE appeared IS NULL")
    op.execute("""
        COMMENT ON TABLE core.player_national_caps IS
        'A player and his senior national team (plan F3): one row per finished match of a senior national side whose squad
         sheet carries him, starter or bench. appeared: true he played, false he stayed on the bench, NULL it cannot be said yet
         (the statistics of the match have not arrived: the match is revisited until they do). minutes only when he played. Youth
         and Olympic sides are not caps (fbi.people.caps). Derived from core.fixture_lineup_players and core.fixture_player_stats
         and rebuilt by python -m scripts.player_history build; never edited by hand.'""")

    # The careers of the coaches point at the person and the club. Nullable, no default: instant. The foreign keys are added
    # NOT VALID and validated after, the way 0082 does it.
    op.execute("ALTER TABLE core.coach_careers ADD COLUMN coach_id BIGINT, ADD COLUMN team_id BIGINT")
    op.execute("ALTER TABLE core.coach_careers ADD CONSTRAINT coach_careers_coach_fk FOREIGN KEY (coach_id) "
               "REFERENCES core.coaches(id) NOT VALID")
    op.execute("ALTER TABLE core.coach_careers ADD CONSTRAINT coach_careers_team_fk FOREIGN KEY (team_id) "
               "REFERENCES core.teams(id) NOT VALID")
    op.execute("ALTER TABLE core.coach_careers VALIDATE CONSTRAINT coach_careers_coach_fk")
    op.execute("ALTER TABLE core.coach_careers VALIDATE CONSTRAINT coach_careers_team_fk")
    op.execute("CREATE INDEX coach_careers_coach ON core.coach_careers (coach_id) WHERE coach_id IS NOT NULL")
    op.execute("CREATE INDEX coach_careers_team ON core.coach_careers (team_id, start_date) WHERE team_id IS NOT NULL")
    op.execute("COMMENT ON COLUMN core.coach_careers.coach_id IS "
               "'The person (core.coaches) of provider_coach_id; filled by fbi.people.coach_links, NULL until then.'")
    op.execute("COMMENT ON COLUMN core.coach_careers.team_id IS "
               "'The club (core.teams) of provider_team_id when we hold it; filled by fbi.people.coach_links, NULL until then or when the club is unknown to us.'")

    # The newest snapshot of each career, with both links. (core.coach_careers_latest was defined with t.* before these columns
    # existed, so it does not carry them.)
    op.execute("""
        CREATE VIEW core.coach_spells AS
        SELECT k.provider_coach_id, k.coach_id, k.provider_team_id, k.team_id, k.team_name, k.start_date, k.end_date, k.observed_at
          FROM core.coach_careers k
         WHERE k.observed_at = (SELECT max(x.observed_at) FROM core.coach_careers x WHERE x.provider_coach_id = k.provider_coach_id)""")
    op.execute("""
        COMMENT ON VIEW core.coach_spells IS
        'The career of each coach as the provider last listed it (plan F3): one row per club he managed, with the dates the
         provider gave (start_date, end_date; NULL end_date: still there as far as the provider says) and the links to the person
         and the club. Not normalised to the half-open days of core.player_spells: these are the provider''s dates.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP VIEW IF EXISTS core.coach_spells")
    op.execute("DROP INDEX IF EXISTS core.coach_careers_team")
    op.execute("DROP INDEX IF EXISTS core.coach_careers_coach")
    op.execute("ALTER TABLE core.coach_careers DROP CONSTRAINT IF EXISTS coach_careers_team_fk, "
               "DROP CONSTRAINT IF EXISTS coach_careers_coach_fk")
    op.execute("ALTER TABLE core.coach_careers DROP COLUMN IF EXISTS team_id, DROP COLUMN IF EXISTS coach_id")
    op.execute("DROP TABLE IF EXISTS core.player_national_caps")
    op.execute("DROP TABLE IF EXISTS core.player_spells")
