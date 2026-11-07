"""IA-016 (``news-coverage-v1``): the news of the owner's priority competitions.

* the order and the coverage (``fbi.ai.cycle.web_choice``): every match of groups 1-3 of ``fbi.intel.day_priority`` is searched at its first
  and pre passes, with or without a candidate, outside ``FBI_AI_MAX_WEB_FIRST`` / ``FBI_AI_MAX_WEB_PRE`` - which keep counting the rest exactly
  as before -, and ``FBI_AI_NEWS_PRIORITY=0`` gives back the old choice;
* the search (``fbi.ai.collectors.collect_web``): a covered match read with level 1 also asks the press search in the competition's language -
  two searches at most, the second never stopped by what the first found -, never once Exa's envelope is spent (whatever the ``budget_v3``
  switch says); a match with more levels keeps exactly its levels; Exa is asked 2,000 characters of each page;
* the sources (``fbi.ai.evidence.seed_rows``): the clubs of group 1 as ``club``, the national press and VAVEL as ``media``;
* the state of the search (``fbi.api.services.news.search_state``): «not searched yet» and «searched, nothing found» are two answers.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from fbi.ai import cache, collectors, cycle, gates
from fbi.ai.config import AiSettings
from fbi.ai.cycle import Allowance, news_covered, web_choice
from fbi.ai.day import DayFixture, Due
from fbi.ai.evidence import SOURCES_V3, seed_rows
from fbi.analyst import search as exa
from fbi.analyst.search import SearchResult
from fbi.api.services.news import empty_reason, search_state

AT = datetime(2026, 11, 7, 5, 30, tzinfo=UTC)
LALIGA, PREMIER, LIBERTADORES, WORLD_CUP_QUALIFIERS, COLOMBIA = 140, 39, 13, 34, 239


def fixture(fid: int, league: int | None, *, priority: float = 10.0, hours: float = 12.0) -> DayFixture:
    return DayFixture(fid, AT + timedelta(hours=hours), fid, f"C{fid}", "Spain", 1, f"H{fid}", f"A{fid}", True, AT, 12, priority,
                      False, league)


def due(fid: int, league: int | None, kind: str = "first", **kw: Any) -> Due:
    return Due(fixture(fid, league, **kw), kind)  # type: ignore[arg-type]


def allow(first: int, pre: int) -> Allowance:
    return Allowance(llm=10, deep=2, watch=2, web_first=first, web_pre=pre)


ON, OFF = AiSettings(), AiSettings(news_priority=False)


# ── the order and the coverage ──────────────────────────────────────────────────────────────────────────────────────


def test_the_switch_is_on_by_default_and_off_only_when_it_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, expected in ((None, True), ("1", True), ("on", True), ("anything", True), ("0", False), ("off", False), ("no", False)):
        env = {} if raw is None else {"FBI_AI_NEWS_PRIORITY": raw}
        monkeypatch.setattr("fbi.ai.config.environment", lambda env=env: env)
        settings = AiSettings.from_env()
        assert settings.news_priority is expected, raw
        assert settings.public()["news_priority"] is expected


def test_a_priority_competition_is_covered_at_the_passes_that_read_the_web_and_only_with_the_switch_on() -> None:
    for league in (LALIGA, PREMIER, 2, LIBERTADORES, WORLD_CUP_QUALIFIERS):
        for kind in ("first", "pre", "request"):
            assert news_covered(due(1, league, kind), ON), (league, kind)
        assert not news_covered(due(1, league, "final"), ON), "the final pass reads the line-ups, not the web"
        assert not news_covered(due(1, league, "first"), OFF)
    for other in (COLOMBIA, None):
        assert not news_covered(due(1, other, "first"), ON), "group 4 keeps the caps"


def test_the_first_pass_covers_every_priority_match_and_the_cap_still_counts_only_the_rest() -> None:
    dues = [due(1, LALIGA, priority=5), due(2, PREMIER, priority=6), due(3, LIBERTADORES, priority=1),
            due(4, COLOMBIA, priority=30), due(5, COLOMBIA, priority=20), due(6, None, priority=10)]
    web, covered = web_choice(dues, {}, escalated=set(), asked=set(), allow=allow(2, 0), settings=ON)
    assert covered == {1, 2, 3}
    assert web == {1, 2, 3, 4, 5}, "the covered ones plus the two best of the rest: the cap of 2 is the rest's own"
    old, none = web_choice(dues, {}, escalated=set(), asked=set(), allow=allow(2, 0), settings=OFF)
    assert none == set() and old == {4, 5}, "the switch off: the old choice, by priority, the cap for every match"


def test_the_pre_pass_covers_a_priority_match_without_a_candidate_and_keeps_the_old_rule_for_the_rest() -> None:
    dues = [due(1, LALIGA, "pre"), due(2, COLOMBIA, "pre"), due(3, COLOMBIA, "pre"), due(4, COLOMBIA, "pre"), due(5, LALIGA, "final")]
    web, covered = web_choice(dues, {}, escalated={3}, asked={4}, allow=allow(0, 1), settings=ON)
    assert covered == {1}
    assert 2 not in web, "a match of group 4 without a candidate, not escalated and asking nothing is not searched at its pre pass"
    assert len(web & {3, 4}) == 1, "the escalated and the asking share the pre cap of 1"
    assert 5 not in web, "the final pass never reads the web"
    assert web_choice(dues, {}, escalated={3}, asked={4}, allow=allow(0, 0), settings=ON)[0] == {1}, \
        "a spent pre cap still leaves the covered match"


def test_the_processing_order_puts_the_rest_without_a_candidate_after_the_covered_only_with_the_switch_on() -> None:
    import inspect

    text = inspect.getsource(cycle._run)
    assert "bool(covered) and f[0] not in by_fixture and f[0] not in covered" in text
    assert "covered: set[int] = set()" in text, "no covered match (switch off, or none today): the order is the one it always was"


def test_a_covered_pass_takes_no_place_of_the_days_web_caps() -> None:
    sql = " ".join(cycle.WEB_USED_SQL.split())
    assert "COALESCE((counts->>'web_priority')::int, 0) = 0" in sql
    assert "COALESCE((counts->>'web_searches')::int, 0) > 0" in sql


# ── the search ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_press_search_is_in_the_competitions_language() -> None:
    ko = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
    assert collectors.press_query("Valencia", "Real Madrid", ko, "Spain") == \
        "Valencia Real Madrid rueda de prensa convocatoria bajas sanción 2026-11-07"
    assert "conferenza stampa" in collectors.press_query("Inter", "Milan", ko, "Italy")
    assert "Pressekonferenz" in collectors.press_query("Bayern", "Dortmund", ko, "Germany")
    assert "conférence de presse" in collectors.press_query("PSG", "Lyon", ko, "France")
    assert "conferência de imprensa" in collectors.press_query("Benfica", "Porto", ko, "Portugal")
    assert collectors.press_query("Arsenal", "Chelsea", ko, "England").startswith("Arsenal vs Chelsea press conference")
    assert collectors.press_query("Arsenal", "Bayern", ko, "World").startswith("Arsenal vs Bayern press conference"), \
        "the Champions League (country World) in English"
    assert set(collectors.PRESS) == set(collectors.TEAM_NEWS), "every language of the tiered search has its press search"
    assert collectors.PRESS_LEVEL not in collectors.LEVELS and collectors.MAX_PRIORITY_SEARCHES == 2


class _Cursor:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, *_: Any, **__: Any) -> None:
        return None

    def fetchone(self) -> dict[str, Any]:
        return self.row


class _Conn:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def cursor(self, **_: Any) -> _Cursor:
        return _Cursor(self.row)


@dataclass
class _Budget:
    allowed: bool


class _Ledger:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(self, **kw: Any) -> None:
        self.rows.append(kw)


@contextmanager
def world(monkeypatch: pytest.MonkeyPatch, *, exa_allowed: bool = True, gate: bool = False,
          known: bool = True) -> Iterator[tuple[_Conn, list[str], _Ledger]]:
    """collect_web on a fake database: an empty cache, a day budget that allows, Exa's envelope as asked, every page of marca.com (a known
    source) when ``known``, and an extraction that finds nothing."""
    asked: list[str] = []
    store: dict[str, Any] = {}
    monkeypatch.setattr(collectors, "budget_of", lambda conn, at, settings: type("B", (), {"allows": lambda self, w: True,
                                                                                         "state": "OK"})())
    monkeypatch.setattr(collectors, "effective_tier", lambda b, tier, settings: "bulk")
    monkeypatch.setattr(gates, "enabled", lambda conn, settings, name, **kw: gate)
    monkeypatch.setattr(collectors, "exa_budget", lambda conn, at, settings: _Budget(exa_allowed))
    monkeypatch.setattr(cache, "get", lambda conn, scope, key, at, **kw: store.get(f"{scope}:{key}"))
    monkeypatch.setattr(cache, "put", lambda conn, scope, key, payload, at, ttl: store.__setitem__(f"{scope}:{key}", payload))
    monkeypatch.setattr(collectors, "tier_of", lambda conn, domain: "media" if known and domain == "marca.com" else "unknown")
    monkeypatch.setattr(collectors, "record_source_results", lambda conn, results, at, cost: None)
    answer = type("Call", (), {"result": type("R", (), {"data": {"items": []}})(), "cost": Decimal(0), "error": None})()
    monkeypatch.setattr(collectors, "call_json", lambda *a, **kw: answer)
    row = {"id": 7, "kickoff_at": AT + timedelta(hours=14), "home_team_id": 1, "away_team_id": 2, "home_name": "Valencia",
           "away_name": "Real Madrid", "home_provider_id": 532, "away_provider_id": 541, "competition_season_id": 1,
           "competition": "La Liga", "country": "Spain"}
    yield _Conn(row), asked, _Ledger()


def _search(asked: list[str]) -> collectors.SearchFn:
    def search(query: str, at: datetime) -> list[SearchResult]:
        asked.append(query)
        n = len(asked)
        return [SearchResult(f"https://www.marca.com/futbol/{n}.html", f"Bajas {n}", "www.marca.com", None, at.isoformat(),
                             "Vinicius cumple sanción.")]
    return search


def test_a_covered_match_asks_level_one_and_the_press_search_even_when_level_one_found_a_known_source(
        monkeypatch: pytest.MonkeyPatch) -> None:
    with world(monkeypatch) as (conn, asked, ledger):
        got = collectors.collect_web(conn, AiSettings(search="exa"), 7, at=AT, ledger=ledger, search=_search(asked),  # type: ignore[arg-type]
                                     provider=(object(), "m"), levels=1, priority=True)  # type: ignore[arg-type]
    assert len(asked) == 2 and got.searches == 2 and got.asked == 2 and got.press
    assert "noticias lesionados convocados" in asked[0] and "rueda de prensa" in asked[1], "Spanish, as LaLiga's press writes it"
    assert got.read == 2, "both pages read once"
    assert [r["purpose"] for r in ledger.rows] == ["web_search", "web_search"]


def test_without_priority_the_search_is_exactly_the_one_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    with world(monkeypatch) as (conn, asked, ledger):
        got = collectors.collect_web(conn, AiSettings(search="exa"), 7, at=AT, ledger=ledger, search=_search(asked),  # type: ignore[arg-type]
                                     provider=(object(), "m"), levels=1)  # type: ignore[arg-type]
    assert len(asked) == 1 and not got.press and got.asked == 1


def test_a_covered_candidate_keeps_its_three_levels_and_no_press_search(monkeypatch: pytest.MonkeyPatch) -> None:
    with world(monkeypatch, known=False) as (conn, asked, ledger):
        got = collectors.collect_web(conn, AiSettings(search="exa"), 7, at=AT, ledger=ledger, search=_search(asked),  # type: ignore[arg-type]
                                     provider=(object(), "m"), levels=3, priority=True)  # type: ignore[arg-type]
    assert len(asked) == 3 and not got.press and not any("rueda de prensa" in q for q in asked)


def test_a_spent_exa_envelope_stops_a_covered_search_whatever_the_budget_switch_says(monkeypatch: pytest.MonkeyPatch) -> None:
    with world(monkeypatch, exa_allowed=False, gate=False) as (conn, asked, ledger):
        got = collectors.collect_web(conn, AiSettings(search="exa"), 7, at=AT, ledger=ledger, search=_search(asked),  # type: ignore[arg-type]
                                     provider=(object(), "m"), levels=1, priority=True)  # type: ignore[arg-type]
    assert asked == [] and got.skipped == "budget_exa" and got.searches == 0
    with world(monkeypatch, exa_allowed=False, gate=False) as (conn, asked, ledger):
        legacy = collectors.collect_web(conn, AiSettings(search="exa"), 7, at=AT, ledger=ledger, search=_search(asked),  # type: ignore[arg-type]
                                        provider=(object(), "m"), levels=1)  # type: ignore[arg-type]
    assert len(asked) == 1 and legacy.searches == 1, "a match outside the coverage: the envelope only with budget v3, as before"


def test_exa_is_asked_two_thousand_characters_of_each_page(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"url": "https://www.vavel.com/es/x", "title": "t", "publishedDate": None,
                                                      "text": "x" * 5000}]})
    monkeypatch.setattr(exa, "environment", lambda: {"EXA_API_KEY": "k"})
    found = exa.search("Valencia Real Madrid", at=AT, transport=httpx.MockTransport(handler))
    assert seen["contents"] == {"text": {"maxCharacters": 2000}} and exa.TEXT_CHARS == 2000
    assert seen["numResults"] == exa.MAX_RESULTS == 8, "the same eight results: the price of a search does not move"
    assert len(found[0].snippet) == 2000


# ── the sources ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_clubs_of_group_one_and_the_national_press_are_seeded_with_their_tier() -> None:
    tiers = dict(seed_rows())
    assert len(tiers) == len(seed_rows()), "every domain once"
    for club in ("valenciacf.com", "sevillafc.es", "athletic-club.eus", "avfc.co.uk", "sscnapoli.it", "bayer04.de", "om.fr",
                 "slbenfica.pt", "fcporto.pt", "sporting.pt"):
        assert tiers[club] == "club", club
    for outlet in ("vavel.com", "superdeporte.es", "cadenaser.com", "cope.es", "repubblica.it", "lefigaro.fr", "publico.pt"):
        assert tiers[outlet] == "media", outlet
    for already in ("as.com", "marca.com", "mundodeportivo.com", "bbc.co.uk", "skysports.com", "gazzetta.it", "kicker.de",
                    "lequipe.fr", "record.pt", "abola.pt"):
        assert tiers[already] == "media", f"{already} was already national media"
    assert tiers["realmadrid.com"] == "club" and tiers["laliga.com"] == "competition", "what was seeded keeps its tier"
    assert tiers["dfl.de"] == "competition" and tiers["lfp.fr"] == "competition"
    assert all(t in ("club", "competition", "media") for t in SOURCES_V3.values())
    assert all(d == d.lower() and not d.startswith("www.") and "/" not in d for d in SOURCES_V3)


# ── the state of the search ──────────────────────────────────────────────────────────────────────────────────────────


def test_not_searched_and_searched_with_nothing_found_are_two_answers() -> None:
    nothing = search_state({"paid_at": None, "searches": 0, "pass_at": None, "sources_read": None, "untracked": 0})
    assert nothing.searched == "no" and nothing.last_searched_at is None and nothing.sources_read == 0
    paid, cached = AT - timedelta(hours=5), AT - timedelta(hours=1)
    searched = search_state({"paid_at": paid, "searches": 2, "pass_at": cached, "sources_read": 6, "untracked": 0})
    assert searched.searched == "yes" and searched.last_searched_at == cached and searched.searches == 2 and searched.sources_read == 6
    older = search_state({"paid_at": paid, "searches": 1, "pass_at": None, "sources_read": None, "untracked": 1})
    assert older.searched == "yes" and older.last_searched_at == paid and older.sources_read is None, \
        "a pass recorded before the pages were counted: the number is not known, never a guess"
    mixed = search_state({"paid_at": paid, "searches": 3, "pass_at": cached, "sources_read": 4, "untracked": 1})
    assert mixed.sources_read is None
    assert search_state(None).searched == "unknown"
    assert empty_reason(nothing) != empty_reason(searched) != empty_reason(search_state(None))
    assert "verified" not in " ".join(empty_reason(s) for s in (nothing, searched, search_state(None)))
