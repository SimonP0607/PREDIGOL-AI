"""The catalogue of markets by family: what settles a bet, and what every match ended with (plan F9)

WHY THIS EXISTS
---------------
After F1 the platform keeps the prices of 55 bets of the provider (``market.market_definitions`` says what each one is), but nothing
says what a price would be graded ON. ``market_definitions.settle_rule`` has been empty since revision 0077, and the only results the
platform could read for a bet were the five markets the pipeline settles. Before a model of corners, of cards or of the goals of a
half is built (F10) the plan asks for the catalogue by family: for each one its definition, the rule that grades it, the dataset of
results and the dataset of prices - and the measured coverage of both, competition by competition.

WHAT IS ADDED (structure only; no row of the catalogue is written here)
------------------------------------------------------------------------
``market.settlement_rules``  the registry of rules. A rule is ONE measure of a match (goals in the first half, corners of the match,
    cards counted as lines, ...) read from the columns of ``market.fixture_outcomes`` it names, in one convention and one version. A
    rule that cannot grade (corners of a half: the provider gives no corners by half) is a row with ``liquidable = false`` and the
    reason - the absence is written down, not implied. A rule is never edited: if a convention changes, it is a new version, and
    the trigger refuses to update or delete one. The rows are written by ``fbi.markets.catalogue.sync`` from ``fbi.markets.rules``.
``market.fixture_outcomes``  a VIEW (no storage): one row per finished match with every figure a rule can read - goals by half,
    corners, cards by period, shots, fouls, offsides, saves - and the competition it belongs to. The figures that come from the
    team statistics are the 90-minute figures only when the match did not go to extra time (the provider does not say whether its
    totals include the extra half hour, so after extra time they are NULL). The cards by period come from the lines of the events
    that F7 classified (``core.fixture_event_kinds``); the match total falls back on the team statistics when there is no
    classification. NULL always means "not known", never zero.
``market.catalogue_runs``  one row per generation of the matrix of markets: the rows themselves (JSONB), the coverage of every
    family by competition, and a summary. Append-only by use.
``market.market_definitions.settle_rule``  (already there) now points at ``market.settlement_rules``: the rule that grades the bet,
    NULL when none can.

NOTHING THAT RUNS TODAY CHANGES
-------------------------------
No existing table is rewritten or rebuilt. The only change to an existing table is one foreign key on ``market.market_definitions``
(338 rows, ``settle_rule`` is NULL in all of them), taken with a ``lock_timeout`` - the worker is stopped while a release migrates.
The new market keys (``OU_1H``, ``CORNERS_OU``...) are NOT inserted here: ``fbi.markets.catalogue.sync`` writes them, with
``is_tracked`` and ``is_model_enabled`` false, so that the five-market pipeline, the quality counters and the tests that count the
catalogue keep seeing what they saw.

Downgrade: drops the view and the two tables, and the foreign key. Nothing else depended on them.
"""

from alembic import op

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076).
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE market.settlement_rules (
            rule_key      TEXT        PRIMARY KEY CHECK (rule_key ~ '^[a-z][a-z0-9_]*@v[0-9]+$'),
            measure       TEXT        NOT NULL CHECK (measure ~ '^[a-z][a-z0-9_]*$'),
            version       INTEGER     NOT NULL CHECK (version >= 1),
            family        TEXT        NOT NULL REFERENCES market.market_families(key),
            period        TEXT        NOT NULL CHECK (period IN ('FT', '1H', '2H')),
            convention    TEXT        NOT NULL CHECK (length(btrim(convention)) > 0),
            columns       TEXT[]      NOT NULL DEFAULT '{}',
            liquidable    BOOLEAN     NOT NULL,
            reason        TEXT        NOT NULL CHECK (reason ~ '^[a-z][a-z0-9_]*$'),
            note          TEXT        NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (measure, version),
            CHECK (rule_key = measure || '@v' || version),
            CHECK ((liquidable AND cardinality(columns) IN (2, 4)) OR (NOT liquidable AND cardinality(columns) = 0))
        )""")
    op.execute("""
        COMMENT ON TABLE market.settlement_rules IS
        'What a bet is graded on: one measure of the match (the columns of market.fixture_outcomes it reads: home and away, in
         that order; four for a measure of two halves), in one convention and one version. liquidable = false is a rule that exists to say WHY nothing can grade (reason). Never edited: a changed
         convention is a new version (the trigger refuses UPDATE and DELETE). Written by fbi.markets.catalogue.sync.'""")
    op.execute("""
        CREATE FUNCTION market.refuse_rule_change() RETURNS trigger LANGUAGE plpgsql AS $fn$
        BEGIN
            RAISE EXCEPTION 'market.settlement_rules: a rule is never edited; write a new version (% refused)', TG_OP
                USING ERRCODE = 'check_violation';
        END
        $fn$""")
    op.execute("CREATE TRIGGER settlement_rules_immutable BEFORE UPDATE OR DELETE ON market.settlement_rules "
               "FOR EACH ROW EXECUTE FUNCTION market.refuse_rule_change()")

    op.execute("""
        ALTER TABLE market.market_definitions
            ADD CONSTRAINT market_definitions_settle_rule_fk
            FOREIGN KEY (settle_rule) REFERENCES market.settlement_rules(rule_key)""")
    op.execute("""
        COMMENT ON COLUMN market.market_definitions.settle_rule IS
        'The key of the rule in market.settlement_rules that grades this bet (what it is graded on and in which convention), or
         NULL when none can: the bet is not understood (kind unspecified) or the data to grade it does not exist (corners of a
         half). A priced bet with no rule is observed, never picked.'""")

    op.execute("""
        CREATE VIEW market.fixture_outcomes AS
        SELECT x.fixture_id,
               x.competition_season_id,
               cs.competition_id,
               cs.season,
               c.competition_type,
               c.is_tracked,
               x.kickoff_at,
               x.extra_time,
               x.goals_home                                            AS goals_ft_home,
               x.goals_away                                            AS goals_ft_away,
               CASE WHEN x.ht_ok THEN x.ht_goals_home END              AS goals_1h_home,
               CASE WHEN x.ht_ok THEN x.ht_goals_away END              AS goals_1h_away,
               CASE WHEN x.ht_ok THEN x.goals_home - x.ht_goals_home END AS goals_2h_home,
               CASE WHEN x.ht_ok THEN x.goals_away - x.ht_goals_away END AS goals_2h_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.corners END     AS corners_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.corners END     AS corners_ft_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.shots END       AS shots_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.shots END       AS shots_ft_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.shots_on_target END AS shots_on_target_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.shots_on_target END AS shots_on_target_ft_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.fouls END       AS fouls_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.fouls END       AS fouls_ft_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.offsides END    AS offsides_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.offsides END    AS offsides_ft_away,
               CASE WHEN x.extra_time THEN NULL ELSE h.saves END       AS saves_ft_home,
               CASE WHEN x.extra_time THEN NULL ELSE a.saves END       AS saves_ft_away,
               -- cards: the lines of the events when F7 classified them (they carry the period), else the team statistics
               CASE WHEN ev.n > 0 THEN ev.y1h_h + ev.y2h_h WHEN NOT x.extra_time THEN h.yellow_cards END AS yellow_ft_home,
               CASE WHEN ev.n > 0 THEN ev.y1h_a + ev.y2h_a WHEN NOT x.extra_time THEN a.yellow_cards END AS yellow_ft_away,
               CASE WHEN ev.n > 0 THEN ev.y1h_h END                    AS yellow_1h_home,
               CASE WHEN ev.n > 0 THEN ev.y1h_a END                    AS yellow_1h_away,
               CASE WHEN ev.n > 0 THEN ev.y2h_h END                    AS yellow_2h_home,
               CASE WHEN ev.n > 0 THEN ev.y2h_a END                    AS yellow_2h_away,
               CASE WHEN ev.n > 0 THEN ev.d1h_h + ev.d2h_h + ev.s1h_h + ev.s2h_h
                    WHEN NOT x.extra_time THEN h.red_cards END         AS red_ft_home,
               CASE WHEN ev.n > 0 THEN ev.d1h_a + ev.d2h_a + ev.s1h_a + ev.s2h_a
                    WHEN NOT x.extra_time THEN a.red_cards END         AS red_ft_away,
               CASE WHEN ev.n > 0 THEN ev.y1h_h + ev.y2h_h + ev.d1h_h + ev.d2h_h + ev.s1h_h + ev.s2h_h
                    WHEN NOT x.extra_time AND h.yellow_cards IS NOT NULL AND h.red_cards IS NOT NULL
                         THEN h.yellow_cards + h.red_cards END         AS cards_lines_ft_home,
               CASE WHEN ev.n > 0 THEN ev.y1h_a + ev.y2h_a + ev.d1h_a + ev.d2h_a + ev.s1h_a + ev.s2h_a
                    WHEN NOT x.extra_time AND a.yellow_cards IS NOT NULL AND a.red_cards IS NOT NULL
                         THEN a.yellow_cards + a.red_cards END         AS cards_lines_ft_away,
               CASE WHEN ev.n > 0 THEN ev.y1h_h + ev.d1h_h + ev.s1h_h END AS cards_lines_1h_home,
               CASE WHEN ev.n > 0 THEN ev.y1h_a + ev.d1h_a + ev.s1h_a END AS cards_lines_1h_away,
               CASE WHEN ev.n > 0 THEN ev.y2h_h + ev.d2h_h + ev.s2h_h END AS cards_lines_2h_home,
               CASE WHEN ev.n > 0 THEN ev.y2h_a + ev.d2h_a + ev.s2h_a END AS cards_lines_2h_away,
               -- booking points: 10 for a yellow, 25 for a straight red, 15 more for the red that follows a second yellow
               CASE WHEN ev.n > 0 THEN 10 * (ev.y1h_h + ev.y2h_h) + 25 * (ev.d1h_h + ev.d2h_h) + 15 * (ev.s1h_h + ev.s2h_h) END
                                                                       AS cards_points_ft_home,
               CASE WHEN ev.n > 0 THEN 10 * (ev.y1h_a + ev.y2h_a) + 25 * (ev.d1h_a + ev.d2h_a) + 15 * (ev.s1h_a + ev.s2h_a) END
                                                                       AS cards_points_ft_away,
               CASE WHEN ev.n > 0 THEN 'events' WHEN NOT x.extra_time AND h.yellow_cards IS NOT NULL THEN 'stats' END AS cards_source,
               CASE WHEN ev.n > 0 AND h.yellow_cards IS NOT NULL AND a.yellow_cards IS NOT NULL
                         AND h.red_cards IS NOT NULL AND a.red_cards IS NOT NULL
                    THEN (ev.y1h_h + ev.y2h_h + ev.d1h_h + ev.d2h_h + ev.s1h_h + ev.s2h_h
                          + ev.y1h_a + ev.y2h_a + ev.d1h_a + ev.d2h_a + ev.s1h_a + ev.s2h_a)
                         = (h.yellow_cards + h.red_cards + a.yellow_cards + a.red_cards) END AS cards_consistent
          FROM (SELECT y.*,
                       (y.ht_goals_home IS NOT NULL AND y.ht_goals_away IS NOT NULL AND y.goals_home IS NOT NULL
                        AND y.goals_away IS NOT NULL
                        AND y.ht_goals_home <= y.goals_home AND y.ht_goals_away <= y.goals_away) AS ht_ok
                  FROM (SELECT f.id AS fixture_id, f.competition_season_id, f.kickoff_at,
                               -- the score after 90 minutes: reg_goals (the stated full-time score, or the final minus extra time) for a
                               -- match played out; for one decided in extra time only the score the provider STATED (settlement says the
                               -- same: without it the 90-minute score is a claim that cannot be made)
                               CASE WHEN (r.et_goals_home IS NOT NULL OR r.pen_home IS NOT NULL OR f.status_short IN ('AET', 'PEN'))
                                    THEN r.ft_goals_home ELSE r.reg_goals_home END AS goals_home,
                               CASE WHEN (r.et_goals_home IS NOT NULL OR r.pen_home IS NOT NULL OR f.status_short IN ('AET', 'PEN'))
                                    THEN r.ft_goals_away ELSE r.reg_goals_away END AS goals_away,
                               r.ht_goals_home, r.ht_goals_away,
                               (r.et_goals_home IS NOT NULL OR r.pen_home IS NOT NULL OR f.status_short IN ('AET', 'PEN')) AS extra_time
                          FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
                         WHERE f.status_group = 'finished') y) x
          JOIN core.competition_seasons cs ON cs.id = x.competition_season_id
          JOIN core.competitions c ON c.id = cs.competition_id
          LEFT JOIN LATERAL (SELECT t.* FROM core.fixture_team_stats t WHERE t.fixture_id = x.fixture_id AND t.team_side = 'home'
                              ORDER BY (t.source = 'api-football') DESC LIMIT 1) h ON true
          LEFT JOIN LATERAL (SELECT t.* FROM core.fixture_team_stats t WHERE t.fixture_id = x.fixture_id AND t.team_side = 'away'
                              ORDER BY (t.source = 'api-football') DESC LIMIT 1) a ON true
          LEFT JOIN LATERAL (
                SELECT count(*) AS n,
                       count(*) FILTER (WHERE e.kind = 'yellow'        AND e.period = '1H' AND e.s = 'home') AS y1h_h,
                       count(*) FILTER (WHERE e.kind = 'yellow'        AND e.period = '1H' AND e.s = 'away') AS y1h_a,
                       count(*) FILTER (WHERE e.kind = 'yellow'        AND e.period = '2H' AND e.s = 'home') AS y2h_h,
                       count(*) FILTER (WHERE e.kind = 'yellow'        AND e.period = '2H' AND e.s = 'away') AS y2h_a,
                       count(*) FILTER (WHERE e.kind = 'red'           AND e.period = '1H' AND e.s = 'home') AS d1h_h,
                       count(*) FILTER (WHERE e.kind = 'red'           AND e.period = '1H' AND e.s = 'away') AS d1h_a,
                       count(*) FILTER (WHERE e.kind = 'red'           AND e.period = '2H' AND e.s = 'home') AS d2h_h,
                       count(*) FILTER (WHERE e.kind = 'red'           AND e.period = '2H' AND e.s = 'away') AS d2h_a,
                       count(*) FILTER (WHERE e.kind = 'second_yellow' AND e.period = '1H' AND e.s = 'home') AS s1h_h,
                       count(*) FILTER (WHERE e.kind = 'second_yellow' AND e.period = '1H' AND e.s = 'away') AS s1h_a,
                       count(*) FILTER (WHERE e.kind = 'second_yellow' AND e.period = '2H' AND e.s = 'home') AS s2h_h,
                       count(*) FILTER (WHERE e.kind = 'second_yellow' AND e.period = '2H' AND e.s = 'away') AS s2h_a
                  FROM (SELECT k.kind, k.period, coalesce(k.player_side, k.side) AS s
                          FROM core.fixture_event_kinds k WHERE k.fixture_id = x.fixture_id) e) ev ON true""")
    op.execute("""
        COMMENT ON VIEW market.fixture_outcomes IS
        'One row per finished match: every figure a settlement rule can read (market.settlement_rules.columns).
         Goals are the 90-minute score (core.fixture_results), halves from the half-time score (NULL when it is missing or
         impossible). Statistics are NULL after extra time. Cards by period come from core.fixture_event_kinds (events-v1); the
         match total falls back on the team statistics. NULL means not known, never zero. A view: no storage, never stale.'""")

    op.execute("""
        CREATE TABLE market.catalogue_runs (
            id               BIGSERIAL   PRIMARY KEY,
            generated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            matrix_version   TEXT        NOT NULL CHECK (length(btrim(matrix_version)) > 0),
            taxonomy_version TEXT        NOT NULL,
            window_days      INTEGER     NOT NULL CHECK (window_days > 0),
            duration_ms      INTEGER     NOT NULL CHECK (duration_ms >= 0),
            rows             JSONB       NOT NULL,
            coverage         JSONB       NOT NULL,
            summary          JSONB       NOT NULL
        )""")
    op.execute("CREATE INDEX catalogue_runs_generated ON market.catalogue_runs (generated_at DESC)")
    op.execute("""
        COMMENT ON TABLE market.catalogue_runs IS
        'One generation of the matrix of markets (plan section 9): rows = the matrix, coverage = result and price coverage of each
         family by competition, summary = counts. Written by fbi.markets.matrix.store; the admin page reads the newest.'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS market.catalogue_runs")
    op.execute("DROP VIEW IF EXISTS market.fixture_outcomes")
    op.execute("ALTER TABLE market.market_definitions DROP CONSTRAINT IF EXISTS market_definitions_settle_rule_fk")
    op.execute("""
        COMMENT ON COLUMN market.market_definitions.settle_rule IS
          'The settlement rule that can grade this bet, or NULL when none is implemented. A priced bet with no rule is
           observed, never picked.'""")
    op.execute("DROP TABLE IF EXISTS market.settlement_rules")
    op.execute("DROP FUNCTION IF EXISTS market.refuse_rule_change()")
