"""The gate of research v2 from the command line (``scripts/ia_research_gate.py``): its exit status, what it records and what it refuses. The verdict
itself is ``test_gate_research`` (a built world) and ``test_research_v2_cycle`` (the cycle's own rows)."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
import pytest

from fbi.ai import gates

from .conftest import Seed
from .test_ai_decision_layer import Savepoints
from .test_gate_research import EARLIEST, LAST, NOW, build, noon, settings

pytestmark = pytest.mark.integration


def rows(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'research_v2'").fetchone()
    assert row is not None
    return int(row[0])


def test_the_command_answers_with_an_exit_status_and_records_only_on_request(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_research_gate as cli

    build(db, seed)
    conn: Any = Savepoints(db)
    doc, code = cli.run("evaluate", conn, settings(), at=NOW)
    assert code == cli.OK and doc["verdict"] == "PASA" and "recorded_row" not in doc
    assert doc["lines"][0] == "GATE DE RESEARCH V2 · PASA" and doc["gate"] == "research_v2"
    assert rows(db) == 0, "asking is not recording"
    doc, code = cli.run("evaluate", conn, settings(), at=NOW, record=True, version="test")
    assert code == cli.OK and isinstance(doc["recorded_row"], int) and rows(db) == 1
    assert gates.gate_state(db, "research_v2").passed and gates.research_mode(db, settings("on")) == "on"
    doc, code = cli.run("evaluate", conn, settings(), at=noon(date(2032, 10, 16)), record=True)
    assert code == cli.PENDING and doc["verdict"] == "PENDIENTE POR TIEMPO REAL" and doc["recorded_row"] is None
    assert "nothing was written" in doc["recorded_note"] and rows(db) == 1, "a verdict that is pending is not evidence of anything"


def test_the_command_exits_one_when_the_gate_says_no_and_a_failure_is_recorded_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_research_gate as cli

    build(db, seed, v2_misses_news=5)
    conn: Any = Savepoints(db)
    doc, code = cli.run("evaluate", conn, settings(), at=NOW, record=True, version="test")
    assert code == cli.NO and doc["verdict"] == "NO PASA" and doc["consequence"] and isinstance(doc["recorded_row"], int)
    assert gates.gate_state(db, "research_v2").passed is False and gates.research_mode(db, settings("on")) == "shadow"


def test_a_change_declared_on_the_command_line_reaches_the_gate(db: psycopg.Connection[Any], seed: Seed) -> None:
    from scripts import ia_research_gate as cli

    build(db, seed, shadow_from=EARLIEST)
    conn: Any = Savepoints(db)
    assert cli.run("evaluate", conn, settings(), at=NOW)[1] == cli.OK
    doc, code = cli.run("evaluate", conn, settings(), at=NOW, changes=[date(2032, 10, 15)])
    assert code == cli.PENDING and doc["window"]["stable_complete_days"] == 4


def test_the_command_refuses_what_it_should(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import ia_research_gate as cli

    build(db, seed)
    conn: Any = Savepoints(db)
    doc, code = cli.run("evaluate", conn, settings(), at=NOW, through=LAST, record=True)
    assert code == cli.CANNOT and "not recorded" in doc["error"] and rows(db) == 0
    doc, code = cli.run("evaluate", conn, settings(), at=NOW, through=date(2032, 10, 20))
    assert code == cli.CANNOT and "not a complete day yet" in doc["error"]
    doc, code = cli.run("revert", conn, settings(), at=NOW)
    assert code == cli.CANNOT and "unknown command" in doc["error"]
    with pytest.raises(SystemExit):
        cli.main(["evaluate", "--through", "yesterday"])
    assert "not a day" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["evaluate", "--changed-on", "2032-13-01"])
    assert "not a day" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["revert"])
