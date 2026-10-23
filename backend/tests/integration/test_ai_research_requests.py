"""PEDIR INVESTIGACIÓN on a built world (plan F6, ``brief-v8``, ``research-v1``; ``fbi.ai.research``): the brief asks the server to look into
something, the server decides - inside what it already allows itself.

The world is ``test_daily_records.World`` (six matches on 1 Aug 2032, F1..F6 two to thirteen hours from kick-off). F6 is made a match
WITHOUT a candidate (its price is one nobody would take) and F5 keeps its candidate; the model asks for research in the brief of F6 and in
no other. What is held here:

* the request is served at the next pass that reads the web, with the levels of the tiered search its topic maps to (availability: team
  news and the official statements; not the international preview a match with a candidate gets) - and it is told to the next reading;
* it is served INSIDE the day's allowance: ranked after the match with a candidate, so with one search left the candidate gets it and the
  request is counted as unserved (``research_unserved_no_allowance``), and near the day's budget it is not served either
  (``research_unserved_near_budget``);
* a final pass never reads the web: what was asked is counted as unserved there (``research_unserved_no_search_pass``) and the owner's
  «run now» (a request pass) serves it;
* asking is not a reason to escalate: no watch review comes of it.

No network and no key: the model is ``FakeProvider``, the search a function. One transaction, rolled back."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai.collectors import queries_for
from fbi.ai.config import AiSettings
from fbi.ai.cycle import run_analysis_cycle
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, budget, shared
from fbi.analyst.search import SearchResult

from .conftest import Seed
from .test_ai_decision_layer import Savepoints, brief_reply, count, review_reply
from .test_daily_records import AT, World

pytestmark = pytest.mark.integration

PRE = AT + timedelta(hours=8)
"""F6 (kick-off at +13 h) is five hours away - its pre pass - and F5 (+10 h) two; F4 is about to start."""
FINAL = AT + timedelta(hours=12, minutes=15)
"""45 minutes before F6 kicks off: its final pass."""
ASK = {"topic": "availability", "side": "both",
       "why": {"text": "El paquete no trae bajas de ninguno de los dos.", "type": "DATA", "refs": ["P:absences"]}}
INJURY = {"result_id": "R1", "side": "home", "player": "Delantero Uno", "kind": "injury", "assertion": "out",
          "claim": "El delantero titular no jugará por lesión.", "published_at": None}


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield World(db, seed)


def config(**over: Any) -> AiSettings:
    return AiSettings(mode="shadow", **over)


def asker(fixture: int, ask: dict[str, Any] = ASK) -> FakeProvider:
    """A model that asks for ``ask`` in the brief of ``fixture`` (and of no other match) until the brief it reads says it asked it."""
    def answer(r: Any) -> dict[str, Any]:
        if r.schema_name == "submit_brief":
            body = json.loads(r.user)
            mine = body["packet"]["fixture"]["id"] == fixture and not body["previous_research"]
            return brief_reply(research=[ask] if mine else [])
        if r.schema_name == "submit_items":
            return {"items": [INJURY]}
        return review_reply("APPROVE")
    return FakeProvider(answer, name="anthropic")


class Web:
    """The search: what was asked, and an answer only for the official statements of F6."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query: str, at: datetime) -> list[SearchResult]:
        self.queries.append(query)
        if "F6-H" in query and "comunicado oficial" in query:
            return [SearchResult("https://www.marca.com/futbol/f6.html", "F6-H: bajas", "www.marca.com",
                                 (at - timedelta(hours=3)).isoformat(), at.isoformat(), "El delantero no jugará.")]
        return []

    def of(self, name: str) -> list[str]:
        return [q for q in self.queries if f"{name}-H" in q]


def cycle(conn: Any, *, at: datetime, model: FakeProvider, search: Web, settings: AiSettings,
          only: list[int] | None = None, request: bool = False) -> Any:
    return run_analysis_cycle(conn, at=at, settings=settings, ledger=UsageLedger(shared(conn._conn)), only_fixtures=only,
                              search=search, provider=(model, "claude-haiku-5-5"), request=request)


def match_without_a_candidate(world: World) -> int:
    """F6 keeps its market and loses its candidate (the price is one nobody would take); F5's price is fresh at its pre pass."""
    world.price("F6", "1.50", AT - timedelta(minutes=5))
    world.price("F6", "1.50", PRE - timedelta(minutes=5))
    world.price("F5", "2.30", PRE - timedelta(minutes=5))
    return world.fixtures["F6"]


def pass_counts(db: psycopg.Connection[Any], fixture: int, kind: str) -> dict[str, int]:
    row = db.execute("SELECT counts FROM ai.fixture_passes WHERE fixture_id = %s AND pass = %s", (fixture, kind)).fetchone()
    assert row is not None, f"{fixture} had no {kind} pass"
    return {str(k): int(v) for k, v in row[0].items()}


def expected(db: psycopg.Connection[Any], fixture: int, levels: int | tuple[int, ...]) -> list[str]:
    """The queries the server writes for a match at those levels - the same ones ``collect_web`` writes."""
    row = db.execute("SELECT f.kickoff_at, h.name, a.name, c.country, c.name FROM core.fixtures f "
                     "JOIN core.teams h ON h.id = f.home_team_id JOIN core.teams a ON a.id = f.away_team_id "
                     "JOIN core.competition_seasons s ON s.id = f.competition_season_id "
                     "JOIN core.competitions c ON c.id = s.competition_id WHERE f.id = %s", (fixture,)).fetchone()
    assert row is not None
    return queries_for(row[1], row[2], row[0], row[3], row[4], levels=levels)


def asked_of(model: FakeProvider, fixture: int) -> list[list[dict[str, str]]]:
    """For each brief the model was asked to write for the match: what the previous reading had asked."""
    bodies = [json.loads(r.user) for r in model.requests if r.schema_name == "submit_brief"]
    return [b["previous_research"] for b in bodies if b["packet"]["fixture"]["id"] == fixture]


def stored_research(db: psycopg.Connection[Any], fixture: int) -> Any:
    row = db.execute("SELECT content -> 'research', escalate FROM ai.match_briefs WHERE fixture_id = %s "
                     "ORDER BY created_at DESC, id DESC LIMIT 1", (fixture,)).fetchone()
    assert row is not None
    return row


def test_a_request_is_served_at_the_next_pass_that_reads_the_web_with_the_levels_of_its_topic(
        db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    f6 = match_without_a_candidate(world)
    model, web = asker(f6), Web()
    settings = config(max_web_first=0, max_web_pre=2)

    # the first pass: the brief of F6 asks, nothing is read (the first pass's allowance is none) and nothing is counted as asked yet
    first = cycle(conn, at=AT, model=model, search=web, settings=settings)
    assert web.queries == [] and first.counts["research_requested"] == 1 and "research_asked" not in first.counts
    ask, escalate = stored_research(db, f6)
    assert [(a["topic"], a["side"]) for a in ask] == [("availability", "both")] and escalate is False, "asking is not escalating"
    counts = pass_counts(db, f6, "first")
    assert counts["research_requested"] == 1 and "research_asked" not in counts

    # the pre pass: F5 has a candidate (read in full: the three levels), F6 asked for availability (the first two levels, not the preview)
    f5 = world.fixtures["F5"]
    pre = cycle(conn, at=PRE, model=model, search=web, settings=settings)
    assert web.of("F5") == expected(db, f5, 3) and len(web.of("F5")) == 3
    assert web.of("F6") == expected(db, f6, 2) == expected(db, f6, (1, 2)), "team news and official statements"
    assert expected(db, f6, 3)[2] not in web.queries, "the international preview was not asked for"
    counts = pass_counts(db, f6, "pre")
    assert counts["research_asked"] == 1 and counts["research_searched"] == 1 and counts["web_searches"] == 2, counts
    assert not [k for k in counts if k.startswith("research_unserved")]
    assert pre.counts["research_asked"] == 1 and pre.counts["research_searched"] == 1
    assert count(db, "SELECT count(*) FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok' AND fixture_id = %s", f6) == 2

    # what was found is evidence with its source, and the next reading is told what the previous one asked (and asks nothing more)
    assert count(db, "SELECT count(*) FROM ai.evidence WHERE origin = 'web' AND fixture_id = %s AND source_domain = 'marca.com'", f6) == 1
    assert asked_of(model, f6) == [[], [{"topic": "availability", "side": "both"}]]
    ask, escalate = stored_research(db, f6)
    reasons = db.execute("SELECT reasons FROM ai.match_briefs WHERE fixture_id = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                         (f6,)).fetchone()
    assert ask == [] and escalate is True and reasons == (["important_news"],), \
        "the second reading escalates for the server's own reason - the key player the search found out - not for having asked"


def test_with_one_search_left_the_match_with_a_candidate_gets_it_and_the_request_is_counted_as_unserved(
        db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    f6 = match_without_a_candidate(world)
    model, web = asker(f6), Web()
    cycle(conn, at=AT, model=model, search=web, settings=config(max_web_first=0, max_web_pre=1))
    pre = cycle(conn, at=PRE, model=model, search=web, settings=config(max_web_first=0, max_web_pre=1))
    assert len(web.of("F5")) == 3 and web.of("F6") == [], "the single search of the pass went to the match with a candidate"
    counts = pass_counts(db, f6, "pre")
    assert counts["research_asked"] == 1 and counts["research_unserved_no_allowance"] == 1, counts
    assert "research_searched" not in counts and counts.get("web_searches", 0) == 0
    assert pre.counts["research_asked"] == 1 and pre.counts["research_unserved_no_allowance"] == 1
    assert "research_searched" not in pre.counts
    ask, _ = stored_research(db, f6)
    assert [a["topic"] for a in ask] == ["availability"], "what was not served is still asked at the next pass that reads the web"


def test_near_the_days_budget_a_match_without_a_candidate_loses_its_research_with_the_rest_of_its_paid_depth(
        db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    f6 = match_without_a_candidate(world)
    model, web = asker(f6), Web()
    settings = config(max_web_first=0, max_web_pre=2)
    cycle(conn, at=AT, model=model, search=web, settings=settings)
    day = budget(db, at=PRE, settings=settings)
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status) VALUES "
               "(%s, 'pick_review', 'analysis', 'anthropic', 'claude-sonnet-5-5', %s, 'ok')",
               (PRE - timedelta(hours=1), (day.daily * Decimal("0.85")).quantize(Decimal("0.0001"))))
    near = budget(db, at=PRE, settings=settings)
    assert near.state == "NORMAL" and not near.marginal_allowed(), "past 80 % of the day, still not over it"
    pre = cycle(conn, at=PRE, model=model, search=web, settings=settings)
    assert web.of("F6") == [], "a request buys nothing the budget would refuse"
    counts = pass_counts(db, f6, "pre")
    assert counts["research_asked"] == 1 and counts["research_unserved_near_budget"] == 1 and counts["marginal_saved"] == 1, counts
    assert pre.counts["research_unserved_near_budget"] == 1


def test_a_final_pass_does_not_read_the_web_and_the_owners_run_now_serves_what_was_asked(
        db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    f6 = match_without_a_candidate(world)
    model, web = asker(f6), Web()
    cycle(conn, at=AT, model=model, search=web, settings=config(max_web_first=0, max_web_pre=2))
    # the pre pass is skipped (nobody ran the cycle between 6 and 1.5 hours before): the final pass comes next
    final = cycle(conn, at=FINAL, model=model, search=web, settings=config(max_web_first=5, max_web_pre=5))
    assert web.of("F6") == [] and final.counts["pass_final"] == 1
    counts = pass_counts(db, f6, "final")
    assert counts["research_asked"] == 1 and counts["research_unserved_no_search_pass"] == 1, counts
    assert "research_searched" not in counts and final.counts["research_unserved_no_search_pass"] == 1
    # the owner presses «run now» on the match: a request pass reads the web, with the same levels
    run_now = cycle(conn, at=FINAL + timedelta(minutes=5), model=model, search=web, settings=config(max_web_first=1),
                    only=[f6], request=True)
    assert run_now.counts["research_asked"] == 1 and run_now.counts["research_searched"] == 1, dict(run_now.counts)
    assert web.of("F6") == expected(db, f6, (1, 2)), "the same two levels: the topic decides, not the pass"
