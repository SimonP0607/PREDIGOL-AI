"""The Knowledge Store (``ks-v1``) over the real schema: a minimal row of each memory and relation, read back as one record type, and cut as of a moment.

One finished match (the golden one of ``knowledge_world``, put together by the Match Knowledge builder) and around it, for its home team, its
competition, its referee, a coach and a player: memory-v4 states, a memory-fam-v1 snapshot, the AI's events and a lesson, hypotheses, spells, caps, a
career and the officials of the match. Each source also gets something written LATER than the moment ``A`` (a newer day of memory, a lesson, a second
referee, a rebuilt spell, a new snapshot of a career, a family's settlement and post-mortem, a new build of the match), so that ``A`` must not see it
and ``B`` must. The transaction is rolled back afterwards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.core import decision_versions as dv
from fbi.knowledge import builder
from fbi.knowledge import store as ks
from tests.integration.conftest import Seed

from .helpers import scalar
from .knowledge_world import KICKOFF, World

pytestmark = pytest.mark.integration

A = KICKOFF + timedelta(days=2)
"""The moment asked about: the match is settled, put together, post-mortemed."""
FUTURE = KICKOFF + timedelta(days=4)
"""When everything A must not see was written."""
B = KICKOFF + timedelta(days=10)
"""A moment that sees everything."""


@dataclass
class Seeded:
    fid: int
    team: int
    other: int
    competition: int
    referee: int
    second_referee: int
    coach: int
    player: int
    ids: dict[str, list[str]]
    """Per source, the ids of the rows written after ``A``."""


def one(db: psycopg.Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(scalar(db.execute(sql, params)))


def entity_memory(db: psycopg.Connection[Any], kind: str, key: str, aspect: str, day: date, built: datetime, stats: dict[str, Any]) -> int:
    return one(db, "INSERT INTO intel.entity_memory (entity_type, entity_id, entity_name, aspect, as_of_day, built_at, version, stats, delta, sources, "
                   "confidence, evidence_ref) VALUES (%s, %s, 'x', %s, %s, %s, 'memory-v4', %s, '{}', '[]', 0.25, %s) RETURNING id",
               (kind, key, aspect, day, built, Jsonb(stats), Jsonb({"fixtures": [1]})))


def event(db: psycopg.Connection[Any], kind: str, entity_type: str, entity_id: str, at: datetime, fixture: int | None = None) -> int:
    return one(db, "INSERT INTO ai.memory_events (created_at, kind, entity_type, entity_id, fixture_id, hypothesis, evidence, result, confidence, sources, "
                   "version) VALUES (%s, %s, %s, %s, %s, 'h', '{\"n\": 1}', 'r', 0.6, '[]', 'test-v1') RETURNING id",
               (at, kind, entity_type, entity_id, fixture))


def hypothesis(db: psycopg.Connection[Any], title: str, evidence: dict[str, Any], created: datetime, history: list[dict[str, Any]]) -> int:
    decided = history[-1]["at"] if history else None
    status = history[-1]["to"] if history else "PROPOSED"
    return one(db, "INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, evidence, status, created_at, decided_at, "
                   "stage_history) VALUES ('system', %s, 'h', 'r', %s, %s, %s, %s, %s) RETURNING id",
               (title, Jsonb(evidence), status, created, decided, Jsonb(history)))


def referee(db: psycopg.Connection[Any], name: str) -> tuple[int, int]:
    rid = one(db, "INSERT INTO core.referees (name, name_key, origin, version) VALUES (%s, %s, 'rules', 'ref-v1') RETURNING id", (name, name.lower()))
    alias = one(db, "INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, version) "
                    "VALUES (%s, %s, 'test', %s, 'identity', 'rules', 'ref-v1') RETURNING id", (rid, name.lower(), name))
    return rid, alias


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Seeded:
    w = World(db, seed)
    fid = w.golden()
    builder.build_many(db, [fid], commit=False)
    team, other = w.team[0], w.team[1]
    competition = one(db, "SELECT cs.competition_id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                          "WHERE f.id = %s", (fid,))
    later: dict[str, list[str]] = {}

    # memory-v4: the day of the match (written that night) and the next day (written after A)
    day = KICKOFF.date()
    entity_memory(db, "team", str(team), "market:1X2", day, KICKOFF + timedelta(hours=6), {"settled": 1})
    entity_memory(db, "team", str(team), "corners", day, KICKOFF + timedelta(hours=6), {"matches": 1})
    later["intel.entity_memory"] = [str(entity_memory(db, "team", str(team), "market:1X2", day + timedelta(days=1), FUTURE, {"settled": 2}))]

    # the AI's log: an event of the team, a lesson written after A, an event of the match
    seen = event(db, "team_pattern", "team", str(team), KICKOFF + timedelta(hours=3))
    later["ai.memory_events"] = [str(event(db, "team_pattern", "team", str(team), FUTURE))]
    event(db, "match_result", "fixture", str(fid), KICKOFF + timedelta(hours=4), fixture=fid)
    event(db, "pick_postmortem", "market", "1X2:Home:0", KICKOFF + timedelta(hours=5), fixture=fid)

    # memory-fam-v1: the competition, as of the day of the match
    db.execute("INSERT INTO intel.family_memory (version, as_of_day, built_at, entity_type, entity_key, stats, confidence, evidence_ref) "
               "VALUES (%s, %s, %s, 'competition', %s, '{\"all\": {\"n\": 1}}', 0.1, '{\"postmortems\": 1}')",
               (dv.MEMORY_FAMILIES, day, KICKOFF + timedelta(hours=7), str(competition)))

    # hypotheses: one names the competition, one cites the team's event and was accepted after A
    hypothesis(db, "The league is forecast worse than the close", {"competition_id": competition}, KICKOFF + timedelta(days=1), [])
    hypothesis(db, "The team's pattern holds", {"memory_refs": [seen]}, KICKOFF + timedelta(days=1),
               [{"from": "PROPOSED", "to": "ACCEPTED", "at": FUTURE.isoformat()}])

    # the referee of the match, and a second observation after A that names another man
    first, first_alias = referee(db, "Referee One")
    second, second_alias = referee(db, "Referee Two")
    db.execute("INSERT INTO core.fixture_officials (fixture_id, role, observed_at, alias_id) VALUES (%s, 'referee', %s, %s), (%s, 'referee', %s, %s)",
               (fid, KICKOFF - timedelta(days=1), first_alias, fid, FUTURE, second_alias))
    later["core.fixture_officials"] = [f"{fid}:{FUTURE.isoformat()}"]

    # a player: a spell at the home club built before, a rebuilt one after; a cap
    provider_team = one(db, "SELECT provider_team_id FROM core.teams WHERE id = %s", (team,))
    db.execute("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, team_name, valid_from, valid_to, source, matches, "
               "last_evidence, version, built_at) VALUES (501, 0, %s, 'Knowledge 0', '2033-07-01', '2034-05-05', 'transfer', 30, '2034-05-02', "
               "'spells-v1', %s), (501, 1, 989799, 'Elsewhere', '2034-05-05', NULL, 'transfer', 0, '2034-05-05', 'spells-v1', %s)",
               (provider_team, KICKOFF - timedelta(days=10), FUTURE))
    later["core.player_spells"] = ["501:1"]
    db.execute("INSERT INTO core.player_national_caps (provider_player_id, fixture_id, team_id, is_starter, appeared, minutes, version, built_at) "
               "VALUES (501, %s, %s, true, true, 90, 'caps-v1', %s)", (fid, other, KICKOFF + timedelta(hours=3)))

    # a coach: his career as observed before A, and a new snapshot after it
    coach = one(db, "INSERT INTO core.coaches (provider_coach_id, name) VALUES (7001, 'Coach Home') RETURNING id")
    entity_memory(db, "coach", "p7001", "profile", day, KICKOFF + timedelta(hours=6), {"matches": 1})
    db.execute("INSERT INTO core.coach_careers (provider_coach_id, observed_at, ordinal, provider_team_id, team_name, start_date, end_date, payload_hash, "
               "normalizer_version, coach_id, team_id) VALUES (7001, %s, 0, %s, 'Knowledge 0', '2033-01-01', '2035-06-30', %s, 'n1', %s, %s), "
               "(7001, %s, 0, 989799, 'Elsewhere', '2034-05-05', NULL, %s, 'n1', %s, NULL)",
               (KICKOFF - timedelta(days=5), provider_team, seed.payload_hash, coach, team, FUTURE, seed.payload_hash, coach))
    later["core.coach_careers"] = [f"7001:{FUTURE.isoformat()}:0"]

    # a family's decision of the match (before the kick-off), settled and post-mortemed after A; the match's own post-mortem
    family = one(db, "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, "
                     "odds, p_model, filters, state, context_status, input_hash) VALUES (%s, %s, 'T-3h', %s, %s, 'CORNERS_OU', 'Over', 9.5, 'corners', "
                     "2.0, 0.55, '[]', 'INVESTIGACION', 'PENDING', 'fam-1') RETURNING id",
                 (dv.DECISION_FAMILIES, KICKOFF - timedelta(hours=3), fid, KICKOFF))
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, version, computed_at) "
               "VALUES (%s, %s, 'win', 1.0, 0, %s, %s)", (family, FUTURE, dv.OUTCOME_FAMILIES, FUTURE))
    later["intel.family_postmortems"] = [str(one(
        db, "INSERT INTO intel.family_postmortems (decision_id, version, created_at, fixture_id, kickoff_at, family, model_name, market_key, selection, "
            "line, competition_id, result, quality, verdict, odds, p_model, profit_flat, answers, evidence) VALUES (%s, %s, %s, %s, %s, 'CORNERS', "
            "'corners', 'CORNERS_OU', 'Over', 9.5, %s, 'win', 'UNKNOWN', 'SIN_DATOS', 2.0, 0.55, 1.0, '{}', '{}') RETURNING id",
        (family, dv.POSTMORTEM_FAMILIES, FUTURE + timedelta(hours=1), fid, KICKOFF, competition)))]
    db.execute("INSERT INTO intel.match_postmortems (fixture_id, created_at, version, outcome, findings) VALUES (%s, %s, 'pm-v6', '{\"score\": \"2-1\"}', '{}')",
               (fid, KICKOFF + timedelta(hours=12)))

    # Match Knowledge: the build the builder made, and a rebuild after A that supersedes it
    first_build = db.execute("SELECT id, known_at, layers, quality FROM intel.match_knowledge WHERE fixture_id = %s", (fid,)).fetchone()
    assert first_build is not None and first_build[1] <= A, "the golden match is put together, knowing what was known by the settlement"
    later["intel.match_knowledge"] = [str(one(
        db, "INSERT INTO intel.match_knowledge (fixture_id, version, supersedes, built_at, known_at, inputs_hash, content_hash, completeness, layers, "
            "quality) VALUES (%s, 'mk-v1', %s, %s, %s, %s, %s, 'complete', %s, %s) RETURNING id",
        (fid, first_build[0], FUTURE, FUTURE, "a" * 64, "b" * 64, Jsonb(first_build[2]), Jsonb(first_build[3]))))]
    return Seeded(fid, team, other, competition, first, second, coach, 501, later)


def ids_of(answer: ks.Answer, table: str) -> set[str]:
    return {r.source.id for r in answer.records if r.source.table == table}


def all_answers(db: psycopg.Connection[Any], w: Seeded, at: datetime) -> list[ks.Answer]:
    return [ks.about(db, "team", w.team, at=at), ks.about(db, "competition", w.competition, at=at), ks.about(db, "referee", w.referee, at=at),
            ks.about(db, "referee", w.second_referee, at=at), ks.about(db, "coach", w.coach, at=at), ks.about(db, "player", w.player, at=at),
            ks.about(db, "market", "1X2", at=at), ks.episode(db, w.fid, at=at), ks.relations(db, "team", w.team, at=at)]


def test_nothing_known_after_the_moment_is_returned(db: psycopg.Connection[Any], world: Seeded) -> None:
    """The proof of the as-of rule: at A no record is known after A and none of the rows written later appears; at B they all do."""
    for at in (KICKOFF - timedelta(days=2), KICKOFF + timedelta(hours=1), A):
        answers = all_answers(db, world, at)
        assert all(r.known_at <= at for a in answers for r in a.records)
        for table, later in world.ids.items():
            assert not set(later) & set().union(*(ids_of(a, table) for a in answers)), f"{table}: a row written after {at} was returned"
    everything = all_answers(db, world, B)
    for table, later in world.ids.items():
        assert set(later) <= set().union(*(ids_of(a, table) for a in everything)), f"{table}: the later row is seen once it was written"
    assert all(r.known_at <= B for a in everything for r in a.records)


def test_about_a_team(db: psycopg.Connection[Any], world: Seeded) -> None:
    answer = ks.about(db, "team", world.team, at=A)
    states = {r.aspect: r for r in answer.by_kind("entity_state")}
    assert set(states) == {"market:1X2", "corners"} and states["market:1X2"].value["stats"] == {"settled": 1}
    assert states["market:1X2"].known_at == ks.day_end(KICKOFF.date()) and states["market:1X2"].confidence == 0.25
    assert [r.aspect for r in answer.by_kind("lesson")] == ["team_pattern"]
    match = answer.by_kind("episode")
    assert [r.value["fixture_id"] for r in match] == [world.fid] and match[0].value["result"], "the match, with its result layer"
    hypotheses = answer.by_kind("hypothesis")
    assert [(h.value["title"], h.status) for h in hypotheses] == [("The team's pattern holds", "PROPOSED")]
    edges = {r.aspect for r in answer.by_kind("relation")}
    assert edges == {"player-club", "coach-club"}, "the club's players and coaches, but no cap: it is not a national side here"
    assert {a.source: a.reason for a in answer.absent}["intel.family_memory"] == "not_held"
    assert {a.source: a.reason for a in answer.absent}["core.player_national_caps"] == "none_as_of"
    later = ks.about(db, "team", world.team, at=B)
    assert {r.aspect: r.value["stats"] for r in later.by_kind("entity_state")}["market:1X2"] == {"settled": 2}
    assert [h.status for h in later.by_kind("hypothesis")] == ["ACCEPTED"]
    only = ks.about(db, "team", world.team, at=A, aspects=["corners"])
    assert [r.aspect for r in only.by_kind("entity_state")] == ["corners"]


def test_about_a_competition_and_a_market(db: psycopg.Connection[Any], world: Seeded) -> None:
    answer = ks.about(db, "competition", world.competition, at=A)
    family = [r for r in answer.by_kind("entity_state") if r.source.table == "intel.family_memory"]
    assert len(family) == 1 and family[0].aspect == "families" and family[0].source.version == dv.MEMORY_FAMILIES
    assert [h.value["title"] for h in answer.by_kind("hypothesis")] == ["The league is forecast worse than the close"]
    assert [r.value["fixture_id"] for r in answer.by_kind("episode")] == [world.fid]
    market = ks.about(db, "market", "1X2", at=A)
    assert market.entity.known and [(r.aspect, r.value["stored_as"]) for r in market.by_kind("event")] == [("pick_postmortem", "market:1X2:Home:0")]


def test_about_a_referee_a_coach_and_a_player(db: psycopg.Connection[Any], world: Seeded) -> None:
    ref = ks.about(db, "referee", world.referee, at=A)
    assert [r.value["fixture_id"] for r in ref.by_kind("relation")] == [world.fid] and [r.value["fixture_id"] for r in ref.by_kind("episode")] == [world.fid]
    assert ks.about(db, "referee", world.referee, at=B).by_kind("relation") == [], "a later observation named another man for the match"
    assert [r.value["fixture_id"] for r in ks.about(db, "referee", world.second_referee, at=B).by_kind("relation")] == [world.fid]
    coach = ks.about(db, "coach", world.coach, at=A)
    assert coach.entity.keys == (str(world.coach), "p7001")
    assert [r.aspect for r in coach.by_kind("entity_state")] == ["profile"], "memory-v4 keys him p<provider id>: found under the canonical id"
    career = coach.by_kind("relation")
    assert [(r.value["team_id"], r.valid_from, r.valid_to) for r in career] == [(world.team, date(2033, 1, 1), None)], "its end was not known yet"
    assert [r.value["team"] for r in ks.relations(db, "coach", world.coach, at=B).records] == ["Elsewhere"]
    player = ks.relations(db, "player", world.player, at=A)
    assert sorted((r.aspect, r.source.table) for r in player.records) == [("player-club", "core.player_spells"),
                                                                        ("player-national_team", "core.player_national_caps")]
    spell = next(r for r in player.records if r.aspect == "player-club")
    assert spell.value["team_id"] == world.team and spell.valid_to is None
    absent = {a.source: a.reason for a in ks.about(db, "player", world.player, at=A).absent}
    assert absent["intel.family_memory"] == "not_held" and absent["intel.entity_memory"] == "none_as_of" and "catalogue" in absent


def test_the_episode_of_a_match(db: psycopg.Connection[Any], world: Seeded) -> None:
    answer = ks.episode(db, world.fid, at=A)
    layers = {r.aspect: r for r in answer.by_kind("episode")}
    assert {"c1_result", "c8_picks", "c9_postmortem", "completeness"} <= set(layers) and len(layers) == 10
    assert layers["c1_result"].status == "ok" and layers["c1_result"].source.table == "intel.match_knowledge"
    decisions = [r for r in answer.by_kind("event") if r.source.table == "intel.decisions"]
    assert sorted(r.value["layer"] for r in decisions) == ["core", "core", "families"]
    family = next(r for r in decisions if r.value["layer"] == "families")
    assert family.value["outcome"] is None, "settled after A"
    assert all(r.value["outcome"] for r in decisions if r.value["layer"] == "core")
    tables = {r.source.table for r in answer.records}
    assert {"intel.postmortems", "intel.match_postmortems", "ai.memory_events", "core.fixture_officials"} <= tables
    assert "intel.family_postmortems" in {a.source for a in answer.absent}
    later = ks.episode(db, world.fid, at=B)
    assert ids_of(later, "intel.match_knowledge") == set(world.ids["intel.match_knowledge"]), "the newest build by then"
    assert next(r for r in later.records if r.source.table == "intel.decisions" and r.value["layer"] == "families").value["outcome"]["result"] == "win"
    assert [r.value["referee_id"] for r in later.by_kind("relation")] == [world.second_referee]
    before = ks.episode(db, world.fid, at=KICKOFF - timedelta(hours=4))
    assert before.records == () and {a.source for a in before.absent} >= {"intel.match_knowledge", "intel.decisions"}
    assert ks.episode(db, 10**12, at=A).absent[0].reason == "not_in_catalogue"


def test_coverage_counts_what_each_memory_holds(db: psycopg.Connection[Any], world: Seeded) -> None:
    report = ks.coverage(db)
    team = report["types"]["team"]
    for source in ("intel.entity_memory", "ai.memory_events", "intel.match_knowledge", "core.player_spells", "core.coach_careers"):
        assert team["sources"][source] >= 1, source
    assert team["pairs"]["ai.memory_events & intel.entity_memory"] >= 1 and team["union"] >= 2
    assert team["not_held_by"] == ["core.fixture_officials", "intel.family_memory"]
    coach = report["types"]["coach"]
    assert coach["pairs"]["core.coach_careers & intel.entity_memory"] >= 1, "the p<provider id> of memory-v4 resolved to the person"
    assert report["types"]["referee"]["sources"]["core.fixture_officials"] >= 2
    assert report["types"]["market"]["sources"]["ai.memory_events"] >= 1
    assert report["types"]["competition"]["sources"]["analytics.research_hypotheses"] >= 1


def test_the_store_writes_nothing(db: psycopg.Connection[Any], world: Seeded) -> None:
    """Read inside a read-only transaction: any write would fail it."""
    db.execute("SAVEPOINT ks")
    db.execute("SET LOCAL transaction_read_only = on")
    all_answers(db, world, B)
    ks.coverage(db)
    db.execute("ROLLBACK TO SAVEPOINT ks")


def test_an_unknown_entity_is_read_under_the_id_given(db: psycopg.Connection[Any], world: Seeded) -> None:
    entity_memory(db, "referee", "999999", "discipline", KICKOFF.date(), KICKOFF + timedelta(hours=6), {"matches": 1})
    answer = ks.about(db, "referee", 999999, at=A)
    assert not answer.entity.known and [r.aspect for r in answer.by_kind("entity_state")] == ["discipline"]
    assert "catalogue" in {a.source for a in answer.absent}
    with pytest.raises(ValueError, match="unknown entity type"):
        ks.about(db, "fixture", 1, at=A)
