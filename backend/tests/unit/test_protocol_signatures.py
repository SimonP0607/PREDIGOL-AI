"""IA-143 (AD-K07): the owner's signature of a preregistered protocol. Pure: no database.

* The catalog is every LAB protocol (their fingerprints untouched) and the chronicle's three own records, each pinned; every figure of those
  records is the constant the chronicle applies.
* A signature counts only for the fingerprint in force: another fingerprint, another version or not the owner does not sign the protocol.
* The command refuses what is not the owner's signature of the protocol as it is now, previews without ``--confirm-owner`` (exit 3) and
  never writes twice.
* A signature turns nothing on: the readers report it and no verdict changes; only the owner's command writes the table; the package that
  the console reads imports nothing of the import cycle.
"""

from __future__ import annotations

import argparse
import ast
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripts import ia_protocols as cli

from fbi import protosign
from fbi.api.services import intelligence_console as console
from fbi.chronicle import protocol as chronicle_protocol
from fbi.chronicle import repetition, retire
from fbi.evalpass import performance
from fbi.evaluation import board
from fbi.protosign import records
from fbi.protosign import store as register
from fbi.research import protocol as lab
from tests.unit.test_research_protocols import PINNED as LAB_PINNED

BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND / "src" / "fbi"
AT = datetime(2026, 11, 18, 10, tzinfo=UTC)

OWN_PINNED = {
    "AD-F04": "17c942303fbc2cd0f39f90a1184f8cf0a699e1c3bffa5c783967952fb32d3608",
    "AD-F05": "1fbeadbddd163eb4eae3b15e952e340c11226544aa304a5551988060f07a7b6a",
    "AD-F06": "33b296c7c3852187e5cb59b223bc752b9f36f997fdf9320b5f8beb4fbee8b47b",
}
"""The chronicle's own protocols are frozen like the LAB ones: a change is a new fingerprint, and the owner signs it again."""


def row(s: protosign.Signable, **kw: Any) -> dict[str, Any]:
    base = {"id": 7, "protocol_key": s.key, "protocol_version": s.version, "framework": s.framework, "fingerprint": s.fingerprint,
            "reason": "Firmo el protocolo tal como está", "decided_by": "owner", "signed_at": AT, "code_version": "abc"}
    return base | kw


# ── the catalog ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_catalog_is_every_lab_protocol_untouched_and_the_three_of_the_chronicle() -> None:
    cat = protosign.catalog()
    assert set(cat) == set(LAB_PINNED) | set(OWN_PINNED)
    for key, fp in LAB_PINNED.items():
        assert cat[key].fingerprint == fp == lab.fingerprint(lab.PROTOCOLS[key]) and cat[key].framework == "lab-protocol-v1"
        assert cat[key].version == lab.PROTOCOLS[key].version and cat[key].body["key"] == key
    for key, fp in OWN_PINNED.items():
        assert cat[key].fingerprint == fp, key
        assert cat[key].framework == "own-record-v1" and cat[key].registered_on == "2026-11-17"
    assert (cat["AD-F04"].version, cat["AD-F05"].version, cat["AD-F06"].version) == (repetition.VERSION, retire.VERSION,
                                                                                     chronicle_protocol.VERSION)
    assert (repetition.KEY, retire.KEY, chronicle_protocol.KEY) == ("AD-F04", "AD-F05", "AD-F06")
    assert all(protosign.KEY.match(k) for k in cat)


def test_the_records_of_the_chronicle_say_exactly_what_the_chronicle_applies() -> None:
    """A threshold changed in the chronicle and not here (or here and not there) fails: the record IS what the owner signs."""
    f04 = records.F04["rule"]
    assert f04 == {"share_max": repetition.SHARE_MAX, "min_corpus": repetition.MIN_CORPUS, "window_days": repetition.WINDOW_DAYS,
                   "corpus_limit": repetition.CORPUS_LIMIT, "generic_rate_max": repetition.GENERIC_RATE_MAX,
                   "repeat_rate_max": repetition.REPEAT_RATE_MAX, "stock_list_sha256": records.STOCK_LIST_SHA256}
    assert records.stock_list_hash({k: p.pattern for k, p in repetition.GENERIC.items()}) == records.STOCK_LIST_SHA256
    f05 = records.F05["rule"]
    assert f05["chronicle"] == retire.CHRONICLE and tuple(f05["texts"]) == retire.TEXTS and f05["metrics"] == retire.METRICS
    assert {k: tuple(v) for k, v in f05["applies"].items()} == retire.APPLIES
    assert (f05["margin"], f05["cost_margin"], f05["min_matches"]) == (retire.MARGIN, str(retire.COST_MARGIN), retire.MIN_MATCHES)
    f06 = records.F06["rule"]
    assert (f06["seed"], f06["sample"], f06["double"], f06["unsupported_max"], f06["agreement_min"], f06["confidence"]) == (
        chronicle_protocol.SEED, chronicle_protocol.SAMPLE, chronicle_protocol.DOUBLE, chronicle_protocol.UNSUPPORTED_MAX,
        chronicle_protocol.AGREEMENT_MIN, chronicle_protocol.CONFIDENCE)
    assert f06["thresholds"] == chronicle_protocol.THRESHOLDS
    from fbi.ai.label_bank import SUPPORT_LABELS

    assert f06["labels"] == list(SUPPORT_LABELS)
    for r in records.RECORDS:
        assert r["framework"] == records.FRAMEWORK and r["where"].startswith("fbi/chronicle/") and len(r["says"]) > 200


def test_a_changed_record_is_another_fingerprint() -> None:
    moved = {**records.F04, "rule": {**records.F04["rule"], "share_max": 0.25}}
    assert records.fingerprint(moved) != OWN_PINNED["AD-F04"]
    assert records.fingerprint(dict(reversed(list(records.F04.items())))) == OWN_PINNED["AD-F04"], "the order of the keys is not the text"


# ── what a signature is ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_signature_counts_only_for_the_fingerprint_in_force() -> None:
    s = protosign.current("AD-K02")
    assert protosign.in_force(s, row(s))
    assert not protosign.in_force(s, row(s, fingerprint="0" * 64)), "a signature of another fingerprint is not a signature of this one"
    assert not protosign.in_force(s, row(s, protocol_version="proto-ad-k02-v0"))
    assert not protosign.in_force(s, row(s, protocol_key="AD-K03"))
    assert not protosign.in_force(s, row(s, decided_by="script"))
    older, now = row(s, id=3, fingerprint="1" * 64), row(s, id=9)
    assert register.in_force_of(s, [older, now]) == now and register.in_force_of(s, [older]) is None


@pytest.mark.parametrize(("key", "fingerprint", "reason", "words"), [
    ("AD-Z99", "a" * 64, "Firmo el protocolo", "no hay protocolo registrado"),
    ("AD-K02", "A" * 64, "Firmo el protocolo", "sha256 en minúsculas"),
    ("AD-K02", "abc", "Firmo el protocolo", "sha256 en minúsculas"),
    ("AD-K02", LAB_PINNED["AD-K03"], "Firmo el protocolo", "no es la vigente"),
    ("AD-K02", LAB_PINNED["AD-K02"], "  ok  ", "de 10 a 600"),
    ("AD-K02", LAB_PINNED["AD-K02"], "x" * 601, "de 10 a 600"),
])
def test_what_a_signature_may_not_be(key: str, fingerprint: str, reason: str, words: str) -> None:
    assert any(words in p for p in protosign.sign_problems(key, fingerprint, reason))


def test_the_owners_signature_of_the_fingerprint_in_force_has_no_problem() -> None:
    for key, s in protosign.catalog().items():
        assert protosign.sign_problems(key, s.fingerprint, "Firmo este protocolo antes de mirar los datos") == []
    with pytest.raises(LookupError):
        protosign.current("AD-Z99")


# ── the readers report it and decide nothing with it ──────────────────────────────────────────────────────────────────────────

def test_the_board_and_the_performance_report_say_the_signature_and_change_nothing_else() -> None:
    assert board.build([])["signed_by_owner"] is False and board.build([], signed=True)["signed_by_owner"] is True
    unsigned, signed = board.build([], signed=False), board.build([], signed=True)
    assert {k: v for k, v in unsigned.items() if k != "signed_by_owner"} == {k: v for k, v in signed.items() if k != "signed_by_owner"}
    period = {"start": "2026-11-01", "end": "2026-11-17"}
    a, b = performance.report([], [], period=period), performance.report([], [], period=period, signed=True)
    assert a["signed_by_owner"] is False and b["signed_by_owner"] is True and b["decides"] is False
    assert {k: v for k, v in a.items() if k != "signed_by_owner"} == {k: v for k, v in b.items() if k != "signed_by_owner"}


def test_the_score_of_a_sheet_says_the_signature_and_nothing_else_moves() -> None:
    rows = [{"review_id": 1, "label": "SUPPORTED", "double": False}]
    a, b = chronicle_protocol.score(rows), chronicle_protocol.score(rows, signed=True)
    assert a["signed"] is False and b["signed"] is True
    assert {k: v for k, v in a.items() if k != "signed"} == {k: v for k, v in b.items() if k != "signed"}


def test_the_console_shows_every_protocol_with_its_signature() -> None:
    cat = protosign.catalog()
    k02 = cat["AD-K02"]
    items = [{**s.head(), "signed_by_owner": key == "AD-K02", "signature": row(k02) if key == "AD-K02" else None,
              "other_fingerprints": 1 if key == "AD-F04" else 0} for key, s in cat.items()]
    block = console.protocols_of(items)
    assert (block.signed, block.pending, len(block.items)) == (1, len(cat) - 1, len(cat))
    shown = {p.key: p for p in block.items}
    assert shown["AD-K02"].signed_by_owner and shown["AD-K02"].signature_row == 7 and shown["AD-K02"].fingerprint == k02.fingerprint
    assert not shown["AD-F04"].signed_by_owner and shown["AD-F04"].other_fingerprints == 1
    assert "no activa nada" in block.notice_es and block.register_version == protosign.VERSION


def _fbi_imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fbi."):
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("fbi."))
    return out


SQL_ON_TABLE = re.compile(r"(?:FROM|INTO|UPDATE|JOIN)\s+ai\.protocol_signatures", re.IGNORECASE)


def test_a_signature_turns_nothing_on() -> None:
    """Only the readers listed here read the register, and each of them only reports it; nothing of the code writes it but the store."""
    readers = {"api/services/intelligence_console.py", "evaluation/views.py", "chronicle/inputs.py"}
    found = set()
    for path in SRC.rglob("*.py"):
        rel = str(path.relative_to(SRC))
        if rel.startswith("protosign/"):
            continue
        text = path.read_text(encoding="utf-8")
        if any(m.startswith("fbi.protosign") for m in _fbi_imports(path)):
            found.add(rel)
        assert not SQL_ON_TABLE.search(text), f"{rel} reads or writes the table: only fbi.protosign.store may"
        assert ".sign(" not in text or "protosign" not in text, rel
    assert found == readers, found
    writers = [p.name for p in (BACKEND / "scripts").glob("*.py")
               if any(m.startswith("fbi.protosign") for m in _fbi_imports(p)) and "register.sign(" in p.read_text(encoding="utf-8")]
    assert writers == ["ia_protocols.py"]
    store = (SRC / "protosign" / "store.py").read_text(encoding="utf-8")
    assert len(re.findall(r"INSERT INTO ai\.protocol_signatures", store)) == 1 and "UPDATE ai." not in store and "DELETE" not in store


def test_the_register_imports_nothing_of_the_import_cycle() -> None:
    """The console, C-03 and C-08 read it: it may import only the LAB protocols (pure) and itself."""
    imported = set().union(*(_fbi_imports(p) for p in (SRC / "protosign").glob("*.py")))
    assert imported <= {"fbi.protosign", "fbi.research"}, imported


# ── the command ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

class FakeRegister:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.signed: list[tuple[str, str]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(register, "exists", lambda conn: True)
        monkeypatch.setattr(register, "signatures", lambda conn, keys=None: [r for r in self.rows if keys is None or r["protocol_key"] in keys])

        def sign(conn: Any, key: str, *, fingerprint: str, reason: str, code_version: str | None = None) -> dict[str, Any]:
            self.signed.append((key, fingerprint))
            return {"written": True, "row": 41}

        monkeypatch.setattr(register, "sign", sign)


class FakeConn:
    committed = 0

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        pass


def ns(command: str, key: str | None = None, fingerprint: str | None = None, reason: str | None = None, confirm: bool = False,
       dry_run: bool = False) -> argparse.Namespace:
    return argparse.Namespace(command=command, key=key, fingerprint=fingerprint, reason=reason, confirm_owner=confirm, dry_run=dry_run,
                              dsn=None)


def test_list_gives_every_pending_protocol_its_exact_command(monkeypatch: pytest.MonkeyPatch) -> None:
    k02 = protosign.current("AD-K02")
    FakeRegister([row(k02), row(protosign.current("AD-F06"), id=8, fingerprint="2" * 64)]).install(monkeypatch)
    doc, code = cli.run(FakeConn(), ns("list"))  # type: ignore[arg-type]
    assert code == cli.OK and doc["signed"] == 1 and doc["pending"] == len(protosign.catalog()) - 1
    by = {p["key"]: p for p in doc["protocols"]}
    assert by["AD-K02"]["signed_by_owner"] and "sign" not in by["AD-K02"]
    assert by["AD-F06"]["other_fingerprints"] == 1 and by["AD-F06"]["sign"] == (
        f'python -m scripts.ia_protocols sign --key AD-F06 --fingerprint {OWN_PINNED["AD-F06"]} --reason "..." --confirm-owner')
    assert by["AD-A03"]["own_gate_signature"]["sign"].startswith("python -m scripts.ia_battery_v4 sign")
    assert "own_gate_signature" in by["AD-C09"] and "own_gate_signature" not in by["AD-K02"]


def test_show_gives_the_whole_protocol_and_the_fingerprint_to_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeRegister().install(monkeypatch)
    doc, code = cli.run(FakeConn(), ns("show", key="AD-K03"))  # type: ignore[arg-type]
    assert code == cli.OK and doc["fingerprint"] == LAB_PINNED["AD-K03"] and doc["protocol"]["pass_rule"]
    assert doc["signed_by_owner"] is False and LAB_PINNED["AD-K03"] in doc["sign"] and doc["history"] == []
    doc, code = cli.run(FakeConn(), ns("show", key="AD-F05"))  # type: ignore[arg-type]
    assert code == cli.OK and doc["protocol"]["rule"]["min_matches"] == 100
    doc, code = cli.run(FakeConn(), ns("show", key="AD-Z99"))  # type: ignore[arg-type]
    assert code == cli.REFUSED and "AD-K02" in doc["error"]


def test_sign_previews_without_the_owner_refuses_another_fingerprint_and_signs_with_the_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRegister()
    fake.install(monkeypatch)
    conn = FakeConn()
    reason = "Firmo el tablero antes de mirar los datos"
    doc, code = cli.run(conn, ns("sign", "AD-K02", LAB_PINNED["AD-K02"], reason))  # type: ignore[arg-type]
    assert code == cli.PREVIEW and doc["written"] is False and doc["would_write"]["decided_by"] == "owner" and fake.signed == []
    doc, code = cli.run(conn, ns("sign", "AD-K02", LAB_PINNED["AD-K02"], reason, confirm=True, dry_run=True))  # type: ignore[arg-type]
    assert code == cli.PREVIEW and fake.signed == []
    doc, code = cli.run(conn, ns("sign", "AD-K02", LAB_PINNED["AD-K04"], reason, confirm=True))  # type: ignore[arg-type]
    assert code == cli.REFUSED and "no es la vigente" in doc["error"] and fake.signed == []
    doc, code = cli.run(conn, ns("sign", "AD-K02", LAB_PINNED["AD-K02"], "corto", confirm=True))  # type: ignore[arg-type]
    assert code == cli.REFUSED and fake.signed == []
    doc, code = cli.run(conn, ns("sign", "AD-K02", LAB_PINNED["AD-K02"], reason, confirm=True))  # type: ignore[arg-type]
    assert code == cli.OK and doc["written"] is True and fake.signed == [("AD-K02", LAB_PINNED["AD-K02"])] and conn.committed == 1


def test_the_preview_says_when_that_fingerprint_is_already_signed(monkeypatch: pytest.MonkeyPatch) -> None:
    k02 = protosign.current("AD-K02")
    FakeRegister([row(k02, id=12)]).install(monkeypatch)
    doc, code = cli.run(FakeConn(), ns("sign", "AD-K02", k02.fingerprint, "Firmo el tablero otra vez"))  # type: ignore[arg-type]
    assert code == cli.PREVIEW and doc["already"]["id"] == 12 and "ya está firmada (fila 12)" in doc["lines"][-1]


@pytest.mark.parametrize("argv", [["sign", "--key", "AD-K02"], ["show"], ["sign", "--fingerprint", "a" * 64, "--reason", "x" * 20],
                                  ["list", "--confirm-owner"], ["firmar"]])
def test_a_usage_error_writes_nothing_and_exits_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(argv) == cli.USAGE


def test_the_owners_guide_has_the_exact_command_of_every_protocol_with_its_fingerprint_of_now() -> None:
    guide = (BACKEND / "docs" / "owner" / "IA_143_FIRMA_DE_PROTOCOLOS.md").read_text(encoding="utf-8")
    for key, s in protosign.catalog().items():
        assert cli.sign_command(key, s.fingerprint) in guide, key
    assert "Una firma no activa nada" in guide and "show --key" in guide and "--confirm-owner" in guide
