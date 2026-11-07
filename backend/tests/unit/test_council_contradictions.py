"""``council-contra-v1`` without a database: each kind of contradiction, its materiality, and the check "did the model already know?"."""

from __future__ import annotations

import itertools
from decimal import Decimal

from fbi.ai.contracts.base import FAMILIES, SIGNAL_CODES
from fbi.council import contradictions as c

D = Decimal


def pos(agent: str = "match", stance: str = "SUPPORT", *, drivers: tuple[str, ...] = ("ABSENCES",), weight: str = "1", candidate: str = "c1",
        run_id: int | None = None, refs: tuple[str, ...] = ("E:7",)) -> c.Position:
    version = {"match": "match-v2", "stats": "stats-v2"}.get(agent, f"{agent}-v1")
    return c.Position(agent, version, f"{agent}_evaluation", candidate, stance, drivers, (), refs,
                      run_id if run_id is not None else (11 if agent == "match" else 12), D(weight))


def sel(*, edge: str | None = "0.05", family: str = "1X2", key: str = "c1", contra: tuple[str, ...] = ()) -> c.Selection:
    if edge is None:  # nothing to read an edge from
        return c.Selection(key, family, family, "Home", D(0), None, None, None, D("0.08"), contra)
    return c.Selection(key, family, family, "Home", D(0), D("0.55"), D("0.50"), D(edge), D("0.08"), contra)


FLAT = c.Market("ok", 0.4, stale=False)
FELL = c.Market("ok", -4.0, stale=False)
ROSE = c.Market("ok", 4.0, stale=False)


def codes(found: tuple[c.Finding, ...]) -> list[str]:
    return [f.code for f in found]


def test_the_table_of_what_the_model_knows_covers_every_family_with_closed_codes() -> None:
    assert set(c.MODEL_KNOWS) == set(FAMILIES)
    assert all(v <= set(SIGNAL_CODES) for v in c.MODEL_KNOWS.values())
    for family in FAMILIES:
        assert not c.MODEL_KNOWS[family] & {"ABSENCES", "LINEUP", "NEWS", "STAKES"}, "no feature of the models reads who plays or the news"
    assert set(c.KIND_OF) == set(c.CODES) and set(c.KIND_OF.values()) == set(c.KINDS)


def test_agent_against_agent_on_the_same_selection() -> None:
    found = c.detect(sel(), [pos("match", "SUPPORT"), pos("stats", "REJECT_SIGNAL")], FLAT)
    aa = [f for f in found if f.code == "AA1"]
    assert len(aa) == 1 and aa[0].kind == "agent_vs_agent" and aa[0].material
    assert aa[0].run_ids == (11, 12) and aa[0].agents == ("match@match-v2", "stats@stats-v2") and aa[0].refs == ("E:7",)
    assert dict(aa[0].detail)["against_stance"] == "REJECT_SIGNAL"


def test_a_voice_that_weighs_nothing_makes_no_contradiction_material() -> None:
    found = c.detect(sel(), [pos("match", "SUPPORT"), pos("stats", "CONCERN", weight="0")], FLAT)
    aa = next(f for f in found if f.code == "AA1")
    assert not aa.material, "the objector is not promoted"
    am = next(f for f in found if f.code == "AM1")
    assert not am.material


def test_no_agent_against_agent_without_two_agents_or_two_sides() -> None:
    assert "AA1" not in codes(c.detect(sel(), [pos("match", "SUPPORT"), pos("stats", "SUPPORT")], FLAT))
    assert "AA1" not in codes(c.detect(sel(), [pos("match", "SUPPORT"), pos("stats", "NEUTRAL")], FLAT))
    assert "AA1" not in codes(c.detect(sel(), [pos("match", "SUPPORT"), pos("match", "CONCERN", run_id=13)], FLAT)), "one agent is one voice"


def test_agent_against_model() -> None:
    against = c.detect(sel(edge="0.05"), [pos("match", "CONCERN")], FLAT)
    assert codes(against) == ["AM1"] and against[0].material and dict(against[0].detail)["edge"] == "0.05"
    support = c.detect(sel(edge="-0.01"), [pos("match", "SUPPORT")], FLAT)
    assert codes(support) == ["AM2"]
    assert codes(c.detect(sel(edge="0.05"), [pos("match", "SUPPORT")], FLAT)) == [], "a support of a selection the model likes agrees"
    assert codes(c.detect(sel(edge=None), [pos("match", "CONCERN")], FLAT)) == [], "no edge: not evaluated"
    derived = c.Selection("c1", "1X2", "1X2", "Home", D(0), D("0.40"), D("0.45"))
    assert codes(c.detect(derived, [pos("match", "SUPPORT")], FLAT)) == ["AM2"], "the edge is p_model - p_market when not stored"


def test_agent_against_market() -> None:
    assert codes(c.detect(sel(), [pos("match", "SUPPORT")], FELL)) == ["AK1"]
    assert codes(c.detect(sel(), [pos("match", "CONCERN")], ROSE)) == ["AK2", "AM1"]
    steam = c.Market("ok", -1.0, steam_down=True, stale=False)
    assert codes(c.detect(sel(), [pos("match", "SUPPORT")], steam)) == ["AK1"], "a steam move counts even if the net movement is small"
    assert codes(c.detect(sel(), [pos("match", "SUPPORT")], c.Market("ok", -2.9, stale=False))) == [], "under three points is not a move"
    stale = c.detect(sel(), [pos("match", "SUPPORT")], c.Market("ok", -4.0, stale=True))
    assert codes(stale) == ["AK1"] and not stale[0].material, "a stale price cannot make it material"
    assert codes(c.detect(sel(), [pos("match", "SUPPORT")], c.Market.unknown())) == []


def test_the_model_already_knew() -> None:
    found = c.detect(sel(), [pos("match", "CONCERN", drivers=("FORM", "VENUE"))], FLAT)
    assert codes(found) == ["AM1", "KN1"]
    am = next(f for f in found if f.code == "AM1")
    assert not am.material, "the model already read form and venue: the disagreement is about weighing, not news"
    kn = next(f for f in found if f.code == "KN1")
    assert kn.kind == "already_known" and not kn.material
    absence = c.detect(sel(), [pos("match", "CONCERN", drivers=("ABSENCES",))], FLAT)
    assert codes(absence) == ["AM1"] and absence[0].material, "an absence is not in the features: it is new information"


def test_novelty_is_the_share_of_drivers_the_model_does_not_read() -> None:
    assert c.novelty(pos(drivers=("FORM", "ABSENCES")), "1X2") == D("0.5")
    assert c.novelty(pos(drivers=("FORM",)), "1X2") == 0
    assert c.novelty(pos(drivers=()), "1X2") == 1
    assert c.novelty(pos(drivers=("REFEREE",)), "CARDS") == 0 and c.novelty(pos(drivers=("REFEREE",)), "1X2") == 1
    assert c.novelty(pos(drivers=("RATE",)), "CORNERS") == 0


def test_the_market_already_knew() -> None:
    found = c.detect(sel(), [pos("match", "SUPPORT")], ROSE)
    assert codes(found) == ["KN2"] and not found[0].material
    assert codes(c.detect(sel(), [pos("match", "CONCERN")], FELL)) == ["AM1", "KN2"]


def test_a_neutral_stance_fires_nothing_and_another_candidate_is_not_read() -> None:
    assert c.detect(sel(), [pos("match", "NEUTRAL"), pos("stats", "NEUTRAL")], FELL) == ()
    assert c.detect(sel(key="c2"), [pos("match", "CONCERN")], FLAT) == ()


def test_the_output_is_the_same_whatever_order_the_positions_come_in() -> None:
    ps = [pos("match", "SUPPORT"), pos("stats", "REJECT_SIGNAL", drivers=("RATE", "FORM")), pos("council", "CONCERN", run_id=99)]
    outs = {c.detect(sel(), list(p), FELL) for p in itertools.permutations(ps)}
    assert len(outs) == 1
