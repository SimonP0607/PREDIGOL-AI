"""Migration 0094 (what a family learns from its own decisions): additive, empty and reversible - and a row of it cannot contradict the rule.

Deploying must change nothing the system does: it adds two tables and a view, alters nothing that existed, writes no row, and leaves as it came.
Run on a scratch database at revision 0093, the way production does. The only foreign key it adds is to ``intel.decisions``: none to
``core.fixtures`` (revision 0090: ``fixtures_sync`` holds a lock on that table for ~27 minutes every six hours, and a migration that waits for it
fails whole).

Then the rows. The post-mortem of a family ties its verdict to the result and to the price against the close, the quality of the price to the
CLV, the profit to the result and the price taken, and itself to the time after the match, in constraints of the table (version ``pm-fam-v1``): a
writer that gets the rule wrong is refused, whatever it is. The constants of the constraints are the code's
(``fbi.market.closing_value.GOOD``, ``fbi.intel.postmortem.verdict_of``, ``fbi.intel.outcomes.profit_per_unit``): here they are held equal on
every combination, and on the edges of the thresholds. Both tables are append-only."""

from __future__ import annotations

import itertools
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from fbi.familydecisions import outcomes as fo
from fbi.intel.outcomes import profit_per_unit
from fbi.intel.postmortem import verdict_of
from fbi.market import closing_value
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, Seed, _dsn

from .knowledge_world import World
from .test_families_score import play
from .test_familydecisions_decide import KICKOFF
from .test_familydecisions_outcomes import LATER, decided

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0094"
POSTMORTEMS, MEMORY, LATEST = "intel.family_postmortems", "intel.family_memory", "intel.family_memory_latest"
OWN = {name.split(".")[1] for name in (POSTMORTEMS, MEMORY, LATEST)}


# ── the migration ────────────────────────────────────────────────────────────────────────────────────────────────

def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table and view the migration must leave alone (all but its own three)."""
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'raw') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "intel" and r[1] in OWN)]


def test_0094_adds_two_tables_and_a_view_and_nothing_else_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in (POSTMORTEMS, MEMORY, LATEST))
            before = _shape(c)

        command.upgrade(_cfg(), "0094")
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in (POSTMORTEMS, MEMORY, LATEST))
            assert _shape(c) == before, "nothing that existed was changed"
            for name in (POSTMORTEMS, MEMORY, LATEST):
                assert c.execute(f"SELECT count(*) FROM {name}").fetchone() == (0,), "the migration writes no row"
                comment = c.execute("SELECT obj_description(%s::regclass)", (name,)).fetchone()
                assert comment is not None and comment[0], f"{name} says what it is"

            indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'intel' "
                                               "AND tablename IN ('family_postmortems', 'family_memory')").fetchall()}
            assert {"family_postmortems_pkey", "family_postmortems_once", "family_postmortems_fixture", "family_postmortems_kickoff",
                    "family_memory_pkey", "family_memory_once", "family_memory_entity"} == indexes
            triggers = {(r[0], r[1]) for r in c.execute(
                "SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE tgrelid IN (%s::regclass, %s::regclass) AND NOT tgisinternal",
                (POSTMORTEMS, MEMORY)).fetchall()}
            assert triggers == {(POSTMORTEMS, "family_postmortems_append_only"), (MEMORY, "family_memory_append_only")}, \
                "what a family learned is never edited or deleted afterwards"
            foreign = c.execute("SELECT conrelid::regclass::text, confrelid::regclass::text FROM pg_constraint WHERE contype = 'f' "
                                "AND conrelid IN (%s::regclass, %s::regclass)", (POSTMORTEMS, MEMORY)).fetchall()
            assert foreign == [(POSTMORTEMS, "intel.decisions")], "the only reference is to the small table of the decisions, never to core.fixtures"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0094",)

        command.downgrade(_cfg(), "0093")
        with psycopg.connect(dsn) as c:
            assert not any(_exists(c, name) for name in (POSTMORTEMS, MEMORY, LATEST))
            assert _shape(c) == before, "and it leaves as it came"

        command.upgrade(_cfg(), "0094")  # and applies again
        with psycopg.connect(dsn) as c:
            assert all(_exists(c, name) for name in (POSTMORTEMS, MEMORY, LATEST))
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.families import forecast

    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


RESULTS = ("win", "loss", "push", "void", "half_win", "half_loss")
QUALITIES = ("GOOD", "NEUTRAL", "BAD", "UNKNOWN")
VERDICTS = ("MERECIDO", "VARIANZA", "SUERTE", "ERROR", "NULO", "SIN_DATOS")
CLV_OF = {"GOOD": Decimal("0.050000"), "NEUTRAL": Decimal("0.000000"), "BAD": Decimal("-0.050000"), "UNKNOWN": None}
"""A closing-line value that is of each quality, and none."""
P_CLOSE = Decimal("0.500000")


def profit_of(result: str, odds: Decimal) -> Decimal:
    """What a unit made, to the four decimals the table keeps: the one function of the system that says it."""
    return profit_per_unit(result, odds).quantize(Decimal("0.0001"))


def post_mortem(decision: int, fixture: int, **changes: Any) -> dict[str, Any]:
    """An honest row of ``pm-fam-v1`` for a decision (a win at a price better than the close), with whatever the test changes."""
    quality = changes.get("quality", "GOOD")
    clv = changes["clv"] if "clv" in changes else CLV_OF.get(quality)
    row: dict[str, Any] = {
        "decision_id": decision, "version": "pm-fam-v1", "created_at": LATER, "fixture_id": fixture, "kickoff_at": KICKOFF, "family": "CORNERS",
        "model_name": "family-corners_ft", "market_key": "CORNERS_OU", "selection": "Over", "line": Decimal("10.50"), "competition_id": None,
        "referee_id": None, "result": "win", "quality": "GOOD", "verdict": "MERECIDO", "odds": Decimal("2.100"), "p_model": Decimal("0.520000"),
        "p_decision": Decimal("0.476190"), "p_close": None if clv is None else P_CLOSE, "clv": clv, "profit_flat": Decimal("1.1000"),
        "actual": Decimal("11.00"), "margin": Decimal("0.50"), "causes": [], "answers": {}, "evidence": {}}
    row.update(changes)
    if "profit_flat" not in changes:  # a result the system does not know has no profit to follow (the constraint reads it as none)
        row["profit_flat"] = profit_of(row["result"], row["odds"]) if row["result"] in RESULTS else Decimal("0.0000")
    row["clv"] = clv
    if clv is None:
        row["p_close"] = changes.get("p_close")
    return row


def insert(db: psycopg.Connection[Any], table: str, row: dict[str, Any]) -> int:
    values = {k: Jsonb(v) if k in ("causes", "answers", "evidence", "stats", "delta", "evidence_ref") else v for k, v in row.items()}
    found = db.execute(f"INSERT INTO {table} ({', '.join(values)}) VALUES ({', '.join(f'%({k})s' for k in values)}) RETURNING id", values).fetchone()
    assert found is not None
    return int(found[0])


def refused(db: psycopg.Connection[Any], table: str, row: dict[str, Any], error: type[psycopg.Error] = psycopg.errors.CheckViolation,
            match: str | None = None) -> None:
    with pytest.raises(error, match=match), db.transaction():
        insert(db, table, row)


@pytest.fixture()
def settled(db: psycopg.Connection[Any], w: World) -> tuple[int, int]:
    """A decision of a family whose match was played and whose outcome is written: (the decision, the match)."""
    fid, _, _ = decided(db, w)
    play(w, fid)
    assert fo.settle(db, at=LATER).settled == 1
    [(decision,)] = db.execute("SELECT decision_id FROM intel.decision_outcomes").fetchall()
    return int(decision), fid


def test_an_honest_post_mortem_is_kept_once_per_decision_and_version(db: psycopg.Connection[Any], settled: tuple[int, int]) -> None:
    decision, fid = settled
    insert(db, POSTMORTEMS, post_mortem(decision, fid))
    refused(db, POSTMORTEMS, post_mortem(decision, fid), psycopg.errors.UniqueViolation)
    # a later version of the post-mortem is another row for the same decision, and it may judge differently: the rule of the constraints is the
    # rule of pm-fam-v1, not of every version there will be
    insert(db, POSTMORTEMS, post_mortem(decision, fid, version="pm-fam-v2", verdict="ERROR"))
    assert db.execute(f"SELECT count(*) FROM {POSTMORTEMS}").fetchone() == (2,)


def test_a_post_mortem_of_a_decision_that_does_not_exist_is_refused(db: psycopg.Connection[Any], settled: tuple[int, int]) -> None:
    _, fid = settled
    refused(db, POSTMORTEMS, post_mortem(987654321, fid), psycopg.errors.ForeignKeyViolation)


def accepted(db: psycopg.Connection[Any], table: str, row: dict[str, Any]) -> None:
    """The row is written - and taken back, so that the next one can be tried on the same decision."""
    with db.transaction(force_rollback=True):
        insert(db, table, row)


def test_the_verdict_is_the_rule_of_the_pipeline_on_every_result_and_every_quality_of_the_price(db: psycopg.Connection[Any],
                                                                                              settled: tuple[int, int]) -> None:
    """Of every row the table could be given, one is accepted and the rest refused: the verdict ``verdict_of`` gives - 6 results x 4 qualities
    x 6 verdicts, 144 rows."""
    decision, fid = settled
    right = 0
    for result, quality, verdict in itertools.product(RESULTS, QUALITIES, VERDICTS):
        row = post_mortem(decision, fid, result=result, quality=quality, verdict=verdict)
        if verdict == verdict_of(result, quality):
            accepted(db, POSTMORTEMS, row)
            right += 1
        else:
            refused(db, POSTMORTEMS, row, match="family_postmortems_verdict_follows_the_rule")
    assert right == len(RESULTS) * len(QUALITIES), "and every combination has its verdict"


def test_the_quality_of_the_price_is_the_closing_line_value_by_the_thresholds_of_the_pipeline(db: psycopg.Connection[Any],
                                                                                              settled: tuple[int, int]) -> None:
    """GOOD above +1 %, BAD below -1 %, NEUTRAL between and on the edges, UNKNOWN without a close: the constants of the constraint are the code's,
    value by value, edges included (the numbers of the table have six decimals)."""
    assert closing_value.GOOD == 0.01, "the constraint of pm-fam-v1 says 0.01: a change of the threshold is a new version, and a new constraint"
    decision, fid = settled
    values = ["0.010000", "0.010001", "0.009999", "-0.010000", "-0.010001", "-0.009999", "0.000000", "0.500000", "-0.500000", "1.234567", None]
    for text in values:
        clv = None if text is None else Decimal(text)
        right = closing_value.quality(None if clv is None else float(clv))
        for quality in QUALITIES:
            row = post_mortem(decision, fid, clv=clv, quality=quality, verdict=verdict_of("win", quality))
            if quality == right:
                accepted(db, POSTMORTEMS, row)
            else:
                refused(db, POSTMORTEMS, row, match="family_postmortems_quality_follows_clv")


def test_a_close_is_both_its_probability_and_its_value_or_neither(db: psycopg.Connection[Any], settled: tuple[int, int]) -> None:
    decision, fid = settled
    refused(db, POSTMORTEMS, post_mortem(decision, fid, p_close=None, clv=Decimal("0.05")) | {"p_close": None}, match="a_close_has_both")
    refused(db, POSTMORTEMS, post_mortem(decision, fid, quality="UNKNOWN", verdict="SIN_DATOS") | {"p_close": Decimal("0.5")},
            match="a_close_has_both")
    accepted(db, POSTMORTEMS, post_mortem(decision, fid, quality="UNKNOWN", verdict="SIN_DATOS"))


def test_the_profit_is_what_the_system_says_a_unit_makes_on_the_result_at_the_price(db: psycopg.Connection[Any], settled: tuple[int, int]) -> None:
    """Win: odds - 1; half win: half of it; push and void: 0; half loss: -1/2; loss: -1 - the function the outcomes are written with, on odds that
    end in every digit, and one unit of a cent more or less is refused."""
    decision, fid = settled
    for result in RESULTS:
        for odds in (Decimal("1.001"), Decimal("1.500"), Decimal("2.105"), Decimal("3.347"), Decimal("11.000")):
            verdict = verdict_of(result, "GOOD")
            right = profit_of(result, odds)
            accepted(db, POSTMORTEMS, post_mortem(decision, fid, result=result, verdict=verdict, odds=odds, profit_flat=right))
            for wrong in (right + Decimal("0.0001"), right - Decimal("0.0001"), -right if right else Decimal("1")):
                refused(db, POSTMORTEMS, post_mortem(decision, fid, result=result, verdict=verdict, odds=odds, profit_flat=wrong),
                        match="family_postmortems_profit_follows_result")


@pytest.mark.parametrize(("changes", "constraint"), [
    ({"margin": Decimal("1.50"), "actual": None}, "margin_needs_actual"),
    ({"created_at": KICKOFF}, "after_the_match"),  # a lesson cannot be written before the match it is about is over
    ({"created_at": KICKOFF - timedelta(hours=2)}, "after_the_match"),
    ({"odds": Decimal("1.000")}, "odds_check"),
    ({"odds": Decimal("0.500")}, "odds_check"),
    ({"p_model": Decimal("0.000000")}, "p_model_check"),
    ({"p_model": Decimal("1.000000")}, "p_model_check"),
    ({"p_decision": Decimal("1.000000")}, "p_decision_check"),
    ({"result": "won"}, "result_check"),  # the word of the pipeline's post-mortem; this table says what the outcome of the decision says
    ({"quality": "FINE"}, "quality_check"),
    ({"verdict": "BIEN"}, "verdict_check"),
    ({"family": "corners"}, "family_check"),
    ({"family": ""}, "family_check"),
    ({"market_key": " "}, "market_key_check"),
    ({"version": ""}, "version_check"),
    ({"causes": {"code": "red_card"}}, "causes_check"),
    ({"answers": []}, "answers_check"),
    ({"evidence": []}, "evidence_check"),
])
def test_a_row_that_is_not_a_post_mortem_is_refused(db: psycopg.Connection[Any], settled: tuple[int, int], changes: dict[str, Any],
                                                    constraint: str) -> None:
    decision, fid = settled
    row = post_mortem(decision, fid, **changes)
    refused(db, POSTMORTEMS, row, match=constraint)


def test_a_post_mortem_is_never_edited_or_deleted(db: psycopg.Connection[Any], settled: tuple[int, int]) -> None:
    decision, fid = settled
    found = insert(db, POSTMORTEMS, post_mortem(decision, fid))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
        db.execute(f"UPDATE {POSTMORTEMS} SET verdict = 'ERROR' WHERE id = %s", (found,))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
        db.execute(f"DELETE FROM {POSTMORTEMS} WHERE id = %s", (found,))
    assert db.execute(f"SELECT verdict FROM {POSTMORTEMS} WHERE id = %s", (found,)).fetchone() == ("MERECIDO",)


# ── the memory ───────────────────────────────────────────────────────────────────────────────────────────────────

DAY = date(2026, 10, 25)


def memory(**changes: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"version": "memory-fam-v1", "as_of_day": DAY, "built_at": datetime(2026, 10, 25, 13, tzinfo=LATER.tzinfo),
                           "entity_type": "family", "entity_key": "CORNERS", "entity_name": "Corners", "stats": {"all": {"n": 12}},
                           "delta": {}, "confidence": Decimal("0.2857"), "evidence_ref": {"n": 12}}
    row.update(changes)
    return row


def test_the_memory_keeps_one_snapshot_of_an_entity_per_day_and_version(db: psycopg.Connection[Any]) -> None:
    insert(db, MEMORY, memory())
    refused(db, MEMORY, memory(), psycopg.errors.UniqueViolation)
    for other in (memory(entity_key="CARDS"), memory(entity_type="market"), memory(as_of_day=DAY + timedelta(days=1)), memory(version="memory-fam-v2")):
        accepted(db, MEMORY, other)


@pytest.mark.parametrize(("changes", "constraint"), [
    ({"entity_type": "team"}, "entity_type_check"),
    ({"entity_key": " "}, "entity_key_check"),
    ({"version": ""}, "version_check"),
    ({"confidence": Decimal("-0.0001")}, "confidence_check"),
    ({"confidence": Decimal("1.0001")}, "confidence_check"),
    ({"stats": []}, "stats_check"),
    ({"delta": []}, "delta_check"),
    ({"evidence_ref": []}, "evidence_ref_check"),
])
def test_a_row_that_is_not_a_memory_is_refused(db: psycopg.Connection[Any], changes: dict[str, Any], constraint: str) -> None:
    refused(db, MEMORY, memory(**changes), match=constraint)


@pytest.mark.parametrize("confidence", [Decimal("0"), Decimal("1")])
def test_a_confidence_is_from_zero_to_one_both_included(db: psycopg.Connection[Any], confidence: Decimal) -> None:
    accepted(db, MEMORY, memory(confidence=confidence))


def test_a_memory_is_never_edited_or_deleted(db: psycopg.Connection[Any]) -> None:
    found = insert(db, MEMORY, memory())
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
        db.execute(f"UPDATE {MEMORY} SET confidence = 1 WHERE id = %s", (found,))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
        db.execute(f"DELETE FROM {MEMORY} WHERE id = %s", (found,))


def test_the_view_gives_the_newest_snapshot_of_each_entity_the_newest_day_first_then_the_newest_version(db: psycopg.Connection[Any]) -> None:
    insert(db, MEMORY, memory(as_of_day=DAY - timedelta(days=1), version="memory-fam-v9"))  # an older day, however high its version
    older = insert(db, MEMORY, memory(version="memory-fam-v1"))
    newer = insert(db, MEMORY, memory(version="memory-fam-v2"))
    insert(db, MEMORY, memory(version="memory-fam-v10", as_of_day=DAY - timedelta(days=2)))
    other = insert(db, MEMORY, memory(entity_key="CARDS", version="memory-fam-v1"))
    same_key_other_type = insert(db, MEMORY, memory(entity_type="market", entity_key="CORNERS", version="memory-fam-v1"))
    found = {(r[0], r[1]): r[2] for r in db.execute(f"SELECT entity_type, entity_key, id FROM {LATEST}").fetchall()}
    assert found == {("family", "CORNERS"): newer, ("family", "CARDS"): other, ("market", "CORNERS"): same_key_other_type}
    assert older not in found.values()
