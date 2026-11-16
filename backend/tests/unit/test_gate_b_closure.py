"""The owner's closure of Gate B as NO EVALUADO (AD-001, IA-055; ``gate_b.record_closure`` and ``scripts/ia_gate_b.py close``), with no
database: ``ai.feature_gates`` is a list in memory that answers only the statements the closure runs, so any other statement fails the test.

What is held: nothing is written without ``--confirm-owner`` (a preview, on a read-only connection); ONE row is written, the owner's, with the
informative cut of ``evaluate`` untouched; a second closure writes nothing and says which row it found; after the closure ``evaluate --record``
records nothing more of ``gate-b-v1``; and ``evaluate`` itself still writes nothing. On a built world against the real schema:
``tests/integration/test_gate_b_bench.py``."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import ia_gate_b

from fbi.ai import gate_b as g
from fbi.ai import gates
from fbi.ai.config import AiSettings

NOW = datetime(2026, 11, 16, 17, 45, 35, tzinfo=UTC)
TODAY = date(2026, 11, 16)
REASON = ("No evaluado: ventana interrumpida por decisión del dueño (Arquitectura definitiva 2026, 16-nov-2026); "
          "corte informativo adjunto")
SETTINGS = AiSettings()


def cut() -> g.GateReport:
    """A report shaped like the cut of 16-nov-2026: anchored on the 11th, 5 of 14 days, battery row 18 and research row 17 saying NO PASA."""
    w = g.window_from(today=TODAY, through=None, first_shadow=date(2026, 11, 1), events=[(date(2026, 11, 10), "match match-v5 first ran")])
    battery = g.BatteryRow(18, datetime(2026, 11, 15, 17, 12, 20, tzinfo=UTC), False,
                           {"battery": "battery-v3", "targets": {"match": {"prompt": "match-assess-v5"}}})
    checks = (g.judge_duplicates(1463, []),
              g.judge_battery(battery, since=datetime(2026, 11, 2, 5, tzinfo=UTC), running={"match": ["match-assess-v5"]}, stale=[]),
              g.judge_research({"id": 17, "at": datetime(2026, 11, 12, 13, 38, 48, tzinfo=UTC), "passed": False,
                                "evidence": {"checks": [{"id": "coverage", "detail": {"coverage_pct": "23.07"}}]}}))
    pending = (f"{w.stable_days} de {g.WINDOW_DAYS} días completos con la configuración estable desde {w.anchor}",)
    return g.GateReport(g.verdict_of(w, checks), NOW, w, checks, pending, preview=not w.complete)


class Gates:
    """``ai.feature_gates`` in memory: the advisory lock, the closure's SELECT and ``gates.record_gate``'s INSERT - nothing else."""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows: list[dict[str, Any]] = list(rows or [])
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.read_only = False

    def cursor(self, row_factory: Any = None) -> Cursor:
        return Cursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    @property
    def inserts(self) -> int:
        return sum(1 for s in self.statements if s == gates.INSERT_SQL)


class Cursor:
    def __init__(self, db: Gates) -> None:
        self.db = db
        self.result: list[Any] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.db.statements.append(sql)
        if sql == g.CLOSURE_LOCK_SQL:
            self.result = [(None,)]
        elif sql == g.CLOSURE_SQL:
            found = [r for r in self.db.rows if r["gate"] == "gate_b" and r["evidence"].get("kind") == params["kind"]]
            self.result = sorted(found, key=lambda r: (r["at"], r["id"]))[:1]
        elif sql == gates.INSERT_SQL:
            if self.db.read_only:
                raise AssertionError("a read-only connection was asked to write")
            gate, at, passed, evidence, digest, decided_by, version = params
            row = {"id": len(self.db.rows) + 1, "gate": gate, "at": at, "passed": passed, "evidence": evidence.obj, "evidence_hash": digest,
                   "decided_by": decided_by, "code_version": version}
            self.db.rows.append(row)
            self.result = [(row["id"],)]
        else:
            raise AssertionError(f"unexpected statement: {sql.strip()[:80]}")

    def fetchone(self) -> Any:
        return self.result[0] if self.result else None


@pytest.fixture()
def evaluated(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """``gate_b.evaluate`` answers the cut (its own arithmetic is ``test_gate_b_pure.py``); the instants it was asked for are kept."""
    asked: list[datetime] = []

    def fake(conn: Any, settings: AiSettings, *, at: datetime, through: date | None = None, changes: Any = ()) -> g.GateReport:
        asked.append(at)
        return cut()

    monkeypatch.setattr(g, "evaluate", fake)
    return asked


def earlier_rows() -> list[dict[str, Any]]:
    """Rows already on file, as in production: research_v2 (17) and battery (18). The closure must leave them as they are."""
    return [{"id": 17, "gate": "research_v2", "at": NOW - timedelta(days=4), "passed": False, "evidence": {"verdict": "NO PASA"},
             "evidence_hash": "a" * 64, "decided_by": "script", "code_version": "x"},
            {"id": 18, "gate": "battery", "at": NOW - timedelta(days=1), "passed": False, "evidence": {"battery": "battery-v3"},
             "evidence_hash": "b" * 64, "decided_by": "script", "code_version": "x"}]


# ── the evidence ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_closure_holds_the_word_the_reason_and_the_cut_untouched() -> None:
    report = cut()
    ev = g.closure_evidence(report, reason=f"  {REASON}  ")
    assert ev["kind"] == g.CLOSURE_KIND == "gate-b-closure-v1" and ev["gate"] == "gate_b" and ev["closes"] == "gate-b-v1"
    assert ev["verdict"] == g.NOT_EVALUATED == "NO EVALUADO" and ev["verdict_es"] == "NO EVALUADO — ventana interrumpida por decisión del dueño"
    assert ev["verdict"] not in (g.PASS, g.FAIL) and ev["decided_by"] == "owner" and ev["reason"] == REASON
    assert ev["informative_cut"] == report.as_json() and ev["informative_cut_hash"] == gates.evidence_hash(report.as_json())
    assert ev["rows_cited"] == {"battery": 18, "research_v2": 17}
    assert "alters no measurement" in ev["measurements_untouched"] and "append-only" in ev["measurements_untouched"]
    assert ev["informative_cut"]["verdict"] == g.PENDING_TIME and ev["informative_cut"]["window"]["stable_complete_days"] == 5
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="reason"):
            g.closure_evidence(report, reason=blank)


def test_the_cut_is_what_evaluate_json_prints_at_the_same_instant(evaluated: list[datetime]) -> None:
    printed, code = ia_gate_b.run(Gates(), SETTINGS, at=NOW)  # type: ignore[arg-type]  # evaluate --json, without its lines for a person
    printed.pop("lines")
    db = Gates()
    c, written = g.record_closure(db, SETTINGS, reason=REASON, at=NOW, confirmed_by_owner=True)  # type: ignore[arg-type]
    assert written and code == ia_gate_b.PENDING and evaluated == [NOW, NOW]
    assert json.loads(json.dumps(db.rows[0]["evidence"]["informative_cut"], default=str)) == json.loads(json.dumps(printed, default=str))
    assert c.cut_verdict == printed["verdict"] == g.PENDING_TIME


# ── record_closure ───────────────────────────────────────────────────────────────────────────────────────────────


def test_without_the_owners_confirmation_nothing_is_written_and_no_connection_is_touched() -> None:
    with pytest.raises(PermissionError, match="--confirm-owner"):
        g.record_closure(None, SETTINGS, reason=REASON, at=NOW, confirmed_by_owner=False)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="reason"):
        g.record_closure(None, SETTINGS, reason="  ", at=NOW, confirmed_by_owner=True)  # type: ignore[arg-type]


def test_one_row_of_the_owner_and_a_second_closure_writes_nothing(evaluated: list[datetime]) -> None:
    db = Gates(earlier_rows())
    before = [dict(r) for r in db.rows]
    c, written = g.record_closure(db, SETTINGS, reason=REASON, at=NOW, confirmed_by_owner=True, code_version="v")  # type: ignore[arg-type]
    assert written and db.inserts == 1 and db.statements[0] == g.CLOSURE_LOCK_SQL, "the lock comes first, then the look for a closure"
    row = db.rows[-1]
    assert (row["gate"], row["passed"], row["decided_by"], row["code_version"]) == ("gate_b", False, "owner", "v")
    assert row["evidence"]["kind"] == g.CLOSURE_KIND and row["evidence_hash"] == gates.evidence_hash(row["evidence"])
    assert (c.row, c.decided_by, c.reason, c.evidence_hash) == (row["id"], "owner", REASON, row["evidence_hash"])
    assert db.rows[:2] == before, "rows 17 and 18 are left as they were"
    again, wrote = g.record_closure(db, SETTINGS, reason="otra vez", at=NOW + timedelta(hours=1), confirmed_by_owner=True)  # type: ignore[arg-type]
    assert not wrote and again == c and db.inserts == 1 and len(db.rows) == 3 and evaluated == [NOW]
    assert again.as_json()["verdict_es"] == g.NOT_EVALUATED_ES and again.as_json()["row"] == row["id"]


def test_after_the_closure_evaluate_record_writes_nothing_more_of_gate_b_v1(evaluated: list[datetime], monkeypatch: pytest.MonkeyPatch) -> None:
    db = Gates()
    g.record_closure(db, SETTINGS, reason=REASON, at=NOW, confirmed_by_owner=True)  # type: ignore[arg-type]
    complete = g.GateReport(g.FAIL, NOW, g.window_from(today=TODAY, through=None, first_shadow=date(2026, 10, 1), events=[]))
    assert complete.recordable and g.record(db, complete) is None and db.inserts == 1  # type: ignore[arg-type]
    monkeypatch.setattr(g, "evaluate", lambda *a, **k: complete)
    doc, code = ia_gate_b.run(db, SETTINGS, at=NOW, record=True)  # type: ignore[arg-type]
    assert code == ia_gate_b.NO and doc["recorded_row"] is None and "closed gate-b-v1 as NO EVALUADO" in doc["recorded_note"]
    assert db.inserts == 1


def test_evaluate_still_writes_nothing(evaluated: list[datetime]) -> None:
    db = Gates()
    doc, _ = ia_gate_b.run(db, SETTINGS, at=NOW)  # type: ignore[arg-type]
    assert db.statements == [] and db.commits == 0 and "recorded_row" not in doc


# ── the command ──────────────────────────────────────────────────────────────────────────────────────────────────


def close(db: Gates, **kw: Any) -> tuple[dict[str, Any], int]:
    args: dict[str, Any] = {"not_evaluated": True, "reason": REASON, "confirm_owner": False, "dry_run": False, "at": NOW} | kw
    return ia_gate_b.close(db, SETTINGS, **args)  # type: ignore[arg-type]


def test_close_without_confirm_owner_is_a_preview_and_writes_nothing(evaluated: list[datetime]) -> None:
    db = Gates()
    for kw in ({}, {"dry_run": True, "confirm_owner": True}):
        doc, code = close(db, **kw)
        assert code == ia_gate_b.PENDING and doc["preview"] is True and doc["recorded_row"] is None, kw
        assert doc["lines"][0].startswith("VISTA PREVIA") and "no se ha escrito nada" in doc["lines"][0]
        assert doc["would_write"]["passed"] is False and doc["would_write"]["decided_by"] == "owner"
        assert doc["would_write"]["evidence"]["informative_cut"] == cut().as_json()
    assert db.inserts == 0 and db.commits == 0 and db.rollbacks == 2 and not db.rows


def test_close_writes_once_and_then_says_it_is_already_closed(evaluated: list[datetime]) -> None:
    db = Gates()
    doc, code = close(db, confirm_owner=True, version="v")
    assert code == ia_gate_b.OK and doc["recorded_row"] == 1 and doc["already_closed"] is False and db.commits == 1
    assert doc["lines"][0] == f"GATE B · {g.NOT_EVALUATED_ES}" and "firmado por el dueño" in doc["lines"][1]
    doc, code = close(db, confirm_owner=True, reason="otra vez")
    assert code == ia_gate_b.OK and doc["already_closed"] is True and doc["recorded_row"] is None and doc["closure"]["row"] == 1
    assert "No se escribe otro cierre" in doc["lines"][1] and db.inserts == 1 and len(db.rows) == 1
    doc, code = close(db)  # a preview after the closure only shows the closure on file
    assert code == ia_gate_b.OK and doc["already_closed"] is True and db.inserts == 1


@pytest.mark.parametrize(("kw", "needs"), [({"not_evaluated": False}, "--not-evaluated"), ({"reason": None}, "--reason"),
                                           ({"reason": "  "}, "--reason")])
def test_close_refuses_without_its_word_or_its_reason(kw: dict[str, Any], needs: str, evaluated: list[datetime]) -> None:
    db = Gates()
    doc, code = close(db, confirm_owner=True, **kw)
    assert code == ia_gate_b.CANNOT and needs in doc["error"] and "nothing was written" in doc["error"] and db.statements == []


@contextlib.contextmanager
def connected(monkeypatch: pytest.MonkeyPatch, db: Gates) -> Iterator[list[Any]]:
    opened: list[Any] = []

    def connect(*a: Any, **k: Any) -> Any:
        opened.append(k)
        return contextlib.nullcontext(db)

    monkeypatch.setattr("psycopg.connect", connect)
    monkeypatch.setattr(ia_gate_b, "code_version", lambda: "test")
    yield opened


def test_the_command_line_preview_runs_on_a_read_only_connection(monkeypatch: pytest.MonkeyPatch, evaluated: list[datetime],
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    db = Gates()
    with connected(monkeypatch, db) as opened:
        assert ia_gate_b.main(["close", "--not-evaluated", "--reason", REASON, "--dsn", "postgresql://x/y"]) == ia_gate_b.PENDING
    assert opened and db.read_only is True and db.inserts == 0
    assert "VISTA PREVIA" in capsys.readouterr().out
    with connected(monkeypatch, db):
        assert ia_gate_b.main(["close", "--not-evaluated", "--reason", REASON, "--confirm-owner", "--dsn", "postgresql://x/y"]) == ia_gate_b.OK
    assert db.read_only is False and db.inserts == 1 and db.rows[0]["code_version"] == "test"
    assert f"GATE B · {g.NOT_EVALUATED_ES}" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["close", "--reason", "x", "--confirm-owner"], ["close", "--not-evaluated", "--confirm-owner"],
                                  ["close", "--not-evaluated", "--reason", " ", "--confirm-owner"]])
def test_the_command_line_refuses_an_incomplete_closure_without_connecting(argv: list[str], monkeypatch: pytest.MonkeyPatch,
                                                                          capsys: pytest.CaptureFixture[str]) -> None:
    def no_connection(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("it must not connect")

    monkeypatch.setattr("psycopg.connect", no_connection)
    assert ia_gate_b.main(argv) == ia_gate_b.CANNOT and "nothing was written" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["evaluate", "--not-evaluated"], ["evaluate", "--dry-run"], ["set-lab-plan", "--not-evaluated", "--confirm-owner"],
                                  ["close", "--not-evaluated", "--reason", "x", "--record"], ["close", "--not-evaluated", "--reason", "x", "--days", "2"],
                                  ["close", "--not-evaluated", "--reason", "x", "--through", "2026-11-15"]])
def test_the_options_of_close_are_its_own(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        ia_gate_b.main(argv)
    assert exc.value.code == 2


# ── the owner's guide ────────────────────────────────────────────────────────────────────────────────────────────

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "owner" / "IA_055_CIERRE_GATE_B.md"
COMMAND = ('docker exec -w /app predigol-worker python -m scripts.ia_gate_b close --not-evaluated --reason "No evaluado: ventana interrumpida '
           'por decisión del dueño (Arquitectura definitiva 2026, 16-nov-2026); corte informativo adjunto" --confirm-owner')


def test_the_guide_gives_the_owners_exact_command_and_what_does_not_change() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    assert COMMAND in text and COMMAND.replace(" --confirm-owner", "") in text, "the preview and the signature, exactly"
    assert g.NOT_EVALUATED_ES in text and g.CLOSURE_KIND in text and "set-lab-plan" in text and "FBI_AI_MODE" in text
    parsed = ia_gate_b.build_parser().parse_args(["close", "--not-evaluated", "--reason", REASON, "--confirm-owner"])
    assert (parsed.command, parsed.not_evaluated, parsed.reason, parsed.confirm_owner, parsed.dry_run) == ("close", True, REASON, True, False)
    assert REASON in COMMAND
