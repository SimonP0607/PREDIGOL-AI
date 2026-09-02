"""No snapshot is called a closing line until it has been proven to be one.

The legacy project believed it had closing-line value. It had no historical odds
at all. The rule these tests enforce is stricter than "don't lie in the docs":
the database itself refuses to record the claim without recording the evidence.

  * There is no table or column named closing_* or clv_* anywhere in the schema.
  * near_close_snapshots / pick_line_value store minutes_to_ko, so the distance
    from kickoff is always visible.
  * is_validated_close cannot be true without close_validation_method.
"""

from __future__ import annotations

import psycopg

from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_accepted, must_be_rejected

FORBIDDEN_NAME_SQL = """
SELECT table_schema || '.' || table_name || '.' || column_name
FROM information_schema.columns
WHERE table_schema IN ('raw','core','market','features','models','picks','analytics','audit')
  AND (column_name LIKE '%%closing%%' OR column_name = 'clv' OR column_name LIKE 'clv\\_%%')
UNION ALL
SELECT table_schema || '.' || table_name
FROM information_schema.tables
WHERE table_schema IN ('raw','core','market','features','models','picks','analytics','audit')
  AND (table_name LIKE '%%closing%%' OR table_name LIKE '%%clv%%')
"""


def test_no_object_in_the_schema_claims_to_be_a_closing_line(db: psycopg.Connection) -> None:
    """A naming test, and deliberately so. The failure mode being prevented is
    a future contributor adding `closing_odds` and the whole team quietly
    believing the number means CLV."""
    with db.cursor() as cur:
        cur.execute(FORBIDDEN_NAME_SQL)
        offenders = [row[0] for row in cur.fetchall()]
    assert offenders == [], (
        "These objects assert an unvalidated closing line: "
        + ", ".join(offenders)
        + ". Use near_close_* until closing-line equivalence is demonstrated empirically."
    )


def test_a_near_close_snapshot_defaults_to_unvalidated(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_accepted(db) as cur:
        cur.execute(
            "INSERT INTO market.near_close_snapshots "
            "(fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,captured_at,"
            " minutes_to_ko,source) "
            "VALUES (%s,%s,'1X2','Home',0,1.95,'2026-09-15 18:48Z',12,'live') "
            "RETURNING is_validated_close, close_validation_method",
            (seed.fixture_id, seed.bookmaker_id),
        )
        assert cur.fetchone() == (False, None)


def test_claiming_a_validated_close_without_a_method_is_rejected(
    db: psycopg.Connection, seed: Seed
) -> None:
    with must_be_rejected(db, "is_validated_close true with no method") as cur:
        cur.execute(
            "INSERT INTO market.near_close_snapshots "
            "(fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,captured_at,"
            " minutes_to_ko,source,is_validated_close) "
            "VALUES (%s,%s,'1X2','Home',0,1.95,'2026-09-15 18:48Z',12,'live',true)",
            (seed.fixture_id, seed.bookmaker_id),
        )


def test_a_negative_distance_to_kickoff_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    """minutes_to_ko < 0 would mean the "pre-kickoff" price was captured after
    the match started."""
    with must_be_rejected(db, "minutes_to_ko = -5") as cur:
        cur.execute(
            "INSERT INTO market.near_close_snapshots "
            "(fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,captured_at,"
            " minutes_to_ko,source) "
            "VALUES (%s,%s,'1X2','Home',0,1.95,'2026-09-15 19:05Z',-5,'live')",
            (seed.fixture_id, seed.bookmaker_id),
        )


def test_line_value_records_how_far_from_kickoff_the_reference_price_was(
    db: psycopg.Connection, seed: Seed
) -> None:
    """near_close_minutes_to_ko is NOT NULL: every line-value figure carries the
    evidence needed to judge whether it means anything."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema='picks' AND table_name='pick_line_value' "
            "AND column_name='near_close_minutes_to_ko'"
        )
        assert cur.fetchone() == ("NO",)
