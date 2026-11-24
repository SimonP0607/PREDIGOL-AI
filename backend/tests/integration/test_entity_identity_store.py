"""External identity and aliases in the database (AD-H01/H02/H09, IA-071): a load is a version, the same release writes nothing
twice, a later one retires what it no longer has, retiring a load brings the previous one back, a person's decision survives
the next load, the old alias tables are absorbed one for one, and the player key is kept by the trigger.

Every test runs in a transaction that is rolled back (the shared test database keeps nothing of it)."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import date
from typing import Any

import psycopg
import pytest

from fbi.people.identity import store
from fbi.people.identity.reep import Alias, Bridge, ExternalRef, ReepData
from fbi.people.identity.rules import Ours
from fbi.players.positions import position_group
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

TODAY = date(2026, 11, 16)
SHA = "a" * 64
_pid = itertools.count(7_100_000)


@pytest.fixture
def db(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as conn:
        yield conn
        conn.rollback()


def one(db: psycopg.Connection[Any], sql: str, *params: object) -> Any:
    return scalar(db.execute(sql, params))


def player(db: psycopg.Connection[Any], name: str, *, first: str | None = None, last: str | None = None,
           birth: date | None = None) -> tuple[int, int]:
    pid = next(_pid)
    eid = int(one(db, "INSERT INTO core.players (provider_player_id, name, firstname, lastname, birth_date) "
                      "VALUES (%s, %s, %s, %s, %s) RETURNING id", pid, name, first, last, birth))
    return eid, pid


def _reep(bridges: dict[int, list[str]], names: dict[str, str]) -> ReepData:
    d = ReepData()
    for pid, reep_ids in bridges.items():
        d.bridges[("player", pid)] = [Bridge(r, "player", 1.0, "test") for r in reep_ids]
    for reep_id, name in names.items():
        d.names[reep_id] = name
        d.externals[reep_id] = [ExternalRef("wikidata", "", "Q" + str(abs(hash(reep_id)) % 10**8), 0.85),
                                ExternalRef("transfermarkt", "spieler", str(abs(hash(reep_id)) % 10**6), 1.0)]
        d.aliases[reep_id] = [Alias(name.upper(), "label", "wikidata", "es", 0.8)]
    return d


def _ours(db: psycopg.Connection[Any], ids: list[int]) -> list[Ours]:
    return [e for e in store.our_entities(db, "player") if e.entity_id in ids]


def _load(db: psycopg.Connection[Any], data: ReepData, release: str, ids: list[int]) -> store.LoadReport:
    return store.load_reep(db, data, release=release, release_sha256=SHA, files={"bridges": SHA}, as_of=TODAY,
                           actor="test", entities=_ours(db, ids))


def _state(db: psycopg.Connection[Any], eid: int, system: str = "reep") -> list[tuple[str, str]]:
    return [(r[0], r[1]) for r in db.execute(
        "SELECT external_id, state FROM core.entity_ids_live WHERE entity_type = 'player' AND entity_id = %s "
        "AND system = %s ORDER BY 1", (eid, system)).fetchall()]


def test_a_release_loads_once_and_a_later_one_retires_what_it_no_longer_has(db: psycopg.Connection[Any]) -> None:
    salah, pid_s = player(db, "M. Salah", first="Mohamed", last="Salah Hamed Ghaly", birth=date(1992, 6, 15))
    other, pid_o = player(db, "J. Doe", first="John", last="Doe", birth=date(1990, 1, 1))
    ids = [salah, other]
    v1 = _reep({pid_s: ["rp_salah"], pid_o: ["rp_doe"]}, {"rp_salah": "Mohamed Salah", "rp_doe": "John Doe"})
    first = _load(db, v1, "t-1", ids)
    assert first.load_id is not None and not first.already_loaded
    assert _state(db, salah) == [("rp_salah", "accepted")]
    assert _state(db, salah, "wikidata")[0][1] == "accepted"
    rows = one(db, "SELECT count(*) FROM core.entity_ids WHERE load_id = %s", first.load_id)

    again = _load(db, v1, "t-1", ids)
    assert again.already_loaded and again.load_id == first.load_id
    assert one(db, "SELECT count(*) FROM core.entity_ids") >= rows
    assert one(db, "SELECT count(*) FROM core.entity_id_loads WHERE release = 't-1'") == 1, "same release, same rows"

    v2 = _reep({pid_s: ["rp_salah"]}, {"rp_salah": "Mohamed Salah"})
    second = _load(db, v2, "t-2", ids)
    assert second.counts["ids_retired"] == 3, "John Doe's Reep, Wikidata and Transfermarkt ids"
    assert second.counts["ids_added"] == 0
    assert _state(db, other) == []
    assert _state(db, salah) == [("rp_salah", "accepted")]

    assert store.retire_load(db, int(second.load_id or 0), actor="test", note="bad release")
    assert _state(db, other) == [("rp_doe", "accepted")], "retiring a load brings back what it retired"
    assert not store.retire_load(db, int(second.load_id or 0), actor="test", note="twice")


def test_conflicts_wait_and_a_decision_survives_the_next_load(db: psycopg.Connection[Any]) -> None:
    a, pid_a = player(db, "K. Vazquez", first="Kevin", last="Vazquez", birth=date(2001, 2, 3))
    b, pid_b = player(db, "K. Vazquez", first="Kevin", last="Vazquez", birth=date(2001, 2, 3))
    c, pid_c = player(db, "M. Elneny", first="Mohamed", last="Elneny", birth=date(1992, 7, 11))
    d, pid_d = player(db, "M. Salah", first="Mohamed", last="Salah", birth=date(1983, 1, 1))
    ids = [a, b, c, d]
    data = _reep({pid_a: ["rp_kv"], pid_b: ["rp_kv"], pid_c: ["rp_salah"], pid_d: ["rp_salah", "rp_salah83"]},
                 {"rp_kv": "Kevin Vázquez", "rp_salah": "Mohamed Salah", "rp_salah83": "Mohamed Salah"})
    _load(db, data, "t-c1", ids)
    assert _state(db, a) == [("rp_kv", "pending")] and _state(db, b) == [("rp_kv", "pending")]
    assert _state(db, d) == [], "one API-Football id, two Reep entities: nothing"
    kinds = dict(db.execute("SELECT kind, count(*) FROM core.entity_identity_queue_open WHERE entity_a = ANY(%s) "
                            "GROUP BY 1", (ids,)).fetchall())
    assert kinds == {"shared_external": 1, "name_mismatch": 1, "bridge_conflict": 1}
    assert one(db, "SELECT count(*) FROM core.entity_aliases_live WHERE entity_type = 'player' AND entity_id = %s "
                   "AND source = 'wikidata'", c) == 0, "a pending link brings no names"

    mismatch = int(one(db, "SELECT id FROM core.entity_identity_queue_open WHERE kind = 'name_mismatch' "
                           "AND entity_a = %s", c))
    with pytest.raises(store.DecisionError):
        store.decide(db, mismatch, "same", actor="test")
    written = store.decide(db, mismatch, "reject", actor="test", note="Elneny is not Salah")
    assert len(written) == 3
    assert {s for _x, s in _state(db, c)} == {"rejected"}
    assert one(db, "SELECT count(*) FROM core.entity_identity_queue_open WHERE id = %s", mismatch) == 0

    shared = int(one(db, "SELECT id FROM core.entity_identity_queue_open WHERE kind = 'shared_external' "
                         "AND entity_a = %s", min(a, b)))
    store.decide(db, shared, "keep_a", actor="test")
    assert _state(db, min(a, b)) == [("rp_kv", "accepted")] and _state(db, max(a, b)) == [("rp_kv", "rejected")]

    data.bridges[("player", 9_999_999)] = []  # a new release with the same links
    _load(db, data, "t-c2", ids)
    assert {s for _x, s in _state(db, c)} == {"rejected"}, "the decision holds over the next release"
    assert one(db, "SELECT count(*) FROM core.entity_identity_queue_open WHERE id = %s", mismatch) == 0

    store.undo(db, actor="test", queue_id=mismatch)
    assert {s for _x, s in _state(db, c)} == {"pending"}
    assert one(db, "SELECT count(*) FROM core.entity_identity_queue_open WHERE id = %s", mismatch) == 1

    with pytest.raises(store.DecisionError):
        store.decide_link(db, ("player", c, "reep", "", "rp_nobody"), "reject", actor="test")
    store.decide_link(db, ("player", c, "reep", "", "rp_salah"), "accept", actor="test")
    assert _state(db, c) == [("rp_salah", "accepted")]
    assert one(db, "SELECT count(*) FROM core.entity_aliases_live WHERE entity_type = 'player' AND entity_id = %s "
                   "AND source = 'wikidata'", c) == 1, "accepted: its names are shown"


def test_rows_are_never_changed_or_deleted(db: psycopg.Connection[Any]) -> None:
    e, pid = player(db, "A. Guard")
    _load(db, _reep({pid: ["rp_guard"]}, {"rp_guard": "Alan Guard"}), "t-g", [e])
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE core.entity_ids SET confidence = 0 WHERE entity_id = %s", (e,))
    db.rollback()
    e, pid = player(db, "A. Guard")
    _load(db, _reep({pid: ["rp_guard"]}, {"rp_guard": "Alan Guard"}), "t-g", [e])
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("DELETE FROM core.entity_aliases WHERE entity_id = %s", (e,))


def test_the_old_alias_tables_and_our_names_are_absorbed_one_for_one(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("INSERT INTO core.team_aliases (source, alias, team_id, method) VALUES ('football-data.co.uk', 'Man United', "
               "%s, 'fixture_and_score')", (seed.home_team_id,))
    ref = int(one(db, "INSERT INTO core.referees (name, name_key, origin, version) VALUES ('Michael Oliver', "
                      "'michael oliver', 'rules', 'test') RETURNING id"))
    ref2 = int(one(db, "INSERT INTO core.referees (name, name_key, origin, version) VALUES ('Mike Oliver', "
                       "'mike oliver', 'rules', 'test') RETURNING id"))
    alias_id = int(one(db, "INSERT INTO core.referee_aliases (referee_id, name_key, scope, display, basis, placed_by, "
                           "version) VALUES (%s, 'm oliver', 'england', 'M. Oliver', 'initial', 'rules', 'test') "
                           "RETURNING id", ref))
    db.execute("INSERT INTO core.coaches (provider_coach_id, name, firstname, lastname) VALUES (7_100_001, "
               "'J. Klopp', 'Jürgen', 'Klopp')")
    db.execute("INSERT INTO core.venues (provider_venue_id, name) VALUES (7_100_001, 'Estadio El Campín')")
    e, _ = player(db, "M. Salah", first="Mohamed", last="Salah Hamed Ghaly", birth=date(1992, 6, 15))
    twin_a, _ = player(db, "Z. Twin", first="Zed", last="Twin", birth=date(2000, 1, 1))
    twin_b, _ = player(db, "Z. Twin", first="Zed", last="Twin", birth=date(2000, 1, 1))

    first = store.sync_core(db, actor="test")
    assert first.load_id is not None
    checks = {c.name: c for c in store.audit(db)}
    assert checks["aliases of core.team_aliases in core.entity_aliases"].ok
    assert checks["aliases of core.referee_aliases in core.entity_aliases"].ok
    assert checks["searchable entity types with an official name"].ok
    names = {r[0]: r[1] for r in db.execute("SELECT alias, alias_type FROM core.entity_aliases_live WHERE "
                                            "entity_type = 'player' AND entity_id = %s", (e,)).fetchall()}
    assert names == {"M. Salah": "official", "Mohamed Salah Hamed Ghaly": "full"}
    assert one(db, "SELECT count(*) FROM core.entity_aliases_live WHERE entity_type = 'player' AND alias_key = 'salah' "
                   "AND entity_id = %s", e) == 0, "a surname alone is never a name of his"
    assert one(db, "SELECT count(*) FROM core.entity_aliases_live WHERE alias_key = 'estadio el campin' "
                   "AND entity_type = 'venue'") == 1
    dup = db.execute("SELECT id, kind FROM core.entity_identity_queue_open WHERE entity_a = %s AND entity_b = %s",
                     (min(twin_a, twin_b), max(twin_a, twin_b))).fetchone()
    assert dup is not None and dup[1] == "possible_duplicate"

    assert store.sync_core(db, actor="test").already_loaded, "nothing changed: nothing written"

    db.execute("UPDATE core.referee_aliases SET referee_id = %s WHERE id = %s", (ref2, alias_id))  # a merge moves it
    moved = store.sync_core(db, actor="test")
    assert (moved.counts["aliases_added"], moved.counts["aliases_retired"]) == (1, 1)
    assert one(db, "SELECT entity_id FROM core.entity_aliases_live WHERE source = 'core.referee_aliases' "
                   "AND alias = 'M. Oliver'") == ref2
    store.decide(db, int(dup[0]), "different", actor="test")
    assert one(db, "SELECT count(*) FROM core.entity_identity_queue_open WHERE id = %s", dup[0]) == 0


def test_the_player_key_is_kept_by_the_trigger(db: psycopg.Connection[Any], seed: Seed) -> None:
    e, pid = player(db, "K. Key")
    db.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, position, first_seen_at, "
               "last_seen_at, payload_hash) VALUES (%s, %s, 'K. Key', 'Midfielder', now(), now(), 'h')",
               (seed.home_team_id, pid))
    assert one(db, "SELECT player_id FROM core.squad_members WHERE provider_player_id = %s", pid) == e
    orphan = next(_pid)
    db.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, position, first_seen_at, "
               "last_seen_at, payload_hash) VALUES (%s, %s, 'N. Body', 'D', now(), now(), %s)",
               (seed.home_team_id, orphan, seed.payload_hash))
    assert one(db, "SELECT player_id FROM core.squad_members WHERE provider_player_id = %s", orphan) is None
    db.execute("UPDATE core.squad_members SET player_id = %s WHERE provider_player_id = %s", (e, orphan))
    assert one(db, "SELECT player_id FROM core.squad_members WHERE provider_player_id = %s", orphan) is None, \
        "derived, never typed"
    evidence = int(one(db, "INSERT INTO ai.evidence (fixture_id, provider_player_id, kind, claim, origin, source_name, "
                           "source_tier, retrieved_at, story_key, content_hash, confidence, relevance, status, "
                           "status_reason, status_changed_at) VALUES (%s, %s, 'injury', 'K. Key is injured', 'provider', "
                           "'test', 'provider', now(), 'story-key-071', 'hash-key-071', 0.9, 0.9, 'CONFIRMED', 'test', "
                           "now()) RETURNING id", seed.fixture_id, pid))
    assert one(db, "SELECT player_id FROM ai.evidence WHERE id = %s", evidence) == e
    db.execute("UPDATE ai.evidence SET status = 'OUTDATED', status_reason = 'later', status_changed_at = now() "
               "WHERE id = %s", (evidence,))
    assert one(db, "SELECT player_id FROM ai.evidence WHERE id = %s", evidence) == e
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("UPDATE ai.evidence SET claim = 'changed claim text' WHERE id = %s", (evidence,))


def test_the_sql_position_table_is_the_python_one(db: psycopg.Connection[Any]) -> None:
    values = ["Midfielder", "M", "Defender", "D", "Attacker", "Forward", "F", "Goalkeeper", "G", "SUB", "U",
              "Substitute", "", "Centre-Back", "left winger", "  defender ", "portero", "Wizard"]
    sql = dict(db.execute("SELECT v, core.position_group(v) FROM unnest(%s::text[]) v", (values,)).fetchall())
    assert sql == {v: position_group(v) for v in values}
    assert one(db, "SELECT core.position_group(NULL)") is None


def test_national_teams_and_competitions_get_their_spanish_and_english_names(db: psycopg.Connection[Any]) -> None:
    """C-10 1.1 (AP-B02, AP-B07): the localized names enter with our own names, with their language, as source
    ``localized``; a club named like a country gets nothing, and a second sync writes nothing."""
    teams = {}
    for pid, name, national in ((7_100_101, "Spain", True), (7_100_102, "Spain U21", True), (7_100_103, "Mexico W U17", True),
                                (7_100_104, "England", False)):
        teams[name] = int(one(db, "INSERT INTO core.teams (provider_team_id, name, country, is_national) VALUES (%s, %s, "
                                  "'Spain', %s) RETURNING id", pid, name, national))
    cup = int(one(db, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                      "competition_type) VALUES (7_100_101, 'World Cup', 'World', 'cup', 'national_team', 'international') "
                      "RETURNING id"))
    store.sync_core(db, actor="test")

    def localized(etype: str, eid: int) -> set[tuple[str, tuple[str, ...]]]:
        rows = db.execute("SELECT alias, languages FROM core.entity_aliases_live WHERE entity_type = %s AND entity_id = %s "
                          "AND alias_type = 'localized' AND source = 'localized'", (etype, eid)).fetchall()
        return {(r[0], tuple(r[1])) for r in rows}

    assert localized("team", teams["Spain"]) == {("España", ("es",))}  # «Spain» in English is its own name already
    assert localized("team", teams["Spain U21"]) == {("España Sub-21", ("es",))}
    assert localized("team", teams["Mexico W U17"]) == {("México Femenina Sub-17", ("es",)), ("Mexico Women U17", ("en",))}
    assert localized("team", teams["England"]) == set(), "only a national team gets a country's names"
    assert {("Mundial", ("es",)), ("Copa del Mundo", ("es",)), ("FIFA World Cup", ("en",))} <= localized("competition", cup)
    assert store.sync_core(db, actor="test").already_loaded
