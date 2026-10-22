"""The referee on the match page (plan F3): the person, under one name and with his id, when the identity is at the newest
observation of the provider - and the string as it came while it is not."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.contracts.center import MatchFacts
from fbi.api.services import center
from fbi.people import referees as store
from tests.integration.test_referee_identity_store import T0, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def facts_of(db: psycopg.Connection[Any], fixture_id: int) -> MatchFacts:
    body = center.match_center(db, fixture_id).data
    assert body is not None and body.facts is not None
    return body.facts


def test_the_page_shows_the_person_under_one_name_whatever_the_provider_wrote(world: World) -> None:  # noqa: F811
    world.match("England", 1, "Michael Oliver", "England")
    target = world.match("England", 10, "M. Oliver")  # the provider wrote the initial this time
    store.build(world.db, apply=True)

    facts = facts_of(world.db, target)
    assert (facts.referee, facts.referee_country) == ("Michael Oliver", "England")
    assert facts.referee_id == world.referee_of(target) and facts.referee_id is not None


def test_a_match_the_identity_has_not_seen_shows_the_string_and_no_id(world: World) -> None:  # noqa: F811
    target = world.match("England", 10, "M. Oliver", "England")
    facts = facts_of(world.db, target)
    assert (facts.referee, facts.referee_country, facts.referee_id) == ("M. Oliver", "England", None)


def test_a_change_the_pass_has_not_seen_yet_shows_the_new_string_and_not_the_old_person(world: World) -> None:  # noqa: F811
    target = world.match("England", 10, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    world.say(target, "Craig Pawson", "England", at=T0 + timedelta(days=30))

    facts = facts_of(world.db, target)
    assert (facts.referee, facts.referee_id) == ("Craig Pawson", None)
    store.build(world.db, apply=True)
    facts = facts_of(world.db, target)
    assert facts.referee == "Craig Pawson" and facts.referee_id == world.referee_of(target)


def test_a_referee_the_provider_took_off_is_nobody(world: World) -> None:  # noqa: F811
    target = world.match("England", 10, "Michael Oliver", "England")
    world.say(target, None, at=T0 + timedelta(days=30))
    store.build(world.db, apply=True)
    facts = facts_of(world.db, target)
    assert (facts.referee, facts.referee_country, facts.referee_id) == (None, None, None)


def test_the_id_goes_out_in_the_json_the_web_reads(world: World) -> None:  # noqa: F811
    target = world.match("England", 10, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    body = center.match_center(world.db, target).data
    assert body is not None
    dumped = body.model_dump(mode="json")["facts"]
    assert dumped["referee"] == "Michael Oliver" and isinstance(dumped["referee_id"], int)
