"""IA-126 (AD-C08): ``credibility-v2`` learns per type of fact with its interval, strictly as of, and never changes a state on its own."""

from __future__ import annotations

import ast
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fbi.ai import intervals
from fbi.evidence import credibility as cred
from fbi.evidence import rules
from fbi.evidence.engine import Item
from fbi.research import protocol
from fbi.shadowjobs import source_credibility as job

BACKEND = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
TEAM = 7


def item(eid: int, *, outlet: str = "diario.example", tier: rules.Tier = "C", kind: str = "injury", assertion: str = "out",
         player: int = 100, fixture: int | None = 1, when: datetime = T0) -> Item:
    return Item(eid, "v1", fixture, TEAM, player, "", kind, rules.topic_of(kind), assertion, "web", outlet, outlet, tier, "test", when, when)


def sheet(starters: set[int], bench: set[int] = frozenset()) -> rules.SquadSheet:  # type: ignore[assignment]
    return rules.SquadSheet(TEAM, T0 + timedelta(days=1), frozenset(starters), frozenset(bench))


def test_the_type_of_a_fact_and_a_doubt_is_not_judged() -> None:
    assert cred.fact_type(item(1, kind="injury", assertion="out")) == "baja"
    assert cred.fact_type(item(1, kind="suspension", assertion="out")) == "sancion"
    assert cred.fact_type(item(1, kind="lineup", assertion="starts")) == "titularidad"
    assert cred.fact_type(item(1, kind="injury", assertion="available")) == "disponible"
    assert cred.fact_type(item(1, kind="doubtful", assertion="doubtful")) is None
    assert cred.fact_type(item(1, kind="coach", assertion="info")) is None


def test_a_source_right_about_line_ups_and_wrong_about_injuries_is_two_numbers_not_their_average() -> None:
    history: list[Item] = []
    sheets: dict[tuple[int, int], rules.SquadSheet] = {}
    for i in range(40):  # line-ups: always right; injuries: always wrong (said out, he played)
        fx = 1000 + i
        sheets[(fx, TEAM)] = sheet({100 + i, 200 + i})
        history.append(item(2 * i, kind="lineup", assertion="starts", player=100 + i, fixture=fx))
        history.append(item(2 * i + 1, kind="injury", assertion="out", player=200 + i, fixture=fx))
    learned = cred.learn_v2(history, history, exclude_fixture=None, team_fixtures={}, sheets=sheets, listings={})
    line = learned[("diario.example", "C", "titularidad")]
    out = learned[("diario.example", "C", "baja")]
    assert (line.corroborated, line.resolved, out.corroborated, out.resolved) == (40, 40, 0, 40)
    assert line.value > 0.85 and out.value < 0.2 and line.sufficient and out.sufficient
    assert line.ci95 is not None and line.ci95[0] > 0.9 and out.ci95 is not None and out.ci95[1] < 0.1
    v1 = rules.credibility("C", 40, 80)
    assert out.value < v1.value < line.value, "v1 averaged both types"


def test_a_claim_never_vouches_for_its_source_in_its_own_match() -> None:
    history = [item(1, fixture=5, player=100), item(2, fixture=6, player=101)]
    sheets = {(5, TEAM): sheet({1}), (6, TEAM): sheet({1})}
    judged = cred.judge(history, history, exclude_fixture=5, team_fixtures={}, sheets=sheets, listings={})
    assert [j.evidence_id for j in judged] == [2]


def test_what_nothing_can_check_is_not_counted_and_below_the_minimum_is_insufficient() -> None:
    history = [item(i, fixture=10 + i, player=100 + i) for i in range(5)]
    sheets = {(10, TEAM): sheet({1}), (11, TEAM): sheet({101})}  # 10: corroborated (not in the sheet), 11: refuted, 12-14: nothing to check
    learned = cred.learn_v2(history, history, exclude_fixture=None, team_fixtures={}, sheets=sheets, listings={})
    c = learned[("diario.example", "C", "baja")]
    assert (c.corroborated, c.resolved, c.sufficient, c.word) == (1, 2, False, "insuficiente")
    shown = c.as_json()
    assert shown["ci95"] is not None and shown["decides"] is False and shown["min_resolved"] == cred.MIN_RESOLVED


def test_with_nothing_resolved_the_value_is_the_tier_prior() -> None:
    c = cred.typed("x", "B", "baja", 0, 0)
    assert (c.value, c.basis, c.ci95, c.sufficient) == (rules.TIER_PRIOR["B"], "prior", None, False)


@pytest.mark.parametrize("n", [30, 200])
@pytest.mark.parametrize("p", [0.3, 0.6, 0.9])
def test_the_interval_covers_as_the_protocol_registers(p: float, n: int) -> None:
    """The simulation the protocol AD-C08 registers: 2.000 repetitions with its seed; the Wilson interval covers at least 90 % in each cell."""
    rng = random.Random(protocol.require("AD-C08").seed)
    covered = 0
    for _ in range(2000):
        k = sum(1 for _ in range(n) if rng.random() < p)
        lo, hi = intervals.wilson(k, n) or (0.0, 1.0)
        covered += int(lo <= p <= hi)
    assert covered / 2000 >= 0.90


def test_property_no_status_changes_because_of_the_credibility() -> None:
    """ladder-v1's status reads tiers only; the credibility only moves the confidence, inside the cap of that status."""
    rng = random.Random(126)
    for _ in range(400):
        n = rng.randint(1, 6)
        items = [rules.Support(i, f"o{rng.randint(0, 4)}", rng.choice(rules.TIERS), rng.random(), T0 - timedelta(hours=rng.randint(0, 40)))
                 for i in range(n)]
        other = [rules.Support(s.evidence_id, s.outlet, s.tier, rng.random(), s.when) for s in items]
        a, b = rules.decide("injury", items, at=T0), rules.decide("injury", other, at=T0)
        assert (a.status, a.rule) == (b.status, b.rule)
        assert a.confidence <= rules.STATUS_CAP[a.status] and b.confidence <= rules.STATUS_CAP[b.status]


def test_the_replay_lists_the_doubts_v1_judged_and_the_types_apart() -> None:
    history = [item(1, kind="doubtful", assertion="doubtful", tier="C", fixture=None, when=T0),
               item(2, kind="doubtful", assertion="doubtful", tier="B", outlet="nacional.example", fixture=None, when=T0)]
    for i in range(12):
        fx = 300 + i
        history.append(item(10 + i, kind="lineup", assertion="starts", player=400 + i, fixture=fx))
    sheets = {(300 + i, TEAM): sheet({400 + i}) for i in range(12)}
    rep = cred.replay(history, history, team_fixtures={}, sheets=sheets, listings={})
    assert rep["by_reason"].get("doubts_not_judged") == 1, rep
    assert rep["decides"] is False and rep["against"] == "credibility-v1"


def test_nothing_of_credibility_v2_writes_a_tier_or_a_domain() -> None:
    for rel in ("src/fbi/evidence/credibility.py", "src/fbi/evidence/credibility_reads.py", "src/fbi/shadowjobs/source_credibility.py",
                "scripts/ia_credibility.py"):
        text = (BACKEND / rel).read_text(encoding="utf-8").lower()
        for forbidden in ("into ai.sources", "update ai.sources", "ai.source_registry", "ai.source_signoffs", "update ai.evidence"):
            assert forbidden not in text, (rel, forbidden)


def test_nothing_that_decides_reads_the_credibility_table() -> None:
    readers = sorted(str(p.relative_to(BACKEND)) for p in [*(BACKEND / "src").rglob("*.py"), *(BACKEND / "scripts").glob("*.py")]
                     if "ai.source_credibility" in p.read_text(encoding="utf-8"))
    assert readers == ["scripts/ia_credibility.py", "src/fbi/research/protocol.py", "src/fbi/shadowjobs/source_credibility.py"], \
        "the protocol names it in words; the job writes it; the command reads it"


def test_the_shadow_job_is_off_by_default_and_its_rows_fit_the_table() -> None:
    assert job.mode({}) == "off" and job.mode({"FBI_SOURCE_CREDIBILITY": "on"}) == "off"
    assert job.mode({"FBI_SOURCE_CREDIBILITY": "shadow"}) == "shadow"
    assert job.every_hours({}) == 24 and job.every_hours({"FBI_SOURCE_CREDIBILITY_HOURS": "2"}) == 24
    snap = {"digest": cred.digest(), "at": T0.isoformat(), "typed": False,
            "credibilities": [cred.typed("a", "C", "baja", 0, 0).as_json(), cred.typed("a", "C", "titularidad", 29, 31).as_json()]}
    rows = job.rows_of(snap, code_version=None)
    for r in rows:
        assert (r["basis"] == "prior") == (r["resolved"] == 0)
        assert r["sufficient"] == (r["resolved"] >= r["min_resolved"])
        assert (r["rate"] is None) == (r["ci_low"] is None) == (r["resolved"] == 0)
    assert len(cred.digest()) == 12


def test_the_code_keeps_the_minimum_the_protocol_registered() -> None:
    p = protocol.require("AD-C08")
    assert f"al menos {cred.MIN_RESOLVED} afirmaciones resueltas" in p.pass_rule and str(cred.MIN_RESOLVED) in p.min_sample
    assert set(cred.FACT_TYPES) == {"baja", "sancion", "titularidad", "disponible"}


def test_the_engine_still_reads_credibility_v1() -> None:
    tree = ast.parse((BACKEND / "src/fbi/evidence/engine.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module for a in n.names}
    assert "credibility" not in imported and rules.CREDIBILITY_VERSION == "credibility-v1"
