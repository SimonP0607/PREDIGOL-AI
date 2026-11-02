"""The referees in the database (plan F3): a pass places every spelling, a second one writes nothing, the history keeps what was
known when, and a merge, an undo and a split move aliases and nothing else."""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.people import referees as store
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_provider = itertools.count(900_000)
_league = itertools.count(900)


@dataclass
class World:
    db: psycopg.Connection
    seed: Seed
    seasons: dict[str, int]
    clock: itertools.count

    def fixture(self, country: str, day: int, hour: int = 15) -> int:
        cur = self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (next(_provider), self.seasons[country], self.seed.home_team_id, self.seed.away_team_id,
             T0 + timedelta(days=day, hours=hour - 12)))
        return int(scalar(cur))

    def say(self, fixture_id: int, referee: str | None, country: str | None = None, *, at: datetime | None = None) -> datetime:
        """The provider says who referees a match (``referee_country`` is the part after the first comma)."""
        when = at or T0 + timedelta(minutes=next(self.clock))
        self.db.execute(
            "INSERT INTO core.fixture_facts (fixture_id, observed_at, referee, referee_country, payload_hash, normalizer_version) "
            "VALUES (%s, %s, %s, %s, %s, 'test')", (fixture_id, when, referee, country, self.seed.payload_hash))
        return when

    def match(self, country: str, day: int, referee: str | None, referee_country: str | None = None, hour: int = 15) -> int:
        fid = self.fixture(country, day, hour)
        self.say(fid, referee, referee_country)
        return fid

    def one(self, sql: str, *params: object) -> Any:
        return scalar(self.db.execute(sql, params))

    def referee_of(self, fixture_id: int) -> int | None:
        row = self.db.execute("SELECT referee_id FROM core.fixture_referees WHERE fixture_id = %s", (fixture_id,)).fetchone()
        return int(row[0]) if row else None

    def referee_named(self, display: str, scope: str) -> int:
        return int(self.one("SELECT referee_id FROM core.referee_aliases WHERE display = %s AND scope = %s", display, scope))

    def alias(self, key: str, scope: str) -> int:
        return int(self.one("SELECT id FROM core.referee_aliases WHERE name_key = %s AND scope = %s", key, scope))


@pytest.fixture()
def world(db: psycopg.Connection, seed: Seed) -> World:
    seasons: dict[str, int] = {}
    for country in ("England", "Netherlands", "Spain"):
        cid = scalar(db.execute(
            "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, country) "
            "VALUES (%s, %s, 'league', 'club', 'domestic_league', %s) RETURNING id", (next(_league), f"{country} league", country)))
        seasons[country] = int(scalar(db.execute(
            "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (cid,))))
    cup = scalar(db.execute(
        "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, country) "
        "VALUES (%s, 'Continental cup', 'cup', 'club', 'continental', 'World') RETURNING id", (next(_league),)))
    seasons["World"] = int(scalar(db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (cup,))))
    return World(db, seed, seasons, itertools.count(1))


def small_world(w: World) -> dict[str, int]:
    """Two English matches of Michael Oliver (once as 'M. Oliver'), and a 'M. Oliver' in the Netherlands."""
    return {"full": w.match("England", 1, "Michael Oliver", "England"), "initial": w.match("England", 8, "M. Oliver"),
            "dutch": w.match("Netherlands", 15, "M. Oliver")}


def test_a_pass_places_every_spelling_and_a_second_pass_writes_nothing(world: World) -> None:
    ids = small_world(world)
    dry = store.build(world.db)
    assert not dry.applied and dry.new_referees == 2 and dry.new_aliases == 3 and dry.officials_to_write == 3
    assert world.one("SELECT count(*) FROM core.referees") == 0, "a dry run writes nothing"

    first = store.build(world.db, apply=True)
    assert first.applied and first.changed and (first.new_referees, first.new_aliases, first.officials_to_write) == (2, 3, 3)
    # 'M. Oliver' written in England is Michael Oliver (the only full name that fits); the one in the Netherlands is a doubt
    assert world.referee_of(ids["full"]) == world.referee_of(ids["initial"]) != world.referee_of(ids["dutch"])
    assert world.one("SELECT count(*) FROM core.referees WHERE status = 'active'") == 2
    assert world.one("SELECT name FROM core.referees WHERE id = %s", world.referee_of(ids["full"])) == "Michael Oliver"
    assert world.one("SELECT country_key FROM core.referees WHERE id = %s", world.referee_of(ids["full"])) == "england"
    assert world.one("SELECT basis FROM core.referee_aliases WHERE name_key = 'm oliver' AND scope = 'england'") == "initial"
    assert world.one("SELECT count(*) FROM core.referee_candidates WHERE status = 'open'") == 1

    second = store.build(world.db, apply=True)
    assert not second.changed, second.as_dict()
    assert world.one("SELECT count(*) FROM core.fixture_officials") == 3


def test_a_surname_first_string_is_put_back_in_order(world: World) -> None:
    fid = world.match("England", 1, "Brooks", "John, England")  # split_referee cut 'Brooks, John, England' at the first comma
    store.build(world.db, apply=True)
    assert world.one("SELECT display FROM core.referee_aliases WHERE id = (SELECT alias_id FROM core.fixture_referees WHERE fixture_id = %s)", fid) == "John Brooks"
    assert world.one("SELECT name_key FROM core.referees WHERE id = %s", world.referee_of(fid)) == "john brooks"


def test_the_history_of_a_match_keeps_who_was_known_at_each_moment(world: World) -> None:
    fid = world.fixture("England", 3)
    t1 = world.say(fid, "A. Taylor")
    t2 = world.say(fid, "Anthony Taylor", "England")
    t3 = world.say(fid, None)  # the provider takes him off
    t4 = world.say(fid, "Craig Pawson", "England")
    store.build(world.db, apply=True)
    rows = world.db.execute("SELECT observed_at, alias_id IS NULL FROM core.fixture_officials WHERE fixture_id = %s ORDER BY observed_at", (fid,)).fetchall()
    assert [(r[0], r[1]) for r in rows] == [(t1, False), (t2, False), (t3, True), (t4, False)]
    assert world.referee_of(fid) is not None and world.one("SELECT display FROM core.referee_aliases a JOIN core.fixture_referees f ON f.alias_id = a.id WHERE f.fixture_id = %s", fid) == "Craig Pawson"

    def as_of(moment: datetime) -> str | None:
        row = world.db.execute(
            "SELECT a.display FROM core.fixture_officials o LEFT JOIN core.referee_aliases a ON a.id = o.alias_id "
            "WHERE o.fixture_id = %s AND o.observed_at <= %s ORDER BY o.observed_at DESC LIMIT 1", (fid, moment)).fetchone()
        return row[0] if row else None

    assert as_of(t1 - timedelta(minutes=1)) is None
    assert as_of(t1) == "A. Taylor" and as_of(t2) == "Anthony Taylor" and as_of(t3) is None and as_of(t4) == "Craig Pawson"
    # ...and the match whose referee was taken off has none now, when the newest word says none
    world.say(fid, None)
    store.build(world.db, apply=True)
    assert world.referee_of(fid) is None
    assert store.build(world.db, apply=True).changed is False


def test_a_later_answer_adds_one_row_and_a_new_spelling_a_new_alias(world: World) -> None:
    small_world(world)
    store.build(world.db, apply=True)
    world.match("England", 22, "Michael Oliver", "England")
    world.match("England", 29, "Mike Oliver", "England")
    report = store.build(world.db, apply=True)
    assert (report.new_aliases, report.officials_to_write, report.new_referees) == (1, 2, 1)  # 'Michael Oliver, England' exists
    assert world.one("SELECT count(*) FROM core.fixture_officials") == 5


def test_a_referee_abroad_joins_his_home_once_the_home_is_big_enough(world: World) -> None:
    home = [world.match("England", d, "Anthony Taylor", "England") for d in range(1, 21)]
    abroad = world.match("Spain", 40, "A. Taylor")
    store.build(world.db, apply=True)
    assert {world.referee_of(f) for f in home} == {world.referee_of(abroad)}
    assert world.one("SELECT basis FROM core.referee_aliases WHERE name_key = 'a taylor' AND scope = 'spain'") == "foreign"


def test_a_spelling_with_no_scope_goes_to_the_one_referee_it_could_be(world: World) -> None:
    home = world.match("England", 1, "Michael Oliver", "England")
    cup = world.match("World", 3, "M. Oliver")
    store.build(world.db, apply=True)
    assert world.referee_of(home) == world.referee_of(cup)
    assert world.one("SELECT basis FROM core.referee_aliases WHERE name_key = 'm oliver' AND scope = '?'") == "unscoped"


def test_a_merge_moves_aliases_and_nothing_else_and_an_undo_puts_them_back(world: World) -> None:
    ids = small_world(world)
    store.build(world.db, apply=True)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None
    before = world.db.execute("SELECT fixture_id, observed_at, alias_id FROM core.fixture_officials ORDER BY 1, 2").fetchall()

    event = store.merge(world.db, keep, other, actor="admin:test", note="same man")
    assert world.referee_of(ids["dutch"]) == keep
    assert world.one("SELECT status FROM core.referees WHERE id = %s", other) == "merged"
    assert world.one("SELECT merged_into FROM core.referees WHERE id = %s", other) == keep
    assert world.db.execute("SELECT fixture_id, observed_at, alias_id FROM core.fixture_officials ORDER BY 1, 2").fetchall() == before
    assert world.one("SELECT status FROM core.referee_candidates") == "merged"
    assert world.one("SELECT basis FROM core.referee_aliases WHERE name_key = 'm oliver' AND scope = 'netherlands'") == "manual"

    # a pass leaves the person's decision alone and does not suggest the pair again
    report = store.build(world.db, apply=True)
    assert not report.changed, report.as_dict()
    assert world.referee_of(ids["dutch"]) == keep
    assert store.audit(world.db)["aliases_on_merged_referee"] == 0

    store.undo(world.db, event, actor="admin:test")
    assert world.referee_of(ids["dutch"]) == other != keep
    assert world.one("SELECT status FROM core.referees WHERE id = %s", other) == "active"
    assert world.one("SELECT basis FROM core.referee_aliases WHERE name_key = 'm oliver' AND scope = 'netherlands'") == "identity"
    assert world.one("SELECT status FROM core.referee_candidates") == "rejected"
    assert world.one("SELECT undone_by IS NOT NULL FROM core.referee_events WHERE id = %s", event) is True
    assert not store.build(world.db, apply=True).changed, "an undone merge is not suggested again"
    with pytest.raises(store.ActionError, match="already undone"):
        store.undo(world.db, event, actor="admin:test")


def test_two_referees_who_officiate_at_the_same_time_cannot_be_merged(world: World) -> None:
    a = world.match("England", 1, "Michael Oliver", "England", hour=15)
    b = world.match("Netherlands", 1, "M. Oliver", hour=16)  # an hour later: one man cannot be at both
    store.build(world.db, apply=True)
    ra, rb = world.referee_of(a), world.referee_of(b)
    assert ra is not None and rb is not None and ra != rb
    assert world.one("SELECT count(*) FROM core.referee_candidates") == 0, "never suggested"
    with pytest.raises(store.ActionError) as err:
        store.merge(world.db, ra, rb, actor="admin:test")
    assert err.value.code == "collision"
    assert world.one("SELECT status FROM core.referees WHERE id = %s", rb) == "active"
    store.merge(world.db, ra, rb, actor="admin:test", force=True)
    assert world.referee_of(b) == ra


def test_a_new_spelling_of_a_merged_referee_joins_him(world: World) -> None:
    ids = small_world(world)
    store.build(world.db, apply=True)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None
    store.merge(world.db, keep, other, actor="admin:test")
    late = world.match("Netherlands", 50, "Michael Oliver")  # the same man, written in full in the Netherlands
    store.build(world.db, apply=True)
    assert world.referee_of(late) == keep, "the new spelling extends the Dutch 'M. Oliver', now a part of Michael Oliver"


def test_a_split_takes_aliases_to_a_new_referee_and_is_not_suggested_back(world: World) -> None:
    ids = small_world(world)
    store.build(world.db, apply=True)
    keep = world.referee_of(ids["full"])
    assert keep is not None
    with pytest.raises(store.ActionError, match="stay"):
        store.split(world.db, keep, [world.alias("m oliver", "england"), world.alias("michael oliver", "england")], actor="admin:test")
    new = store.split(world.db, keep, [world.alias("m oliver", "england")], actor="admin:test", name="Mark Oliver")
    assert world.referee_of(ids["initial"]) == new != keep
    assert world.one("SELECT name_locked FROM core.referees WHERE id = %s", new) is True
    assert world.one("SELECT origin FROM core.referees WHERE id = %s", new) == "manual"
    assert world.one("SELECT count(*) FROM core.referee_candidates WHERE status = 'rejected' AND referee_a = %s AND referee_b = %s", min(keep, new), max(keep, new)) == 1
    report = store.build(world.db, apply=True)
    assert (report.new_referees, report.new_aliases, report.officials_to_write, report.renamed) == (0, 0, 0, 0), report.as_dict()
    assert world.referee_of(ids["initial"]) == new, "a stored alias is never moved by the rules"
    # the rejected pair is not asked again; the split made new questions (the Dutch 'M. Oliver' now fits two referees)
    assert world.one("SELECT status FROM core.referee_candidates WHERE referee_a = %s AND referee_b = %s", min(keep, new), max(keep, new)) == "rejected"
    assert not store.build(world.db, apply=True).changed
    with pytest.raises(store.ActionError):
        store.split(world.db, keep, [999_999_999], actor="admin:test")


def test_rename_locks_the_name_and_giving_it_back_restores_the_rules(world: World) -> None:
    ids = small_world(world)
    store.build(world.db, apply=True)
    ref = world.referee_of(ids["full"])
    assert ref is not None
    store.rename(world.db, ref, "Michael L. Oliver", actor="admin:test")
    assert world.one("SELECT name FROM core.referees WHERE id = %s", ref) == "Michael L. Oliver"
    world.match("England", 60, "Michael Oliver", "England")
    store.build(world.db, apply=True)
    assert world.one("SELECT name FROM core.referees WHERE id = %s", ref) == "Michael L. Oliver", "a person's name stays"
    store.rename(world.db, ref, None, actor="admin:test")
    assert world.one("SELECT name FROM core.referees WHERE id = %s", ref) == "Michael Oliver"
    assert world.one("SELECT name_locked FROM core.referees WHERE id = %s", ref) is False
    with pytest.raises(store.ActionError):
        store.rename(world.db, ref, "   ", actor="admin:test")


def test_reject_and_reopen_a_pair(world: World) -> None:
    ids = small_world(world)
    store.build(world.db, apply=True)
    a, b = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert a is not None and b is not None
    store.reject(world.db, a, b, actor="admin:test", note="two men")
    assert world.one("SELECT status FROM core.referee_candidates") == "rejected"
    assert not store.build(world.db, apply=True).changed
    store.reopen(world.db, b, a, actor="admin:test")
    assert world.one("SELECT status FROM core.referee_candidates") == "open"
    with pytest.raises(store.ActionError):
        store.reopen(world.db, a, b, actor="admin:test")
    with pytest.raises(store.ActionError):
        store.reject(world.db, a, a, actor="admin:test")


def test_a_question_goes_away_when_the_data_answers_it(world: World) -> None:
    small_world(world)
    store.build(world.db, apply=True)
    assert world.one("SELECT count(*) FROM core.referee_candidates WHERE status = 'open'") == 1
    world.match("Netherlands", 1, "M. Oliver", hour=16)  # an hour after Michael Oliver's English match of that day: two men
    report = store.build(world.db, apply=True)
    assert report.candidates_removed == 1 and report.vetoes == 1
    assert world.one("SELECT count(*) FROM core.referee_candidates") == 0


def test_the_audit_says_what_is_placed_and_what_a_pass_would_still_write(world: World) -> None:
    small_world(world)
    before = store.audit(world.db)
    assert before["placed_share"] == 0.0 and before["pass_would_write"]["officials"] == 3
    store.build(world.db, apply=True)
    after = store.audit(world.db)
    assert after["placed_share"] == 1.0
    assert after["pass_would_write"] == {"referees": 0, "aliases": 0, "officials": 0, "renames": 0, "candidates": 0}
    assert (after["referees_active"], after["aliases"], after["candidates_open"]) == (2, 3, 1)
    assert after["active_without_alias"] == 0 and after["aliases_on_merged_referee"] == 0
    assert after["settled_share"] < 1.0 and after["matches_with_a_doubt"] == 1  # the Dutch 'M. Oliver' waits for a person


def test_a_pass_that_finds_the_lock_taken_does_nothing(world: World, migrated_database: str) -> None:
    small_world(world)
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (store.LOCK_KEY,))
        report = store.build(world.db, apply=True)
        assert report.skipped_locked and not report.applied
        assert world.one("SELECT count(*) FROM core.referees") == 0
        other.rollback()
    assert store.build(world.db, apply=True).applied
