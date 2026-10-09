"""PrediGol AI V2 on a built world (``test_daily_records.World``: six matches on 1 Aug 2032 in Bogotá, one the next
day). What is tested here:

* only TODAY's matches (Bogotá) WITH a market get a model; a match without a market and tomorrow's get none;
* the day opens at 00:05 Bogotá, not before; each match gets its first, pre and final pass once;
* an identical input is never paid twice (the brief, the reviews, the web search while fresh);
* the adaptive budget (pace x load, ceiling, states) and the month's alerts, once each;
* a web search outage costs nothing and stops nothing; evidence from the web keeps its source;
* the cycle runs one at a time (a second one while the first holds the lock does nothing);
* after the matches: the post-mortem of every studied selection (the ten questions, the class of a loss) and the
  day's notes; nothing here changes a model, a rule or a pick;
* the user's own parlay: probabilities, combined odds and dependence - and never a model call.

No network and no key: the model is ``FakeProvider``, the search a function. One transaction, rolled back."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai.collectors import collect_web
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.cycle import run_analysis_cycle, run_learning_cycle
from fbi.ai.day import due_pass
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, budget, check_alerts, shared
from fbi.analyst.search import SearchResult
from fbi.userdata.records import LegIn, validate_parlay

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints, brief_reply, count, review_reply
from .test_daily_records import AT, World

SHADOW = AiSettings(mode="shadow")
DAY = AT.date()  # 1 Aug 2032 (AT is 07:00 in Bogotá)
MIDNIGHT = datetime(2032, 8, 1, 5, 0, tzinfo=UTC)  # 00:00 in Bogotá


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield World(db, seed)


def smart(decision: str = "APPROVE", *, extract: list[dict[str, Any]] | None = None, **kw: Any) -> FakeProvider:
    def answer(r: Any) -> dict[str, Any]:
        if r.schema_name == "submit_brief":
            return brief_reply()
        if r.schema_name == "submit_items":
            return {"items": extract or []}
        if r.schema_name == "submit_postmortem":
            return {"summary": "Perdió con una cuota justa: varianza.", "agrees_with_class": True, "lessons": []}
        if r.schema_name == "submit_lessons":
            return {"lessons": []}
        if r.schema_name == "submit_hypotheses":
            return {"hypotheses": []}
        return review_reply(decision)
    return FakeProvider(answer, name="anthropic", **kw)


def asked(model: FakeProvider, schema: str) -> int:
    return sum(1 for r in model.requests if r.schema_name == schema)


def run(conn: Any, *, at: datetime = AT, provider: FakeProvider | None = None, settings: AiSettings = SHADOW,
        search: Any = None, only: list[int] | None = None) -> Any:
    return run_analysis_cycle(conn, at=at, settings=settings, ledger=UsageLedger(shared(conn._conn)),
                              only_fixtures=only, search=search,
                              provider=None if provider is None else (provider, "claude-haiku-5-5"))


def unpriced_today(db: psycopg.Connection[Any], world: World) -> int:
    """A seventh match of the day, in the same league, with no market at all."""
    cur = db.cursor()
    season = db.execute("SELECT competition_season_id FROM core.fixtures WHERE id = %s",
                        (world.fixtures["F1"],)).fetchone()
    assert season is not None
    teams = []
    for n in (0, 1):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                    (975100 + n, f"F8-{'HA'[n]}"))
        teams.append(scalar(cur))
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at) VALUES (7340190, %s, %s, %s, %s) RETURNING id",
                (season[0], teams[0], teams[1], AT + timedelta(hours=5)))
    return scalar(cur)


# ── the day: only today's matches with a market ──────────────────────────────

def test_a_model_reads_only_todays_matches_that_have_a_market(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    f8 = unpriced_today(db, world)
    model = smart()
    report = run(conn, provider=model)
    assert report.status == "ok", report.errors
    today = [world.fixtures[f"F{i}"] for i in range(1, 7)]
    assert report.counts["universe"] == 6, "six matches of the day have a market; the seventh has none"
    briefed = {r[0] for r in db.execute("SELECT DISTINCT fixture_id FROM ai.match_briefs")}
    assert briefed == set(today)
    paid = {r[0] for r in db.execute("SELECT DISTINCT fixture_id FROM ai.usage WHERE fixture_id IS NOT NULL")}
    assert paid <= set(today) and world.fixtures["F7"] not in paid and f8 not in paid
    assert asked(model, "submit_brief") == 6 and asked(model, "submit_review") >= 1
    plan = db.execute("SELECT stage, fixtures_total, fixtures_with_market FROM ai.day_plans WHERE day = %s",
                      (DAY,)).fetchone()
    assert plan == ("opened", 7, 6)
    passes = db.execute("SELECT pass, count(*) FROM ai.fixture_passes WHERE day = %s GROUP BY pass", (DAY,)).fetchall()
    assert passes == [("first", 6)]
    # tomorrow's match still has its free analysis
    assert count(db, "SELECT count(*) FROM ai.match_analyses WHERE fixture_id = %s", world.fixtures["F7"]) == 1


def test_the_day_opens_at_00_05_bogota_and_not_before(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    for name in ("F1", "F2", "F3", "F4", "F5", "F6"):
        world.price(name, "2.30", MIDNIGHT - timedelta(hours=1))
    model = smart()
    run(conn, at=MIDNIGHT + timedelta(minutes=2), provider=model)
    assert model.requests == [] and count(db, "SELECT count(*) FROM ai.day_plans") == 0, "00:02: not yet"
    report = run(conn, at=MIDNIGHT + timedelta(minutes=6), provider=model)
    assert report.counts["day_opened"] == 1 and report.counts["pass_first"] == 6
    assert asked(model, "submit_brief") == 6


def test_each_pass_runs_once_and_an_unchanged_match_is_not_paid_again(db: psycopg.Connection[Any],
                                                                      world: World) -> None:
    conn = Savepoints(db)
    model = smart()
    run(conn, provider=model)
    first = len(model.requests)
    run(conn, at=AT + timedelta(minutes=15), provider=model)
    assert len(model.requests) == first, "between passes nothing is asked of a model"
    assert count(db, "SELECT count(*) FROM ai.fixture_passes") == 6
    # two hours later F3 (kick-off +6 h) and F4 (+8 h, not yet) - the pre pass: same input, nothing paid again
    f3 = world.fixtures["F3"]
    reviews_f3 = count(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND fixture_id = %s", f3)
    run(conn, at=AT + timedelta(hours=2), provider=model)
    kinds = {r[0] for r in db.execute("SELECT pass FROM ai.fixture_passes WHERE fixture_id = %s", (f3,))}
    assert kinds == {"first", "pre"}
    assert count(db, "SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND fixture_id = %s", f3) == \
        reviews_f3, "no material change: the review in force is carried, not bought again"
    # 50 minutes before kick-off: the final pass
    run(conn, at=AT + timedelta(hours=5, minutes=10), provider=model)
    kinds = {r[0] for r in db.execute("SELECT pass FROM ai.fixture_passes WHERE fixture_id = %s", (f3,))}
    assert kinds == {"first", "pre", "final"}
    run(conn, at=AT + timedelta(hours=5, minutes=30), provider=model)
    assert count(db, "SELECT count(*) FROM ai.fixture_passes WHERE fixture_id = %s", f3) == 3, "never twice"


def test_a_price_move_or_new_evidence_is_a_material_change(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    model = smart()
    only = [world.fixtures["F3"]]
    run(conn, provider=model, only=only)
    before = asked(model, "submit_review")
    world.price("F3", "2.40", AT + timedelta(hours=1))  # +14 % on the price taken
    run(conn, at=AT + timedelta(hours=2), provider=model, only=only)
    assert asked(model, "submit_review") == before + 1


def test_pass_rules_are_pure() -> None:
    ko = AT + timedelta(hours=5)
    assert due_pass(ko, at=AT, done={}, lineups_confirmed=False) == "first"
    first = {"first": AT}
    assert due_pass(ko, at=AT + timedelta(minutes=30), done=first, lineups_confirmed=False) is None
    assert due_pass(ko, at=AT + timedelta(hours=2), done=first, lineups_confirmed=False) == "pre"
    both = first | {"pre": AT + timedelta(hours=2)}
    assert due_pass(ko, at=ko - timedelta(minutes=95), done=both, lineups_confirmed=False) is None, \
        "waits for the line-ups"
    assert due_pass(ko, at=ko - timedelta(minutes=95), done=both, lineups_confirmed=True) == "final"
    assert due_pass(ko, at=ko - timedelta(minutes=45), done=both, lineups_confirmed=False) == "final"
    assert due_pass(ko, at=ko - timedelta(minutes=5), done={}, lineups_confirmed=True) is None, "too late"


# ── the budget ───────────────────────────────────────────────────────────────

OWNER = AiSettings(mode="shadow", monthly_budget=Decimal("150"), daily_budget=Decimal("5"))
MID = datetime(2032, 8, 15, 17, tzinfo=UTC)  # 12:00 in Bogotá, 17 days left in August


def _spend(db: psycopg.Connection[Any], at: datetime, usd: str) -> None:
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status) VALUES "
               "(%s, 'pick_review', 'analysis', 'anthropic', 'claude-sonnet-5-5', %s, 'ok')", (at, Decimal(usd)))


def test_the_daily_budget_follows_the_pace_left_in_the_month(db: psycopg.Connection[Any], seed: Seed) -> None:
    b = budget(db, at=MID, settings=OWNER)
    assert b.days_left == 17 and b.state == "NORMAL"
    assert b.daily == Decimal("8.8235"), "150 left over 17 days: a light first half leaves more for the rest"
    _spend(db, datetime(2032, 8, 10, 17, tzinfo=UTC), "105")
    b = budget(db, at=MID, settings=OWNER)
    assert b.daily == Decimal("2.6471") and b.cap == Decimal("3.9707"), "45 left over 17 days"
    _spend(db, MID - timedelta(hours=1), "2.70")
    assert budget(db, at=MID, settings=OWNER).state == "REDUCED", "past today's budget: no strong model"
    _spend(db, MID - timedelta(minutes=50), "0.70")
    assert budget(db, at=MID, settings=OWNER).state == "CHEAP_ONLY"
    _spend(db, MID - timedelta(minutes=40), "0.60")
    assert budget(db, at=MID, settings=OWNER).state == "EXHAUSTED", "the day's ceiling"


def test_an_important_day_may_spend_more_and_a_light_one_less(db: psycopg.Connection[Any], seed: Seed) -> None:
    for d in range(1, 15):
        db.execute("INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, "
                   "universe) VALUES (%s, 'opened', %s, 'day-v1', 50, 40, '[]')",
                   (MID.date() - timedelta(days=d), MID - timedelta(days=d)))
    db.execute("INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, "
               "universe) VALUES (%s, 'opened', %s, 'day-v1', 100, 80, '[]')", (MID.date(), MID - timedelta(hours=11)))
    _spend(db, datetime(2032, 8, 10, 17, tzinfo=UTC), "71")  # 79 left over 17 days: a pace of 4.65
    b = budget(db, at=MID, settings=OWNER)
    assert b.load == 2.0 and b.daily == Decimal("9.2941"), "twice a typical day's matches: twice the pace"
    with db.transaction():  # the owner's maintenance switch: a light day instead (10 matches against 40)
        db.execute("SET LOCAL fbi.ai_maintenance = 'on'")
        db.execute("UPDATE ai.day_plans SET fixtures_with_market = 10 WHERE day = %s", (MID.date(),))
        light = budget(db, at=MID, settings=OWNER)
    assert light.load == 0.5 and light.daily == Decimal("2.3235"), "a light day spends half the pace"


def test_the_months_alerts_are_recorded_once_each(db: psycopg.Connection[Any], seed: Seed) -> None:
    _spend(db, datetime(2032, 8, 10, 17, tzinfo=UTC), "106")
    assert check_alerts(db, at=MID, settings=OWNER) == [70]
    assert check_alerts(db, at=MID, settings=OWNER) == [], "once"
    _spend(db, datetime(2032, 8, 11, 17, tzinfo=UTC), "44")
    assert check_alerts(db, at=MID, settings=OWNER) == [85, 95, 100]
    assert budget(db, at=MID, settings=OWNER).state == "EXHAUSTED", "the month's cap stops everything"
    from fbi.notify.service import collect

    drafts = [d for d in collect(db, at=MID) if d.kind == "ai_budget"]
    assert {d.payload["threshold"] for d in drafts} == {70, 85, 95, 100}


# ── the web ─────────────────────────────────────────────────────────────────

def test_the_web_is_asked_once_while_fresh_and_its_evidence_keeps_its_source(db: psycopg.Connection[Any],
                                                                              world: World) -> None:
    conn: Any = Savepoints(db)
    calls: list[str] = []

    def search(query: str, at: datetime) -> list[SearchResult]:
        calls.append(query)
        return [SearchResult("https://www.marca.com/futbol/f1.html", "F1-H: bajas", "www.marca.com",
                             (at - timedelta(hours=3)).isoformat(), at.isoformat(), "El delantero no jugará."),
                SearchResult("https://foro.example/f1", "rumor", "foro.example", None, at.isoformat(), "dicen que")]
    model = smart(extract=[{"result_id": "R1", "side": "home", "player": "Delantero Uno", "kind": "injury",
                            "assertion": "out", "claim": "El delantero titular no jugará por lesión.",
                            "published_at": None}])
    settings = AiSettings(mode="shadow", max_web_first=2)
    run(conn, provider=model, settings=settings, search=search)
    assert len(calls) == 2, "the first pass searches only the most important matches"
    assert "noticias" in calls[0], "a Colombian league is searched in Spanish"
    web = db.execute("SELECT source_url, source_domain, source_tier, retrieved_at IS NOT NULL, status FROM ai.evidence "
                     "WHERE origin = 'web'").fetchall()
    assert web and all(r[0].startswith("https://") and r[3] for r in web)
    assert {r[1] for r in web} == {"marca.com"} and {r[2] for r in web} == {"media"}
    stats = db.execute("SELECT domain, results FROM ai.source_stats ORDER BY domain").fetchall()
    assert ("marca.com", 2) in stats and ("foro.example", 2) in stats
    # half an hour later the same match: the cached answer is fresh, nothing is asked again
    again = collect_web(conn, settings, world.fixtures["F1"], at=AT + timedelta(minutes=30),
                        ledger=UsageLedger(shared(db)), search=search, provider=(model, "claude-haiku-5-5"))
    assert again.skipped == "cached" and again.searches == 0 and len(calls) == 2
    assert count(db, "SELECT count(*) FROM ai.usage WHERE purpose = 'web_search' AND status = 'ok'") == 2
    assert db.execute("SELECT max(hits), max(last_hit_at) IS NOT NULL FROM ai.research_cache WHERE scope = 'search'"
                      ).fetchone() == (1, True)


def test_a_search_outage_costs_nothing_and_stops_nothing(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)

    def down(query: str, at: datetime) -> list[SearchResult]:
        raise RuntimeError("web research failed with HTTP 503")
    report = run(conn, provider=smart(), settings=AiSettings(mode="shadow", max_web_first=1), search=down)
    assert report.status == "ok"
    assert db.execute("SELECT status, cost_usd FROM ai.usage WHERE purpose = 'web_search'").fetchall() == \
        [("failed", Decimal("0"))]
    assert count(db, "SELECT count(*) FROM ai.fixture_passes") == 6, "the day went on"


# ── one cycle at a time ─────────────────────────────────────────────────────

def test_a_second_cycle_while_one_runs_does_nothing(db: psycopg.Connection[Any], world: World,
                                                    migrated_database: str) -> None:
    other = psycopg.connect(migrated_database, autocommit=True)
    try:
        other.execute("SELECT pg_advisory_lock(7310073)")
        model = smart()
        report = run(Savepoints(db), provider=model)
        assert report.counts["skipped_busy"] == 1 and model.requests == []
    finally:
        other.execute("SELECT pg_advisory_unlock(7310073)")
        other.close()


# ── after the matches ───────────────────────────────────────────────────────

def test_every_studied_selection_gets_its_post_mortem_and_the_day_its_notes(db: psycopg.Connection[Any],
                                                                            world: World) -> None:
    conn: Any = Savepoints(db)
    model = smart("APPROVE")
    run(conn, provider=model)
    world.result("F1", 0, 2)  # the approved home win lost
    world.result("F3", 2, 0)  # won
    world.result("F5", 1, 1)
    next_morning = datetime(2032, 8, 2, 12, 35, tzinfo=UTC)  # 07:35 in Bogotá
    report = run_learning_cycle(conn, at=next_morning, settings=SHADOW, provider=(model, "claude-haiku-5-5"),
                                ledger=UsageLedger(shared(db)))
    assert report.status in ("ok", "partial"), report.errors
    rows = db.execute("SELECT fixture_id, verdict, classification, answers FROM ai.pick_postmortems").fetchall()
    by = {r[0]: r for r in rows}
    f1, f3 = world.fixtures["F1"], world.fixtures["F3"]
    assert by[f1][1] in ("approved_lost", "caution_lost") and by[f1][2] is not None, "a loss has a class"
    assert by[f3][1] in ("approved_won", "caution_won") and by[f3][2] is None, "a win has no class"
    questions = {"expected", "happened", "model", "information", "ignored_signal", "odds_moved", "key_absence",
                 "lineup_changed", "uncertainty", "variance", "win_quality"}
    assert set(by[f1][3]) == questions
    notes = {r[0] for r in db.execute("SELECT kind FROM ai.learning_notes WHERE day = %s", (DAY,))}
    assert {"summary", "approved"} <= notes
    assert "pick_postmortem" in {r[0] for r in db.execute("SELECT DISTINCT kind FROM ai.memory_events")}
    assert report.counts["tomorrow_prepared"] == 1
    # learning again the same morning writes nothing twice
    run_learning_cycle(conn, at=next_morning + timedelta(minutes=5), settings=SHADOW)
    assert count(db, "SELECT count(*) FROM ai.pick_postmortems") == len(rows)
    # and nothing in production moved
    assert count(db, "SELECT count(*) FROM analytics.research_hypotheses WHERE status NOT IN ('PROPOSED')") == 0


# ── the user's own parlay: never a model ────────────────────────────────────

def test_a_users_parlay_is_measured_without_any_model(db: psycopg.Connection[Any], world: World) -> None:
    legs = [LegIn(world.fixtures["F1"], "1X2", "Home", Decimal(0)), LegIn(world.fixtures["F4"], "1X2", "Home",
                                                                          Decimal(0))]
    v = validate_parlay(db, legs, at=AT)
    assert v.ok and v.combined_odds == Decimal("5.290")
    assert v.dependency["level"] == "low", "two competitions"
    assert v.estimated_probability is not None and v.fair_probability is not None
    assert v.estimated_probability == pytest.approx(Decimal("0.25"), abs=Decimal("0.0001")), "0.50 x 0.50 by the model"
    same = validate_parlay(db, [LegIn(world.fixtures["F1"], "1X2", "Home", Decimal(0)),
                                LegIn(world.fixtures["F2"], "1X2", "Home", Decimal(0))], at=AT)
    assert same.dependency["level"] == "medium" and "same_competition_day" in same.dependency["reasons"]
    assert count(db, "SELECT count(*) FROM ai.usage") == 0, "the user's parlay never calls a model"


def test_no_tier_configured_means_rules_only(db: psycopg.Connection[Any], world: World) -> None:
    settings = AiSettings(mode="shadow", tiers={"bulk": TierModel("anthropic", "claude-haiku-5-5")})
    report = run(Savepoints(db), settings=settings)
    assert report.counts["briefs_rules"] == 6 and count(db, "SELECT count(*) FROM ai.usage") == 0, \
        "a tier without its key is not configured: the rules write the briefs"


def test_an_incomplete_brief_is_asked_once_more_and_never_paid_twice_for_the_same_input(
        db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    answers = iter([{"context": "no list"}, brief_reply(summary="Segunda respuesta, completa.")])

    def script(r: Any) -> dict[str, Any]:
        return next(answers) if r.schema_name == "submit_brief" else review_reply("APPROVE")
    model = FakeProvider(script, name="anthropic")
    run(conn, provider=model, only=[world.fixtures["F1"]])
    assert asked(model, "submit_brief") == 2, "one more try, told what was wrong"
    row = db.execute("SELECT engine, status, content->>'summary' FROM ai.match_briefs WHERE fixture_id = %s",
                     (world.fixtures["F1"],)).fetchone()
    assert row == ("llm", "ok", "Segunda respuesta, completa.")
    broken = FakeProvider(lambda r: {"nothing": True} if r.schema_name == "submit_brief" else review_reply(),
                          name="anthropic")
    run(conn, provider=broken, only=[world.fixtures["F3"]])
    assert asked(broken, "submit_brief") == 2
    rows = db.execute("SELECT engine, status FROM ai.match_briefs WHERE fixture_id = %s ORDER BY id",
                      (world.fixtures["F3"],)).fetchall()
    assert rows == [("llm", "invalid_output"), ("rules", "invalid_output")], "the rules write it; the model's two " \
        "invalid answers are recorded"
