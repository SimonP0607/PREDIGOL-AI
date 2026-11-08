"""The current-price book: the prices IN FORCE of every match, for every bet type the provider sends (plan Cuotas, BE-010)

WHY THIS EXISTS
---------------
The provider sends 137 bet types (14 days, 1,703 matches); the platform structures 55 of them into ``market.odds_quotes``,
the history the models, the picks and the shadow families read, and the odds page shows 5. Extracting the other types into that
history would triple its growth (measured: 3.23 million rows a day against 1.32) for prices nobody models. The explorer needs
something else: for each upcoming match, the price in force of every type, by bookmaker, with the best price and - where it
means something - the fair one. This table is that, and nothing more: a CACHE, rebuilt from RAW (``fbi.odds.book``), never a
source of truth.

ONE ROW PER (match, bet type) OF THE ANSWER IN FORCE
----------------------------------------------------
Which answer is in force is decided exactly as ``fbi.odds.quote_current`` decides it (A -> B -> A reads A; an empty answer
withdraws every price): the builder calls the same function. The row says which body (``payload_hash``), when it was first
fetched (``captured_at``), the provider's own update stamp (``provider_update_at``), the ask whose answer it is
(``checked_at``) and since when it has been the answer (``in_force_since``). ``summary`` holds lines -> selections -> the odds of
each bookmaker, the best price and its bookmaker, how many bookmakers, the fair price where the type allows one, the difference
with it and the outlier flag.

DELIBERATE CHOICES
------------------
* Nothing here is read by the models, the picks, the shadow layer or the parlay: ``market.odds_snapshots``,
  ``market.market_consensus`` and ``market.odds_quotes`` are not touched, and nothing writes this table unless the owner
  switches the book on (``FBI_ODDS_BOOK``, off by default).
* Rows of matches that kicked off more than 6 hours ago are deleted by the builder: the history stays in RAW (never deleted)
  and, for the extracted types, in ``market.odds_quotes``.
* Bookmakers are named by the PROVIDER's id inside ``summary`` (``market.bookmakers.provider_bookmaker_id``): the book is built
  from RAW alone and writes nothing anywhere else.
* Not partitioned: one row per match and type of the next few days (50-150 MB measured, see the owner's guide), deleted as the
  matches end.
* Privileges: like every table of ``market``, the worker writes it and the API reads it through ``deploy/vps/db/grants.sql``,
  which the release runs after every migration (and whose default privileges cover a table the owner creates).
* Additive only: no existing table, view or constraint is altered. Downgrade drops the table.

Revision ID: 0128
Revises: 0127
"""

from __future__ import annotations

from alembic import op

revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). The table is new; the foreign keys
    # take a short lock on core.fixtures, market.market_definitions and raw.ingestion_payloads.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE market.book_current (
            fixture_id          BIGINT      NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            definition_id       INTEGER     NOT NULL REFERENCES market.market_definitions(id),
            kickoff_at          TIMESTAMPTZ NOT NULL,
            captured_at         TIMESTAMPTZ NOT NULL,
            provider_update_at  TIMESTAMPTZ,
            checked_at          TIMESTAMPTZ NOT NULL,
            in_force_since      TIMESTAMPTZ NOT NULL,
            newer_pending       BOOLEAN     NOT NULL DEFAULT false,
            payload_hash        TEXT        NOT NULL REFERENCES raw.ingestion_payloads(hash),
            builder_version     TEXT        NOT NULL,
            summary             JSONB       NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
            built_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (fixture_id, definition_id),
            CHECK (captured_at < kickoff_at),
            CHECK (captured_at <= in_force_since AND in_force_since <= checked_at)
        )""")
    op.execute("CREATE INDEX book_current_definition_kickoff_idx ON market.book_current (definition_id, kickoff_at)")
    op.execute("CREATE INDEX book_current_kickoff_idx ON market.book_current (kickoff_at)")
    op.execute("""
        COMMENT ON TABLE market.book_current IS
        'The current-price book (plan Cuotas, BE-010): one row per match and bet type of the provider''s answer IN FORCE (the
         rule of fbi.odds.quote_current: A -> B -> A reads A, an empty answer withdraws every price), for every type tax-v3 can
         read. A cache rebuilt from RAW by fbi.odds.book (python -m scripts.rebuild_odds_book); rows of matches that kicked off
         more than 6 h ago are deleted. Nothing of the models, picks, shadow layer or parlay reads it.'""")
    op.execute("""
        COMMENT ON COLUMN market.book_current.summary IS
        'lines -> selections -> {odds: provider bookmaker id -> decimal odds, best, best_bk, n} and, where the type allows a
         fair price (an exhaustive type, three complete bookmakers), {fair, p, n_fair, edge = best * p - 1, outlier = edge >
         0.25}. Layout version in "v"; the builder in builder_version.'""")
    op.execute("""
        COMMENT ON COLUMN market.book_current.captured_at IS
        'When the body in force was first fetched (RAW keeps an identical body once). checked_at is the ask whose answer it is,
         in_force_since the first ask of the unbroken run of asks it answered.'""")
    op.execute("""
        COMMENT ON COLUMN market.book_current.newer_pending IS
        'A newer ask brought a body the extractor has not read yet: what is in force is the newest one it has read.'""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market.book_current")
