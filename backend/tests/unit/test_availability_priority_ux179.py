"""UX-179 (plan PM, PM-09-05): C-16 1.2.0 gives each competition its editorial priority of annex A - P0 Colombia, P1 international,
P2 priority countries, P3 the rest followed, P4 the English pyramid - read from ``config/coverage/prioridad_editorial.yaml``; the
directory (lámina I08) marks P0 and P1 as «Destacada». A league the file does not list says ``sin_datos``, never a guess."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.api.contracts.intelligence.availability import Availability, CompetitionAvailability
from fbi.api.contracts.intelligence.base import Missing
from fbi.api.services import availability as svc
from fbi.coverage import depth


def test_the_contract_is_1_2_0_and_carries_the_priority() -> None:
    assert Availability.CONTRACT_VERSION == "1.2.0"
    assert "priority" in CompetitionAvailability.model_fields


def test_the_priorities_of_annex_a_are_the_ones_served() -> None:
    prio = depth.priorities()
    assert (prio[239], prio[13]) == ("P0", "P1")


def test_the_service_reads_the_priority_by_the_providers_league_id(monkeypatch: pytest.MonkeyPatch) -> None:
    comps = [{"id": 1, "provider_league_id": 239, "name": "Primera A", "country": "Colombia", "tier": 1},
             {"id": 2, "provider_league_id": 880001, "name": "Liga Ficticia", "country": None, "tier": None}]
    seasons = [{"id": 11, "competition_id": 1, "season": 2026}, {"id": 12, "competition_id": 2, "season": 2026}]

    def fetch_all(_conn: Any, sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        if sql is svc.COMPETITIONS_SQL:
            return comps
        if sql is svc.SEASONS_SQL:
            return seasons
        return []

    monkeypatch.setattr(svc, "fetch_all", fetch_all)
    out = svc._competitions(None, None, with_seasons=False)  # type: ignore[arg-type]
    by_id = {c.competition_id: c for c in out}
    assert by_id[1].priority == "P0"
    assert isinstance(by_id[2].priority, Missing) and by_id[2].priority.missing_reason == "sin_datos"
