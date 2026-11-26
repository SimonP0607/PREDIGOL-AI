"""The consensus of the real close of the market (plan RP-1.4, finding H7), beside the reference that was always called "the close"

WHY THIS EXISTS
---------------
Every closing-line value of the system (``intel.decision_outcomes.clv``) is measured against the last consensus WE captured before kick-off: a
median of ~175 minutes before it (F7, 23 Oct 2026). The provider's last pre-match price per bookmaker (``market.final_prematch_odds``, read after
the match) is a median of ~85 minutes before kick-off and exists for most matches. This migration gives the second one a place of its own, so the two
can be seen side by side; it replaces nothing and rewrites no row.

WHAT CHANGES (additive: two new tables, no existing table is touched, ``lock_timeout`` 10 s)
* ``market.closing_consensus``: the de-vigged consensus of the LAST price of each bookmaker, when it was stamped in the last hour before kick-off, per
  match / market / selection / line / method, with the number of bookmakers and the minutes before kick-off it stands for. Written once.
* ``intel.decision_real_close``: for each decision that was settled, the value of its price against that real close (``clv_real``, the same
  ``clv-v1`` formula) and how near kick-off it was. It is a table of its own and not two columns of ``intel.decision_outcomes`` because that table
  is append-only by trigger: a column added to it could never be filled for the decisions already settled, and the plan asks to backfill. Append-only
  by the same trigger (``intel.refuse_change``).

Nothing here is read before a match: the real close does not exist before it, and no decision, pick or model reads either table.

Revision ID: 0179
Revises: 0178
"""

from __future__ import annotations

from alembic import op

revision = "0179"
down_revision = "0178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        CREATE TABLE market.closing_consensus (
            fixture_id          BIGINT       NOT NULL REFERENCES core.fixtures(id) ON DELETE CASCADE,
            market_key          TEXT         NOT NULL REFERENCES market.markets(key),
            selection           TEXT         NOT NULL,
            line                NUMERIC(6,2) NOT NULL DEFAULT 0,
            devig_method        TEXT         NOT NULL CHECK (devig_method IN ('shin', 'proportional', 'power')),
            p_fair              NUMERIC(8,6) NOT NULL CHECK (p_fair > 0 AND p_fair < 1),
            n_bookmakers        SMALLINT     NOT NULL CHECK (n_bookmakers >= 1),
            minutes_to_ko       INTEGER      NOT NULL CHECK (minutes_to_ko >= 0),
            newest_minutes_to_ko INTEGER     NOT NULL CHECK (newest_minutes_to_ko >= 0),
            best_odds           NUMERIC(9,3),
            version             TEXT         NOT NULL,
            computed_at         TIMESTAMPTZ  NOT NULL,
            PRIMARY KEY (fixture_id, market_key, selection, line, devig_method)
        )""")
    op.execute("""
        COMMENT ON TABLE market.closing_consensus IS
          'The consensus of the real close: the last pre-match price of each bookmaker (market.final_prematch_odds) stamped in the last hour before
           kick-off, de-vigged and averaged. minutes_to_ko is the median of the books'' stamps, newest_minutes_to_ko the nearest. Evaluation only: it
           exists after the match, no decision may read it.'""")
    op.execute("""
        CREATE TABLE intel.decision_real_close (
            decision_id    BIGINT       PRIMARY KEY REFERENCES intel.decisions(id),
            fixture_id     BIGINT       NOT NULL REFERENCES core.fixtures(id),
            real_p_fair    NUMERIC(8,6) NOT NULL,
            real_minutes_to_ko INTEGER  NOT NULL,
            n_bookmakers   SMALLINT     NOT NULL,
            clv_real       NUMERIC(10,6) NOT NULL,
            reference      TEXT         NOT NULL,
            version        TEXT         NOT NULL,
            computed_at    TIMESTAMPTZ  NOT NULL
        )""")
    op.execute("""
        COMMENT ON TABLE intel.decision_real_close IS
          'The value of a settled decision''s price against the consensus of the real close (market.closing_consensus, Shin): odds x p - 1, the
           clv-v1 formula. Beside intel.decision_outcomes.clv, which is measured against the last captured consensus; neither replaces the other.'""")
    op.execute("""
        CREATE TRIGGER decision_real_close_append_only BEFORE UPDATE OR DELETE ON intel.decision_real_close
        FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP TABLE IF EXISTS intel.decision_real_close")
    op.execute("DROP TABLE IF EXISTS market.closing_consensus")
