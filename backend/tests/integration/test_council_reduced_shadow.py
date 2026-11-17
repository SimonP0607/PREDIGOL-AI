"""The reduced Council in the shadow (IA-124, AD-D10) against the real schema (revision 0161): the pass deliberates every pass of the shadow as
of its own moment, writes one row per selection to ``ai.council_reduced`` - the rules for all of them, the judge wanted only where a material
contradiction with value and time is recorded - asks no model, writes nothing else, and the table itself refuses a Council that raises, a
judge's word without a reading and any change. The world is ``test_council_protocol``'s own; the transaction is rolled back afterwards."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.councilpass import store

from .test_council_protocol import AT, KNOWN, KO, World

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    conn = psycopg.connect(migrated_database, options="-c TimeZone=UTC")
    monkeypatch.setattr(conn, "commit", lambda: None)  # the pass commits its own work: here it stays inside the test's transaction
    try:
        yield World(conn)
    finally:
        psycopg.Connection.rollback(conn)
        conn.close()


def rows(w: World) -> list[dict[str, Any]]:
    cur = w.conn.cursor(row_factory=psycopg.rows.dict_row)
    return [dict(r) for r in cur.execute("SELECT * FROM ai.council_reduced WHERE fixture_id = %s ORDER BY candidate", (w.fixture,)).fetchall()]


def test_every_selection_of_a_pass_gets_its_row_and_the_judge_is_wanted_only_with_a_material_contradiction(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import usage

    def no_model(*_: Any, **__: Any) -> Any:
        raise AssertionError("the reduced Council asked a model")

    monkeypatch.setattr(usage, "call_json", no_model)
    world.standard()
    counts = {t: world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in
              ("ai.match_runs", "ai.agent_runs", "ai.pick_reviews", "intel.decisions", "intel.decisions_v2")}
    report = store.run_pass(world.conn, now=AT, code_version="test")
    assert (report.passes, report.deliberated, report.written, report.failed, report.lowered) == (1, 1, 3, 0, 0), report.as_json()
    got = rows(world)
    assert [r["candidate"] for r in got] == ["c1", "c2", "c3"], "every named selection of the pass, none left out"
    by = {r["candidate"]: r for r in got}
    c1 = by["c1"]
    assert c1["judge_wanted"] and c1["judge_status"] == "not_asked" and set(c1["material"]) >= {"AA1"} and c1["source"] == "rules"
    assert c1["rules_verdict"] == c1["final_verdict"] == "FALTA_INFO" and c1["rules_word"] == "ABSTAIN"
    assert not by["c2"]["judge_wanted"] and by["c2"]["judge_status"] == "not_needed" and by["c2"]["material"] == []
    assert all(r["version"] == "council-reduced-v1" and r["protocol"] == "council-protocol-v1" and r["deliberated_at"] < r["kickoff_at"]
               for r in got)
    assert c1["detail"]["need"]["reasons"] == ["material_value_and_time"] and c1["detail"]["rules"]["adjustment"]["verdict"] == "FALTA_INFO"
    assert report.judge_wanted == 1, "one case would call the judge (three readings): what the cost of the judge depends on"
    assert {t: world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in counts} == counts, "it writes its table and nothing else"

    again = store.run_pass(world.conn, now=AT + timedelta(minutes=30), code_version="test")
    assert again.passes == 0 and len(rows(world)) == 3, "a pass already reduced is not read again"


def test_each_pass_is_deliberated_as_of_its_own_moment(world: World) -> None:
    world.standard()
    later = world.shadow_pass(known=KNOWN + timedelta(hours=2), created=KNOWN + timedelta(hours=2, minutes=5))
    r = store.run_pass(world.conn, now=KO - timedelta(minutes=30))
    assert (r.passes, r.deliberated, r.superseded) == (2, 2, 0), r.as_json()
    by_run = world.conn.execute("SELECT match_run_id, count(*), max(deliberated_at) FROM ai.council_reduced WHERE fixture_id = %s "
                                "GROUP BY 1 ORDER BY 1", (world.fixture,)).fetchall()
    assert [n for _, n, _ in by_run] == [3, 3] and by_run[1][0] == later
    assert by_run[1][2] == KNOWN + timedelta(hours=2, minutes=5), "the moment the pass was written, not the moment of the job"


def test_the_table_refuses_a_council_that_raises_and_any_change(world: World) -> None:
    world.standard()
    store.run_pass(world.conn, now=AT)
    base = {k: v for k, v in rows(world)[0].items() if k not in ("id", "created_at")}
    base["detail"] = Jsonb(base["detail"])
    columns = ", ".join(base)
    values = ", ".join(f"%({k})s" for k in base)

    def refused(change: dict[str, Any]) -> bool:
        with pytest.raises(psycopg.errors.CheckViolation), world.conn.transaction():
            world.conn.execute(f"INSERT INTO ai.council_reduced ({columns}) VALUES ({values})", base | {"candidate": "c9"} | change)
        return True

    assert refused({"source": "judge", "majority": "APPROVE", "judge_status": "asked", "final_verdict": "CONFIRMA"}), "a judge that raises"
    assert refused({"source": "rules", "final_verdict": "BLOQUEA"}), "the rules' row with another verdict"
    assert refused({"majority": "REJECT", "judge_status": "not_asked"}), "a majority with no reading"
    assert refused({"judge_status": "not_needed"}), "wanted and not needed at once"
    assert refused({"deliberated_at": KO}), "after the kick-off"
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), world.conn.transaction():
        world.conn.execute("UPDATE ai.council_reduced SET final_verdict = rules_verdict WHERE fixture_id = %s", (world.fixture,))
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), world.conn.transaction():
        world.conn.execute("DELETE FROM ai.council_reduced WHERE fixture_id = %s", (world.fixture,))
    with world.conn.transaction():
        world.conn.execute(f"INSERT INTO ai.council_reduced ({columns}) VALUES ({values})",
                           base | {"candidate": "c9", "source": "judge", "majority": "REJECT", "judge_status": "asked",
                                   "final_verdict": "BLOQUEA"})
    assert len(rows(world)) == 4, "a judge that lowers is a row the table takes"
