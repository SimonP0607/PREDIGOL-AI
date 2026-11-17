"""AD-J09 (IA-134): contract C-12 «Inicio» - ``featured_analyses`` in ``GET /home``, public projection only.

The candidates are made from C-01's own public examples (``tests/fixtures/contracts/intelligence/C-01``), as the service makes them from
the match's public C-01, so a featured analysis is always a summary of what the match's tab serves. The examples of C-12 are made by the
service's builder (``FBI_WRITE_EXAMPLES=1`` rewrites them). Here: nothing published gives an empty list with its reason, a match in the
shadow never reaches it, the rule (favourite team, followed competition, the soonest) and its cut, the switch, and Home unchanged while
the field is absent.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fbi.api.contracts.intelligence.featured import FeaturedAnalyses, FeaturedAnalysesPrivate
from fbi.api.contracts.intelligence.match import MatchIntelligence
from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.product import DataFreshness, Home
from fbi.api.envelope import DataStatus, ok, section
from fbi.api.services import featured as svc

C01 = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-01"
EXAMPLES = C01.parent / "C-12"
AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)


def c01(case: str) -> MatchIntelligence:
    return MatchIntelligence.model_validate(json.loads((C01 / f"{case}.public.json").read_text(encoding="utf-8")))


def candidate(case: str, *, fixture: int, home: int, away: int, competition: int, hours: float) -> svc.Candidate:
    base = svc.summary(c01(case))
    match = base.match.model_copy(update={
        "id": fixture, "kickoff_at": AT + timedelta(hours=hours),
        "home": base.match.home.model_copy(update={"id": home, "name": f"Club Ejemplo {home}"}),
        "away": base.match.away.model_copy(update={"id": away, "name": f"Club Ejemplo {away}"}),
        "competition": base.match.competition.model_copy(update={"id": competition})})
    return svc.Candidate(match=match, selections=base.selections)


def pool() -> list[svc.Candidate]:
    return [candidate("con_alineacion_oficial", fixture=990101, home=990011, away=990012, competition=990200, hours=3),
            candidate("con_alineacion_oficial", fixture=990102, home=990021, away=990022, competition=990300, hours=20),
            candidate("antes_del_partido", fixture=990103, home=990031, away=990032, competition=990200, hours=1)]


def cases() -> dict[str, FeaturedAnalysesPrivate]:
    return {"sin_publicados": svc.assemble([], at=AT),
            "destacados": svc.assemble(pool(), at=AT, teams=frozenset({990021}), leagues=frozenset({990200}), personalised=True)}


def dumped(model: Any) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def test_the_examples_are_what_the_builder_makes() -> None:
    files: dict[Path, dict[str, Any]] = {}
    for case, m in cases().items():
        files[EXAMPLES / f"{case}.private.json"] = dumped(m)
        files[EXAMPLES / f"{case}.public.json"] = dumped(to_public(m, FeaturedAnalyses))
    if os.environ.get("FBI_WRITE_EXAMPLES") == "1":
        for path, data in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for path, data in files.items():
        assert json.loads(path.read_text(encoding="utf-8")) == data, path.name


def test_nothing_published_is_an_empty_list_with_its_reason() -> None:
    public = dumped(to_public(cases()["sin_publicados"], FeaturedAnalyses))
    assert public["items"] == {"items": [], "missing_reason": "sin_publicados"}
    assert public["projection"] == "public" and public["rule"]["version"] == "featured-v1"


def test_a_match_without_a_published_selection_never_reaches_it() -> None:
    m = cases()["destacados"]
    assert m.candidates == 3 and [i.match.id for i in m.items.items] == [990102, 990101]
    assert all(s.public_state in ("publicada", "en_juego", "liquidada") for i in m.items.items for s in i.selections)
    public = dumped(to_public(m, FeaturedAnalyses))
    assert "candidates" not in public and all("published" not in i for i in public["items"]["items"])
    assert leaks(public, public_schema=FeaturedAnalyses.model_json_schema(mode="serialization"),
                 private_schema=FeaturedAnalysesPrivate.model_json_schema(mode="serialization")) == []
    assert "s.source = 'qualified'" in svc.CANDIDATES_SQL and "evaluation" not in svc.CANDIDATES_SQL


def test_the_rule_ranks_by_favourite_team_then_followed_competition_then_the_soonest() -> None:
    items = cases()["destacados"].items.items
    assert [i.reasons for i in items] == [["equipo_favorito", "partido_proximo"], ["competicion_seguida", "partido_proximo"]]
    common = svc.assemble(pool(), at=AT)
    assert [i.match.id for i in common.items.items] == [990101, 990102] and not common.personalised
    assert all(i.reasons == ["partido_proximo"] for i in common.items.items)
    many = [candidate("con_alineacion_oficial", fixture=991000 + n, home=2 * n + 1, away=2 * n + 2, competition=1, hours=n + 1)
            for n in range(7)]
    assert len(svc.assemble(many, at=AT).items.items) == svc.MAX_ITEMS == 4


def test_the_field_needs_the_switch_and_a_failure_leaves_home_as_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: False)
    monkeypatch.setattr(svc, "candidates", lambda conn, at=None: (_ for _ in ()).throw(AssertionError("read while off")))
    assert svc.for_home(None, user_id=7) is None  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "match_intelligence_on", lambda: True)
    assert svc.for_home(None, user_id=7) is None  # type: ignore[arg-type]  # the read failed: no field
    monkeypatch.setattr(svc, "candidates", lambda conn, at=None: tuple(pool()))
    monkeypatch.setattr(svc, "_favourites", lambda conn, user_id: (frozenset(), frozenset({990300}), True))
    got = svc.for_home(None, user_id=7, at=AT)  # type: ignore[arg-type]
    assert isinstance(got, FeaturedAnalyses) and got.personalised
    assert [i.match.id for i in got.items.items] == [990102, 990101]


def home() -> Home:
    empty: Any = section([], status=DataStatus.EMPTY, reason="nothing")
    return Home(source="qualified", data_freshness=DataFreshness(live_at=None), relevant=empty, at_stake=empty, live=empty, results=empty)


def test_home_keeps_its_shape_while_the_field_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.routers import product as route
    from fbi.api.services import product as product_service

    plain = home()
    assert "featured_analyses" not in dumped(plain)
    monkeypatch.setattr(product_service, "home", lambda conn, include_shadow: ok(plain))

    class Reader:
        user_id = 7

    monkeypatch.setattr(svc, "for_home", lambda conn, user_id: None)
    assert dumped(route.get_home(None, Reader()).data) == dumped(plain)  # type: ignore[arg-type]
    shown = to_public(cases()["sin_publicados"], FeaturedAnalyses)
    monkeypatch.setattr(svc, "for_home", lambda conn, user_id: shown)
    data = dumped(route.get_home(None, Reader()).data)  # type: ignore[arg-type]
    assert data.pop("featured_analyses")["contract"] == "C-12" and data == dumped(plain)
