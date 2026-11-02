"""The material change of a match (Plan Maestro IA, section 19): what pays for a brief again, and what does not.

A price that moves 2 % reuses the brief and one that moves 4 % rebuilds it; so does a line-up, an absence, a piece of evidence, a
change of kick-off, of scenario or of candidates. A model figure, a statistic or a data-quality score that the brief does not read as
context does not. No database, no model, no network."""

from __future__ import annotations

import json
from typing import Any

from fbi.ai.material import MATERIAL_VERSION, PRICE_MOVE, Material, compare, material_of, moved
from fbi.ai.packet import Packet

from .test_ai_decisions import KO, packet


def cards(**over: Any) -> list[dict[str, Any]]:
    base: dict[str, Any] = {"market": "1X2", "selection": "Home", "line": "0", "kind": "value", "odds": "2.400",
                            "p_model": "0.5200", "p_market": "0.4500", "verdict": "recommended"}
    return [base | over]


def snapshot(p: Packet, c: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The material as the database keeps it: through JSON."""
    out: dict[str, Any] = json.loads(json.dumps(material_of(p, cards() if c is None else c).as_json()))
    return out


def change(before: Packet, after: Packet, *, c0: list[dict[str, Any]] | None = None,
           c1: list[dict[str, Any]] | None = None) -> Any:
    return compare(snapshot(before, c0), material_of(after, cards() if c1 is None else c1))


def odds(p: Packet, selection: str, value: float) -> Packet:
    for s in p.content["market"]["selections"]:
        if s["market"] == "1X2" and s["selection"] == selection:
            s["best_odds"] = value
    return p


def test_the_same_match_is_the_same_material_even_through_json() -> None:
    a, b = material_of(packet(), cards()), material_of(packet(), cards())
    assert a == b and a.hash == b.hash
    assert change(packet(), packet()).same
    assert snapshot(packet())["v"] == MATERIAL_VERSION


def test_a_price_that_moves_two_percent_reuses_the_brief_and_one_that_moves_four_percent_rebuilds_it() -> None:
    two = change(packet(), odds(packet(), "Home", 2.448))  # 2.4 -> 2.448: +2 %
    assert two.same and two.moved == () and two.parts == ()
    four = change(packet(), odds(packet(), "Home", 2.496))  # +4 %
    assert not four.same and four.parts == () and four.moved == (("odds|1X2|Home|0", "2.4", "2.496"),)
    assert four.why == "odds|1X2|Home|0:2.4>2.496"
    down = change(packet(), odds(packet(), "Home", 2.304))  # -4 %
    assert not down.same, "a price that falls moves as much as one that rises"


def test_exactly_three_percent_is_not_a_change_and_a_hair_more_is() -> None:
    assert PRICE_MOVE.as_integer_ratio() == (3, 100)
    assert not moved("2.00", "2.06")
    assert moved("2.00", "2.0601")
    assert not moved("2.00", "1.94")
    assert moved("2.00", "1.9399")
    assert not moved("0", "0") and moved("0", "0.01")


def test_the_candidates_price_and_probability_are_numbers_too() -> None:
    assert change(packet(), packet(), c1=cards(odds="2.448")).same, "the card's price +2 %"
    assert not change(packet(), packet(), c1=cards(odds="2.496")).same, "+4 %"
    assert not change(packet(), packet(), c1=cards(p_model="0.5400")).same, "the model's number for the candidate +3.8 %"
    assert change(packet(), packet(), c1=cards(p_model="0.5300")).same, "+1.9 %"


def test_the_fair_probability_of_the_market_is_a_number_too() -> None:
    after = packet()
    after.content["market"]["selections"][0]["p_fair"] = 0.47  # 0.45 -> 0.47: +4.4 %
    assert change(packet(), after).moved[0][0] == "fair|1X2|Home|0"
    quiet = packet()
    quiet.content["market"]["selections"][0]["p_fair"] = 0.455  # +1.1 %
    assert change(packet(), quiet).same


def test_drift_is_counted_against_what_the_brief_read_not_against_the_last_look() -> None:
    read = snapshot(packet())  # what the model read: 2.40
    for price in (2.42, 2.44, 2.46, 2.48):  # a cent or two at a time
        step = compare(read, material_of(odds(packet(), "Home", price), cards()))
        assert step.same is (price <= 2.472), price
    assert not compare(read, material_of(odds(packet(), "Home", 2.48), cards())).same


def test_a_lineup_that_appears_or_changes_is_a_change() -> None:
    confirmed = packet(lineups={"confirmed": True, "home": {"formation": "4-3-3", "coach": "A", "starters": [1, 2, 3]},
                                "away": {"formation": "4-4-2", "coach": "B", "starters": [4, 5, 6]}})
    assert change(packet(), confirmed).parts == ("lineups",)
    other = packet(lineups={"confirmed": True, "home": {"formation": "4-3-3", "coach": "A", "starters": [1, 2, 9]},
                            "away": {"formation": "4-4-2", "coach": "B", "starters": [4, 5, 6]}})
    assert change(confirmed, other).parts == ("lineups",)
    assert change(confirmed, confirmed).same
    reordered = packet(lineups={"confirmed": True, "home": {"formation": "4-3-3", "coach": "A", "starters": [3, 1, 2]},
                                "away": {"formation": "4-4-2", "coach": "B", "starters": [6, 5, 4]}})
    assert change(confirmed, reordered).same, "the same eleven in another order"


def test_a_new_coach_is_a_change_even_before_the_lineup() -> None:
    before = packet(dossier={"teams": {"home": {"coach": {"name": "Pérez"}}, "away": {"coach": {"name": "Gómez"}}}})
    after = packet(dossier={"teams": {"home": {"coach": {"name": "Ruiz"}}, "away": {"coach": {"name": "Gómez"}}}})
    assert change(before, after).parts == ("lineups",)
    elsewhere = packet(dossier={"teams": {"home": {"coach": {"name": "Pérez", "matches_seen": 9}},
                                          "away": {"coach": {"name": "Gómez"}}}})
    assert change(before, elsewhere).same, "his sample size is not a coach"


def test_an_injury_or_a_return_is_a_change_but_the_weights_around_it_are_not() -> None:
    out = {"player_id": 77, "name": "Delantero", "type": "Missing Fixture", "reason": "Knee", "key": True,
           "first_choice_gk": False, "weight": 0.31, "minutes_share": 0.8, "ga_share": 0.3}
    hurt = packet(absences={"checked": True, "home": {"players": [out], "weight": 0.31, "key_out": 1},
                            "away": {"players": [], "weight": 0, "key_out": 0}})
    assert change(packet(), hurt).parts == ("absences",)
    reweighted = packet(absences={"checked": True, "home": {"players": [out | {"weight": 0.29, "minutes_share": 0.7}],
                                                              "weight": 0.29, "key_out": 1},
                                  "away": {"players": [], "weight": 0, "key_out": 0}})
    assert change(hurt, reweighted).same, "the squad statistics moved a little: the same player is out for the same reason"
    doubtful = packet(absences={"checked": True, "home": {"players": [out | {"type": "Questionable"}], "weight": 0.31,
                                                           "key_out": 0},
                                "away": {"players": [], "weight": 0, "key_out": 0}})
    assert change(hurt, doubtful).parts == ("absences",), "out becomes doubtful"
    assert change(packet(absences={"checked": False}), packet()).parts == ("absences",), "the check was made"


def test_new_evidence_or_a_new_status_is_a_change() -> None:
    news = {"id": 31, "status": "PROBABLE", "origin": "web", "kind": "injury", "claim": "x"}
    assert change(packet(), packet(evidence=[news])).parts == ("evidence",)
    assert change(packet(evidence=[news]), packet(evidence=[news | {"status": "CONFIRMED"}])).parts == ("evidence",)
    assert change(packet(evidence=[news]), packet(evidence=[news | {"status": "CONTRADICTORY"}])).parts == ("evidence",)
    assert change(packet(evidence=[news]), packet(evidence=[news | {"claim": "reworded"}])).same


def test_a_new_kickoff_or_a_suspension_is_a_change() -> None:
    moved_ko = packet()
    moved_ko.content["fixture"]["kickoff_at"] = (KO.replace(hour=(KO.hour + 2) % 24)).isoformat()
    assert change(packet(), moved_ko).parts == ("schedule",)
    postponed = packet()
    postponed.content["fixture"]["status"] = "PST"
    assert change(packet(), postponed).parts == ("schedule",)
    noted = packet()
    noted.content["fixture"]["kickoff_changes"] = [{"observed_at": "2032-08-01T00:00:00+00:00", "before": None, "after": "x"}]
    assert change(packet(), noted).parts == ("schedule",)


def test_the_competitive_scenario_is_a_change() -> None:
    after = packet(stakes={"home": {"pressure": "title_race"}, "away": {"pressure": "mid_table"}})
    assert change(packet(), after).parts == ("scenario",)


def test_the_candidates_the_brief_writes_a_note_for_are_a_change() -> None:
    both = cards() + cards(market="OU", selection="Over", line="2.5", odds="1.900", p_model="0.5000")
    assert change(packet(), packet(), c0=cards(), c1=both).parts == ("cards", "priced")
    swapped = cards(selection="Away", odds="3.600", p_model="0.2300")
    assert "cards" in change(packet(), packet(), c0=cards(), c1=swapped).parts
    assert change(packet(), packet(), c0=cards(), c1=cards(verdict="caution")).same, "a verdict is not an input of the brief"
    assert change(packet(), packet(), c0=cards(line="0"), c1=cards(line="0.00")).same, "the same line written two ways"


def test_what_the_brief_does_not_read_as_context_does_not_rebuild_it() -> None:
    after = packet()
    after.content["models"]["dixon_coles"]["selections"][0]["p"] = 0.60  # not a candidate's number
    after.content["quality"] = {"competition_score": {"class": "MODEL_READY", "score": 0.5}, "lineups_confirmed": False}
    after.content["schedule"] = {"flags": ["home_short_rest"], "home": {"next_match": "x"}, "away": {"next_match": None}}
    after.content["form"] = {"home": {"n": 6}, "away": {"n": 6}}
    after.content["elo"] = {"home": 1500.0, "away": 1490.0}
    after.missing = ["h2h", "stats"]
    assert change(packet(), after).same


def test_a_block_that_arrives_late_is_a_change() -> None:
    before = packet()
    before.missing = ["lineups"]
    assert change(before, packet()).parts == ("missing",)
    no_market = packet(market={"observed": False, "selections": []})
    no_market.missing = ["market"]
    after = change(no_market, packet())
    assert "priced" in after.parts and "missing" in after.parts


def test_a_snapshot_of_another_version_or_unreadable_is_never_reused() -> None:
    now = material_of(packet(), cards())
    assert compare(None, now).parts == ("version",)
    assert compare({"v": "material-v0", "parts": {}, "numbers": {}}, now).parts == ("version",)
    assert compare({"v": MATERIAL_VERSION, "parts": "x", "numbers": {}}, now).parts == ("unreadable",)
    broken = snapshot(packet())
    broken["numbers"]["odds|1X2|Home|0"] = "not a number"
    assert compare(broken, now).parts == ("unreadable",)
    assert isinstance(now, Material)
