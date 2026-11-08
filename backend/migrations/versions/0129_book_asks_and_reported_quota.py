"""The book's own asks and the provider's reported quota (plan Cuotas, BE-011)

WHY THIS EXISTS
---------------
The six model windows ask ``/odds`` at most six times a match, the last one three hours before kick-off; measured over 14 days
(1,578 matches) the provider's last pre-match update came a median 103 minutes before kick-off, after that capture in 84 % of
the matches. The explorer's book (``market.book_current``, revision 0128) may ask again in between (``fbi.odds.book_refresh``,
behind ``FBI_ODDS_BOOK_REFRESH``, off by default) - without the models, the picks, the shadow layer or the parlay seeing a single
price of it.

market.book_asks
----------------
One row per ``/odds?fixture=`` request of a book refresh, answered or empty, with the hash of the answer's first page: the same
shape and meaning as ``market.odds_asks`` (revision 0064), which stays the capture's alone. That separation is the point:
``market.odds_asks`` is what ``fbi.odds.quote_current`` (the Match Center), the capture planner and the extractor's readers go by,
and none of them reads this table. The book reads both (the newest ask before kick-off decides, A -> B -> A reads A, an empty
answer withdraws). ``window_minutes`` is the refresh point the ask served.

The bodies go to RAW and to ``raw.ingestion_payloads`` like any capture, under the refresh's ledger run (job
``odds_book_refresh``); ``fbi.odds.quote_extract`` skips a payload whose run is that job, so ``market.odds_quotes``,
``market.odds_snapshots``, ``market.market_consensus`` and ``quote_current`` see what they saw before. RAW keeps an identical body
once: when another job later receives a body a refresh fetched first, ``fbi.ingestion.ledger.RunLedger.record_payloads`` gives
the index row to that job, at its own fetch time - the row it would have written had the refresh never asked (code, not schema).

raw.provider_reported_quota
---------------------------
What the provider says of our quota in the headers of each answer (``x-ratelimit-requests-limit`` / ``-remaining`` for the day,
``X-RateLimit-Limit`` / ``-Remaining`` for the minute), which nobody read until now: one row per provider and UTC day, the latest
observation. ``raw.provider_quota`` stays OUR budget, counted before each request; this is the provider's own count, read after.

market.book_current.books
-------------------------
How many bookmakers a row quotes (it was only inside ``summary``): the explorer's family counts read it for every row of a window
without opening the JSON. Filled by the builder (``bk-2``), which rewrites every row of an older builder on its next pass.

Additive only: two new tables and one nullable column, no default (no rewrite). Privileges: the worker writes and the API reads
both tables through ``deploy/vps/db/grants.sql``, run by the release after every migration (its default privileges already cover a
table the owner creates). Downgrade drops them.

Revision ID: 0129
Revises: 0128
"""

from __future__ import annotations

from alembic import op

revision = "0129"
down_revision = "0128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The tables are new; the foreign keys take
    # a short lock on raw.ingestion_payloads and raw.ingestion_runs, and the new column one on market.book_current (a cache).
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE market.book_asks (
            provider_fixture_id BIGINT      NOT NULL,
            asked_at            TIMESTAMPTZ NOT NULL,
            minutes_to_ko       INTEGER     NOT NULL,
            window_minutes      INTEGER,
            results             INTEGER     NOT NULL CHECK (results >= 0),
            quotes              INTEGER     NOT NULL DEFAULT 0 CHECK (quotes >= 0),
            payload_hash        TEXT        REFERENCES raw.ingestion_payloads(hash),
            run_id              BIGINT      REFERENCES raw.ingestion_runs(id),
            PRIMARY KEY (provider_fixture_id, asked_at)
        )""")
    op.execute("CREATE INDEX book_asks_asked_at ON market.book_asks (asked_at)")
    op.execute("""
        COMMENT ON TABLE market.book_asks IS
        'Every /odds request of the book refreshes (plan Cuotas, BE-011; fbi.odds.book_refresh), answered or empty: results =
         response entries, quotes = prices the provider''s reader parsed, payload_hash = the first page. The shape of
         market.odds_asks, which stays the capture''s: nothing the models, the picks, the Match Center or the capture planner
         read looks here. window_minutes = the refresh point served. Read by the current-price book (fbi.odds.book) only.'""")
    op.execute("""
        CREATE TABLE raw.provider_reported_quota (
            provider           TEXT        NOT NULL,
            quota_date         DATE        NOT NULL,
            observed_at        TIMESTAMPTZ NOT NULL,
            requests_limit     INTEGER,
            requests_remaining INTEGER,
            minute_limit       INTEGER,
            minute_remaining   INTEGER,
            PRIMARY KEY (provider, quota_date)
        )""")
    op.execute("""
        COMMENT ON TABLE raw.provider_reported_quota IS
        'The PROVIDER''s count of our quota, as its answers'' headers said it (x-ratelimit-requests-limit / -remaining: the
         day; X-RateLimit-Limit / -Remaining: the minute): one row per provider and UTC day, the latest observation
         (observed_at). raw.provider_quota is OUR budget, counted before each request; this is read after.'""")
    op.execute("ALTER TABLE market.book_current ADD COLUMN books SMALLINT")
    op.execute("""
        COMMENT ON COLUMN market.book_current.books IS
        'How many bookmakers the row quotes (summary.books), for the explorer''s counts without opening the JSON. Written by
         builder bk-2 on; NULL only in a row an older builder wrote, which the next pass rewrites.'""")


def downgrade() -> None:
    op.execute("ALTER TABLE market.book_current DROP COLUMN IF EXISTS books")
    op.execute("DROP TABLE IF EXISTS raw.provider_reported_quota")
    op.execute("DROP TABLE IF EXISTS market.book_asks")
