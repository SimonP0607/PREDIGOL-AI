"""AD-H01 (IA-071): which external id goes to which of our entities (``entid-v1``), and the homonyms a person looks at."""

from __future__ import annotations

import random
from datetime import date

from fbi.people.identity.reep import Alias, Bridge, ExternalRef, ReepData
from fbi.people.identity.rules import Ours, plan_homonyms, plan_links

TODAY = date(2026, 11, 16)


def _data() -> ReepData:
    d = ReepData()
    d.bridges[("player", 306)] = [Bridge("rp_salah", "player", 1.0, "v4.reverified.canonical_bridge")]
    d.names["rp_salah"] = "Mohamed Salah"
    d.externals["rp_salah"] = [ExternalRef("wikidata", "", "Q1354960", 0.85, "transfermarkt:P2446|dob-agrees"),
                               ExternalRef("transfermarkt", "spieler", "148455", 1.0)]
    d.aliases["rp_salah"] = [Alias("M. Salah", "initial_name", "reep", None, None),
                             Alias("Mohamed Salah", "label", "wikidata", "en", 0.8),
                             Alias("Mohamed Salah", "label", "wikidata", "es", 0.8),
                             Alias("محمد صلاح", "label", "wikidata", "ar", 0.8)]
    d.bridges[("team", 33)] = [Bridge("rt_mun", "team", 1.0, "r")]
    d.names["rt_mun"] = "Manchester United FC"
    return d


def _salah(eid: int = 1, pid: int = 306, names: tuple[str, ...] = ("M. Salah", "Mohamed Salah Hamed Ghaly"),
           birth: date | None = date(1992, 6, 15)) -> Ours:
    return Ours("player", eid, pid, names, birth, "Mohamed")


def test_an_exact_bridge_gives_reep_wikidata_and_transfermarkt() -> None:
    plan = plan_links([_salah(), Ours("team", 9, 33, ("Manchester United",))], _data(), as_of=TODAY)
    rows = {(r.entity_id, r.system, r.namespace, r.external_id): r for r in plan.ids}
    assert set(rows) == {(1, "reep", "", "rp_salah"), (1, "wikidata", "", "Q1354960"),
                         (1, "transfermarkt", "spieler", "148455"), (9, "reep", "", "rt_mun")}
    assert all(r.review == "accepted" for r in plan.ids)
    assert rows[(1, "wikidata", "", "Q1354960")].confidence == 0.85
    assert rows[(1, "reep", "", "rp_salah")].method == "exact_bridge"
    assert rows[(1, "wikidata", "", "Q1354960")].method == "bridge_chain"
    assert not plan.queue


def test_aliases_merge_languages_and_tell_a_transliteration() -> None:
    plan = plan_links([_salah()], _data(), as_of=TODAY)
    by = {(a.alias, a.alias_type, a.source): a for a in plan.aliases}
    assert by[("Mohamed Salah", "localized", "wikidata")].languages == ("en", "es")
    assert by[("محمد صلاح", "transliteration", "wikidata")].script == "arabic"
    assert ("M. Salah", "short", "reep") in by
    assert ("Mohamed Salah", "full", "reep") in by, "the canonical name"
    assert all(a.via_external == "rp_salah" for a in plan.aliases)


def test_m_salah_one_api_id_two_reep_entities_links_nothing() -> None:
    d = _data()
    d.bridges[("player", 306)].append(Bridge("rp_salah_1983", "player", 1.0, "r"))
    plan = plan_links([_salah()], d, as_of=TODAY)
    assert plan.ids == []
    assert [q.kind for q in plan.queue] == ["bridge_conflict"]
    assert plan.queue[0].evidence["reep_ids"] == ["rp_salah", "rp_salah_1983"]


def test_two_of_our_players_on_one_reep_entity_get_it_neither() -> None:
    d = _data()
    d.bridges[("player", 9306)] = [Bridge("rp_salah", "player", 1.0, "r")]
    plan = plan_links([_salah(1), _salah(2, 9306)], d, as_of=TODAY)
    assert {r.review for r in plan.ids} == {"pending"}
    assert {r.entity_id for r in plan.ids} == {1, 2}
    pairs = [q for q in plan.queue if q.kind == "shared_external"]
    assert len(pairs) == 1, "one question per pair, whatever external raised it"
    assert (pairs[0].entity_a, pairs[0].entity_b, pairs[0].system) == (1, 2, "reep")


def test_a_name_that_contradicts_the_id_waits_for_a_person() -> None:
    plan = plan_links([_salah(names=("M. Elneny", "Mohamed Elneny"))], _data(), as_of=TODAY)
    assert {r.review for r in plan.ids} == {"pending"}
    assert [q.kind for q in plan.queue] == ["name_mismatch"]


def test_a_minor_is_not_linked() -> None:
    plan = plan_links([_salah(birth=date(2010, 1, 1))], _data(), as_of=TODAY)
    assert plan.ids == [] and plan.queue == [] and plan.aliases == []
    assert plan.stats["player:withheld_minor"] == 1


def test_a_name_alone_never_links() -> None:
    """Same name as the Reep entity, but no bridge from our id: nothing."""
    plan = plan_links([_salah(eid=5, pid=99999, names=("Mohamed Salah",))], _data(), as_of=TODAY)
    assert plan.ids == [] and plan.stats["player:unbridged"] == 1


def test_same_release_same_rows_whatever_the_order() -> None:
    entities = [_salah(i, 306 if i == 1 else 1000 + i, (f"P. Player{i}",), None) for i in range(1, 60)]
    a = plan_links(entities, _data(), as_of=TODAY)
    random.Random(7).shuffle(entities)
    b = plan_links(entities, _data(), as_of=TODAY)
    assert [r.row_key for r in a.ids] == [r.row_key for r in b.ids]
    assert [x.row_key for x in a.aliases] == [x.row_key for x in b.aliases]
    assert [q.item_key for q in a.queue] == [q.item_key for q in b.queue]


def _p(eid: int, name: str, birth: date | None, first: str | None = None) -> Ours:
    return Ours("player", eid, eid, (name,), birth, first)


def test_twins_are_not_queued() -> None:
    queue, stats = plan_homonyms([_p(1, "A. Smith", date(2000, 3, 1), "Alan"), _p(2, "A. Smith", date(2000, 3, 1), "Andrew")])
    assert queue == [] and stats["twins_or_siblings_skipped"] == 1


def test_father_and_son_are_two_people() -> None:
    queue, stats = plan_homonyms([_p(1, "Paolo Maldini", date(1968, 6, 26)), _p(2, "Paolo Maldini", date(1997, 4, 1))])
    assert queue == []
    assert stats["names_repeated"] == 1


def test_same_name_and_birth_date_is_a_possible_duplicate() -> None:
    queue, _ = plan_homonyms([_p(7, "M. Salah", date(1992, 6, 15), "Mohamed"), _p(3, "M. Salah", date(1992, 6, 15))])
    assert [(q.kind, q.entity_a, q.entity_b) for q in queue] == [("possible_duplicate", 3, 7)]


def test_a_birth_date_1_to_5_days_apart_goes_to_the_queue() -> None:
    for days, kind in ((1, "near_birth_date"), (5, "near_birth_date"), (6, None)):
        queue, _ = plan_homonyms([_p(1, "Lucas Veríssimo", date(1995, 7, 2)),
                                  _p(2, "Lucas Verissimo", date(1995, 7, 2 + days))])
        assert [q.kind for q in queue] == ([kind] if kind else [])


def test_without_a_birth_date_nothing_is_queued() -> None:
    queue, stats = plan_homonyms([_p(1, "Paulinho", None), _p(2, "Paulinho", None), _p(3, "Paulinho", date(1990, 1, 1))])
    assert queue == [] and stats["players_without_birth_date"] == 2
