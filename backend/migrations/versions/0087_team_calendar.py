"""Every team's calendar, in every competition, kept apart from the matches PrediGol follows (plan F4)

WHY THIS EXISTS
---------------
``core.fixtures`` holds the matches of the competitions PrediGol follows (``core.competitions.is_tracked``): 246,017 of them on
22 Oct 2026, every one in a followed competition. A team plays more than that: a cup or a continental tie that is not followed,
a friendly. Rest and congestion, read from ``core.fixtures`` alone, are therefore *bounds* (the real rest is at most the recorded
one, the real number of matches at least the recorded one), and the AI's packet has to say so (plan F0, defect 10). The provider can
list a team's matches in ALL its competitions (``/fixtures?team=&season=``); this revision gives that list a place to live.

WHY NOT A MARK ON ``core.fixtures`` (the plan said "1 column + 1 view")
-----------------------------------------------------------------------
A match of a competition that is not followed would need a competition, a season and, for the opponent, a team in ``core``;
and every query that reads ``core.fixtures`` (the Elo, the features, the backtests, the picks, the settlement) would have to learn to
leave it out. A separate table makes it impossible by construction for such a match to reach a model or a pick, and a test holds the
door shut (``tests/unit/test_calendar_isolation.py``). The outcome the plan asked for - a calendar with all of a team's matches - is
the same; only the mechanism differs.

WHAT IS ADDED
-------------
``core.calendar_matches``  one row per (provider fixture, ``observed_at``), change-only, like every reference table: a row is added when
    what the provider says about the match changes (it is rescheduled, it is played, its score changes). "What did we know about the
    schedule at time T" is the newest row with ``observed_at <= T`` - the calendar is read *as of* a moment, never as of today.
    It holds only matches that ``core.fixtures`` does not hold when they are read; the view below never shows one twice.
``core.calendar_fetches``  the log of the questions: when a team's list was last read (per team and season), how many matches it gave and
    how many of them PrediGol already follows. A calendar is only as complete as its last fetch, and a packet built at time T
    may only claim what was fetched by T.
``core.calendar_matches_latest``  the newest row of each match (and when it was first seen).
``core.team_calendar``  per team, the matches of both sources side by side: ``source`` is ``followed`` (``core.fixtures``) or
    ``calendar`` (this revision's table). The newest state - for a reading as of a moment use ``fbi.competitions.team_calendar``.

Nothing existing is altered: two new tables and two views. The downgrade drops them. The tables are derived (every row names the RAW
payload that said it), so losing them loses nothing that cannot be read again.

Revision ID: 0087
Revises: 0086
"""

from __future__ import annotations

from alembic import op

revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). Both tables are new; their foreign key
    # takes a short lock on raw.ingestion_payloads.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE core.calendar_matches (
            provider_fixture_id   BIGINT       NOT NULL CHECK (provider_fixture_id > 0),
            observed_at           TIMESTAMPTZ  NOT NULL,
            kickoff_at            TIMESTAMPTZ  NOT NULL,
            status_short          TEXT         NOT NULL CHECK (length(btrim(status_short)) > 0),
            status_group          TEXT         NOT NULL
                                  CHECK (status_group IN ('scheduled', 'live', 'finished', 'cancelled', 'postponed')),
            provider_league_id    INTEGER      NOT NULL,
            league_name           TEXT         NOT NULL CHECK (length(btrim(league_name)) > 0),
            league_country        TEXT,
            season                INTEGER      NOT NULL,
            round                 TEXT,
            home_provider_team_id INTEGER      NOT NULL CHECK (home_provider_team_id > 0),
            home_name             TEXT         NOT NULL CHECK (length(btrim(home_name)) > 0),
            away_provider_team_id INTEGER      NOT NULL CHECK (away_provider_team_id > 0),
            away_name             TEXT         NOT NULL CHECK (length(btrim(away_name)) > 0),
            goals_home            SMALLINT     CHECK (goals_home >= 0),
            goals_away            SMALLINT     CHECK (goals_away >= 0),
            payload_hash          TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
            normalizer_version    TEXT         NOT NULL,
            PRIMARY KEY (provider_fixture_id, observed_at),
            CONSTRAINT calendar_matches_two_teams CHECK (home_provider_team_id <> away_provider_team_id)
        )""")
    op.execute("CREATE INDEX calendar_matches_home ON core.calendar_matches (home_provider_team_id, observed_at)")
    op.execute("CREATE INDEX calendar_matches_away ON core.calendar_matches (away_provider_team_id, observed_at)")
    op.execute("""
        COMMENT ON TABLE core.calendar_matches IS
        'A team''s matches in competitions PrediGol does not follow (plan F4): date, rival, competition and state as the provider
         lists them in /fixtures?team=&season=, change-only (a row when the match is rescheduled, played or its score changes).
         Never a model input and never a pick: nothing that trains, predicts or decides reads it - it feeds rest and congestion
         for display and for the AI packet. Read as of a moment: the newest row with observed_at <= that moment.'""")

    op.execute("""
        CREATE TABLE core.calendar_fetches (
            provider_team_id   INTEGER      NOT NULL CHECK (provider_team_id > 0),
            season             INTEGER      NOT NULL,
            fetched_at         TIMESTAMPTZ  NOT NULL,
            matches            INTEGER      NOT NULL CHECK (matches >= 0),
            followed           INTEGER      NOT NULL CHECK (followed >= 0 AND followed <= matches),
            rows_added         INTEGER      NOT NULL DEFAULT 0 CHECK (rows_added >= 0),
            payload_hash       TEXT         NOT NULL REFERENCES raw.ingestion_payloads(hash),
            normalizer_version TEXT         NOT NULL,
            PRIMARY KEY (provider_team_id, season, fetched_at)
        )""")
    op.execute("CREATE INDEX calendar_fetches_read ON core.calendar_fetches (provider_team_id, fetched_at DESC)")
    op.execute("""
        COMMENT ON TABLE core.calendar_fetches IS
        'When a team''s list of matches (all competitions, one season) was read from the provider, how many matches it gave and how
         many of them PrediGol already follows (core.fixtures). A calendar is only as complete as its last fetch: a packet built at
         time T may claim only what had been fetched by T.'""")

    op.execute("""
        CREATE VIEW core.calendar_matches_latest AS
        SELECT provider_fixture_id, observed_at, first_seen_at, kickoff_at, status_short, status_group, provider_league_id,
               league_name, league_country, season, round, home_provider_team_id, home_name, away_provider_team_id, away_name,
               goals_home, goals_away, payload_hash, normalizer_version
          FROM (SELECT m.*,
                       min(m.observed_at) OVER (PARTITION BY m.provider_fixture_id) AS first_seen_at,
                       row_number() OVER (PARTITION BY m.provider_fixture_id ORDER BY m.observed_at DESC) AS newest
                  FROM core.calendar_matches m) x
         WHERE newest = 1""")

    op.execute("""
        CREATE VIEW core.team_calendar AS
        SELECT t.id AS team_id, t.provider_team_id, f.provider_fixture_id, f.id AS fixture_id, 'followed'::text AS source,
               f.kickoff_at, f.status_short, f.status_group, f.created_at AS known_since,
               (f.home_team_id = t.id) AS is_home,
               o.id AS opponent_team_id, o.provider_team_id AS opponent_provider_team_id, o.name AS opponent_name,
               c.provider_league_id, c.name AS competition_name, c.country AS competition_country,
               c.competition_type, cs.season, f.round,
               CASE WHEN f.home_team_id = t.id THEN r.goals_home ELSE r.goals_away END AS goals_for,
               CASE WHEN f.home_team_id = t.id THEN r.goals_away ELSE r.goals_home END AS goals_against
          FROM core.teams t
          JOIN core.fixtures f ON f.home_team_id = t.id OR f.away_team_id = t.id
          JOIN core.teams o ON o.id = CASE WHEN f.home_team_id = t.id THEN f.away_team_id ELSE f.home_team_id END
          JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
        UNION ALL
        SELECT t.id, t.provider_team_id, m.provider_fixture_id, NULL::bigint, 'calendar'::text,
               m.kickoff_at, m.status_short, m.status_group, m.first_seen_at,
               (m.home_provider_team_id = t.provider_team_id),
               o.id, CASE WHEN m.home_provider_team_id = t.provider_team_id THEN m.away_provider_team_id
                          ELSE m.home_provider_team_id END,
               CASE WHEN m.home_provider_team_id = t.provider_team_id THEN m.away_name ELSE m.home_name END,
               m.provider_league_id, m.league_name, m.league_country, c.competition_type, m.season, m.round,
               CASE WHEN m.home_provider_team_id = t.provider_team_id THEN m.goals_home ELSE m.goals_away END,
               CASE WHEN m.home_provider_team_id = t.provider_team_id THEN m.goals_away ELSE m.goals_home END
          FROM core.teams t
          JOIN core.calendar_matches_latest m ON t.provider_team_id IN (m.home_provider_team_id, m.away_provider_team_id)
          LEFT JOIN core.teams o ON o.provider_team_id = CASE WHEN m.home_provider_team_id = t.provider_team_id
                                                              THEN m.away_provider_team_id ELSE m.home_provider_team_id END
          LEFT JOIN core.competitions c ON c.provider_league_id = m.provider_league_id
         WHERE NOT EXISTS (SELECT 1 FROM core.fixtures f WHERE f.provider_fixture_id = m.provider_fixture_id)""")
    op.execute("""
        COMMENT ON VIEW core.team_calendar IS
        'Per team, every match known now: the ones PrediGol follows (source = followed, core.fixtures) and the others the provider
         lists for the team (source = calendar, core.calendar_matches), never the same match twice. Newest state. For a reading as
         of a moment (a packet, a backtest) use fbi.competitions.team_calendar, which honours observed_at.'""")


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS core.team_calendar")
    op.execute("DROP VIEW IF EXISTS core.calendar_matches_latest")
    op.execute("DROP TABLE IF EXISTS core.calendar_fetches")
    op.execute("DROP TABLE IF EXISTS core.calendar_matches")
