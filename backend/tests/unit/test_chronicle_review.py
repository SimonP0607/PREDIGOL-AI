"""The review of a chronicle after the match (IA-022, ``fbi.chronicle.review``): the judgement of each reference, with no database."""

from __future__ import annotations

from typing import Any

from fbi.api.services.story import Fact
from fbi.chronicle import review as rv


def squad(*, lineups: list[tuple[str, int, str, bool]] | None = None, minutes: list[tuple[str, int, str, int | None]] | None = None) -> rv.Squad:
    return rv.squad_of(
        [{"team_side": s, "provider_player_id": i, "player_name": n, "is_starter": st} for s, i, n, st in lineups or []],
        [{"team_side": s, "provider_player_id": i, "player_name": n, "minutes": m} for s, i, n, m in minutes or []])


def absence(ref: str, player: str, status: str = "out", side: str = "home") -> dict[str, Fact]:
    return {ref: Fact(ref, side, "absence", {"side": side, "team": "X", "player": player, "status": status, "reason": None,
                                              "kind": "injury", "key": True})}


def check(ref: str, facts: dict[str, Fact], s: rv.Squad, evidence: dict[int, dict[str, Any]] | None = None) -> rv.Check:
    return rv.checks_of([ref], absences=facts, evidence=evidence or {}, squad=s, home=1, away=2)[0]


FULL = squad(lineups=[("home", 10, "Lisandro Martínez", True), ("home", 11, "Bruno Fernandes", True), ("home", 12, "Tom Heaton", False)],
             minutes=[("home", 10, "Lisandro Martínez", 90), ("home", 11, "Bruno Fernandes", 90), ("home", 12, "Tom Heaton", None)])


def test_a_player_the_chronicle_said_was_out_and_played_contradicts_it() -> None:
    c = check("P:absences.home.1", absence("P:absences.home.1", "Lisandro Martínez"), FULL)
    assert (c.verdict, c.code, c.detail) == (rv.CONTRADICTED, "absence", "played")


def test_a_player_said_to_be_out_who_did_not_play_held() -> None:
    c = check("P:absences.home.1", absence("P:absences.home.1", "Tom Heaton"), FULL)
    assert c.verdict == rv.HELD


def test_names_are_compared_without_accents_case_or_punctuation() -> None:
    c = check("P:absences.home.1", absence("P:absences.home.1", "LISANDRO  MARTINEZ."), FULL)
    assert c.verdict == rv.CONTRADICTED
    assert rv.fold("Vinícius Júnior") == "vinicius junior"


def test_a_player_in_doubt_is_told_by_whether_he_played() -> None:
    assert check("P:absences.home.1", absence("P:absences.home.1", "Bruno Fernandes", "doubtful"), FULL).verdict == rv.PLAYED
    assert check("P:absences.home.1", absence("P:absences.home.1", "Tom Heaton", "doubtful"), FULL).verdict == rv.DID_NOT_PLAY


def test_the_side_matters_a_namesake_of_the_other_side_is_not_him() -> None:
    s = squad(lineups=[("away", 30, "Lisandro Martínez", True)], minutes=[("away", 30, "Lisandro Martínez", 90)])
    c = check("P:absences.home.1", absence("P:absences.home.1", "Lisandro Martínez"), s)
    assert c.verdict == rv.HELD, "nobody of the home side has the name, nobody resembles it: he took no part"


def test_a_name_nobody_has_in_full_but_somebody_resembles_is_not_checkable_never_a_hit() -> None:
    s = squad(lineups=[("home", 10, "L. Martínez", True)], minutes=[("home", 10, "L. Martínez", 90)])
    c = check("P:absences.home.1", absence("P:absences.home.1", "Lisandro Martínez"), s)
    assert c.verdict == rv.NOT_CHECKABLE and "similar" in (c.detail or "")


def test_without_line_ups_and_minutes_everything_waits() -> None:
    empty = squad()
    assert not empty.ready
    assert check("P:absences.home.1", absence("P:absences.home.1", "Tom Heaton"), empty).verdict == rv.PENDING


def test_with_only_the_line_ups_a_starter_played_and_a_name_absent_from_them_is_not_proof() -> None:
    s = squad(lineups=[("home", 10, "Lisandro Martínez", True), ("home", 12, "Tom Heaton", False)])
    assert check("P:absences.home.1", absence("P:absences.home.1", "Lisandro Martínez"), s).verdict == rv.CONTRADICTED
    assert check("P:absences.home.1", absence("P:absences.home.1", "Tom Heaton"), s).verdict == rv.NOT_CHECKABLE, "a bench player's minutes are unknown"
    assert check("P:absences.home.1", absence("P:absences.home.1", "Nadie Conocido"), s).verdict == rv.NOT_CHECKABLE, "the minutes are missing"


def test_an_absence_the_packet_does_not_have_is_not_checkable() -> None:
    assert check("P:absences.home.3", {}, FULL).verdict == rv.NOT_CHECKABLE


def test_a_news_item_about_a_player_is_judged_by_his_provider_id() -> None:
    news = {5: {"id": 5, "kind": "injury", "status": "CONFIRMED", "provider_player_id": 10, "player_name": "Lisandro Martínez"},
            6: {"id": 6, "kind": "doubtful", "status": "PROBABLE", "provider_player_id": 12, "player_name": "Tom Heaton"},
            7: {"id": 7, "kind": "news", "status": "RUMOR", "provider_player_id": None, "player_name": None},
            8: {"id": 8, "kind": "injury", "status": "CONFIRMED", "provider_player_id": 99, "player_name": "Ausente"}}
    assert check("E:5", {}, FULL, news).verdict == rv.CONTRADICTED
    assert check("E:6", {}, FULL, news).verdict == rv.DID_NOT_PLAY
    assert check("E:7", {}, FULL, news).verdict == rv.NOT_EVALUABLE
    assert check("E:8", {}, FULL, news).verdict == rv.HELD, "in neither list, with both the line-ups and the minutes"
    assert check("E:404", {}, FULL, news).verdict == rv.NOT_CHECKABLE


def test_history_and_context_are_not_evaluable_and_never_a_hit() -> None:
    for ref in ("P:form.home", "P:results.home.1", "P:h2h", "P:stakes.away", "P:dossier.players.home"):
        c = check(ref, {}, FULL)
        assert (c.verdict, c.code) == (rv.NOT_EVALUABLE, "context"), ref


def test_a_sentence_takes_the_first_verdict_of_its_references_in_the_order_of_the_list() -> None:
    mixed = [rv.Check("a", "x", rv.NOT_EVALUABLE), rv.Check("b", "x", rv.HELD), rv.Check("c", "x", rv.CONTRADICTED)]
    assert rv.verdict_of(mixed) == rv.CONTRADICTED
    assert rv.verdict_of(mixed[:2]) == rv.HELD
    assert rv.verdict_of([rv.Check("a", "x", rv.PENDING), rv.Check("b", "x", rv.NOT_EVALUABLE)]) == rv.PENDING
    assert rv.verdict_of([]) == rv.NOT_EVALUABLE


def test_the_items_follow_the_spanish_chronicle_and_the_summary_counts_what_could_be_checked() -> None:
    content = {"es": [{"key": "home", "sentences": [
                   {"text": "Viene de ganar 2-1.", "refs": ["P:results.home.1"]},
                   {"text": "Lisandro Martínez es baja.", "refs": ["P:absences.home.1"]},
                   {"text": "Tom Heaton es baja.", "refs": ["P:absences.home.2"]}]}],
               "en": [{"key": "home", "sentences": []}]}
    facts = absence("P:absences.home.1", "Lisandro Martínez") | absence("P:absences.home.2", "Tom Heaton")
    items = rv.review_items(content, absences=facts, evidence={}, squad=FULL, home=1, away=2)
    assert [(i["section"], i["index"], i["verdict"]) for i in items] == [
        ("home", 0, rv.NOT_EVALUABLE), ("home", 1, rv.CONTRADICTED), ("home", 2, rv.HELD)]
    summary = rv.summarise(items)
    assert (summary["sentences"], summary["firm_claims"], summary["held"], summary["contradicted"]) == (3, 2, 1, 1)
    assert summary["by_sentence"] == {rv.NOT_EVALUABLE: 1, rv.CONTRADICTED: 1, rv.HELD: 1}
    assert "did not cause the result" in summary["note"], "the review says it states no cause"


def test_the_news_ids_of_a_chronicle_are_read_from_its_references_only() -> None:
    content = {"es": [{"key": "risks", "sentences": [{"text": "x", "refs": ["E:12", "P:form.home", "E:7", "E:12", "E:x"]}]}]}
    assert rv.news_ids(content) == [7, 12]
