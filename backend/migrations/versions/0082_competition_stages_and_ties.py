"""A competition season is stored as stages and knock-out ties, and every fixture says which stage, tie and leg it is (plan F2)

WHY THIS EXISTS
---------------
Where a match sits in its competition reached the system as free text (``core.fixtures.round``: "Apertura - Quarter-finals",
"Round of 16", "Group Stage - 3"), and four places read that text with a regular expression of their own - the standings
phases, the AI context, the dossier, the neutral-venue rule - so they could disagree about one match. Nothing said that a
match is the second leg of a tie, what the aggregate was, or who went through: the dossier guessed "the last meeting of the
same two teams in the last 60 days is the first leg", which takes a group-stage match for a first leg.

The reader of a label is now one module (``fbi.competitions.stages``) and the grouping of a stage's matches into ties is
another (``fbi.competitions.ties``); ``fbi.competitions.builder`` runs them over a competition season and writes what they
say here, so the rest of the system asks the database instead of re-reading words.

WHAT IS ADDED
-------------
``core.competition_stages``  one row per (competition season, stage): the stage (the round label without its match day),
    its phase (the label's first part: "Apertura" for "Apertura - Quarter-finals"), what it is (kind and role), which round
    of a bracket (round_key, teams in the round), how many fixtures and when, how the ties of the stage are played
    (single / two_legged / mixed / series, or not_a_bracket when no pairings can be built) and the versions of the rules
    that read it. A stage of replays names the stage it replays (``base_stage``).
``core.ties``  one row per pairing of a knock-out stage: the two sides (A is the home side of the first match), the format,
    the matches and how many were played, the aggregate, the winner and how it was decided (normal time, extra time,
    penalties, aggregate, away goals, tiebreak, walkover, series), the shoot-out, and whether the next round agrees with the
    winner (``winner_check``). A pairing that cannot be settled says why (``reason``) instead of guessing.
``core.fixtures.stage_id / leg / tie_id``  the stage a fixture belongs to and, in a knock-out stage, its tie and its leg.
    NULL means "not built yet": the system behaves as it did before this revision.

These are DERIVED tables, like ``core.fixture_venue_class``: the builder rewrites them when the facts change (a result
corrected, a round renamed by the provider, a rule improved), so they are not append-only. They hold the OUTCOME of a tie
(winner, aggregate): like ``core.fixture_results`` they must not be read before the match they describe; the pre-match
readers go through ``fbi.competitions.context``, which answers "as of" a moment from the legs settled by then, and a test
keeps the other modules away from the outcome columns.

Nothing here changes a model, a forecast, a pick or a settlement. ``core.fixtures.updated_at`` is not touched when a fixture
is given its stage (the builder writes the three columns only).

Additive and non-blocking: the three new columns are nullable with no default (instant), the foreign keys are added NOT VALID
and validated afterwards (a validation does not block writers), and the indexes are partial, so they are empty when created.
The downgrade drops the columns and the two tables (the tables hold only derived rows: ``python -m scripts.competition_stages
build`` rewrites them).

Revision ID: 0082
Revises: 0081
"""

from __future__ import annotations

from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE core.competition_stages (
            id                    BIGSERIAL   PRIMARY KEY,
            competition_season_id BIGINT      NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            stage                 TEXT        NOT NULL,
            ordinal               SMALLINT    NOT NULL CHECK (ordinal >= 1),
            phase                 TEXT        NOT NULL,
            base_stage            TEXT        NOT NULL,
            is_replay             BOOLEAN     NOT NULL DEFAULT false,
            kind                  TEXT        NOT NULL
                                  CHECK (kind IN ('league', 'knockout', 'qualifying', 'friendly', 'unresolved')),
            role                  TEXT        NOT NULL
                                  CHECK (role IN ('league', 'group', 'knockout', 'playoff', 'final', 'third_place',
                                                  'placement', 'qualifying', 'friendly', 'unresolved')),
            rule                  TEXT        NOT NULL CHECK (length(btrim(rule)) > 0),
            numbered              BOOLEAN     NOT NULL,
            round_key             TEXT,
            teams                 SMALLINT    CHECK (teams > 0),
            round_no              SMALLINT    CHECK (round_no > 0),
            fixtures              INTEGER     NOT NULL CHECK (fixtures > 0),
            first_kickoff_at      TIMESTAMPTZ NOT NULL,
            last_kickoff_at       TIMESTAMPTZ NOT NULL,
            tie_format            TEXT        CHECK (tie_format IN ('single', 'two_legged', 'mixed', 'series',
                                                                    'not_a_bracket', 'empty')),
            tie_reason            TEXT,
            ties                  INTEGER     NOT NULL DEFAULT 0 CHECK (ties >= 0),
            stages_version        TEXT        NOT NULL CHECK (length(btrim(stages_version)) > 0),
            ties_version          TEXT        NOT NULL CHECK (length(btrim(ties_version)) > 0),
            build_hash            TEXT        NOT NULL CHECK (length(btrim(build_hash)) > 0),
            built_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT competition_stages_stage_key UNIQUE (competition_season_id, stage),
            CONSTRAINT competition_stages_kickoffs_in_order CHECK (last_kickoff_at >= first_kickoff_at)
        )""")
    op.execute("""
        COMMENT ON TABLE core.competition_stages IS
        'The stages of a competition season (plan F2): the round label without its match day (stage), what it is (kind: league,
         knockout, qualifying, friendly or unresolved - the coarse reading the standings use; role: the finer one), which
         round of a bracket (round_key, teams) and how its ties are played (tie_format). Read from the labels by
         fbi.competitions.stages (stages_version) and from the matches by fbi.competitions.ties (ties_version); written by
         fbi.competitions.builder. Derived and rewritten when the facts or the rules change; unresolved is a state, not a
         failure: a label no rule reads is kept as it is.'""")
    op.execute("COMMENT ON COLUMN core.competition_stages.stage IS "
               "'The round label without its trailing match-day number (Clausura - 12 -> Clausura); empty when the fixture has no round.'")
    op.execute("COMMENT ON COLUMN core.competition_stages.base_stage IS "
               "'The stage whose ties this stage''s matches belong to: itself, or for a stage of replays (is_replay) the stage replayed.'")
    op.execute("COMMENT ON COLUMN core.competition_stages.rule IS "
               "'The rule of fbi.competitions.stages that decided kind (evidence), e.g. league_format, numbered, knockout_word, no_rule.'")
    op.execute("COMMENT ON COLUMN core.competition_stages.build_hash IS "
               "'A digest of the whole season''s build (fbi.competitions.seasons.fingerprint), the same on every stage of a season: when "
               "the builder computes the digest it already finds here it writes nothing, so a rebuild that changes nothing costs nothing.'")
    op.execute("COMMENT ON COLUMN core.competition_stages.tie_format IS "
               "'How the ties of a knock-out stage are played, read from its matches: single, two_legged, mixed, series; not_a_bracket "
               "when a team meets several opponents in the stage (no pairings are built); NULL for a stage that has no ties.'")

    op.execute("""
        CREATE TABLE core.ties (
            id             BIGSERIAL   PRIMARY KEY,
            stage_id       BIGINT      NOT NULL REFERENCES core.competition_stages(id) ON DELETE CASCADE,
            team_a_id      BIGINT      NOT NULL REFERENCES core.teams(id),
            team_b_id      BIGINT      NOT NULL REFERENCES core.teams(id),
            format         TEXT        NOT NULL CHECK (format IN ('single', 'two_legged', 'replay', 'series')),
            status         TEXT        NOT NULL CHECK (status IN ('scheduled', 'in_progress', 'decided', 'unresolved')),
            legs           SMALLINT    NOT NULL CHECK (legs >= 1),
            played         SMALLINT    NOT NULL CHECK (played >= 0),
            aggregate_a    SMALLINT,
            aggregate_b    SMALLINT,
            winner_team_id BIGINT      REFERENCES core.teams(id),
            decided_by     TEXT        CHECK (decided_by IN ('normal_time', 'extra_time', 'penalties', 'aggregate',
                                                             'away_goals', 'tiebreak', 'walkover', 'series')),
            reason         TEXT,
            decided_at     TIMESTAMPTZ,
            shootout_a     SMALLINT,
            shootout_b     SMALLINT,
            winner_check   TEXT        NOT NULL DEFAULT 'unknown'
                           CHECK (winner_check IN ('confirmed', 'contradicted', 'unknown')),
            flags          TEXT[]      NOT NULL DEFAULT '{}',
            version        TEXT        NOT NULL CHECK (length(btrim(version)) > 0),
            built_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ties_distinct_sides CHECK (team_a_id <> team_b_id),
            CONSTRAINT ties_aggregate_pair CHECK ((aggregate_a IS NULL) = (aggregate_b IS NULL)),
            CONSTRAINT ties_shootout_pair CHECK ((shootout_a IS NULL) = (shootout_b IS NULL)),
            CONSTRAINT ties_winner_in_pair CHECK (winner_team_id IS NULL OR winner_team_id IN (team_a_id, team_b_id)),
            CONSTRAINT ties_decided_iff_winner CHECK ((status = 'decided') = (winner_team_id IS NOT NULL)),
            CONSTRAINT ties_decided_by_needs_winner CHECK (decided_by IS NULL OR winner_team_id IS NOT NULL)
        )""")
    op.execute("CREATE UNIQUE INDEX ties_pair ON core.ties "
               "(stage_id, LEAST(team_a_id, team_b_id), GREATEST(team_a_id, team_b_id))")
    op.execute("""
        COMMENT ON TABLE core.ties IS
        'The pairings of a knock-out stage (plan F2): the matches between the same two sides in one stage (a team plays one
         opponent per round), how many there are (format), the aggregate, who went through and how (decided_by), the
         shoot-out, and whether the next round agrees (winner_check: confirmed, contradicted, unknown). Side A is the home side of
         the first match. A tie that cannot be settled is unresolved with its reason - a winner is never guessed and the
         away-goals rule is never assumed. The aggregate counts the goals of the matches played (extra time in, shoot-out out).
         OUTCOME data: like fixture_results it must not be read before the match it describes; pre-match readers use
         fbi.competitions.context. Derived and rewritten by fbi.competitions.builder.'""")
    op.execute("COMMENT ON COLUMN core.ties.winner_check IS "
               "'confirmed: the winner plays on in a later round of the bracket and the loser does not; contradicted: the next round says the "
               "opposite (an administrative decision or a data error: the sporting winner is kept and an audit lists it); unknown: nothing "
               "comes after (a final) or the next round is not stored.'")
    op.execute("COMMENT ON COLUMN core.ties.flags IS "
               "'Facts about how the tie was read: score_repaired (the provider''s extra-time score was double-counted and was repaired with "
               "the shoot-out), score_inconsistent_with_shootout, settled_by_next_round, shootout_not_stored, second_leg_not_listed, "
               "single_leg_in_two_legged_round, legs_not_swapped.'")

    # The columns of a fixture. Nullable, no default: instant. The foreign keys are added NOT VALID and validated after.
    op.execute("ALTER TABLE core.fixtures ADD COLUMN stage_id BIGINT, ADD COLUMN leg SMALLINT, ADD COLUMN tie_id BIGINT")
    op.execute("ALTER TABLE core.fixtures ADD CONSTRAINT fixtures_leg_check CHECK (leg IS NULL OR leg >= 1) NOT VALID")
    op.execute("ALTER TABLE core.fixtures ADD CONSTRAINT fixtures_stage_fk FOREIGN KEY (stage_id) "
               "REFERENCES core.competition_stages(id) ON DELETE SET NULL NOT VALID")
    op.execute("ALTER TABLE core.fixtures ADD CONSTRAINT fixtures_tie_fk FOREIGN KEY (tie_id) "
               "REFERENCES core.ties(id) ON DELETE SET NULL NOT VALID")
    op.execute("ALTER TABLE core.fixtures VALIDATE CONSTRAINT fixtures_leg_check")
    op.execute("ALTER TABLE core.fixtures VALIDATE CONSTRAINT fixtures_stage_fk")
    op.execute("ALTER TABLE core.fixtures VALIDATE CONSTRAINT fixtures_tie_fk")
    op.execute("CREATE INDEX fixtures_stage_id ON core.fixtures (stage_id, kickoff_at) WHERE stage_id IS NOT NULL")
    op.execute("CREATE INDEX fixtures_tie_id ON core.fixtures (tie_id, leg) WHERE tie_id IS NOT NULL")
    op.execute("COMMENT ON COLUMN core.fixtures.stage_id IS "
               "'The stage of its competition season this fixture belongs to (core.competition_stages); NULL until fbi.competitions.builder has read the season.'")
    op.execute("COMMENT ON COLUMN core.fixtures.tie_id IS "
               "'The knock-out tie this fixture is a leg of (core.ties); NULL in a league stage, for a cancelled match, or until the season is built.'")
    op.execute("COMMENT ON COLUMN core.fixtures.leg IS "
               "'Which match of its tie this is (1, 2 ...), in the order played; NULL when tie_id is.'")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP INDEX IF EXISTS core.fixtures_tie_id")
    op.execute("DROP INDEX IF EXISTS core.fixtures_stage_id")
    op.execute("ALTER TABLE core.fixtures DROP CONSTRAINT IF EXISTS fixtures_tie_fk")
    op.execute("ALTER TABLE core.fixtures DROP CONSTRAINT IF EXISTS fixtures_stage_fk")
    op.execute("ALTER TABLE core.fixtures DROP CONSTRAINT IF EXISTS fixtures_leg_check")
    op.execute("ALTER TABLE core.fixtures DROP COLUMN IF EXISTS tie_id, DROP COLUMN IF EXISTS leg, "
               "DROP COLUMN IF EXISTS stage_id")
    op.execute("DROP TABLE IF EXISTS core.ties")
    op.execute("DROP TABLE IF EXISTS core.competition_stages")
