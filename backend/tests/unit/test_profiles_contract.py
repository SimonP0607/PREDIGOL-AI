"""C-09, the profiles (AD-H07 IA-090, AD-H05 IA-091, AD-H06 IA-092): what the contract may and may not carry.

The generic tests of every Intelligence contract (examples, projection, no leak, 403 of the private routes, version) run from
the registry; these add what is particular to C-09: nothing medical anywhere, nothing of the player engine, no estimated
starter, no identity queue and no state of the cycle in the public projection, and the switch.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.api.contracts.intelligence.profiles import Profile, ProfilePrivate
from fbi.api.contracts.intelligence.projection import LIFECYCLE_ONLY, schema_paths
from fbi.api.problem import ApiError
from fbi.api.services import profiles

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-09"
MEDICAL = ("reason", "diagnosis", "injury", "medical", "end_date", "return", "expected_back", "days_out", "sidelined",
           "absence_type", "claim")
ENGINE = ("start_probability", "p_start", "p_play", "expected_minutes", "engine", "prop", "lineup_probability",
          "starter", "player_markets", "intelligence", "identity", "open_reviews", "not_yet_private", "external_id")


def public_paths() -> frozenset[str]:
    return schema_paths(Profile.model_json_schema(mode="serialization"))


def private_paths() -> frozenset[str]:
    return schema_paths(ProfilePrivate.model_json_schema(mode="serialization"))


def test_no_field_of_either_projection_can_carry_a_medical_detail() -> None:
    for path in private_paths():
        leaf = path.rsplit(".", 1)[-1].lower()
        if leaf in ("missing_reason", "stale_reason"):  # the contract's own «why absent» and «why old»: codes, not text
            continue
        assert not any(word in leaf for word in MEDICAL), path


def test_availability_is_only_state_basis_source_and_dates() -> None:
    leaves = {p.rsplit(".", 1)[-1] for p in private_paths() if ".availability." in p}
    allowed = {"status", "basis", "source", "known_at", "fixture_id", "report_checked_at", "unavailable", "items",
               "player_id", "name", "missing_reason", "expected_piece", "expected_at", "sample", "min_sample"}
    assert leaves <= allowed, leaves - allowed


def test_the_public_projection_carries_nothing_of_the_engine_the_cycle_or_identity() -> None:
    for path in public_paths():
        leaf = path.rsplit(".", 1)[-1].lower()
        assert not any(word in leaf for word in ENGINE), path
    added = private_paths() - public_paths()
    assert {"$.team.intelligence", "$.team.identity", "$.player.identity", "$.not_yet_private"} <= added


def public_examples() -> Iterator[Path]:
    yield from sorted(EXAMPLES.glob("*.public.json"))


@pytest.mark.parametrize("path", list(public_examples()), ids=lambda p: p.name)
def test_a_public_example_shows_no_state_of_the_cycle_and_a_monogram(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["projection"] == "public"
    assert not any(f'"{state}"' in text for state in LIFECYCLE_ONLY)
    if data["kind"] == "player":
        assert data["player"]["header"]["photo"] == {"kind": "monograma"}
        assert "photo_url" not in text


def test_the_examples_cover_the_cases_of_the_ficha() -> None:
    names = {p.name.split(".")[0] for p in EXAMPLES.glob("*.json")}
    assert {"club", "club_sin_plantilla", "seleccion", "jugador", "jugador_poca_muestra", "competicion"} <= names
    club = json.loads((EXAMPLES / "club.private.json").read_text(encoding="utf-8"))
    assert club["team"]["intelligence"]["items"], "the private example shows a selection in shadow"
    thin = json.loads((EXAMPLES / "jugador_poca_muestra.public.json").read_text(encoding="utf-8"))
    reasons = {i["value"]["missing_reason"] for i in thin["player"]["per90"]["items"] if isinstance(i["value"], dict)}
    assert "muestra_insuficiente" in reasons
    nation = json.loads((EXAMPLES / "seleccion.public.json").read_text(encoding="utf-8"))
    call_up = nation["team"]["national"]["call_up"]
    assert call_up["level"] == "proveedor" and call_up["official_state"] == "ninguna_fuente_oficial_autorizada"


def test_every_rate_shows_its_sample() -> None:
    for path in EXAMPLES.glob("jugador*.json"):
        for item in json.loads(path.read_text(encoding="utf-8"))["player"]["per90"]["items"]:
            assert {"matches", "minutes_sample", "count", "sample_ok"} <= item.keys()
            assert item["sample_ok"] == (not isinstance(item["value"], dict))


def test_a_profile_carries_exactly_the_body_of_its_kind() -> None:
    data = json.loads((EXAMPLES / "club.public.json").read_text(encoding="utf-8"))
    with pytest.raises(ValueError):
        Profile.model_validate({**data, "kind": "player"})
    with pytest.raises(ValueError):
        Profile.model_validate({**data, "kind": "national_team"})


@pytest.mark.parametrize("call", [profiles.public_team, profiles.public_player, profiles.public_competition])
def test_the_public_routes_do_not_exist_while_the_switch_is_off(monkeypatch: pytest.MonkeyPatch, call: Any) -> None:
    monkeypatch.setenv("FBI_PROFILES", "0")
    with pytest.raises(ApiError) as caught:
        call(None, 1)  # the switch is read before the database
    assert caught.value.status == 404


class _Refusing:
    """A connection whose table does not exist yet (a database before the migration that adds it)."""

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def cursor(self, **_: Any) -> Any:
        raise psycopg.errors.UndefinedTable("relation does not exist")


def test_a_table_a_later_migration_adds_reads_as_absent() -> None:
    conn: Any = _Refusing()
    assert profiles._identity(conn, "team", 1).missing_reason == "sin_datos"  # type: ignore[union-attr]
    assert profiles._shadow(conn, 1, datetime(2026, 11, 21, tzinfo=UTC)).missing_reason == "sin_resultados"
