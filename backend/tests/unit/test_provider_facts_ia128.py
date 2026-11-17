"""IA-128 (AD-C10): API-Football's line-ups, absences, suspensions and events as typed assertions of the same model, with authority, four
dates and a moment of knowledge; its coverage per competition as a fact - «sin dato», never «sin bajas»."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fbi.ai import assertions
from fbi.ai import provider_facts as pf

BACKEND = Path(__file__).resolve().parents[2]
KICKOFF = datetime(2026, 11, 20, 20, tzinfo=UTC)
SEEN = KICKOFF - timedelta(hours=1)
MEDICAL = "Hamstring Injury"


def lineup() -> pf.Made:
    made = pf.Made()
    pf.lineup_facts(made, fixture_id=1, kickoff_at=KICKOFF, team_id=10, side="home", players=[(100, True), (101, True), (102, False), (None, False)],
                    seen_at=SEEN, known_from="arrival")
    return made


def obs(pid: int, at: datetime, status: str = "LISTED", kind: str | None = "Missing Fixture", reason: str | None = MEDICAL) -> dict[str, object]:
    return {"provider_player_id": pid, "provider_team_id": 33, "observed_at": at, "status": status, "absence_type": kind, "reason": reason}


def injuries(rows: list[dict[str, object]]) -> pf.Made:
    made = pf.Made()
    pf.injury_facts(made, fixture_id=1, kickoff_at=KICKOFF, team_of={33: 10}, observations=rows)
    return made


def test_every_player_of_a_registered_line_up_is_an_assertion_that_confirms_with_its_four_dates() -> None:
    made = lineup()
    assert [f.assertion.claim_type for f in made.facts] == ["STARTER", "STARTER", "AVAILABLE"]
    assert made.untyped == {"lineup_player_without_id": 1}
    for f in made.facts:
        a = f.assertion
        assert a.source is pf.PROVIDER and a.source.source_id == "api-football" and a.authority == "confirma"
        assert a.published_at is None and a.published_from == "none", "the provider gives no publication date: never today's"
        assert a.seen_at == SEEN and f.known_at == SEEN and f.known_from == "arrival"
        assert a.fact_at == KICKOFF and a.valid_until is not None and a.valid_until > SEEN and a.fixture_id == 1
    assert {k.rung for k in pf.rungs(made.facts, at=SEEN)} == {"OFICIAL"}
    empty = pf.Made()
    pf.lineup_facts(empty, fixture_id=1, kickoff_at=KICKOFF, team_id=10, side="home", players=[(1, False)], seen_at=SEEN, known_from="arrival")
    assert not empty.facts and empty.untyped == {"lineup_without_starters": 1}


def test_absences_and_suspensions_inform_and_never_carry_the_medical_detail() -> None:
    made = injuries([obs(1, SEEN), obs(2, SEEN, reason="Red Card"), obs(3, SEEN, kind="Questionable"), obs(4, SEEN, kind="Something")])
    types = {f.assertion.subject_id: f.assertion.claim_type for f in made.facts}
    assert types == {1: "OUT", 2: "SUSPENSION", 3: "DOUBT"} and made.untyped == {"absence_type_unknown": 1}
    assert {f.assertion.authority for f in made.facts} == {"informa"}
    assert {k.rung for k in pf.rungs(made.facts, at=SEEN)} == {"REPORTE"}, "one origin informs: a report, never official"
    dumped = json.dumps([f.as_json() for f in made.facts], default=str)
    assert MEDICAL not in dumped and "Hamstring" not in dumped and "Red Card" not in dumped
    assert all(f.assertion.quote == "" for f in made.facts)


def test_an_absence_is_valid_until_the_provider_changes_it_and_a_cleared_player_is_no_longer_out() -> None:
    cleared = SEEN + timedelta(hours=3)
    made = injuries([obs(1, SEEN), obs(1, cleared, status="CLEARED", kind=None, reason=None)])
    (fact,) = made.facts
    assert fact.assertion.valid_until == cleared
    assert assertions.live([fact.assertion], SEEN + timedelta(hours=1))
    assert not assertions.live([fact.assertion], cleared + timedelta(minutes=1))


def test_nothing_known_after_the_moment_of_a_decision_enters_it() -> None:
    later = lineup().facts + injuries([obs(1, SEEN + timedelta(minutes=30))]).facts
    assert pf.as_of(later, SEEN - timedelta(minutes=1)) == []
    assert len(pf.as_of(later, SEEN)) == 3 and len(pf.as_of(later, SEEN + timedelta(minutes=30))) == 4
    assert pf.rungs(later, at=SEEN - timedelta(minutes=1)) == []


def test_events_confirm_and_an_event_without_a_player_is_not_guessed() -> None:
    made = pf.Made()
    after = KICKOFF + timedelta(hours=2)
    pf.event_facts(made, fixture_id=1, kickoff_at=KICKOFF, team_of={"home": 10, "away": 11}, events=[
        {"seq": 0, "minute": 23, "extra_minute": None, "team_side": "home", "provider_player_id": 100, "event_type": "Goal", "detail": "Normal Goal",
         "fetched_at": after},
        {"seq": 1, "minute": 50, "extra_minute": 2, "team_side": "away", "provider_player_id": 200, "event_type": "Card", "detail": "Red Card",
         "fetched_at": after},
        {"seq": 2, "minute": 60, "extra_minute": None, "team_side": "away", "provider_player_id": None, "event_type": "subst", "detail": None,
         "fetched_at": after},
        {"seq": 3, "minute": 61, "extra_minute": None, "team_side": "away", "provider_player_id": 9, "event_type": "Weird", "detail": None,
         "fetched_at": after}])
    assert [f.assertion.claim_type for f in made.facts] == ["EVENT_GOAL", "EVENT_CARD"]
    assert {f.assertion.authority for f in made.facts} == {"confirma"} and made.facts[1].assertion.team_id == 11
    assert made.untyped == {"event_without_player": 1, "event_type_unknown": 1}


def test_a_competition_the_provider_does_not_cover_is_no_data_never_no_absences() -> None:
    none = pf.coverage_facts({"injuries": False, "lineups": True, "events": True})
    assert none["injuries"] == {"state": "no_cubre", "means": "el proveedor no da bajas en esta competición"}
    assert pf.availability_word(none, checked_at=SEEN, listed=0)[0] == "sin_dato"
    unknown = pf.coverage_facts(None)
    assert {v["state"] for v in unknown.values()} == {"desconocida"} and pf.availability_word(unknown, checked_at=SEEN, listed=0)[0] == "sin_dato"
    covered = pf.coverage_facts({"injuries": True, "lineups": True, "events": True})
    assert pf.availability_word(covered, checked_at=None, listed=0)[0] == "sin_dato", "not asked for is not «nobody»"
    assert pf.availability_word(covered, checked_at=SEEN, listed=0)[0] == "sin_bajas_listadas"
    assert pf.availability_word(covered, checked_at=SEEN, listed=2)[0] == "con_bajas"


def test_the_replay_against_todays_statuses_lists_only_what_differs_with_its_reason() -> None:
    facts = lineup().facts + injuries([obs(1, SEEN), obs(2, SEEN, kind="Questionable"), obs(3, SEEN - timedelta(hours=5)),
                                       obs(3, SEEN - timedelta(hours=2), status="CLEARED", kind=None, reason=None)]).facts
    evidence: list[dict[str, Any]] = [
        {"id": 1, "fixture_id": 1, "team_id": 10, "provider_player_id": None, "kind": "lineup", "status": "CONFIRMED", "status_changed_at": SEEN,
         "retrieved_at": SEEN},
        {"id": 2, "fixture_id": 1, "team_id": 10, "provider_player_id": 1, "kind": "injury", "status": "PROBABLE", "status_changed_at": SEEN,
         "retrieved_at": SEEN},
        {"id": 3, "fixture_id": 1, "team_id": 10, "provider_player_id": 2, "kind": "doubtful", "status": "PROBABLE", "status_changed_at": SEEN,
         "retrieved_at": SEEN},
        {"id": 4, "fixture_id": 1, "team_id": 10, "provider_player_id": 3, "kind": "injury", "status": "OUTDATED", "status_changed_at": SEEN,
         "retrieved_at": SEEN},
        {"id": 5, "fixture_id": 1, "team_id": 11, "provider_player_id": None, "kind": "lineup", "status": "CONFIRMED", "status_changed_at": SEEN,
         "retrieved_at": SEEN},
    ]
    rep = pf.replay(evidence, facts)
    assert rep["matrix"]["lineup:CONFIRMED->OFICIAL"] == 1 and rep["matrix"]["injury:PROBABLE->REPORTE"] == 1
    assert rep["matrix"]["injury:OUTDATED->retirada"] == 1
    assert rep["differences"] == 1 and rep["by_reason"] == {"sin_afirmacion": 1}, rep
    assert rep["decides"] is False


def test_the_provider_is_a_source_with_authority_per_type_and_never_a_d_source() -> None:
    assert pf.PROVIDER.tier == "A" and pf.PROVIDER.domain == "api-football.com"
    assert pf.AUTHORITY["alineaciones"]["level"] == "confirma"
    assert pf.AUTHORITY["lesiones"]["level"] == pf.AUTHORITY["sanciones"]["level"] == "informa"
    assert pf.authority_of("STARTER") == "confirma" and pf.authority_of("OUT") == "informa" and pf.authority_of("EVENT_GOAL") == "confirma"


def test_no_new_request_reaches_the_provider() -> None:
    for rel in ("src/fbi/ai/provider_facts.py", "src/fbi/ai/provider_facts_reads.py", "scripts/ia_provider_facts.py"):
        text = (BACKEND / rel).read_text(encoding="utf-8")
        for word in ("httpx", "api_football.client", "providers.api_football", "INSERT INTO", "UPDATE "):
            assert word not in text, (rel, word)
