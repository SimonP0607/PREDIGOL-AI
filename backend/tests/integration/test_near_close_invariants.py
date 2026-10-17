"""No snapshot is called a closing line until it has been proven to be one.

The legacy project believed it had closing-line value. It had no historical odds
at all. The rule these tests enforce is stricter than "don't lie in the docs":
the database itself refuses to record the claim without recording the evidence.

  * There is no table or column named closing_* or clv_* anywhere in the schema.
  * near_close_snapshots / pick_line_value store minutes_to_ko, so the distance
    from kickoff is always visible.
  * is_validated_close cannot be true without close_validation_method.

And, since revision 0026, a near-close row is a PROJECTION of the odds series:
it cannot exist without the snapshot it names, cannot disagree with it, and
carries the payload hash that ties it back to the provider's answer.
"""

from __future__ import annotations

import psycopg

from tests.integration.conftest import Seed
from tests.integration.helpers import (
    must_be_accepted,
    must_be_rejected,
    must_be_rejected_saying,
)

CAPTURED = "2026-09-15 18:48Z"


def series_row(db: psycopg.Connection, seed: Seed, *, market: str = "1X2", selection: str = "Home",
               line: str = "0", odds: str = "1.95", captured_at: str = CAPTURED,
               minutes: int = 12, source: str = "live") -> None:
    """The snapshot a near-close row projects. Written first, exactly as the
    capture service writes it first."""
    db.execute(
        "INSERT INTO market.odds_snapshots (fixture_id,bookmaker_id,market_key,selection,line,"
        "odds_decimal,captured_at,minutes_to_ko,source,payload_hash) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (seed.fixture_id, seed.bookmaker_id, market, selection, line, odds, captured_at,
         minutes, source, seed.payload_hash),
    )

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
    series_row(db, seed)
    with must_be_accepted(db) as cur:
        cur.execute(
            "INSERT INTO market.near_close_snapshots "
            "(fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,captured_at,"
            " minutes_to_ko,source,payload_hash) "
            "VALUES (%s,%s,'1X2','Home',0,1.95,%s,12,'live',%s) "
            "RETURNING is_validated_close, close_validation_method",
            (seed.fixture_id, seed.bookmaker_id, CAPTURED, seed.payload_hash),
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


# ── the projection cannot drift from the series ─────────────────────────────


def _near_close(db: psycopg.Connection, seed: Seed, *, odds: str = "1.95", minutes: int = 12,
                source: str = "live", payload: str | None = None, captured_at: str = CAPTURED) -> None:
    db.execute(
        "INSERT INTO market.near_close_snapshots (fixture_id,bookmaker_id,market_key,selection,line,"
        "odds_decimal,captured_at,minutes_to_ko,source,payload_hash) "
        "VALUES (%s,%s,'1X2','Home',0,%s,%s,%s,%s,%s)",
        (seed.fixture_id, seed.bookmaker_id, odds, captured_at, minutes, source,
         payload or seed.payload_hash),
    )


def test_a_near_close_row_without_a_snapshot_is_refused(db: psycopg.Connection, seed: Seed) -> None:
    """The claim "this was the price near kick-off" has to be backed by the
    price we actually stored at that instant."""
    with must_be_rejected_saying(db, "nothing to project"):
        _near_close(db, seed)


def test_a_near_close_row_that_disagrees_with_its_snapshot_is_refused(
    db: psycopg.Connection, seed: Seed
) -> None:
    series_row(db, seed, odds="1.95")
    with must_be_rejected_saying(db, "disagrees with the snapshot"):
        _near_close(db, seed, odds="2.50")


def test_the_distance_to_kickoff_cannot_be_rewritten(db: psycopg.Connection, seed: Seed) -> None:
    """minutes_to_ko is the honest measure of how close to a close this is.
    Copying a T-180 price in as if it were seen at T-5 is exactly the lie the
    table's name exists to prevent."""
    series_row(db, seed, minutes=180)
    with must_be_rejected_saying(db, "disagrees with the snapshot"):
        _near_close(db, seed, minutes=5)


def test_a_near_close_row_cannot_borrow_another_payloads_provenance(
    db: psycopg.Connection, seed: Seed
) -> None:
    series_row(db, seed)
    db.execute(
        "INSERT INTO raw.ingestion_payloads (hash,run_id,endpoint,fetched_at,http_status,file_path,bytes) "
        "VALUES ('another-payload',%s,'/odds',now(),200,'x',1)", (seed.run_id,)
    )
    with must_be_rejected_saying(db, "disagrees with the snapshot"):
        _near_close(db, seed, payload="another-payload")


def test_the_provenance_column_is_mandatory_and_a_real_payload(
    db: psycopg.Connection, seed: Seed
) -> None:
    """Two guards, and the stricter one wins in practice.

    A near-close row pointing at a payload that is not the one its snapshot came
    from is refused by the projection check before the foreign key gets a chance.
    The foreign key still earns its place: it is what makes the column mean
    "a payload we have on disk" for any writer that bypasses the trigger path,
    and what stops a payload row from being deleted out from under a price.
    """
    series_row(db, seed)
    with must_be_rejected_saying(db, "disagrees with the snapshot"):
        _near_close(db, seed, payload="never-fetched")
    with must_be_rejected(db, "payload_hash is NOT NULL"):
        db.execute(
            "INSERT INTO market.near_close_snapshots (fixture_id,bookmaker_id,market_key,selection,"
            "line,odds_decimal,captured_at,minutes_to_ko,source) "
            "VALUES (%s,%s,'1X2','Home',0,1.95,%s,12,'live')",
            (seed.fixture_id, seed.bookmaker_id, CAPTURED),
        )
    with db.cursor() as cur:
        cur.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conname = 'near_close_payload_exists' AND contype = 'f'"
        )
        assert cur.fetchone() == ("raw.ingestion_payloads",)


def test_a_payload_still_referenced_by_a_price_cannot_be_deleted(
    db: psycopg.Connection, seed: Seed
) -> None:
    series_row(db, seed)
    _near_close(db, seed)
    with must_be_rejected(db, "the payload is still referenced"):
        db.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (seed.payload_hash,))


def test_deleting_a_snapshot_that_is_still_projected_is_refused(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The other direction: the evidence cannot be removed while the conclusion
    stays. The guard is DEFERRABLE so that a cascade from core.fixtures still
    works, which is why the test forces the check with SET CONSTRAINTS rather
    than committing."""
    series_row(db, seed)
    _near_close(db, seed)
    with must_be_rejected_saying(db, "still projects the snapshot") as cur:
        cur.execute("DELETE FROM market.odds_snapshots WHERE fixture_id = %s", (seed.fixture_id,))
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_deleting_the_projection_first_is_allowed(db: psycopg.Connection, seed: Seed) -> None:
    series_row(db, seed)
    _near_close(db, seed)
    with must_be_accepted(db) as cur:
        cur.execute("DELETE FROM market.near_close_snapshots WHERE fixture_id = %s", (seed.fixture_id,))
        cur.execute("DELETE FROM market.odds_snapshots WHERE fixture_id = %s", (seed.fixture_id,))
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("SELECT count(*) FROM market.near_close_snapshots WHERE fixture_id = %s",
                    (seed.fixture_id,))
        assert cur.fetchone() == (0,)


def test_deleting_the_fixture_takes_both_tables_with_it(db: psycopg.Connection, seed: Seed) -> None:
    """A cascade deletes the series row and the projection in an order we do not
    control. An immediate guard would refuse a legitimate cascade; a deferred one
    lets it finish and then finds nothing orphaned."""
    with must_be_accepted(db) as cur:
        cur.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
            "away_team_id, kickoff_at, status_short, status_group) "
            "VALUES (9002,%s,%s,%s,'2026-09-15 19:00Z','NS','scheduled') RETURNING id",
            (seed.season_id, seed.home_team_id, seed.away_team_id),
        )
        row = cur.fetchone()
        assert row is not None
        doomed = int(row[0])
        for table in ("market.odds_snapshots", "market.near_close_snapshots"):
            cur.execute(
                f"INSERT INTO {table} (fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,"
                "captured_at,minutes_to_ko,source,payload_hash) "
                "VALUES (%s,%s,'1X2','Home',0,1.95,%s,12,'live',%s)",
                (doomed, seed.bookmaker_id, CAPTURED, seed.payload_hash),
            )
        cur.execute("DELETE FROM core.fixtures WHERE id = %s", (doomed,))
        cur.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cur.execute("SELECT count(*) FROM market.near_close_snapshots WHERE fixture_id = %s", (doomed,))
        assert cur.fetchone() == (0,)


# ── the chain, end to end ───────────────────────────────────────────────────


def test_the_lineage_view_reaches_the_request_from_the_price(
    db: psycopg.Connection, seed: Seed
) -> None:
    """One query from a near-close price to the run, endpoint and params that
    produced it: exactly the chain the platform is supposed to be able to show."""
    series_row(db, seed)
    _near_close(db, seed)
    with db.cursor() as cur:
        cur.execute(
            "SELECT provider_fixture_id, bookmaker_name, market_key, selection, line, odds_decimal, "
            "       captured_at, minutes_to_ko, source, is_validated_close, payload_hash, endpoint, "
            "       payload_file, run_id, job_name, market_is_model_enabled "
            "FROM market.near_close_lineage WHERE fixture_id = %s", (seed.fixture_id,)
        )
        row = cur.fetchone()
    assert row is not None
    (provider_fixture_id, bookmaker, market, selection, _line, _odds, _captured, minutes, source,
     validated, payload_hash, endpoint, payload_file, run_id, job_name, model_enabled) = row
    assert (market, selection, source, minutes) == ("1X2", "Home", "live", 12)
    assert validated is False, "still not a closing line"
    assert (payload_hash, endpoint, payload_file) == (seed.payload_hash, "/odds", "x")
    assert (run_id, job_name) == (seed.run_id, "test")
    assert model_enabled is True, "1X2 is one of the markets the models may use"
    assert isinstance(provider_fixture_id, int) and isinstance(bookmaker, str)


def test_the_lineage_view_never_exposes_a_request_header(db: psycopg.Connection, seed: Seed) -> None:
    """params is sanitised at the source - the key travels as a header and is
    stripped before the payload is indexed - so the view cannot leak it. Pinned
    here because the view is the thing an admin endpoint would read."""
    series_row(db, seed)
    _near_close(db, seed)
    with db.cursor() as cur:
        cur.execute("SELECT request_params::text FROM market.near_close_lineage WHERE fixture_id = %s",
                    (seed.fixture_id,))
        row = cur.fetchone()
    assert row is not None
    lowered = row[0].lower()
    for forbidden in ("apisports", "x-apisports-key", "authorization", "api_key", "apikey", "token"):
        assert forbidden not in lowered
