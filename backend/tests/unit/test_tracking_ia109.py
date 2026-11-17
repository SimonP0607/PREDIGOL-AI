"""IA-109 (AD-E05): the tracking of loose selections - En juego -> Liquidada -> Evaluada on ``settle-v4`` - is pure where it decides.

* what it keeps: the first settlement once final, a correction only where a SCORE decided it and the current score decides otherwise, the
  firm evaluation once after the window of corrections; the cases postponed, suspended, void at 72 h and corrected;
* what it holds for a person is exactly what the re-settlement of the picks holds (``fbi.picks.resettlement.judge``), case by case;
* the cycle's moves after kick-off (``derive.after_kickoff``) and the derivation of a layer whose chains it settles;
* the plain words of «Cómo se liquida»;
* what it writes (``intel.selection_settlements`` and, through the cycle's API, the chains), and who may import it.
"""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.lifecycle import derive, machine
from fbi.lifecycle import store as lifecycle
from fbi.picks import resettlement, settlement
from fbi.tracking import selections as tracking
from fbi.tracking.selections import Kept, NewRow, plan

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
KO = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+TABLE)\s+([a-z_]+\.[a-z0-9_]+)?",
                   re.IGNORECASE)


def state(status: str, home: int | None = None, away: int | None = None, *, ko: datetime = KO) -> settlement.MatchState:
    return settlement.MatchState(status, home, away, None, None, home, away, ko)


def verdict(status: str, home: int | None = None, away: int | None = None, *, at: datetime = KO + timedelta(hours=3),
            market: str = "OU", selection: str = "Over", line: str = "2.5") -> settlement.Settlement:
    return settlement.settle(market, selection, Decimal(line), Decimal("2.0"), Decimal(1), state(status, home, away), at=at)


def kept(kind: str, result: str, basis: str | None, n: int = 1, at: datetime = KO + timedelta(hours=3)) -> Kept:
    return Kept(n, kind, result, basis, at)


def test_the_window_of_corrections_is_the_resettlements() -> None:
    assert tracking.FIRM_AFTER == resettlement.RECHECK_WINDOW
    assert tracking.FIRM_AFTER + tracking.FIRM_HOLD < tracking.BACK and settlement.VOID_AFTER < tracking.BACK
    assert lifecycle.WRITER not in tracking.WRITERS


def test_a_finished_match_is_settled_once_and_a_second_pass_adds_nothing() -> None:
    v = verdict("FT", 2, 1)
    first = plan([], v, now=KO + timedelta(hours=3), kickoff_at=KO)
    assert first == [NewRow("primera", "win", settlement.BASIS, None)]
    assert plan([kept("primera", "win", settlement.BASIS)], v, now=KO + timedelta(hours=4), kickoff_at=KO) == []


@pytest.mark.parametrize("status", ["NS", "1H", "HT", "PST", "SUSP", "INT", "ABD"])
def test_a_match_still_open_waits(status: str) -> None:
    assert plan([], verdict(status), now=KO + timedelta(hours=3), kickoff_at=KO) == []


def test_postponed_or_suspended_is_void_72_hours_after_kick_off() -> None:
    late = KO + settlement.VOID_AFTER + timedelta(minutes=1)
    for status in ("PST", "SUSP", "ABD"):
        v = verdict(status, at=late)
        assert plan([], v, now=late, kickoff_at=KO) == [NewRow("primera", "void", settlement.NO_RESULT_BASIS, None)]
    assert plan([], verdict("CANC"), now=KO, kickoff_at=KO) == [NewRow("primera", "void", "not_played", None)]


def test_a_corrected_score_is_a_new_row_naming_the_one_it_supersedes() -> None:
    trail = [kept("primera", "win", settlement.BASIS, 11)]
    fixed = verdict("FT", 1, 1)
    assert plan(trail, fixed, now=KO + timedelta(hours=9), kickoff_at=KO) == [NewRow("correccion", "loss", settlement.BASIS, 11)]
    trail.append(kept("correccion", "loss", settlement.BASIS, 12, KO + timedelta(hours=9)))
    back = verdict("FT", 2, 1)
    assert plan(trail, back, now=KO + timedelta(hours=10), kickoff_at=KO) == [NewRow("correccion", "win", settlement.BASIS, 12)]


def test_a_void_by_rule_stands_and_a_score_is_not_undone_by_a_rule() -> None:
    void = [kept("primera", "void", settlement.NO_RESULT_BASIS)]
    played = verdict("FT", 3, 0, at=KO + timedelta(days=5))
    assert plan(void, played, now=KO + timedelta(days=5), kickoff_at=KO) == []
    assert tracking.held(void, played) == "void_by_rule_stands"
    scored = [kept("primera", "win", settlement.BASIS)]
    cancelled = verdict("CANC")
    assert plan(scored, cancelled, now=KO + timedelta(hours=5), kickoff_at=KO) == []
    assert tracking.held(scored, cancelled) == "settles_by_rule_now"
    reopened = verdict("PST", at=KO + timedelta(hours=5))
    assert plan(scored, reopened, now=KO + timedelta(hours=5), kickoff_at=KO) == []
    assert tracking.held(scored, reopened) == "no_longer_settles"


def test_the_firm_evaluation_comes_once_after_the_window() -> None:
    v = verdict("FT", 2, 1)
    trail = [kept("primera", "win", settlement.BASIS, 5)]
    assert plan(trail, v, now=KO + tracking.FIRM_AFTER - timedelta(minutes=1), kickoff_at=KO) == []
    firm = plan(trail, v, now=KO + tracking.FIRM_AFTER, kickoff_at=KO)
    assert firm == [NewRow("firme", "win", settlement.BASIS, 5)]
    trail.append(kept("firme", "win", settlement.BASIS, 6, KO + tracking.FIRM_AFTER))
    assert plan(trail, v, now=KO + tracking.FIRM_AFTER + timedelta(days=1), kickoff_at=KO) == []
    late = [kept("primera", "win", settlement.BASIS, 5), kept("correccion", "loss", settlement.BASIS, 6, KO + timedelta(days=7))]
    assert plan(late, verdict("FT", 1, 1), now=KO + tracking.FIRM_AFTER + timedelta(hours=1), kickoff_at=KO) == [], \
        "a correction is firm only a day after it was kept"


@pytest.mark.parametrize(("stored", "basis", "status", "home", "away"), [
    ("win", settlement.BASIS, "FT", 1, 1), ("win", settlement.BASIS, "FT", 3, 1), ("void", settlement.NO_RESULT_BASIS, "FT", 3, 0),
    ("void", "not_played", "FT", 0, 0), ("win", settlement.BASIS, "CANC", None, None), ("loss", settlement.BASIS, "PST", None, None),
    ("loss", settlement.BASIS, "AET", 1, 1), ("void", settlement.NO_RESULT_BASIS, "PST", None, None)])
def test_what_it_holds_is_what_the_resettlement_holds(stored: str, basis: str, status: str, home: int | None, away: int | None) -> None:
    v = verdict(status, home, away, at=KO + timedelta(hours=5))
    mine = tracking.held([kept("primera", stored, basis)], v)
    theirs = resettlement.judge(stored_status=stored, stored_profit=None, score_based=basis == settlement.BASIS, outcome=v, priced=False,
                                upper=False, status_short=status)
    assert (theirs.action == "held") == (mine is not None)
    if theirs.action == "held":
        assert theirs.code == mine
    changes = plan([kept("primera", stored, basis)], v, now=KO + timedelta(hours=5), kickoff_at=KO)
    assert (theirs.action == "change") == (bool(changes) and changes[0].kind == "correccion")


def test_the_value_against_the_close() -> None:
    assert tracking.line_value(Decimal("2.10"), Decimal("0.5")) == Decimal("0.050000")
    assert tracking.line_value(None, Decimal("0.5")) is None and tracking.line_value(Decimal("2"), None) is None


def settled(n: int, kind: str, at: datetime, result: str = "win") -> derive.Settled:
    return derive.Settled(n, kind, at, result)


def test_the_moves_after_kick_off() -> None:
    s = [settled(1, "primera", KO + timedelta(hours=2)), settled(2, "firme", KO + timedelta(days=7))]
    moves = derive.after_kickoff("en_juego", s, now=KO + timedelta(days=8))
    assert [(m[0].state, m[0].reason, m[0].settlement_result, m[2], m[3]) for m in moves] == [
        ("liquidada", "resultado", "win", derive.SETTLEMENTS, 1), ("evaluada", "evaluacion_posterior", None, derive.SETTLEMENTS, 2)]
    assert [m[0].state for m in derive.after_kickoff("en_juego", s, now=KO + timedelta(days=1))] == ["liquidada"]
    assert derive.after_kickoff("liquidada", [settled(1, "primera", KO), settled(3, "correccion", KO + timedelta(hours=4), "loss")],
                                now=KO + timedelta(days=1)) == [], "a correction moves nothing"
    assert derive.after_kickoff("descartada", s, now=KO + timedelta(days=8)) == []
    assert derive.after_kickoff("evaluada", s, now=KO + timedelta(days=8)) == []
    machine.check_chain([machine.Step("detectado", "candidato_nuevo"), machine.Step("confirmada_sombra", "cumple_todo"),
                         machine.Step("en_juego", "saque"), *[m[0] for m in moves]])


def test_a_layer_settled_by_the_tracking_derives_its_whole_chain() -> None:
    k = derive.Key.of(7, "OU", "Over", "2.5")
    h = derive.History(k, decisions=[derive.Decision(1, "decision-v2", KO - timedelta(hours=3), "E1", "APROBADO", (), "FULL", KO)])
    f = derive.Fixture(7, KO, "FT", "finished")
    h.settlements = [settled(40, "primera", KO + timedelta(hours=2), "loss"), settled(41, "firme", KO + timedelta(days=7), "loss")]
    rows = derive.derive(h, f, now=KO + timedelta(days=8), source="intel.decisions_v2")
    assert [(r.step.state, r.source, r.source_id) for r in rows][-3:] == [
        ("en_juego", "core.fixtures", 7), ("liquidada", derive.SETTLEMENTS, 40), ("evaluada", derive.SETTLEMENTS, 41)]
    assert rows[-2].step.settlement_result == "loss"
    assert derive.as_of(h, KO + timedelta(hours=1)).settlements == []


def test_append_refuses_the_cycles_own_writer_and_an_illegal_move() -> None:
    k = derive.Key.of(7, "OU", "Over", "2.5")
    row = derive.Row(machine.Step("liquidada", "resultado", settlement_result="win"), KO, derive.SETTLEMENTS, 1, "decision-v2")
    with pytest.raises(ValueError):
        lifecycle.append(None, writer=lifecycle.WRITER, key=k, rows=[row], previous_id=1, from_state="en_juego", dry_run=True)  # type: ignore[arg-type]
    with pytest.raises(machine.IllegalTransitionError):
        lifecycle.append(None, writer="decision-v2-shadow-v1", key=k, rows=[row], previous_id=1, from_state="confirmada_sombra",  # type: ignore[arg-type]
                         dry_run=True)
    assert lifecycle.append(None, writer="decision-v2-shadow-v1", key=k, rows=[row], previous_id=1, from_state="en_juego",  # type: ignore[arg-type]
                            dry_run=True) == 0


@pytest.mark.parametrize(("market", "selection", "line", "words"), [
    ("1X2", "Home", "0", "Gana si el local gana el partido"), ("DC", "X2", "0", "visitante gana o empata"),
    ("BTTS", "Yes", "0", "los dos equipos marcan"), ("OU", "Over", "2.5", "más de 2,5 goles"),
    ("OU", "Under", "3", "exactamente 3 goles se devuelve"), ("OU", "Over", "2.75", "Línea partida (2,75)"),
    ("AH", "Home", "-0.5", "Se restan 0,5 goles al resultado del local"), ("AH", "Away", "-0.25", "Hándicap asiático partido"), ("AH", "Home", "1", "Se suma 1 gol al resultado del local"),
    ("CORNERS_OU", "Over", "9.5", "no tiene regla de liquidación")])
def test_how_it_settles_in_plain_words(market: str, selection: str, line: str, words: str) -> None:
    text = tracking.how_it_settles(market, selection, line)
    assert words in text
    if "no tiene regla" not in text:
        assert "prórroga y los penaltis no cuentan" in text and "72 horas" in text


def _strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_what_the_tracking_and_parlay_v6_write() -> None:
    def writes(p: Path) -> set[tuple[str, str]]:
        return {(m.group(1).upper().split()[0], (m.group(2) or "").lower()) for s in _strings(p) for m in WRITE.finditer(s)}

    assert writes(SRC / "tracking" / "selections.py") == {("INSERT", "intel.selection_settlements")}
    assert writes(SRC / "tracking" / "parlay_v6_shadow.py") == {("INSERT", "intel.parlays_v6"), ("INSERT", "intel.parlay_v6_legs")}
    assert writes(SRC / "tracking" / "parlay_v6.py") == set()


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_only_the_shadow_doors_import_the_tracking_and_parlay_v6() -> None:
    found: dict[str, set[str]] = {"fbi.tracking.selections": set(), "fbi.tracking.parlay_v6": set(), "fbi.tracking.parlay_v6_shadow": set()}
    for root in (SRC, ROOT / "apps", ROOT / "scripts"):
        for p in root.rglob("*.py"):
            names = _imports(p)
            for mod in found:
                if mod in names:
                    found[mod].add(p.relative_to(ROOT).as_posix())
    assert found["fbi.tracking.selections"] == {"src/fbi/shadowjobs/selection_settle.py", "scripts/ia_parlays_v6.py"}
    assert found["fbi.tracking.parlay_v6_shadow"] == {"src/fbi/shadowjobs/selection_settle.py", "scripts/ia_parlays_v6.py"}
    assert found["fbi.tracking.parlay_v6"] == {"src/fbi/tracking/parlay_v6_shadow.py", "scripts/ia_parlays_v6.py"}
    for serving in ("persist.py", "builder.py", "engine.py"):
        assert not [n for n in _imports(SRC / "parlays" / serving) if n.startswith(("fbi.tracking.parlay_v6", "fbi.tracking.selections"))]
