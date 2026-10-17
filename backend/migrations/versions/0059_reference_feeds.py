"""reference feeds: the API-Football endpoints the contract audit found missing, kept change-only

The contract audit (4 Oct 2026) listed 16 documented endpoints PrediGol never requested and 8 it only
sampled. This revision adds the tables their normalizers write. Every answer is a RAW payload first;
a table row names that payload and the normalizer version. Nothing is updated in place: a row is
added when what the provider says changes, and the ``*_latest`` views give the newest state.

* ``core.reference_checks`` - per feed and target, when it was last asked and when its answer last
  changed, whatever the answer (the same role ``core.context_checks`` plays for tables and injuries).
* ``core.provider_predictions`` - /predictions: the provider's own forecast of a match. AUXILIARY: it is
  the provider's opinion, labelled as such; no model reads it and no pick is made from it.
* ``core.season_rounds`` / ``core.season_current_round`` - /fixtures/rounds (with dates; and ``current``).
* ``core.season_leaders`` - /players/topscorers, /topassists, /topyellowcards, /topredcards.
* ``core.coach_profiles`` / ``core.coach_careers`` - /coachs.
* ``core.person_sidelined`` / ``core.person_trophies`` - /sidelined and /trophies, players and coaches.
* ``core.player_transfers`` - /transfers.
* ``core.countries`` - /countries (name, code, flag).
* ``core.player_season_stats`` - /players?league&season: the provider's season aggregate per player, team and
  competition (filled by the backfill's players_season units, weekly for current seasons).
* ``core.team_season_stats`` (0003, never written until now) gains provenance and the counts /teams/statistics
  sends; the team_statistics feed fills it.
* ``market.odds_mapping_seen`` - /odds/mapping: when the provider first listed a fixture as priced.
* ``market.provider_catalogue_changes`` - a bet or bookmaker the provider renamed: the old and the new
  name, the payload that said it (the catalogue tables keep the current name).
* the evidence ledger accepts area ``raw_integrity`` / ``reference``, issue ``RAW_PAYLOAD_DAMAGED`` and run kind
  ``raw_integrity`` (``scripts.audit_raw_integrity``).

Lists (a season's rounds, a top-scorer table, a coach's career, a player's transfers) are written as
**snapshots**: when the list a payload gives differs from the newest one stored for that key, the whole
list is added under the payload's time, in the provider's order (``ordinal``).

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from alembic import op

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

PAYLOAD = "payload_hash TEXT NOT NULL REFERENCES raw.ingestion_payloads(hash), normalizer_version TEXT NOT NULL"

AREAS_0057 = ("baseline", "leagues", "fixtures", "standings", "teams", "team_stats", "team_history", "players",
              "player_stats", "identity", "squads", "injuries", "coaches", "venues", "normalization", "golden", "odds",
              "phases", "api_contract", "field_coverage", "predictions", "transfers", "trophies", "sidelined", "h2h",
              "media", "datasets")
AREAS = (*AREAS_0057, "raw_integrity", "reference")
ISSUES_0057 = ("PROVIDER_STALE", "NORMALIZER_BUG", "MAPPING_ERROR", "MISSING_BACKFILL", "STALE_ENTITY",
               "SEASON_MISMATCH", "STANDINGS_MISMATCH", "PLAYER_STATS_MISMATCH", "TEAM_STATS_MISMATCH",
               "WRONG_SEASON", "MISSING_SEASON", "DUPLICATE_COMPETITION", "WRONG_TYPE", "WRONG_COUNTRY",
               "STALE_CURRENT_SEASON", "REAL_LOW_HISTORY", "PROVIDER_COVERAGE", "IDENTITY_MAPPING_ERROR",
               "SEASON_NOT_MIGRATED", "DROPPED_USEFUL_FIELD", "UNSUPPORTED_FIELD", "INTENTIONALLY_IGNORED",
               "PROVIDER_DEFINED_METRIC", "FIXTURE_MISMATCH", "RESULT_MISMATCH", "PROVIDER_EXTERNAL_MISMATCH",
               "DUPLICATE_ENTITY", "PRODUCT_SCOPE", "PHASE_TABLE_MIXED", "PHASE_TABLE_UNMAPPED", "BUG_DROPPED_FIELD",
               "STORED_NOT_USED", "API_CONTRACT_GAP", "MISSING_ENDPOINT")
ISSUES = (*ISSUES_0057, "RAW_PAYLOAD_DAMAGED")
KINDS_0057 = ("baseline", "leagues", "fixtures", "standings", "team_stats", "team_history", "player_stats", "identity",
              "fields", "golden", "external", "phases", "api_contract", "field_coverage", "teams", "players",
              "data_truth", "datasets")
KINDS = (*KINDS_0057, "raw_integrity")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _checks(kinds: tuple[str, ...], areas: tuple[str, ...], issues: tuple[str, ...]) -> None:
    op.execute(f"""
        ALTER TABLE audit.truth_v2_runs DROP CONSTRAINT IF EXISTS truth_v2_runs_kind_check;
        ALTER TABLE audit.truth_v2_runs ADD CONSTRAINT truth_v2_runs_kind_check CHECK (kind IN ({_in(kinds)}));
        ALTER TABLE audit.evidence_ledger DROP CONSTRAINT IF EXISTS evidence_ledger_area_check;
        ALTER TABLE audit.evidence_ledger ADD CONSTRAINT evidence_ledger_area_check CHECK (area IN ({_in(areas)}));
        ALTER TABLE audit.evidence_ledger DROP CONSTRAINT IF EXISTS evidence_ledger_issue_type_check;
        ALTER TABLE audit.evidence_ledger ADD CONSTRAINT evidence_ledger_issue_type_check
            CHECK (issue_type IN ({_in(issues)}));
    """)


def _latest(view: str, table: str, key: str) -> str:
    """The newest snapshot of each key: every row stamped with that key's newest observed_at."""
    return (f"CREATE OR REPLACE VIEW {view} AS SELECT t.* FROM {table} t "
            f"WHERE t.observed_at = (SELECT max(x.observed_at) FROM {table} x WHERE "
            + " AND ".join(f"x.{k} = t.{k}" for k in key.split(", ")) + ")")


def upgrade() -> None:
    _checks(KINDS, AREAS, ISSUES)
    op.execute("""
        CREATE TABLE IF NOT EXISTS core.reference_checks (
            feed          TEXT        NOT NULL,
            target        TEXT        NOT NULL,
            checked_at    TIMESTAMPTZ NOT NULL,
            changed_at    TIMESTAMPTZ,
            payload_hash  TEXT        REFERENCES raw.ingestion_payloads(hash),
            results       INTEGER,
            rows_added    INTEGER     NOT NULL DEFAULT 0,
            error         TEXT,
            PRIMARY KEY (feed, target)
        )""")
    op.execute("COMMENT ON TABLE core.reference_checks IS 'When each reference feed last asked about a target "
               "(a match, a season, a team, a batch of people), what answered, and when the answer last changed.'")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.provider_predictions (
            fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            observed_at         TIMESTAMPTZ NOT NULL,
            winner_team_id      INTEGER,
            winner_name         TEXT,
            winner_comment      TEXT,
            win_or_draw         BOOLEAN,
            under_over          TEXT,
            goals_home          TEXT,
            goals_away          TEXT,
            advice              TEXT,
            percent_home        NUMERIC(5,2) CHECK (percent_home BETWEEN 0 AND 100),
            percent_draw        NUMERIC(5,2) CHECK (percent_draw BETWEEN 0 AND 100),
            percent_away        NUMERIC(5,2) CHECK (percent_away BETWEEN 0 AND 100),
            comparison          JSONB,
            {PAYLOAD},
            PRIMARY KEY (fixture_id, observed_at)
        )""")
    op.execute("""COMMENT ON TABLE core.provider_predictions IS
        'API-Football /predictions: the PROVIDER''s forecast of a match (Poisson, team statistics, last matches;
         no odds), a row per change. Auxiliary and labelled as the provider''s: never a model input, never a pick,
         never mixed with PrediGol''s forecasts or the market.'""")
    op.execute("CREATE OR REPLACE VIEW core.provider_predictions_latest AS SELECT DISTINCT ON (fixture_id) * "
               "FROM core.provider_predictions ORDER BY fixture_id, observed_at DESC")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.season_rounds (
            competition_season_id  BIGINT      NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            observed_at            TIMESTAMPTZ NOT NULL,
            ordinal                SMALLINT    NOT NULL,
            round                  TEXT        NOT NULL,
            dates                  DATE[],
            {PAYLOAD},
            PRIMARY KEY (competition_season_id, observed_at, ordinal)
        )""")
    op.execute("COMMENT ON TABLE core.season_rounds IS '/fixtures/rounds?dates=true: every round of a season in the "
               "provider''s order with its dates, a snapshot per change.'")
    op.execute(_latest("core.season_rounds_latest", "core.season_rounds", "competition_season_id"))
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.season_current_round (
            competition_season_id  BIGINT      NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            observed_at            TIMESTAMPTZ NOT NULL,
            rounds                 TEXT[]      NOT NULL,
            {PAYLOAD},
            PRIMARY KEY (competition_season_id, observed_at)
        )""")
    op.execute("COMMENT ON TABLE core.season_current_round IS '/fixtures/rounds?current=true: the round(s) the "
               "provider calls current, a row per change.'")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.season_leaders (
            competition_season_id  BIGINT      NOT NULL REFERENCES core.competition_seasons(id) ON DELETE CASCADE,
            list                   TEXT        NOT NULL CHECK (list IN ('topscorers', 'topassists', 'topyellowcards',
                                                                        'topredcards')),
            observed_at            TIMESTAMPTZ NOT NULL,
            ordinal                SMALLINT    NOT NULL,
            provider_player_id     INTEGER     NOT NULL,
            player_name            TEXT,
            photo_url              TEXT,
            provider_team_id       INTEGER,
            team_name              TEXT,
            appearances            SMALLINT,
            minutes                INTEGER,
            goals                  SMALLINT,
            assists                SMALLINT,
            penalties_scored       SMALLINT,
            yellow_cards           SMALLINT,
            yellowred_cards        SMALLINT,
            red_cards              SMALLINT,
            rating                 NUMERIC(6,4),
            statistics             JSONB       NOT NULL,
            {PAYLOAD},
            PRIMARY KEY (competition_season_id, list, observed_at, ordinal)
        )""")
    op.execute("COMMENT ON TABLE core.season_leaders IS 'The provider''s top scorers, assists, yellow and red cards "
               "of a season, in its order, a snapshot per change. statistics = the player''s whole entry for that "
               "competition as sent (rating is the provider''s).'")
    op.execute(_latest("core.season_leaders_latest", "core.season_leaders", "competition_season_id, list"))

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.coach_profiles (
            provider_coach_id  INTEGER     NOT NULL,
            observed_at        TIMESTAMPTZ NOT NULL,
            name               TEXT,
            firstname          TEXT,
            lastname           TEXT,
            birth_date         DATE,
            birth_place        TEXT,
            birth_country      TEXT,
            nationality        TEXT,
            height             TEXT,
            weight             TEXT,
            photo_url          TEXT,
            provider_team_id   INTEGER,
            {PAYLOAD},
            PRIMARY KEY (provider_coach_id, observed_at)
        )""")
    op.execute("COMMENT ON TABLE core.coach_profiles IS '/coachs: a coach as the provider describes them, a row per "
               "change (age is not kept: it follows from the birth date).'")
    op.execute("CREATE OR REPLACE VIEW core.coach_profiles_latest AS SELECT DISTINCT ON (provider_coach_id) * "
               "FROM core.coach_profiles ORDER BY provider_coach_id, observed_at DESC")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.coach_careers (
            provider_coach_id  INTEGER     NOT NULL,
            observed_at        TIMESTAMPTZ NOT NULL,
            ordinal            SMALLINT    NOT NULL,
            provider_team_id   INTEGER,
            team_name          TEXT,
            start_date         DATE,
            end_date           DATE,
            {PAYLOAD},
            PRIMARY KEY (provider_coach_id, observed_at, ordinal)
        )""")
    op.execute(_latest("core.coach_careers_latest", "core.coach_careers", "provider_coach_id"))

    for table, cols, comment in (
        ("person_sidelined", "type TEXT, start_date DATE, end_date DATE",
         "/sidelined: the periods a player or coach was out (injury, suspension...), a snapshot per change."),
        ("person_trophies", "league TEXT, country TEXT, season TEXT, place TEXT",
         "/trophies: a player''s or coach''s trophies as the provider lists them, a snapshot per change."),
    ):
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS core.{table} (
                person_kind         TEXT        NOT NULL CHECK (person_kind IN ('player', 'coach')),
                provider_person_id  INTEGER     NOT NULL,
                observed_at         TIMESTAMPTZ NOT NULL,
                ordinal             SMALLINT    NOT NULL,
                {cols},
                {PAYLOAD},
                PRIMARY KEY (person_kind, provider_person_id, observed_at, ordinal)
            )""")
        op.execute(f"COMMENT ON TABLE core.{table} IS '{comment}'")
        op.execute(_latest(f"core.{table}_latest", f"core.{table}", "person_kind, provider_person_id"))

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.player_transfers (
            provider_player_id    INTEGER     NOT NULL,
            observed_at           TIMESTAMPTZ NOT NULL,
            ordinal               SMALLINT    NOT NULL,
            transfer_date         DATE,
            type                  TEXT,
            team_in_id            INTEGER,
            team_in_name          TEXT,
            team_out_id           INTEGER,
            team_out_name         TEXT,
            provider_update_at    TIMESTAMPTZ,
            {PAYLOAD},
            PRIMARY KEY (provider_player_id, observed_at, ordinal)
        )""")
    op.execute("COMMENT ON TABLE core.player_transfers IS '/transfers: a player''s transfers as the provider lists "
               "them (type is its text: a fee, Loan, Free...), a snapshot per change.'")
    op.execute(_latest("core.player_transfers_latest", "core.player_transfers", "provider_player_id"))

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.countries (
            name         TEXT        NOT NULL,
            observed_at  TIMESTAMPTZ NOT NULL,
            code         TEXT,
            flag_url     TEXT,
            {PAYLOAD},
            PRIMARY KEY (name, observed_at)
        )""")
    op.execute("CREATE OR REPLACE VIEW core.countries_latest AS SELECT DISTINCT ON (name) * FROM core.countries "
               "ORDER BY name, observed_at DESC")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS market.odds_mapping_seen (
            provider_fixture_id  BIGINT      PRIMARY KEY,
            provider_league_id   INTEGER,
            season               INTEGER,
            fixture_date         TIMESTAMPTZ,
            first_seen_at        TIMESTAMPTZ NOT NULL,
            provider_update_at   TIMESTAMPTZ,
            {PAYLOAD}
        )""")
    op.execute("COMMENT ON TABLE market.odds_mapping_seen IS '/odds/mapping: the first time the provider listed a "
               "fixture as priced, with its update stamp then. Later listings stay in RAW.'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS market.provider_catalogue_changes (
            catalogue     TEXT        NOT NULL CHECK (catalogue IN ('prematch', 'inplay', 'bookmakers')),
            provider_id   INTEGER     NOT NULL,
            observed_at   TIMESTAMPTZ NOT NULL,
            old_name      TEXT,
            new_name      TEXT,
            {PAYLOAD},
            PRIMARY KEY (catalogue, provider_id, observed_at)
        )""")
    op.execute("COMMENT ON TABLE market.provider_catalogue_changes IS 'A bet or bookmaker the provider renamed: the "
               "catalogue tables keep the current name, this keeps the old one and the payload that changed it.'")
    season_stats()


PLAYER_STAT_COLS = (
    ("appearances", "SMALLINT"), ("lineups", "SMALLINT"), ("minutes", "INTEGER"), ("shirt_number", "SMALLINT"),
    ("position", "TEXT"), ("rating", "NUMERIC(8,6)"), ("captain", "BOOLEAN"), ("subs_in", "SMALLINT"),
    ("subs_out", "SMALLINT"), ("subs_bench", "SMALLINT"), ("shots_total", "SMALLINT"), ("shots_on", "SMALLINT"),
    ("goals", "SMALLINT"), ("goals_conceded", "SMALLINT"), ("assists", "SMALLINT"), ("saves", "SMALLINT"),
    ("passes_total", "INTEGER"), ("passes_key", "SMALLINT"), ("passes_accuracy", "SMALLINT"),
    ("tackles", "SMALLINT"), ("blocks", "SMALLINT"), ("interceptions", "SMALLINT"), ("duels_total", "SMALLINT"),
    ("duels_won", "SMALLINT"), ("dribbles_attempts", "SMALLINT"), ("dribbles_success", "SMALLINT"),
    ("dribbled_past", "SMALLINT"), ("fouls_drawn", "SMALLINT"), ("fouls_committed", "SMALLINT"),
    ("yellow_cards", "SMALLINT"), ("yellowred_cards", "SMALLINT"), ("red_cards", "SMALLINT"),
    ("penalties_won", "SMALLINT"), ("penalties_committed", "SMALLINT"), ("penalties_scored", "SMALLINT"),
    ("penalties_missed", "SMALLINT"), ("penalties_saved", "SMALLINT"),
)


def season_stats() -> None:
    cols = ",\n            ".join(f"{c} {t}" for c, t in PLAYER_STAT_COLS)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS core.player_season_stats (
            provider_player_id  INTEGER     NOT NULL,
            provider_league_id  INTEGER     NOT NULL,
            season              INTEGER     NOT NULL,
            provider_team_id    INTEGER     NOT NULL,
            observed_at         TIMESTAMPTZ NOT NULL,
            {cols},
            {PAYLOAD},
            PRIMARY KEY (provider_player_id, provider_league_id, season, provider_team_id, observed_at)
        )""")
    op.execute("""COMMENT ON TABLE core.player_season_stats IS
        '/players?league&season: the PROVIDER''s season aggregate of a player for one team in one competition (rating
         is its own metric), a row per change. PrediGol''s own aggregates are computed from the per-match statistics
         and labelled apart; this table is the provider''s, for display and for the audit that compares the two.'""")
    op.execute("CREATE INDEX IF NOT EXISTS player_season_stats_league ON core.player_season_stats "
               "(provider_league_id, season)")
    op.execute("CREATE OR REPLACE VIEW core.player_season_stats_latest AS SELECT DISTINCT ON (provider_player_id, "
               "provider_league_id, season, provider_team_id) * FROM core.player_season_stats ORDER BY "
               "provider_player_id, provider_league_id, season, provider_team_id, observed_at DESC")
    # core.team_season_stats (0003) was never written: it gains provenance and the counts the provider sends,
    # and is filled by the team_statistics feed, a snapshot per change.
    op.execute("""
        ALTER TABLE core.team_season_stats
            ADD COLUMN IF NOT EXISTS draws_home SMALLINT, ADD COLUMN IF NOT EXISTS draws_away SMALLINT,
            ADD COLUMN IF NOT EXISTS loses_home SMALLINT, ADD COLUMN IF NOT EXISTS loses_away SMALLINT,
            ADD COLUMN IF NOT EXISTS goals_for_total_home SMALLINT, ADD COLUMN IF NOT EXISTS goals_for_total_away SMALLINT,
            ADD COLUMN IF NOT EXISTS goals_against_total_home SMALLINT,
            ADD COLUMN IF NOT EXISTS goals_against_total_away SMALLINT,
            ADD COLUMN IF NOT EXISTS penalties_scored SMALLINT, ADD COLUMN IF NOT EXISTS penalties_missed SMALLINT,
            ADD COLUMN IF NOT EXISTS payload_hash TEXT REFERENCES raw.ingestion_payloads(hash),
            ADD COLUMN IF NOT EXISTS normalizer_version TEXT""")
    op.execute("""COMMENT ON TABLE core.team_season_stats IS
        '/teams/statistics: the PROVIDER''s aggregate of a team in one competition season, a snapshot per change
         (snapshot_at = the payload''s time). goals_for_home / goals_for_away / goals_against_* are AVERAGES per match;
         *_total_* are counts. raw = the whole answer (minutes, under/over, biggest, line-ups, cards).'""")
    op.execute("CREATE OR REPLACE VIEW core.team_season_stats_latest AS SELECT DISTINCT ON (competition_season_id, "
               "team_id) * FROM core.team_season_stats ORDER BY competition_season_id, team_id, snapshot_at DESC")


def downgrade() -> None:
    _checks(KINDS_0057, AREAS_0057, ISSUES_0057)
    op.execute("DROP VIEW IF EXISTS core.team_season_stats_latest; DROP VIEW IF EXISTS core.player_season_stats_latest; "
               "DROP TABLE IF EXISTS core.player_season_stats")
    op.execute("ALTER TABLE core.team_season_stats DROP COLUMN IF EXISTS draws_home, DROP COLUMN IF EXISTS draws_away, "
               "DROP COLUMN IF EXISTS loses_home, DROP COLUMN IF EXISTS loses_away, "
               "DROP COLUMN IF EXISTS goals_for_total_home, DROP COLUMN IF EXISTS goals_for_total_away, "
               "DROP COLUMN IF EXISTS goals_against_total_home, DROP COLUMN IF EXISTS goals_against_total_away, "
               "DROP COLUMN IF EXISTS penalties_scored, DROP COLUMN IF EXISTS penalties_missed, "
               "DROP COLUMN IF EXISTS payload_hash, DROP COLUMN IF EXISTS normalizer_version")
    for view in ("core.provider_predictions_latest", "core.season_rounds_latest", "core.season_leaders_latest",
                 "core.coach_profiles_latest", "core.coach_careers_latest", "core.person_sidelined_latest",
                 "core.person_trophies_latest", "core.player_transfers_latest", "core.countries_latest"):
        op.execute(f"DROP VIEW IF EXISTS {view}")
    for table in ("market.provider_catalogue_changes", "market.odds_mapping_seen", "core.countries",
                  "core.player_transfers", "core.person_trophies", "core.person_sidelined", "core.coach_careers",
                  "core.coach_profiles", "core.season_leaders", "core.season_current_round", "core.season_rounds",
                  "core.provider_predictions", "core.reference_checks"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
