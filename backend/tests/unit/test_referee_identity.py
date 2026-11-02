"""Who is who among the spellings of referees (plan F3, ``refid-v1``): every rule, and what none of them may do."""

from __future__ import annotations

import itertools
import random
from typing import cast

from fbi.people import referee_identity as ri
from fbi.people.referee_identity import Form, resolve

_ids = itertools.count(1)
DAY = 1440


def games(slot: int, n: int) -> list[ri.Game]:
    """``n`` matches, one a day, at the minute-of-day ``slot * 300``. Two forms in different slots never kick off less than two
    hours apart; two in the SAME slot always do."""
    return [(day * DAY + slot * 300, next(_ids)) for day in range(n)]


def form(key: str, scope: str, n: int = 1, slot: int = 0, entity: int | None = None) -> Form:
    return Form(key, scope, games(slot, n), entity, seen=n)


def together(res: ri.Resolution, a: tuple[str, str], b: tuple[str, str]) -> bool:
    return res.group_of[a] == res.group_of[b]


def questions(res: ri.Resolution) -> set[tuple[tuple[str, str], tuple[str, str], str]]:
    """The open candidates as (form of group a, form of group b, reason)."""
    out = set()
    for c in res.candidates:
        pair = cast("list[list[str]]", c.evidence["forms"])
        out.add(((pair[0][0], pair[0][1]), (pair[1][0], pair[1][1]), c.reason))
    return out


# ── rule 1: one scope ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_name_and_the_same_name_with_a_middle_name_are_one_referee() -> None:
    res = resolve([form("danny makkelie", "netherlands", 30), form("danny desmond makkelie", "netherlands", 3, slot=1)])
    assert len(res.groups) == 1
    assert res.basis[("danny desmond makkelie", "netherlands")] == "identity"  # the longest anchors the group
    assert res.basis[("danny makkelie", "netherlands")] == "extension"
    assert res.groups[0].canonical == ("danny makkelie", "netherlands")  # called by the one with most matches
    assert not res.candidates and not res.vetoes


def test_a_chain_of_longer_names_collapses_whatever_the_order() -> None:
    forms = [form("danny makkelie", "netherlands", 5), form("danny desmond makkelie", "netherlands", 3, slot=1),
             form("danny desmond john makkelie", "netherlands", 1, slot=2)]
    assert len(resolve(forms).groups) == 1
    assert len(resolve(list(reversed(forms))).groups) == 1


def test_a_short_name_that_two_different_long_names_extend_is_left_for_a_person() -> None:
    res = resolve([form("danny makkelie", "netherlands", 10), form("danny desmond makkelie", "netherlands", 10, slot=1),
                   form("danny john makkelie", "netherlands", 10, slot=2)])
    assert len(res.groups) == 3
    assert {r for _, _, r in questions(res)} == {"longer_name"}
    assert len(res.candidates) == 2


def test_an_initial_joins_the_one_full_name_it_could_be() -> None:
    res = resolve([form("m oliver", "england", 40), form("michael oliver", "england", 8, slot=1), form("mark taylor", "england", 5, slot=2)])
    assert together(res, ("m oliver", "england"), ("michael oliver", "england"))
    assert not together(res, ("m oliver", "england"), ("mark taylor", "england"))
    assert res.basis[("m oliver", "england")] == "initial"
    assert not res.candidates


def test_an_initial_beside_two_full_names_is_not_decided() -> None:
    """'r gupta' fits 'rahul kumar gupta' and 'rajesh gupta': the data cannot say which."""
    res = resolve([form("r gupta", "india", 12), form("rahul kumar gupta", "india", 12, slot=1), form("rajesh gupta", "india", 12, slot=2)])
    assert len(res.groups) == 3
    assert {r for _, _, r in questions(res)} == {"initial_and_full"}
    assert len(res.candidates) == 2


def test_an_initial_beside_two_full_names_goes_to_the_one_that_dominates() -> None:
    res = resolve([form("s stockbridge", "england", 200), form("sebastian stockbridge", "england", 39, slot=1),
                   form("seb stockbridge", "england", 1, slot=2)])
    assert together(res, ("s stockbridge", "england"), ("sebastian stockbridge", "england"))
    assert not together(res, ("s stockbridge", "england"), ("seb stockbridge", "england"))
    # the stray is still a question, but a small one
    assert any(c.reason == "initial_and_full" for c in res.candidates)
    # ...and with two big ones nothing dominates
    res2 = resolve([form("s stockbridge", "england", 200), form("sebastian stockbridge", "england", 39, slot=1),
                    form("simon stockbridge", "england", 30, slot=2)])
    assert len(res2.groups) == 3


def test_two_people_who_referee_at_once_are_not_one_even_in_one_scope() -> None:
    res = resolve([form("m oliver", "england", 10), form("michael oliver", "england", 10)])  # same slot: same kick-offs
    assert len(res.groups) == 2
    assert len(res.vetoes) == 1 and res.vetoes[0].collisions > 0
    assert not res.candidates


# ── rule 2: the visitor and the spelling with no scope ───────────────────────────────────────────────────────────────


def test_a_referee_abroad_joins_his_home() -> None:
    res = resolve([form("d makkelie", "netherlands", 40), form("d makkelie", "saudi arabia", 3, slot=1),
                   form("d makkelie", "greece", 2, slot=2)])
    assert len(res.groups) == 1
    assert res.basis[("d makkelie", "saudi arabia")] == "foreign"
    assert res.basis[("d makkelie", "netherlands")] == "identity"


def test_a_name_in_a_small_place_is_nobodys_home() -> None:
    res = resolve([form("a kovacs", "hungary", 10), form("a kovacs", "romania", 1, slot=1)])
    assert len(res.groups) == 2  # a 'home' needs hub_min matches
    assert questions(res) == {(("a kovacs", "hungary"), ("a kovacs", "romania"), "same_name_other_scope")}


def test_a_visitor_with_too_many_matches_is_not_a_visitor() -> None:
    res = resolve([form("a kovacs", "hungary", 40), form("a kovacs", "romania", 10, slot=1)])  # 10 > 15 % of 40
    assert len(res.groups) == 2
    assert len(res.candidates) == 1


def test_where_two_homes_could_be_nothing_is_joined() -> None:
    res = resolve([form("j martinez", "spain", 60), form("j martinez", "mexico", 50, slot=1), form("j martinez", "saudi arabia", 2, slot=2)])
    assert len(res.groups) == 3
    assert len(res.candidates) == 3  # every pair is a question: the two homes and each of them with the visitor


def test_homonyms_who_referee_at_once_are_vetoed_and_never_suggested() -> None:
    res = resolve([form("j martinez", "spain", 60), form("j martinez", "mexico", 50)])  # same slot: they collide
    assert len(res.groups) == 2
    assert not res.candidates
    assert len(res.vetoes) == 1 and res.vetoes[0].collisions > 0


def test_a_visitor_that_referees_at_once_with_its_home_is_somebody_else() -> None:
    res = resolve([form("d makkelie", "netherlands", 40), form("d makkelie", "greece", 3)])  # same slot
    assert len(res.groups) == 2
    assert len(res.vetoes) == 1


def test_a_visitor_cannot_come_from_a_scope_its_home_already_has() -> None:
    """'menelaos antoniou' (Cyprus) is beside 'm antoniou' in Cyprus, and rule 1 left them apart (two full names fit the
    initial). He cannot then become a 'visitor' of that same home through the 'm antoniou' written in Croatia."""
    res = resolve([form("m antoniou", "cyprus", 80), form("m antoniou", "croatia", 2, slot=1), form("menelaos antoniou", "cyprus", 5, slot=2),
                   form("marios antoniou", "cyprus", 1, slot=3)])
    assert together(res, ("m antoniou", "cyprus"), ("m antoniou", "croatia"))
    assert not together(res, ("m antoniou", "cyprus"), ("menelaos antoniou", "cyprus"))
    assert not together(res, ("m antoniou", "cyprus"), ("marios antoniou", "cyprus"))


def test_a_visitor_whose_full_name_contradicts_the_homes_is_somebody_else() -> None:
    """'a rojas' is Andres in Colombia and Antonio in Spain: the two full names cannot be one person."""
    res = resolve([form("a rojas", "colombia", 60), form("andres rojas", "colombia", 20, slot=1),
                   form("a rojas", "spain", 2, slot=2), form("antonio rojas", "spain", 2, slot=3)])
    assert together(res, ("a rojas", "colombia"), ("andres rojas", "colombia"))
    assert together(res, ("a rojas", "spain"), ("antonio rojas", "spain"))
    assert not together(res, ("a rojas", "colombia"), ("a rojas", "spain"))


def test_a_spelling_with_no_scope_joins_the_one_scoped_name_it_could_be() -> None:
    res = resolve([form("d makkelie", "?", 12, slot=1), form("d makkelie", "netherlands", 3), form("danny makkelie", "netherlands", 30, slot=2)])
    assert len(res.groups) == 1
    assert res.basis[("d makkelie", "?")] == "unscoped"


def test_a_spelling_with_no_scope_does_not_choose_between_two_equal_homes() -> None:
    res = resolve([form("j martinez", "?", 30, slot=2), form("j martinez", "spain", 60), form("j martinez", "mexico", 50, slot=1)])
    assert len(res.groups) == 3
    assert not together(res, ("j martinez", "?"), ("j martinez", "spain"))


def test_a_spelling_with_no_scope_goes_to_the_home_that_dominates() -> None:
    """Marciniak: 85 matches in continental cups, 233 at home and 16 in Saudi Arabia (not a 'visitor' by size: too many)."""
    res = resolve([form("s marciniak", "?", 85, slot=2), form("s marciniak", "poland", 233), form("s marciniak", "saudi arabia", 16, slot=1)])
    assert together(res, ("s marciniak", "?"), ("s marciniak", "poland"))
    assert not together(res, ("s marciniak", "saudi arabia"), ("s marciniak", "poland"))
    assert any(c.reason == "same_name_other_scope" for c in res.candidates)  # the Saudi matches wait for a person


def test_a_visitor_of_a_visitor_follows_the_cascade() -> None:
    """The small clusters go first, so by the time the spelling with no scope looks, its home is one cluster."""
    res = resolve([form("s marciniak", "?", 85, slot=2), form("s marciniak", "poland", 233), form("s marciniak", "cyprus", 2, slot=1)])
    assert len(res.groups) == 1


# ── rule 3 and the stored referees ───────────────────────────────────────────────────────────────────────────────────


def test_two_stored_referees_are_never_joined_by_a_rule() -> None:
    res = resolve([form("danny makkelie", "netherlands", 30, entity=1), form("danny desmond makkelie", "netherlands", 3, slot=1, entity=2)])
    assert len(res.groups) == 2
    assert {g.entity for g in res.groups} == {1, 2}
    assert {r for _, _, r in questions(res)} == {"longer_name"}  # the machine still SAYS they could be one


def test_the_spellings_of_one_stored_referee_are_one_group() -> None:
    res = resolve([form("m oliver", "england", 30, entity=7), form("michael oliver", "england", 3, slot=1, entity=7),
                   form("m oliver", "greece", 1, slot=2, entity=7)])
    assert len(res.groups) == 1 and res.groups[0].entity == 7
    assert set(res.basis.values()) == {"stored"}


def test_a_new_spelling_joins_a_stored_referee_and_the_group_keeps_its_number() -> None:
    res = resolve([form("d makkelie", "netherlands", 40, entity=3), form("d makkelie", "greece", 1, slot=1)])
    assert len(res.groups) == 1 and res.groups[0].entity == 3
    assert res.basis[("d makkelie", "netherlands")] == "stored"
    assert res.basis[("d makkelie", "greece")] == "foreign"


def test_a_stored_spelling_never_moves_to_another_referee() -> None:
    """A person split 'd makkelie' (Greece) away from the Dutch referee: it stays with its own."""
    res = resolve([form("d makkelie", "netherlands", 40, entity=3), form("d makkelie", "greece", 1, slot=1, entity=9)])
    assert len(res.groups) == 2
    assert {g.entity for g in res.groups} == {3, 9}


def test_a_spelling_already_with_its_full_name_is_not_pulled_to_another_one() -> None:
    """'m oliver' sits with 'michael oliver' (one stored referee, 3 matches): a bigger 'mark oliver' fits the initial too, and
    must not take the stored referee over because it dominates."""
    res = resolve([form("m oliver", "england", 2, entity=1), form("michael oliver", "england", 1, slot=1, entity=1),
                   form("mark oliver", "england", 40, slot=2)])
    assert len(res.groups) == 2
    assert not together(res, ("m oliver", "england"), ("mark oliver", "england"))


def test_a_stored_visitor_joins_a_new_home() -> None:
    """The home is new and the visitor was stored alone: the home's spellings take the visitor's referee."""
    res = resolve([form("d makkelie", "netherlands", 40), form("d makkelie", "greece", 2, slot=1, entity=5)])
    assert len(res.groups) == 1 and res.groups[0].entity == 5


# ── properties ───────────────────────────────────────────────────────────────────────────────────────────────────────


def world() -> list[Form]:
    return [
        form("danny makkelie", "netherlands", 40), form("danny desmond makkelie", "netherlands", 4, slot=1),
        form("d makkelie", "netherlands", 9, slot=2), form("d makkelie", "saudi arabia", 3, slot=3), form("d makkelie", "?", 14, slot=4),
        form("j martinez", "spain", 60, slot=1), form("j martinez", "mexico", 50, slot=2), form("j martinez", "?", 20, slot=3),
        form("r gupta", "india", 12, slot=3), form("rahul kumar gupta", "india", 12, slot=4), form("rajesh gupta", "india", 12, slot=0),
        form("christian ballweg", "germany", 30, slot=0), form("cristian ballweg", "germany", 2, slot=1),
        form("m oliver", "england", 40, slot=2), form("michael oliver", "england", 8, slot=3),
        form("a rojas", "colombia", 60, slot=0), form("andres rojas", "colombia", 20, slot=1), form("a rojas", "spain", 2, slot=2),
        form("antonio rojas", "spain", 2, slot=3),
    ]


def test_the_result_does_not_depend_on_the_order_of_the_input() -> None:
    forms = world()
    first = resolve(forms)
    for seed in range(5):
        shuffled = forms[:]
        random.Random(seed).shuffle(shuffled)
        again = resolve(shuffled)
        assert again.groups == first.groups
        assert again.candidates == first.candidates
        assert again.vetoes == first.vetoes
        assert again.basis == first.basis
        assert again.group_of == first.group_of


def test_every_spelling_is_in_exactly_one_group_and_the_numbers_are_dense() -> None:
    res = resolve(world())
    assert sorted(res.group_of) == sorted(f.id for f in world())
    assert sorted(g.number for g in res.groups) == list(range(1, len(res.groups) + 1))
    assert sum(g.games for g in res.groups) == sum(len(f.games) for f in world())
    for g in res.groups:
        assert all(res.group_of[f] == g.number for f in g.forms)
        assert g.canonical in g.forms


def test_a_group_never_holds_two_full_names_that_contradict_each_other() -> None:
    from fbi.people import referee_names as rn

    for g in resolve(world()).groups:
        fulls = [f[0] for f in g.forms if not rn.is_initial_form(f[0])]
        assert not any(rn.names_conflict(a, b) for a in fulls for b in fulls), g


def test_a_pair_is_never_both_a_question_and_a_veto() -> None:
    res = resolve(world())
    asked = {(c.a, c.b) for c in res.candidates}
    vetoed = {(v.a, v.b) for v in res.vetoes}
    assert not asked & vetoed


def test_the_summary_counts_the_matches_that_no_question_touches() -> None:
    res = resolve([form("danny makkelie", "netherlands", 30), form("r gupta", "india", 12), form("rahul kumar gupta", "india", 12, slot=1),
                   form("rajesh gupta", "india", 12, slot=2)])
    s = res.summary()
    assert s["forms"] == 4 and s["groups"] == 4 and s["new_groups"] == 4
    assert s["games"] == 66 and s["games_settled"] == 30  # the three Guptas wait for a person
    assert s["candidates"] == 2 and s["vetoes"] == 0


def test_nothing_in_nothing_out() -> None:
    res = resolve([])
    assert res.groups == () and res.candidates == () and res.vetoes == () and res.group_of == {}


def test_a_spelling_given_twice_is_a_mistake() -> None:
    import pytest

    with pytest.raises(ValueError, match="only once"):
        resolve([form("a b", "x"), form("a b", "x")])


# ── the pieces ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_collisions_count_kickoffs_less_than_the_window_apart_and_ignore_the_same_match() -> None:
    a: list[ri.Game] = [(1000, 1), (5000, 2)]
    assert ri.collisions(a, [(1119, 10)], 120) == 1  # 119 minutes apart
    assert ri.collisions(a, [(1120, 10)], 120) == 0  # 120 is not less than 120
    assert ri.collisions(a, [(881, 10)], 120) == 1 and ri.collisions(a, [(880, 10)], 120) == 0
    assert ri.collisions(a, [(1000, 1)], 120) == 0  # the same match under two spellings is no collision
    assert ri.collisions(a, [], 120) == 0 and ri.collisions([], a, 120) == 0
    assert ri.collisions(a, [(1001, 10), (1002, 11)], 120) == 2
    assert ri.collisions([(1001, 10), (1002, 11)], a, 120) == 2  # symmetric


def test_text_compatible_names_the_strongest_way() -> None:
    assert ri.text_compatible("d makkelie", "d makkelie") == "same_name_other_scope"
    assert ri.text_compatible("danny makkelie", "danny desmond makkelie") == "longer_name"
    assert ri.text_compatible("d makkelie", "danny makkelie") == "initial_and_full"
    assert ri.text_compatible("danny makkelie", "d makkelie") == "initial_and_full"
    assert ri.text_compatible("christian ballweg", "cristian ballweg") == "spelling_variant"
    assert ri.text_compatible("michael oliver", "mark taylor") is None


def test_the_canonical_spelling_is_a_full_name_before_an_initial() -> None:
    forms = [form("m oliver", "england", 100), form("michael oliver", "england", 2, slot=1)]
    assert ri.pick_canonical(forms) == ("michael oliver", "england")
    forms = [form("michael oliver", "england", 2), form("michael oliver", "greece", 5, slot=1), form("mike oliver", "england", 5, slot=2)]
    assert ri.pick_canonical(forms) == ("michael oliver", "greece")  # most matches, then the longest, then alphabetical
