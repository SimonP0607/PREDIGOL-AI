"""The notifier records every kind it drafts (revision 0067).

From 5 Oct 2026 05:45 UTC the run watchdog's messages (run_recovered, job_failing) were drafted but refused by the
database CHECK, and each refusal rolled back every other message of the run: nothing was recorded for 21 hours."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from fbi.ingestion.ledger import RunCounters, RunLedger
from fbi.notify import service
from fbi.notify.service import KINDS, Draft, run_notifier
from fbi.ops.run_watchdog import recover_runs

from .conftest import Seed


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database) as c:
        top = c.execute("SELECT coalesce(max(id), 0) FROM audit.notifications").fetchone()
        c.commit()
        yield c
        c.rollback()
        c.execute("DELETE FROM audit.notifications WHERE id > %s", (top[0] if top else 0,))
        c.execute("DELETE FROM raw.ingestion_runs WHERE job_name LIKE 'nt-%' OR job_type LIKE 'nt_%'")
        c.commit()


def test_every_kind_the_notifier_drafts_is_a_kind_the_database_accepts(conn: psycopg.Connection) -> None:
    row = conn.execute("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                       "WHERE conname = 'notifications_kind_check'").fetchone()
    assert row is not None
    accepted = set(re.findall(r"'([a-z_]+)'", row[0]))
    assert set(KINDS) <= accepted, f"kinds drafted but refused by the database: {set(KINDS) - accepted}"
    source = (service.__file__ or "")
    with open(source, encoding="utf-8") as fh:
        drafted = set(re.findall(r'Draft\(\s*"([a-z_]+)"', fh.read()))
    assert drafted and drafted <= set(KINDS), f"drafted without being listed in KINDS: {drafted - set(KINDS)}"
    with pytest.raises(ValueError, match="not in KINDS"):
        Draft("a_new_kind", "k", "t", "b")


def test_the_watchdog_messages_are_recorded_with_the_others(conn: psycopg.Connection) -> None:
    ledger = RunLedger(conn)
    for _ in range(3):
        ledger.close(ledger.open("nt_broken"), RunCounters(errors=["boom"]))
    hung = ledger.open("live_match_capture")
    conn.execute("UPDATE raw.ingestion_runs SET job_name = 'nt-hung' WHERE id = %s", (hung,))
    conn.commit()
    recover_runs(conn, at=datetime.now(UTC) + timedelta(minutes=11))
    report = run_notifier(conn, None, at=datetime.now(UTC) + timedelta(minutes=12))
    assert report.refused == 0
    kinds = {k for (k,) in conn.execute("SELECT kind FROM audit.notifications WHERE dedup_key = %s "
                                        "OR dedup_key LIKE 'job_failing:nt_broken:%%'",
                                        (f"run:{hung}:stale",)).fetchall()}
    assert kinds == {"run_recovered", "job_failing"}


def test_a_message_the_database_refuses_does_not_take_the_others_with_it(conn: psycopg.Connection,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    refused = Draft("worker_down", "nt:refused", None, "no title")  # type: ignore[arg-type]
    kept = Draft("worker_down", "nt:kept", "Worker silent", "kept")
    monkeypatch.setattr(service, "collect", lambda conn, at: [refused, kept])
    report = run_notifier(conn, None)
    assert (report.drafted, report.refused, report.new) == (2, 1, 1)
    rows = conn.execute("SELECT dedup_key FROM audit.notifications WHERE dedup_key LIKE 'nt:%'").fetchall()
    assert rows == [("nt:kept",)]


def test_only_the_picks_not_announced_yet_are_drafted(db: psycopg.Connection, seed: Seed) -> None:
    """Regression (13 Oct 2026): every run re-drafted every shadow pick of the week - 137,974 drafts every ten
    minutes, one savepoint each - which held the notifier's transaction open 7-9 minutes of every 10."""
    from tests.integration.test_intel import IntelWorld

    w = IntelWorld(db, seed)
    at = datetime.now(UTC)
    fid = w.fixture(at + timedelta(hours=5))
    told = w.pick(fid, "OU", "Over", "2.5", p_model=0.6, p_market=0.55, odds=1.9, created=at - timedelta(hours=1))
    new = w.pick(fid, "BTTS", "Yes", "0", p_model=0.6, p_market=0.55, odds=1.9, created=at - timedelta(minutes=30))
    db.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) "
               "VALUES ('shadow_pick', %s, 't', 'b', '{}')", (f"pick:{told}:created",))
    keys = {d.dedup_key for d in service.collect(db, at=at)}
    assert f"pick:{new}:created" in keys and f"pick:{told}:created" not in keys
    # once it settles, the announced pick comes back for its result - and only until that is recorded too
    w.settle(told, True, at)
    db.execute("UPDATE picks.picks SET status = 'settled', status_changed_at = clock_timestamp() WHERE id = %s",
               (told,))
    keys = {d.dedup_key for d in service.collect(db, at=at)}
    assert f"pick:{told}:settled" in keys
    db.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) "
               "VALUES ('pick_settled', %s, 't', 'b', '{}')", (f"pick:{told}:settled",))
    keys = {d.dedup_key for d in service.collect(db, at=at)}
    assert not {f"pick:{told}:created", f"pick:{told}:settled"} & keys


def _queued(db: psycopg.Connection, kind: str, key: str, title: str) -> int:
    row = db.execute("INSERT INTO audit.notifications (kind, dedup_key, title, body, payload) "
                     "VALUES (%s, %s, %s, 'b', '{}') RETURNING id", (kind, key, title)).fetchone()
    assert row is not None
    return int(row[0])


def test_the_operational_messages_go_out_before_the_shadow_picks(db: psycopg.Connection) -> None:
    """Regression (13 Oct 2026): 132,082 shadow-pick messages were queued; a budget alert behind them would have
    waited weeks for its turn (20 a run, every 10 minutes)."""
    picks = [_queued(db, "shadow_pick", f"nt:queue:{i}", "t") for i in range(25)]
    budget = _queued(db, "ai_budget", "nt:queue:budget", "Presupuesto de IA: 50 % del mes")
    order = [int(r[0]) for r in db.execute(service.QUEUE_SQL, (1_000_000,)).fetchall()]
    assert order.index(budget) < min(order.index(p) for p in picks), "the alert first, though it was queued last"


def test_with_the_picks_notices_off_no_pick_is_drafted_and_the_rest_still_is(
        db: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing plan 4.4 (P14): the owner's chat can be left without the notices of shadow picks and their settlement
    while the operational messages stay. The switch changes whom the notifier tells and nothing else: the picks are
    not read for it and nothing recorded changes."""
    from tests.integration.test_intel import IntelWorld

    w = IntelWorld(db, seed)
    at = datetime.now(UTC)
    fid = w.fixture(at + timedelta(hours=5))
    pick = w.pick(fid, "OU", "Over", "2.5", p_model=0.6, p_market=0.55, odds=1.9, created=at - timedelta(minutes=30))
    before = db.execute("SELECT status, p_calibrated FROM picks.picks WHERE id = %s", (pick,)).fetchone()
    monkeypatch.delenv(service.PICKS_ENV, raising=False)
    assert f"pick:{pick}:created" in {d.dedup_key for d in service.collect(db, at=at)}
    monkeypatch.setenv(service.PICKS_ENV, "off")
    kinds = {d.kind for d in service.collect(db, at=at)}
    assert not kinds & {"shadow_pick", "pick_settled"}
    assert db.execute("SELECT status, p_calibrated FROM picks.picks WHERE id = %s", (pick,)).fetchone() == before


def test_with_the_picks_notices_off_what_is_queued_about_picks_waits_untouched(
        conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uses ``conn`` (it commits, and removes what it left): a queued pick message left behind would be sent by the
    notifier of the pick pipeline's test."""
    db = conn
    monkeypatch.setenv(service.PICKS_ENV, "off")
    old = _queued(db, "shadow_pick", "nt:off:pick", "t")
    budget = _queued(db, "ai_budget", "nt:off:budget", "Presupuesto de IA: 50 % del mes")
    sent: list[str] = []

    class Spy:
        name = "spy"

        def send(self, title: str, body: str) -> None:
            sent.append(title)

    monkeypatch.setattr(service, "collect", lambda conn, at: [])
    run_notifier(db, Spy())
    assert "Presupuesto de IA: 50 % del mes" in sent and "t" not in sent
    rows: dict[int, str] = dict(
        db.execute("SELECT id, status FROM audit.notifications WHERE id IN (%s, %s)", (old, budget)).fetchall())
    assert rows == {old: "queued", budget: "sent"}


def test_the_picks_switch_reads_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(service.PICKS_ENV, raising=False)
    assert service.picks_notices_on()
    for off in ("off", "OFF", "0", "false", "no"):
        monkeypatch.setenv(service.PICKS_ENV, off)
        assert not service.picks_notices_on()
    monkeypatch.setenv(service.PICKS_ENV, "on")
    assert service.picks_notices_on()
