"""IA-079 (AD-J08): the Intelligence console over HTTP, on PostgreSQL migrated to head.

* As SUPER_ADMIN the answer is C-11, read only: nothing is written, the registry's seven capabilities carry their state, the newest battery row
  and leakage audit are the ones stored, and «nada sale de la sombra» holds with the Picks board on its legacy path.
* With ``FBI_PICKS_SOURCE=intelligence`` it says it does not hold.
* A database that lacks a table the console reads (what a QA database behind the code had) still gets its answer: the block says
  ``UndefinedTable`` and ``schema_check`` names the table - instead of a 500.
* A reader gets 403.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.contracts.intelligence.console import ConsoleContract
from fbi.api.deps import get_db
from fbi.api.services import intelligence_console
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration

URL = "/api/v1/admin/intelligence/console"
AT = datetime(2026, 11, 15, 17, 12, tzinfo=UTC)
COUNTED = ("ai.feature_gates", "intel.capability_transitions", "intel.capabilities", "intel.audit_checks")


@pytest.fixture(autouse=True)
def _fresh_panel() -> Iterator[None]:
    intelligence_console.clear_cache()
    yield
    intelligence_console.clear_cache()


def client(db: psycopg.Connection[Any], role: str = "SUPER_ADMIN") -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE, raise_server_exceptions=False)


def counts(db: psycopg.Connection[Any]) -> dict[str, int]:
    return {t: int(db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in COUNTED}  # type: ignore[index]


def stored(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
                     "VALUES ('battery', %s, false, %s, %s, 'script') RETURNING id", (AT, Jsonb({"verdict": "fail"}), "c" * 64)).fetchone()
    assert row is not None
    db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) VALUES ('switches', %s, true, %s, %s, "
               "'script')", (AT, Jsonb({"words": {"mode": "shadow", "research_v2": "shadow", "agents": "match,council"}}), "d" * 64))
    for rule, n in (("price_known", 0), ("evidence_known", 2)):
        db.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations) "
                   "VALUES (%s, %s, 'leak-audit-v9', %s, 50, %s)", (date(2026, 11, 14), AT, rule, n))
    return int(row[0])


def test_the_console_answers_c11_and_writes_nothing(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PICKS_SOURCE", raising=False)
    monkeypatch.setenv("FBI_AI_MODE", "enforce")
    battery = stored(db)
    before = counts(db)
    answer = client(db).get(URL)
    assert answer.status_code == 200, answer.text
    console = ConsoleContract.model_validate(answer.json()["data"])
    assert counts(db) == before, "the console wrote a row"
    assert console.contract == "C-11" and console.projection == "private" and console.decides is False

    shadow = console.shadow
    assert shadow.verdict == "se_cumple" and shadow.breaks == [] and shadow.published_picks == 0
    assert shadow.picks_source.reads_as == "legacy" and shadow.ai_mode.reads_as == "enforce"
    assert shadow.ai_enforcement.enforced is False  # type: ignore[union-attr]  # enforce without a report of combined that passed
    assert shadow.ai_mode.worker_recorded == "shadow", "the worker's ledger says what the worker runs with, beside the API's word"
    agents = next(s for s in shadow.switches if s.switch == "FBI_AI_AGENTS")
    assert agents.worker_recorded == "match,council"

    caps = console.capabilities
    assert not hasattr(caps, "read_failed")
    seeded = {"research_v2", "readers", "council", "haiku_arm", "family_decisions", "attribution", "chronicle_review"}
    assert {i.state for i in caps.items.items if i.key in seeded} == {"en_sombra"}  # revision 0138 seeds the seven
    assert all(i.key in seeded or not isinstance(i.state, str) for i in caps.items.items), "a later piece waits for sync --write"
    research = next(i for i in caps.items.items if i.key == "research_v2")
    assert research.safety_gates[0].verdict == "NO PASA" and research.safety_gates[0].row == battery
    assert any("dice NO PASA" in w for w in research.warnings)

    security = console.security
    assert security.battery.verdict == "NO PASA" and security.battery.row == battery  # type: ignore[union-attr]
    audit = security.leak_audit
    assert audit.day == date(2026, 11, 14) and audit.violations == 2 and audit.rules == 2  # type: ignore[union-attr]
    assert security.schema_check.up_to_date and security.schema_check.missing_relations == []  # type: ignore[union-attr]
    assert security.gates.rule_holds and not any(g.approved for g in security.gates.items)  # type: ignore[union-attr]
    assert not hasattr(console.costs, "read_failed")
    assert console.news_engine.expected_piece == "AD-G01" and console.alert_queue.expected_piece == "AD-D08"


def test_the_shadow_does_not_hold_with_the_board_on_intelligence(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_PICKS_SOURCE", "intelligence")
    data = client(db).get(URL).json()["data"]
    assert data["shadow"]["verdict"] == "no_se_cumple" and data["shadow"]["breaks"] == ["picks_source_intelligence"]
    assert data["shadow"]["picks_source"]["changeable_here"] is False


def test_a_database_behind_the_code_gets_its_answer_and_is_told(db: psycopg.Connection[Any]) -> None:
    db.execute("DROP TABLE intel.capability_transitions CASCADE")  # rolled back with the test's transaction
    db.execute("DROP TABLE intel.family_memory CASCADE")
    answer = client(db).get(URL)
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data["capabilities"] == {"read_failed": True, "error": "UndefinedTable"}
    schema = data["security"]["schema_check"]
    assert schema["up_to_date"] is False and schema["missing_relations"] == ["intel.capability_transitions", "intel.family_memory"]
    assert data["shadow"]["verdict"] == "se_cumple", "the other blocks are still read"


def test_a_reader_gets_403(db: psycopg.Connection[Any]) -> None:
    answer = client(db, "USER").get(URL)
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "forbidden"
