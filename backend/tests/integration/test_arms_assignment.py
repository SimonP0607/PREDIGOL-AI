"""``fbi.ai.arms.assign`` and ``stored`` against the real table (``ai.shadow_assignments``, migration 0119).

What the shadow's comparison stands on: a match is put in its arms ONCE, before its first pass, by the hash of its id and the share in force; the row
is the experiment's memory and never changes, whatever the share becomes and however many workers ask at the same moment; and the table accepts
every row the code writes (it refuses a row that contradicts the rule of the sample, so a bug there would be a failed assignment, not a silent one).
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any

import psycopg
import pytest

from fbi.ai import arms
from fbi.ai.arms import OUTSIDE, SALT, Assignment

pytestmark = pytest.mark.integration

D = Decimal
NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
IDS = list(range(5000, 5400))


def table(db: psycopg.Connection[Any], experiment: str = SALT) -> dict[int, tuple[Any, ...]]:
    """Every row of an experiment, by match: (bucket, sampled, council_solo, share, assigned_at)."""
    rows = db.execute("SELECT fixture_id, bucket, sampled, council_solo, share, assigned_at FROM ai.shadow_assignments WHERE experiment = %s "
                      "ORDER BY fixture_id", (experiment,)).fetchall()
    return {r[0]: tuple(r[1:]) for r in rows}


def drawn(ids: list[int], share: str, salt: str = SALT) -> dict[int, Assignment]:
    return {i: arms.arms_of(i, D(share), salt) for i in ids}


# ── the first assignment ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_first_call_puts_every_match_in_its_arms_and_writes_what_it_decided(db: psycopg.Connection[Any]) -> None:
    got = arms.assign(db, IDS, at=NOON, share=D("0.3"))
    assert got == drawn(IDS, "0.3")
    rows = table(db)
    assert sorted(rows) == IDS, "every match has a row, the ones outside the sample too: a match is never assigned twice"
    for i in IDS:
        bucket, sampled, solo, share, at = rows[i]
        assert bucket == arms.bucket(i) and sampled == got[i].sampled and solo == got[i].council_solo and share == D("0.3") and at == NOON
    sampled = sum(a.sampled for a in got.values())
    solo = sum(a.council_solo for a in got.values())
    assert 90 < sampled < 150 and 0 < solo < sampled, "about a third of the matches, and about half of those in COUNCIL SOLO"
    assert arms.stored(db, IDS) == got


def test_the_moment_is_stored_as_an_instant_whatever_the_zone_it_came_in(db: psycopg.Connection[Any]) -> None:
    bogota = timezone(timedelta(hours=-5))
    arms.assign(db, [7001], at=NOON.astimezone(bogota), share=D("0.3"))
    assert table(db)[7001][4] == NOON


def test_the_stored_arms_are_the_ones_the_hashes_give_for_any_share_the_owner_might_type(db: psycopg.Connection[Any]) -> None:
    """The table refuses a row that contradicts ``bucket < share * 10000``, to the last digit of the share: every share the code can be given - the
    configuration clamps and does not round - must be one it accepts, for every match."""
    ids = list(range(1, 1501))
    for n, share in enumerate(("0.0001", "0.01", "0.3333", "0.123456789", "0.5", "0.99999999", "1", "1.00", "0.30000000000000000000000000001",
                               "0.2999999999999999999999999999")):
        name = f"exp-{n}"
        got = arms.assign(db, ids, at=NOON, share=D(share), experiment=name)
        assert got == drawn(ids, share, name), share
        assert {i: a.sampled for i, a in got.items()} == {i: arms.bucket(i, name) < Fraction(D(share)) * 10_000 for i in ids}, share
    assert db.execute("SELECT count(*) FROM ai.shadow_assignments").fetchone() == (15_000,)


def test_the_experiments_are_independent_each_has_its_own_groups(db: psycopg.Connection[Any]) -> None:
    first = arms.assign(db, IDS, at=NOON, share=D("0.3"))
    other = arms.assign(db, IDS, at=NOON, share=D("0.3"), experiment="ma-shadow-v2")
    assert first == drawn(IDS, "0.3") and other == drawn(IDS, "0.3", "ma-shadow-v2")
    assert first != other, "another salt is another draw"
    assert len(table(db)) == len(table(db, "ma-shadow-v2")) == len(IDS)
    assert arms.stored(db, IDS) == first and arms.stored(db, IDS, experiment="ma-shadow-v2") == other
    assert arms.stored(db, IDS, experiment="ma-shadow-v3") == {}


# ── "ningun partido cambia de grupo" ─────────────────────────────────────────────────────────────────────────────────────────────

def test_a_second_call_changes_nothing_whatever_the_share_and_the_moment(db: psycopg.Connection[Any]) -> None:
    first = arms.assign(db, IDS, at=NOON, share=D("0.1"))
    written = table(db)
    would_now = drawn(IDS, "0.9")
    assert any(not first[i].sampled and would_now[i].sampled for i in IDS), "the test bites: some match is out at 10 % and would be in at 90 %"
    for share, at in (("0.9", NOON + timedelta(days=1)), ("1", NOON + timedelta(days=2)), ("0.0001", NOON + timedelta(days=3)), ("0", NOON + timedelta(days=4))):
        assert arms.assign(db, IDS, at=at, share=D(share)) == first, share
        assert table(db) == written, f"nothing was written, changed or moved at a share of {share}"
    assert all(row[3] == D("0.1") and row[4] == NOON for row in table(db).values()), "each row says the share and the moment of its own day"


def test_the_matches_seen_after_the_share_moved_are_assigned_at_the_new_share_and_the_old_ones_stay_where_they_were(db: psycopg.Connection[Any]) -> None:
    early, late = IDS[:200], IDS[200:]
    first = arms.assign(db, early, at=NOON, share=D("0.1"))
    written = table(db)
    both = arms.assign(db, IDS, at=NOON + timedelta(days=7), share=D("0.5"))
    assert {i: both[i] for i in early} == first, "the matches of the first day keep their groups"
    assert {i: both[i] for i in late} == {i: a for i, a in drawn(IDS, "0.5").items() if i in late}, "the new ones are drawn at the new share"
    rows = table(db)
    assert {i: rows[i] for i in early} == written, "and their rows are as they were written"
    assert all(rows[i][3] == D("0.5") and rows[i][4] == NOON + timedelta(days=7) for i in late)
    stayed_out = [i for i in early if not first[i].sampled and arms.bucket(i) < 5000]
    assert stayed_out, "the test bites: a match that the 50 % sample would hold stays out because it was assigned at 10 %"
    assert all(first[i].sampled for i in early if arms.bucket(i) < 1000), "and the sample of 10 % is inside the one of 50 %"


def test_a_share_of_zero_writes_nothing_and_leaves_the_stored_groups_as_they_are(db: psycopg.Connection[Any]) -> None:
    assert arms.assign(db, IDS, at=NOON, share=D(0)) == dict.fromkeys(IDS, OUTSIDE)
    assert table(db) == {}, "while the shadow is off no match is assigned"
    assert arms.stored(db, IDS) == {}
    stored = arms.assign(db, IDS[:50], at=NOON, share=D("0.3"))
    with_zero = arms.assign(db, IDS, at=NOON + timedelta(days=1), share=D(0))
    assert {i: with_zero[i] for i in IDS[:50]} == stored, "the ones assigned keep their arms"
    assert {i: with_zero[i] for i in IDS[50:]} == dict.fromkeys(IDS[50:], OUTSIDE)
    assert sorted(table(db)) == IDS[:50]


def test_each_match_asked_is_answered_once_in_the_order_asked(db: psycopg.Connection[Any]) -> None:
    got = arms.assign(db, [30, 10, 30, 20, 10], at=NOON, share=D("0.3"))
    assert list(got) == [30, 10, 20] and sorted(table(db)) == [10, 20, 30]
    assert arms.assign(db, iter([20, 10]), at=NOON, share=D("0.3")) == {20: got[20], 10: got[10]}
    assert arms.assign(db, [], at=NOON, share=D("0.3")) == {} and arms.stored(db, []) == {}


def test_a_match_that_was_never_assigned_is_not_in_what_is_stored(db: psycopg.Connection[Any]) -> None:
    assert arms.stored(db, [1, 2, 3]) == {}
    arms.assign(db, [1, 2], at=NOON, share=D("1"))
    assert sorted(arms.stored(db, [1, 2, 3])) == [1, 2]


def test_a_caller_that_rolls_back_leaves_no_assignment_behind(db: psycopg.Connection[Any]) -> None:
    """The assignment belongs to the caller's transaction: the caller commits it before the first pass, and a pass that is undone is undone with it."""
    arms.assign(db, IDS, at=NOON, share=D("0.3"))
    db.rollback()
    assert table(db) == {}
    assert arms.assign(db, IDS, at=NOON + timedelta(days=1), share=D("0.6")) == drawn(IDS, "0.6"), "and the next call is the first call"


@pytest.mark.parametrize(("call", "message"), [
    ({"fixture_ids": [0]}, "fixture id"), ({"fixture_ids": [-1]}, "fixture id"), ({"fixture_ids": [1.5]}, "fixture id"),
    ({"share": D("1.2")}, "share"), ({"share": D(-1)}, "share"), ({"share": D("NaN")}, "share"),
    ({"at": NOON.replace(tzinfo=None)}, "timezone"), ({"experiment": "no good"}, "experiment"),
])
def test_a_bad_call_is_refused_without_aborting_the_transaction_of_the_caller(db: psycopg.Connection[Any], call: dict[str, Any], message: str) -> None:
    arms.assign(db, [11], at=NOON, share=D("0.3"))
    args: dict[str, Any] = {"fixture_ids": [12], "at": NOON, "share": D("0.3"), "experiment": SALT} | call
    with pytest.raises(ValueError, match=message):
        arms.assign(db, args["fixture_ids"], at=args["at"], share=args["share"], experiment=args["experiment"])
    assert db.execute("SELECT 1").fetchone() == (1,), "the connection can still be used: nothing was sent to the database"
    assert sorted(table(db)) == [11], "and what was written before is still there"


# ── at the same moment ───────────────────────────────────────────────────────────────────────────────────────────────────────────

class Workers:
    """Connections of their own to the test database, committed for real - and the rows they leave removed afterwards, the one way an append-only
    table allows (the maintenance lift of the owner, inside one transaction)."""

    def __init__(self, dsn: str, experiment: str) -> None:
        self.dsn, self.experiment = dsn, experiment

    def connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self.dsn)

    def rows(self) -> dict[int, tuple[Any, ...]]:
        with self.connect() as c:
            return table(c, self.experiment)

    def clean(self) -> None:
        with self.connect() as c:
            c.execute("SET LOCAL fbi.ai_maintenance = 'on'")
            c.execute("DELETE FROM ai.shadow_assignments WHERE experiment = %s", (self.experiment,))
            c.commit()


@pytest.fixture()
def workers(migrated_database: str) -> Iterator[Workers]:
    made = Workers(migrated_database, f"conc-{uuid.uuid4().hex[:12]}")
    yield made
    made.clean()


def test_the_second_worker_waits_for_the_first_and_both_agree_on_the_first_ones_row(workers: Workers) -> None:
    """Two workers assign the same matches at once with different shares: the first to insert decides, the other waits for its commit - it
    cannot insert a row of its own - and answers with the row of the first."""
    ids = list(range(9000, 9200))
    inserted, answers = threading.Event(), {}
    waited: list[float] = []

    def first() -> None:
        with workers.connect() as c:
            answers["first"] = arms.assign(c, ids, at=NOON, share=D("0.9"), experiment=workers.experiment)
            inserted.set()
            time.sleep(0.6)  # the pass has not started: the assignment is not yet committed
            c.commit()

    def second() -> None:
        inserted.wait(10)
        started = time.monotonic()
        with workers.connect() as c:
            answers["second"] = arms.assign(c, ids, at=NOON + timedelta(minutes=1), share=D("0.1"), experiment=workers.experiment)
            waited.append(time.monotonic() - started)
            c.commit()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads), "neither worker hangs"
    assert answers["first"] == answers["second"] == drawn(ids, "0.9", workers.experiment), "both answer with the row of the first"
    assert waited and waited[0] >= 0.4, f"the second one waited for the commit of the first ({waited})"
    rows = workers.rows()
    assert sorted(rows) == ids, "one row per match"
    assert all(row[3] == D("0.9") and row[4] == NOON for row in rows.values()), "and every one is the row of the first worker"


@pytest.mark.parametrize("attempt", range(4))
def test_two_workers_taking_the_same_matches_in_opposite_orders_do_not_deadlock(workers: Workers, attempt: int) -> None:
    """The rows go in by fixture id whatever the order asked, so two transactions that want the same keys take them in the same order and wait for
    each other instead of each holding what the other needs."""
    ids = list(range(100, 500))
    gate = threading.Barrier(2)
    answers: dict[str, dict[int, Assignment]] = {}
    failures: list[BaseException] = []

    def work(name: str, order: list[int], share: str) -> None:
        try:
            with workers.connect() as c:
                gate.wait(10)
                answers[name] = arms.assign(c, order, at=NOON, share=D(share), experiment=workers.experiment)
                c.commit()
        except BaseException as exc:  # the thread reports, the test judges
            failures.append(exc)

    threads = [threading.Thread(target=work, args=("up", ids, "0.3")), threading.Thread(target=work, args=("down", ids[::-1], "0.7"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not failures, failures
    assert not any(t.is_alive() for t in threads)
    assert answers["up"] == answers["down"], f"attempt {attempt}: both workers read the same groups"
    rows = workers.rows()
    assert sorted(rows) == ids
    shares = {row[3] for row in rows.values()}
    assert shares in ({D("0.3")}, {D("0.7")}), "all of it from one of the two: the one that took the keys first"
    assert list(answers["up"]) == ids and list(answers["down"]) == ids[::-1], "each in the order it asked"
