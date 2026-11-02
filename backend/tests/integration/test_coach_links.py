"""The careers of the coaches tied to the person and to the club (plan F3): a person for the coach who has a profile and that no match
sheet has named, the links of every row of a career, what is left alone, and a second pass that writes nothing."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.people import coach_links as cl
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

T0 = datetime(2026, 3, 1, 15, 0, tzinfo=UTC)
_coach = itertools.count(9_100_000)
_team = itertools.count(91_000)


def d(n: int) -> date:
    return (T0 + timedelta(days=n)).date()


@dataclass
class World:
    db: psycopg.Connection
    seed: Seed

    def team(self, name: str) -> int:
        """A club of ours; returns its provider id."""
        provider = next(_team)
        self.db.execute("INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (%s, %s, false)", (provider, name))
        return provider

    def team_id(self, provider: int) -> int:
        return int(scalar(self.db.execute("SELECT id FROM core.teams WHERE provider_team_id = %s", (provider,))))

    def coach(self) -> int:
        return next(_coach)

    def profile(self, coach: int, name: str | None = "Some Coach", *, observed: int = 0, firstname: str | None = None,
                lastname: str | None = None, born: date | None = None, nationality: str | None = None) -> None:
        self.db.execute("INSERT INTO core.coach_profiles (provider_coach_id, observed_at, name, firstname, lastname, birth_date, nationality, "
                        "payload_hash, normalizer_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'test')",
                        (coach, T0 + timedelta(days=observed), name, firstname, lastname, born, nationality, self.seed.payload_hash))

    def career(self, coach: int, rows: list[tuple[int | None, str | None, int | None, int | None]], *, observed: int = 0) -> None:
        """A snapshot of the career as the provider listed it: (provider club id, club name, first day, last day)."""
        for ordinal, (club, name, start, end) in enumerate(rows):
            self.db.execute("INSERT INTO core.coach_careers (provider_coach_id, observed_at, ordinal, provider_team_id, team_name, start_date, "
                            "end_date, payload_hash, normalizer_version) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'test')",
                            (coach, T0 + timedelta(days=observed), ordinal, club, name,
                             None if start is None else d(start), None if end is None else d(end), self.seed.payload_hash))

    def person(self, coach: int, name: str) -> int:
        return int(scalar(self.db.execute("INSERT INTO core.coaches (provider_coach_id, name) VALUES (%s, %s) RETURNING id", (coach, name))))

    def person_row(self, coach: int) -> tuple[Any, ...] | None:
        return self.db.execute("SELECT id, name, firstname, lastname, birth_date, nationality, source_payload_hash, source_fetched_at "
                               "FROM core.coaches WHERE provider_coach_id = %s", (coach,)).fetchone()

    def links(self, coach: int) -> list[tuple[Any, ...]]:
        """(observed day, ordinal, coach_id, team_id) of every row of the career."""
        return [(r[0], r[1], r[2], r[3]) for r in self.db.execute(
            "SELECT (observed_at AT TIME ZONE 'UTC')::date, ordinal, coach_id, team_id FROM core.coach_careers "
            "WHERE provider_coach_id = %s ORDER BY observed_at, ordinal", (coach,)).fetchall()]


@pytest.fixture()
def world(db: psycopg.Connection, seed: Seed) -> World:
    return World(db, seed)


def test_a_coach_with_a_profile_and_no_person_gets_one_and_his_career_is_tied_to_it_and_to_the_clubs(world: World) -> None:
    alpha, beta, far_away = world.team("Alpha FC"), world.team("Beta FC"), 123_456
    c = world.coach()
    world.profile(c, "Pep Rollo", firstname="P.", lastname="Rollo", born=date(1971, 1, 18), nationality="Catalonia", observed=1)  # older
    world.profile(c, "  Pep Roller ", firstname="Pep", lastname="Roller", born=date(1970, 1, 18), nationality="Spain", observed=3)
    world.career(c, [(alpha, "Alpha FC", -400, -10), (beta, "Beta FC", -10, None), (far_away, "Far Away United", -900, -400)], observed=3)

    dry = cl.build(world.db)
    assert (dry.persons_created, dry.careers_coach_linked, dry.careers_team_linked) == (1, 3, 2) and not dry.applied
    assert world.person_row(c) is None and world.links(c) == [(d(3), 0, None, None), (d(3), 1, None, None), (d(3), 2, None, None)]

    done = cl.build(world.db, apply=True)
    assert done.applied and done.changed and (done.persons_created, done.careers_coach_linked, done.careers_team_linked) == (1, 3, 2)
    said = done.as_dict()
    assert isinstance(said.pop("seconds"), float)
    assert said == {"applied": True, "skipped_locked": False, "persons_created": 1, "careers_coach_linked": 3, "careers_team_linked": 2}
    person = world.person_row(c)
    assert person is not None
    assert person[1:] == ("Pep Roller", "Pep", "Roller", date(1970, 1, 18), "Spain", world.seed.payload_hash, T0 + timedelta(days=3))
    assert world.links(c) == [(d(3), 0, person[0], world.team_id(alpha)), (d(3), 1, person[0], world.team_id(beta)), (d(3), 2, person[0], None)], \
        "the club we do not hold keeps no link"

    again = cl.build(world.db, apply=True)
    assert not again.changed and (again.persons_created, again.careers_coach_linked, again.careers_team_linked) == (0, 0, 0)
    assert not cl.build(world.db).changed, "and a dry run finds nothing to do either"

    spells = world.db.execute("SELECT coach_id, provider_team_id, team_id, start_date, end_date FROM core.coach_spells "
                              "WHERE provider_coach_id = %s ORDER BY start_date", (c,)).fetchall()
    assert spells == [(person[0], far_away, None, d(-900), d(-400)), (person[0], alpha, world.team_id(alpha), d(-400), d(-10)),
                      (person[0], beta, world.team_id(beta), d(-10), None)]


def test_the_person_a_match_sheet_made_is_kept_as_it_is(world: World) -> None:
    alpha = world.team("Alpha FC")
    c = world.coach()
    sheet_person = world.person(c, "P. Roller")
    world.profile(c, "Pep Roller", firstname="Pep", nationality="Spain")
    world.career(c, [(alpha, "Alpha FC", -400, None)])
    no_profile = world.coach()
    unprofiled = world.person(no_profile, "A. Nobody")      # a person from the sheets whose profile has not come
    world.career(no_profile, [(alpha, "Alpha FC", -20, None)])
    dry = cl.build(world.db)
    assert (dry.persons_created, dry.careers_coach_linked, dry.careers_team_linked) == (0, 2, 2), "the dry run sees the same"
    done = cl.build(world.db, apply=True)
    assert done.persons_created == 0 and done.careers_coach_linked == 2
    assert world.links(no_profile) == [(d(0), 0, unprofiled, world.team_id(alpha))]
    assert world.person_row(c) == (sheet_person, "P. Roller", None, None, None, None, None, None), "what the sheets said is not rewritten"
    assert world.links(c) == [(d(0), 0, sheet_person, world.team_id(alpha))]


def test_what_cannot_be_tied_stays_untied(world: World) -> None:
    alpha = world.team("Alpha FC")
    nameless, blank, nobody, no_profile = world.coach(), world.coach(), 0, world.coach()
    world.profile(nameless, None)
    world.profile(blank, "   ")
    world.profile(nobody, "Nobody")
    for coach in (nameless, blank, nobody, no_profile):
        world.career(coach, [(alpha, "Alpha FC", -5, None), (None, "No club given", -50, -5)])
    done = cl.build(world.db, apply=True)
    assert done.persons_created == 0 and done.careers_coach_linked == 0
    assert done.careers_team_linked == 4, "the clubs are tied whoever the coach is"
    for coach in (nameless, blank, nobody, no_profile):
        assert world.person_row(coach) is None
        assert world.links(coach) == [(d(0), 0, None, world.team_id(alpha)), (d(0), 1, None, None)]
    # a name arrives later: the person is made and the career tied
    world.profile(nameless, "Now Named", observed=7)
    later = cl.build(world.db, apply=True)
    assert later.persons_created == 1 and later.careers_coach_linked == 2
    made = world.person_row(nameless)
    assert made is not None and {row[2] for row in world.links(nameless)} == {made[0]}


def test_a_pass_that_does_only_one_of_its_three_things_is_a_change_all_the_same(world: World) -> None:
    alpha = world.team("Alpha FC")
    # only a person: a profile with a name and no career at all
    world.profile(world.coach(), "Just Named")
    person_only = cl.build(world.db, apply=True)
    assert (person_only.persons_created, person_only.careers_coach_linked, person_only.careers_team_linked) == (1, 0, 0)
    assert person_only.changed
    # only a link to the person: he exists (a match sheet made him) and the club is one we do not hold
    known = world.coach()
    world.person(known, "From A Sheet")
    world.career(known, [(123_456, "Far Away United", -50, None)])
    coach_only = cl.build(world.db, apply=True)
    assert (coach_only.persons_created, coach_only.careers_coach_linked, coach_only.careers_team_linked) == (0, 1, 0)
    assert coach_only.changed
    # only a link to the club: a coach nobody has a name for, at a club we hold
    world.career(world.coach(), [(alpha, "Alpha FC", -5, None)])
    team_only = cl.build(world.db, apply=True)
    assert (team_only.persons_created, team_only.careers_coach_linked, team_only.careers_team_linked) == (0, 0, 1)
    assert team_only.changed
    assert not cl.build(world.db, apply=True).changed


def test_every_snapshot_of_a_career_is_tied_and_the_view_shows_the_newest(world: World) -> None:
    alpha, beta = world.team("Alpha FC"), world.team("Beta FC")
    c = world.coach()
    world.profile(c, "Ann Coach")
    world.career(c, [(alpha, "Alpha FC", -100, None)], observed=0)
    world.career(c, [(alpha, "Alpha FC", -100, -3), (beta, "Beta FC", -3, None)], observed=7)
    done = cl.build(world.db, apply=True)
    assert done.careers_coach_linked == 3 and done.careers_team_linked == 3
    person = world.person_row(c)
    assert person is not None
    assert [(r[0], r[1], r[2] == person[0], r[3] is not None) for r in world.links(c)] == [(d(0), 0, True, True), (d(7), 0, True, True), (d(7), 1, True, True)]
    newest = world.db.execute("SELECT provider_team_id, end_date FROM core.coach_spells WHERE provider_coach_id = %s ORDER BY start_date", (c,)).fetchall()
    assert newest == [(alpha, d(-3)), (beta, None)], "the view shows the newest snapshot only"
    # a snapshot that arrives later is tied by the next pass and the earlier ones are not touched
    world.career(c, [(beta, "Beta FC", -3, None)], observed=14)
    next_pass = cl.build(world.db, apply=True)
    assert (next_pass.persons_created, next_pass.careers_coach_linked, next_pass.careers_team_linked) == (0, 1, 1)


def test_a_link_already_made_is_never_touched_and_the_audit_says_when_one_is_wrong(world: World) -> None:
    alpha, beta = world.team("Alpha FC"), world.team("Beta FC")
    c, other = world.coach(), world.coach()
    world.profile(c, "Ann Coach")
    world.profile(other, "Bob Coach")
    world.career(c, [(alpha, "Alpha FC", -100, None)])
    cl.build(world.db, apply=True)
    assert cl.broken_invariants(cl.audit(world.db)) == []
    someone_else = world.person_row(other)
    assert someone_else is not None
    world.db.execute("UPDATE core.coach_careers SET team_id = %s, coach_id = %s WHERE provider_coach_id = %s",
                     (world.team_id(beta), someone_else[0], c))
    again = cl.build(world.db, apply=True)
    assert not again.changed, "a link that is there is not rewritten"
    figures = cl.audit(world.db)
    assert figures["coach_links_to_another_person"] == 1 and figures["team_links_to_another_club"] == 1
    assert cl.broken_invariants(figures) == ["coach_links_to_another_person", "team_links_to_another_club"]


def test_the_figures_count_the_persons_the_careers_and_what_is_left_untied(world: World) -> None:
    alpha = world.team("Alpha FC")
    before = cl.counts(world.db)
    tied, unnamed = world.coach(), world.coach()
    world.profile(tied, "Ann Coach")
    world.profile(unnamed, None)
    world.career(tied, [(alpha, "Alpha FC", -100, None)], observed=-7)      # an older snapshot: the view of the spells does not show it
    world.career(tied, [(alpha, "Alpha FC", -100, None), (123_457, "Far Away United", -300, -100), (None, "?", None, -500)])
    world.career(unnamed, [(alpha, "Alpha FC", -9, -1)])
    waiting = cl.audit(world.db)
    assert waiting["pass_would_write"] == {"persons": 1, "coach_links": 4, "team_links": 3}
    assert world.person_row(tied) is None, "the audit only looks"
    assert waiting["profiles_without_person"] - before["profiles_without_person"] == 2
    cl.build(world.db, apply=True)
    after = cl.audit(world.db)
    assert after["pass_would_write"] == {"persons": 0, "coach_links": 0, "team_links": 0}
    delta = {k: after[k] - before[k] for k in before}
    assert delta["coaches"] == 1 and delta["careers"] == 5, "five rows of careers, two of the coach who has an older snapshot"
    assert delta["careers_without_coach"] == 1, "the career of the coach nobody has a name for"
    assert delta["careers_of_clubs_not_held"] == 1 and delta["careers_without_club"] == 1
    assert delta["spells"] == 4, "the newest snapshot of each career only"
    assert delta["spells_with_person_and_club"] == 1
    assert delta["spells_open"] == 1, "one still going (three have an end)"
    assert delta["profiles_without_person"] == 1 and cl.broken_invariants(after) == []


def test_a_pass_that_finds_the_lock_taken_gives_way_and_looking_goes_on(world: World, migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = world.team("Alpha FC")
    c = world.coach()
    world.profile(c, "Ann Coach")
    world.career(c, [(alpha, "Alpha FC", -100, None)])
    monkeypatch.setattr(cl, "MANUAL_LOCK_WAIT", "200ms")
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (cl.LOCK_KEY,))
        skipped = cl.build(world.db, apply=True)
        looked = cl.build(world.db)
        with pytest.raises(psycopg.errors.LockNotAvailable):
            cl.build(world.db, apply=True, wait=True)
        other.rollback()
    assert skipped.skipped_locked and not skipped.applied and not skipped.changed
    assert not looked.skipped_locked and looked.persons_created == 1
    assert world.person_row(c) is None
    assert cl.build(world.db, apply=True, wait=True).persons_created == 1, "a person at the console waits for the lock and gets it"
