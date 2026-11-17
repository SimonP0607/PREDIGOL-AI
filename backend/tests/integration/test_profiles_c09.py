"""C-09, the profiles, against a real database (AD-H07 IA-090, AD-H05 IA-091, AD-H06 IA-092): what each block reads, the
parity of the rates per 90 with ``core.fixture_player_stats``, availability with its precedence and no diagnosis, the
national team's list from the provider with its reason, and the two projections over HTTP."""

from __future__ import annotations

import json
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.contracts.intelligence.profiles import Profile, ProfilePrivate
from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.deps import get_db
from fbi.api.services import profiles
from fbi.api.switches import PROFILES
from tests.integration import profiles_world
from tests.integration.conftest import Seed
from tests.integration.profiles_world import AT, DIAGNOSIS, World
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return profiles_world.build(db, seed.payload_hash)


def public_json(answer: ProfilePrivate) -> dict[str, Any]:
    data: dict[str, Any] = to_public(answer, Profile).model_dump(mode="json")
    assert leaks(data, public_schema=Profile.model_json_schema(mode="serialization"),
                 private_schema=ProfilePrivate.model_json_schema(mode="serialization")) == []
    return data


def test_a_clubs_profile(db: psycopg.Connection[Any], world: World) -> None:
    answer = profiles.build_team(db, world.club_id, at=AT)
    team = answer.team
    assert team is not None and answer.kind == "club" and team.national is None
    assert team.header.coach.name == "G. Ejemplo" and team.header.coach.basis == "ultima_alineacion"  # type: ignore[union-attr]
    assert [f.result for f in team.form.items] == ["L", "D", "L", "L", "D"]  # newest first, the team's goals first
    stats = team.season_stats
    assert stats.record.matches == 6 and stats.home.matches == 3 and stats.away.matches == 3  # type: ignore[union-attr]
    assert stats.xg_for.matches_with_data == 3 and stats.xg_for.per_match == 1.4  # type: ignore[union-attr]
    assert [(h.competition.name, h.season) for h in team.honours.computed.items] == [("Liga Ejemplo", 2025)]
    assert team.honours.since_season == 2025
    [record] = team.competitions.items
    assert (record.rank, record.points) == (2, 28)
    [selection] = team.intelligence.items
    assert selection.state == "detectado"
    data = public_json(answer)
    assert "intelligence" not in data["team"] and "identity" not in data["team"]


def test_availability_states_its_basis_and_never_a_diagnosis(db: psycopg.Connection[Any], world: World) -> None:
    team = profiles.build_team(db, world.club_id, at=AT).team
    assert team is not None
    block = team.availability
    [out] = block.unavailable.items  # type: ignore[union-attr]
    assert (out.name, out.status, out.basis) == ("B. Ejemplo", "sancionado", "proveedor")
    assert out.player_id == world.rookie_id
    striker = profiles.build_player(db, world.striker_id, at=AT).player
    assert striker is not None
    # the report was asked for and does not name him: «disponible» from the provider beats one outlet saying «duda»
    assert (striker.availability.status, striker.availability.basis) == ("disponible", "proveedor")  # type: ignore[union-attr]
    for answer in (profiles.build_team(db, world.club_id, at=AT), profiles.build_player(db, world.striker_id, at=AT)):
        text = json.dumps(answer.model_dump(mode="json"), ensure_ascii=False)
        assert DIAGNOSIS not in text and "ligamento" not in text and "Red Card" not in text


def test_outside_the_providers_coverage_availability_says_so(db: psycopg.Connection[Any], world: World) -> None:
    db.execute("DELETE FROM core.context_checks WHERE competition_season_id = %s", (world.season_id,))
    db.execute("DELETE FROM core.player_availability_obs WHERE fixture_id = %s", (world.next_fixture_id,))
    team = profiles.build_team(db, world.rival_id, at=AT).team
    assert team is not None
    assert team.availability.missing_reason == "sin_cobertura"  # type: ignore[union-attr]
    assert team.squad.missing_reason == "sin_datos"  # type: ignore[union-attr]


def test_the_rates_per_90_are_those_of_the_stored_sheets(db: psycopg.Connection[Any], world: World) -> None:
    player = profiles.build_player(db, world.striker_id, at=AT).player
    assert player is not None
    got: dict[str, Any] = {i.metric: i for i in player.per90.items}
    for metric, column in (("goals", "goals"), ("shots", "shots_total"), ("shots_on_target", "shots_on"),
                           ("fouls_committed", "fouls_committed")):
        row = db.execute(f"SELECT COALESCE(sum({column}), 0), count(*), COALESCE(sum(minutes), 0) "  # fixed column names
                         f"FROM core.fixture_player_stats WHERE provider_player_id = %s AND minutes > 0 "
                         f"AND {column} IS NOT NULL", (world.striker_pid,)).fetchone()
        assert row is not None
        count, matches, minutes = (int(v) for v in row)
        item = got[metric]
        assert (item.count, item.matches, item.minutes_sample) == (count, matches, minutes), metric
        assert item.value == round(count * 90 / minutes, 2) and item.sample_ok
        assert item.interval.low <= item.value <= item.interval.high
    assert got["shots"].matches == 5, "the sheet that did not report shots is left out with its minutes"
    assert "saves" not in got, "an outfield player has no saves line"
    assert player.header.photo.kind == "monograma" and player.header.shirt_number == 9
    assert player.caps.appeared == 1  # type: ignore[union-attr]
    assert len(player.form_last10.items) == 7


def test_a_player_with_few_minutes_shows_no_rate(db: psycopg.Connection[Any], world: World) -> None:
    player = profiles.build_player(db, world.rookie_id, at=AT).player
    assert player is not None
    goals = next(i for i in player.per90.items if i.metric == "goals")
    assert goals.value.missing_reason == "muestra_insuficiente" and goals.minutes_sample == 180  # type: ignore[union-attr]
    assists = next(i for i in player.per90.items if i.metric == "assists")
    assert assists.value.missing_reason == "sin_datos", "not recorded is not zero"  # type: ignore[union-attr]
    assert (player.availability.status, player.availability.basis) == ("sancionado", "proveedor")  # type: ignore[union-attr]


def test_a_national_teams_list_is_the_providers_with_its_reason(db: psycopg.Connection[Any], world: World) -> None:
    answer = profiles.build_team(db, world.nation_id, at=AT)
    team = answer.team
    assert team is not None and answer.kind == "national_team" and team.national is not None
    call_up = team.national.call_up
    assert call_up.level == "proveedor" and call_up.basis == "convocados_ultimo_partido"  # type: ignore[union-attr]
    assert call_up.official_state == "ninguna_fuente_oficial_autorizada"  # type: ignore[union-attr]
    assert call_up.permitted_official_sources == 0  # type: ignore[union-attr]
    [man] = call_up.players.items  # type: ignore[union-attr]
    assert man.club.name == "Club Ejemplo Norte" and man.position == "forward"  # type: ignore[union-attr]
    assert [r.value for r in team.national.caps_leaders.items] == [1]
    public_json(answer)


def test_a_competitions_profile(db: psycopg.Connection[Any], world: World) -> None:
    competition = profiles.build_competition(db, world.league_id, at=AT).competition
    assert competition is not None
    assert [r.rank for r in competition.standings.items] == [1, 2]
    assert competition.coverage.finished_matches == 6 and competition.coverage.with_team_stats == 3  # type: ignore[union-attr]
    assert competition.scorers.items[0].value == 2
    assert competition.header.rules_coded is False


def client(db: psycopg.Connection[Any], role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE, raise_server_exceptions=False)


def test_the_routes_serve_the_two_projections(db: psycopg.Connection[Any], world: World,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    reader, admin = client(db, "USER"), client(db, "SUPER_ADMIN")
    monkeypatch.setenv(PROFILES, "0")
    assert reader.get(f"/api/v1/teams/{world.club_id}/profile").status_code == 404
    assert reader.get(f"/api/v1/teams/{world.club_id}").status_code == 200, "the route of today is untouched"
    monkeypatch.setenv(PROFILES, "1")
    for path in (f"/api/v1/teams/{world.club_id}/profile", f"/api/v1/teams/{world.nation_id}/profile",
                 f"/api/v1/players/{world.striker_id}/profile", f"/api/v1/competitions/{world.league_id}/profile"):
        answer = reader.get(path)
        assert answer.status_code == 200, (path, answer.text)
        data = answer.json()["data"]
        assert data["projection"] == "public" and data["contract"] == "C-09"
        assert leaks(data, public_schema=Profile.model_json_schema(mode="serialization"),
                     private_schema=ProfilePrivate.model_json_schema(mode="serialization")) == []
    assert reader.get("/api/v1/teams/999999999/profile").status_code == 404
    assert reader.get(f"/api/v1/admin/intelligence/teams/{world.club_id}/profile").status_code == 403
    private = admin.get(f"/api/v1/admin/intelligence/teams/{world.club_id}/profile")
    assert private.status_code == 200, private.text
    body = private.json()["data"]
    assert body["projection"] == "private" and "intelligence" in body["team"]
    player = admin.get(f"/api/v1/admin/intelligence/players/{world.striker_id}/profile").json()["data"]
    assert {p["block"] for p in player["not_yet_private"]} == {"start_probability", "engine_forecasts", "player_markets"}
