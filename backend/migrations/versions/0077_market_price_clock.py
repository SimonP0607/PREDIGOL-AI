"""The price clock: every priced market structured from what the provider already sent (plan F1)

WHY THIS EXISTS
---------------
API-Football sends 333 of its 338 pre-match bet types in every ``/odds`` answer and keeps pre-match prices for only
7 days. We modelled five of them: the other 333 stayed in the gzipped RAW payloads and nothing could be asked of
them. A week without structuring them is a week of price history that cannot be validated later, and price history is
the one piece of evidence that cannot be bought back. Nothing here asks the provider anything: the extractor reads the
RAW payloads the capture already stored (``raw.ingestion_payloads`` + the gzipped body) and writes four NEW tables.
The live pipeline (``market.odds_snapshots`` and everything that reads it) is not touched.

THE FOUR TABLES
---------------
``market.market_families``    the small vocabulary of kinds of market (result, goals, goals by half, corners, ...).
``market.market_definitions`` one row per provider bet id: which family, which period, which subject, how its
                              ``value`` strings are read, whether its prices are extracted, and its status. It is
                              the registry that decides what the extractor does; changing a row and replaying RAW is
                              how a market starts (or stops) being structured. Nothing is lost by NOT extracting
                              a bet today: its prices are in RAW, and RAW is never deleted.
``market.odds_extractions``   the ledger: one row per distinct RAW ``/odds`` body, with the provider's own ``update``
                              stamp, the kick-off the payload itself named, how many prices were written and how many
                              were refused. "Which payloads are not structured yet" is a question this table answers,
                              and the idempotency of the whole job rests on its unique ``payload_hash``.
``market.odds_quotes``        the prices: (fixture, bookmaker, definition, selection, line, captured_at) -> odds,
                              RANGE-partitioned by month like ``odds_snapshots``. ``captured_at`` is in the primary
                              key, so a price is never overwritten, only followed by the next one.

DELIBERATE CHOICES
------------------
* A quote row is the first time we saw that price body, not every time we asked: RAW keeps identical bodies once.
  The asks themselves stay in ``market.odds_asks``. A quote is in force until the next row of the same
  (fixture, bookmaker, definition, selection, line).
* ``captured_at`` is when WE saw the price (the payload's ``fetched_at``). For a payload fetched after kick-off (the
  provider keeps pre-match prices for 7 days, and ``final_prematch`` reads them back) the only trustworthy instant is
  the provider's own ``update`` stamp, and only when it is before kick-off; otherwise nothing is written.
* ``minutes_to_ko`` is measured against the kick-off the payload itself carried, which is the kick-off at the time of
  the capture, not the one a later reschedule left in ``core.fixtures``.
* The line follows the convention of ``odds_snapshots``: a number the schema can compare, 0 when the market has no
  line, and for handicap-shaped markets the handicap that applies to the selection stored beside it.
* Partitions are created here for the months the backfill needs (the series starts on 2026-09-25) and for the months
  ahead; from then on ``fbi.odds.partitions`` maintains them with the odds_snapshots ones (the worker is not the
  owner and may not create them; the owner's daily maintenance does).
* Additive only: no existing table, view, trigger or constraint is altered. Downgrade drops the four tables.

Revision ID: 0077
Revises: 0076
"""

from __future__ import annotations

from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None

FAMILIES = (
    # key, label, description, sort_order, extract_default
    ("result", "Result", "Full-time result markets: 1X2, double chance, draw no bet, handicaps.", 10, True),
    ("goals", "Goals", "Full-time goal markets: totals, both teams to score, team totals, odd/even, exact goals.", 20, True),
    ("goals_half", "Goals by half", "Anything about the goals or the result of one half: halves' totals, winners, "
                                    "both teams to score, handicaps, HT/FT.", 30, True),
    ("corners", "Corners", "Corner totals, handicaps, 1X2 and team corners.", 40, True),
    ("cards", "Cards", "Card totals (yellow, red, booking points), handicaps, team cards.", 50, True),
    ("shots", "Team shots", "Shots and shots on target of the teams (not of players).", 60, True),
    ("fouls", "Fouls", "Fouls committed by the teams.", 70, False),
    ("offsides", "Offsides", "Offsides of the teams.", 80, False),
    ("tackles", "Tackles", "Tackles of the teams.", 85, False),
    ("saves", "Goalkeeper saves", "Saves by the goalkeepers (team level).", 90, False),
    ("timing", "Timing and sequences", "Minute of the goal, goal or corner in an interval, result at minute X, "
                                       "first/last team to score, races.", 100, False),
    ("special", "Specials", "Own goal, penalty awarded, method of the goal, extra time, penalties.", 110, False),
    ("advance", "Qualification", "To qualify, to advance handicap.", 120, False),
    ("players", "Players", "Anything about a named player: scorers, shots, cards, assists, fouls.", 130, False),
    ("other_sport", "Other sports", "Bet types of other sports that the catalogue lists (American football, "
                                    "tennis sets): never football.", 140, False),
    ("unclassified", "Unclassified", "A bet the provider sent that the taxonomy has not classified yet.", 999, False),
)

# The months the backfill needs and the months ahead. The series of RAW /odds payloads starts on 2026-09-25.
PARTITION_MONTHS = (
    (2026, 9), (2026, 10), (2026, 11), (2026, 12), (2027, 1), (2027, 2), (2027, 3),
)


def _month_end(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The tables are new and
    # nothing is altered, but the foreign keys take a short lock on core.fixtures and market.bookmakers.
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute("""
        CREATE TABLE market.market_families (
            key             TEXT PRIMARY KEY,
            label           TEXT        NOT NULL,
            description     TEXT        NOT NULL,
            sort_order      SMALLINT    NOT NULL,
            extract_default BOOLEAN     NOT NULL
        );
        COMMENT ON TABLE market.market_families IS
          'The kinds of market the price clock distinguishes. Reference data, seeded by the migration.';
    """)
    for key, label, description, sort_order, extract_default in FAMILIES:
        op.execute(
            "INSERT INTO market.market_families (key, label, description, sort_order, extract_default) VALUES "
            f"('{key}', '{label}', '{description.replace(chr(39), chr(39) * 2)}', {sort_order}, "
            f"{'true' if extract_default else 'false'})"
        )

    op.execute("""
        CREATE TABLE market.market_definitions (
            id                  SERIAL PRIMARY KEY,
            provider            TEXT        NOT NULL DEFAULT 'api-football',
            scope               TEXT        NOT NULL DEFAULT 'prematch' CHECK (scope IN ('prematch', 'inplay')),
            provider_bet_id     INTEGER     NOT NULL,
            name                TEXT        NOT NULL,
            family              TEXT        NOT NULL REFERENCES market.market_families(key),
            period              TEXT        NOT NULL CHECK (period IN ('FT', '1H', '2H', 'INTERVAL', 'OTHER')),
            subject             TEXT        NOT NULL CHECK (subject IN ('match', 'home', 'away', 'player', 'keeper')),
            kind                TEXT        NOT NULL,
            schema              TEXT        NOT NULL,
            has_line            BOOLEAN     NOT NULL DEFAULT false,
            line_is_signed      BOOLEAN     NOT NULL DEFAULT false,
            away_line_negated   BOOLEAN     NOT NULL DEFAULT false,
            status              TEXT        NOT NULL CHECK (status IN ('ACTIVE', 'RESEARCH', 'CANDIDATE', 'NOT_MODELABLE')),
            extract             BOOLEAN     NOT NULL DEFAULT false,
            market_key          TEXT        REFERENCES market.markets(key),
            settle_rule         TEXT,
            taxonomy_version    TEXT        NOT NULL,
            classified_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (provider, scope, provider_bet_id),
            CHECK (NOT line_is_signed OR has_line),
            CHECK (NOT away_line_negated OR line_is_signed)
        );
        CREATE INDEX market_definitions_family_idx ON market.market_definitions (family, extract);
        COMMENT ON TABLE market.market_definitions IS
          'One row per provider bet id: what it is, how its values are read, whether its prices are extracted.
           Written by fbi.odds.quote_taxonomy (idempotent). A bet the taxonomy does not know arrives as
           family = unclassified, extract = false: visible, never silently dropped.';
        COMMENT ON COLUMN market.market_definitions.extract IS
          'Prices of this bet are structured into market.odds_quotes. false does not lose anything: they stay in RAW
           and a replay with extract = true structures them.';
        COMMENT ON COLUMN market.market_definitions.away_line_negated IS
          'The provider repeats the HOME handicap on the away row (bet 4: "Home -0.25" / "Away -0.25"); the stored
           line is the handicap that applies to the stored selection, so the away row is negated.';
        COMMENT ON COLUMN market.market_definitions.settle_rule IS
          'The settlement rule that can grade this bet, or NULL when none is implemented. A priced bet with no rule is
           observed, never picked.';
    """)

    op.execute("""
        CREATE TABLE market.odds_extractions (
            id                   BIGSERIAL PRIMARY KEY,
            payload_hash         TEXT        NOT NULL UNIQUE REFERENCES raw.ingestion_payloads(hash),
            extractor_version    TEXT        NOT NULL,
            provider_fixture_id  BIGINT      NOT NULL,
            fixture_id           BIGINT      REFERENCES core.fixtures(id),
            page                 SMALLINT,
            fetched_at           TIMESTAMPTZ NOT NULL,
            provider_update_at   TIMESTAMPTZ,
            kickoff_at           TIMESTAMPTZ,
            captured_at          TIMESTAMPTZ,
            stamped_by           TEXT        NOT NULL CHECK (stamped_by IN ('fetch', 'provider_update', 'none')),
            bookmakers           SMALLINT    NOT NULL DEFAULT 0,
            bets_seen            SMALLINT    NOT NULL DEFAULT 0,
            bets_extracted       SMALLINT    NOT NULL DEFAULT 0,
            quotes_written       INTEGER     NOT NULL DEFAULT 0,
            quotes_refused       INTEGER     NOT NULL DEFAULT 0,
            status               TEXT        NOT NULL CHECK (status IN ('ok', 'empty', 'no_fixture', 'after_kickoff', 'error')),
            detail               TEXT,
            extracted_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX odds_extractions_fetched_idx ON market.odds_extractions (fetched_at);
        CREATE INDEX odds_extractions_fixture_idx ON market.odds_extractions (fixture_id, captured_at);
        CREATE INDEX odds_extractions_pending_idx ON market.odds_extractions (status, extracted_at)
            WHERE status IN ('no_fixture', 'error');
        COMMENT ON TABLE market.odds_extractions IS
          'The ledger of the price clock: one row per distinct RAW /odds body. The unique payload_hash makes the job
           idempotent; extractor_version says which version of the taxonomy and the parser last read it, so a new
           version replays by updating the row, never by adding a second.';
        COMMENT ON COLUMN market.odds_extractions.stamped_by IS
          'fetch: the quotes carry the instant we fetched the payload. provider_update: the payload was fetched after
           kick-off and the quotes carry the provider''s own update stamp (before kick-off). none: nothing written.';
    """)

    op.execute("""
        CREATE TABLE market.odds_quotes (
            fixture_id      BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            bookmaker_id    INTEGER      NOT NULL REFERENCES market.bookmakers(id),
            definition_id   INTEGER      NOT NULL REFERENCES market.market_definitions(id),
            selection       TEXT         NOT NULL CHECK (char_length(selection) <= 60),
            line            NUMERIC(7,2) NOT NULL DEFAULT 0,
            odds_decimal    NUMERIC(9,3) NOT NULL CHECK (odds_decimal > 1.0 AND odds_decimal < 1000),
            captured_at     TIMESTAMPTZ  NOT NULL,
            minutes_to_ko   INTEGER      NOT NULL CHECK (minutes_to_ko >= 0),
            extraction_id   BIGINT       NOT NULL REFERENCES market.odds_extractions(id),
            PRIMARY KEY (fixture_id, bookmaker_id, definition_id, selection, line, captured_at),
            CHECK (line * 4 = trunc(line * 4))
        ) PARTITION BY RANGE (captured_at);
        COMMENT ON TABLE market.odds_quotes IS
          'Prices of every structured market, from the RAW /odds payloads. captured_at is part of the key: a price is
           never overwritten. A row is the first time that price body was seen; it stays in force until the next row
           of the same (fixture, bookmaker, definition, selection, line). Read it AS OF a cut-off
           (captured_at <= cutoff); there is no "latest" view on purpose.';
        COMMENT ON COLUMN market.odds_quotes.line IS
          '0 when the market has no line (market_definitions.has_line = false). For handicap-shaped markets the
           handicap that applies to the selection stored beside it.';
        COMMENT ON COLUMN market.odds_quotes.minutes_to_ko IS
          'Minutes between captured_at and the kick-off the payload carried, floored at 0.';
        CREATE TABLE market.odds_quotes_default PARTITION OF market.odds_quotes DEFAULT;
        CREATE INDEX odds_quotes_captured_brin ON market.odds_quotes USING BRIN (captured_at);
        CREATE INDEX odds_quotes_definition_idx ON market.odds_quotes (definition_id, captured_at);
    """)
    for year, month in PARTITION_MONTHS:
        end_year, end_month = _month_end(year, month)
        op.execute(
            f"CREATE TABLE market.odds_quotes_{year}_{month:02d} PARTITION OF market.odds_quotes "
            f"FOR VALUES FROM ('{year:04d}-{month:02d}-01') TO ('{end_year:04d}-{end_month:02d}-01')"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.odds_quotes")
    op.execute("DROP TABLE IF EXISTS market.odds_extractions")
    op.execute("DROP TABLE IF EXISTS market.market_definitions")
    op.execute("DROP TABLE IF EXISTS market.market_families")
