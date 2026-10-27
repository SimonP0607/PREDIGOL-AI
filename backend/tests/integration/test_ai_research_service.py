"""Research by entity and topic for the Admin Console (``fbi.api.services.ai_research``) on a built world.

The world is the gate's (``test_gate_research.build``: October 2032, five matches a day, the passes of shadow from the 13th, the facts of v1 and
the same facts as typed claims of research v2), to which each test adds what it needs: the answers research v2 kept, the pages it read, the
ledger's searches, claims of other classes of source. Today is the 20th at noon in Bogotá. The service only reads: a test says so too."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import cache, gate_research, gates
from fbi.ai.contracts.mcp import source_class
from fbi.ai.evidence import EvidenceIn, domain_of, store
from fbi.ai.usage import UsageLedger, shared
from fbi.api.contracts.ai_research import ResearchOverview
from fbi.api.envelope import DataStatus
from fbi.api.services import ai_research as svc

from .conftest import Seed
from .test_gate_research import FIRST, LAST, NOW, World, build, noon, settings

pytestmark = pytest.mark.integration

D = Decimal
FAR = NOW + timedelta(days=3)  # a kick-off far enough for an answer to be reused for a day
TABLES = ("ai.feature_gates", "ai.evidence", "ai.fixture_passes", "ai.usage", "ai.research_cache")
NO_STATUS = {"CONFIRMED": 0, "PROBABLE": 0, "RUMOR": 0, "CONTRADICTORY": 0, "OUTDATED": 0}


def page(db: psycopg.Connection[Any], *, at: datetime = NOW, days: int = 8, word: str = "shadow") -> ResearchOverview:
    envelope = svc.overview(db, at=at, days=days, settings=settings(word))
    assert envelope.status is DataStatus.OK
    return envelope.data


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return build(db, seed)


def team_name(db: psycopg.Connection[Any], team_id: int) -> str:
    row = db.execute("SELECT name FROM core.teams WHERE id = %s", (team_id,)).fetchone()
    assert row is not None
    return str(row[0])


def answer(db: psycopg.Connection[Any], kind: str, entity: int, topic: str, *, at: datetime, level: int = 1, results: int = 4, standing: bool = True,
           classes: dict[str, int] | None = None, nearest: datetime = FAR) -> None:
    """What research v2 keeps after a search: the body it writes (``fbi.ai.entity_research``), under the key of the entity and the topic."""
    body = {"v": cache.KEY_VERSION, "topic": topic, "level": level, "search": "k", "searched_at": at.isoformat(), "results": results,
            "standing": standing, "classes": classes if classes is not None else {"media": results - 1, "official": 1}}
    cache.remember(db, kind, entity, topic, body, at=at, nearest_kickoff=nearest)


def claim(db: psycopg.Connection[Any], seed: Seed, tag: str, *, tier: str, host: str, at: datetime, fixture: int | None = None, claim_type: str = "OTHER",
          subject: str = "TEAM", fresh_hours: int = 24, flagged: bool = False, status: str | None = None) -> None:
    """A typed claim of any class of source, as the extractor of research v2 writes them."""
    item = EvidenceIn(fixture_id=fixture, team_id=seed.home_team_id, kind="news", claim=f"claim {tag}", origin="web", source_name=host, retrieved_at=at,
                      story_key=f"t:{tag}", source_url=f"https://{host}/{tag}", assertion="info", source_tier=tier,
                      published_at=at - timedelta(hours=1), attributes={"instruction_like": True} if flagged else {}, claim_type=claim_type,
                      subject_type=subject, subject_id=seed.home_team_id if subject == "TEAM" else (fixture or 1),
                      fresh_until=at + timedelta(hours=fresh_hours))
    evidence_id, created = store(db, item, at=at)
    assert created
    if status is not None:
        db.execute("UPDATE ai.evidence SET status = %s WHERE id = %s", (status, evidence_id))


def search(ledger: UsageLedger, at: datetime, cost: str, tag: str, status: str = "ok") -> None:
    ledger.record(at=at, purpose="web_search", tier="search", provider="exa", model="exa", usage=None, cost=D(cost), status=status,
                  input_hash=tag)


def extraction(ledger: UsageLedger, at: datetime, status: str = "ok") -> None:
    ledger.record(at=at, purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None, cost=D("0.001"), status=status,
                  input_hash="x", agent="claim_extractor")


# ── a page with nothing in it ────────────────────────────────────────────────────────────────────────────────────────

def test_a_database_without_research_gives_a_page_of_zeros_that_says_so(db: psycopg.Connection[Any]) -> None:
    p = page(db, days=7)
    assert (p.days, p.since) == (7, datetime(2032, 10, 14, 5, 0, tzinfo=UTC)), "the window starts at Bogotá's midnight of its first day"
    assert (p.switch.asked, p.switch.mode, p.switch.typed_visible, p.switch.gate_passed, p.switch.gate_at, p.switch.history) == (
        "shadow", "shadow", False, False, None, [])
    assert [(t.topic, t.entity, t.levels, t.entries, t.fresh, t.expired, t.reuses) for t in p.freshness.topics] == [
        ("availability", "TEAM", [1, 2], 0, 0, 0, 0), ("confirmation", "TEAM", [2], 0, 0, 0, 0), ("preview", "MATCH", [3], 0, 0, 0, 0)]
    assert p.freshness.unreadable == 0 and p.answers == []
    assert p.claims.total == 0 and p.claims.by_status == NO_STATUS
    assert [c.key for c in p.claims.by_class] == ["OFFICIAL", "PROVIDER", "JOURNALIST", "RELIABLE_MEDIA", "LOCAL_MEDIA", "AGGREGATOR", "SOCIAL", "UNKNOWN"], \
        "every class of source is a row, even the ones nothing came from: that is a finding"
    assert [c.key for c in p.claims.by_type] == ["OUT", "DOUBT", "AVAILABLE", "STARTER", "SUSPENSION", "COACH", "SCHEDULE", "VENUE", "OTHER"]
    assert [d.day for d in p.per_day] == [date(2032, 10, 20) - timedelta(days=k) for k in range(7)], "newest first, a day with nothing is a row of zeros"
    assert all(d.passes == 0 and d.searches == 0 and d.exa_v1_usd == 0 and d.exa_v2_usd == 0 for d in p.per_day)
    assert (p.pages.remembered, p.pages.fresh, p.pages.reuses, p.pages.read) == (0, 0, 0, 0)
    assert (p.comparison.status, p.comparison.code, p.comparison.data) == (DataStatus.EMPTY, "no_v2_passes", None)
    assert p.gate.status is DataStatus.OK and p.gate.data is not None and p.gate.data.verdict == gate_research.PENDING_TIME
    assert p.gate.data.checks == [] and "ningún día completo" in p.gate.data.pending[0]


def test_the_last_day_of_the_page_is_the_day_in_bogota_and_not_the_day_in_utc(db: psycopg.Connection[Any]) -> None:
    at = datetime(2032, 10, 21, 3, 0, tzinfo=UTC)  # 22:00 of the 20th in Bogotá, already the 21st in UTC
    p = page(db, at=at, days=7)
    assert [d.day for d in p.per_day] == [date(2032, 10, 20) - timedelta(days=k) for k in range(7)]
    assert p.since == datetime(2032, 10, 14, 5, 0, tzinfo=UTC)


# ── the switch ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_switch_shows_the_word_the_mode_and_the_evidence_behind_on(world: World) -> None:
    db = world.db
    for word, mode in (("off", "off"), ("shadow", "shadow"), ("on", "shadow")):
        s = page(db, word=word).switch
        assert (s.asked, s.mode, s.typed_visible, s.gate_passed) == (word, mode, False, False), "on without evidence behaves as shadow"
    assert "waiting for the research_v2 gate" in page(db, word="on").switch.why
    first = gate_research.record(db, gate_research.evaluate(db, settings(), at=NOW))
    s = page(db, word="on").switch
    assert (s.asked, s.mode, s.typed_visible, s.gate_passed, s.gate_at) == ("on", "on", True, True, NOW)
    assert [(r.id, r.passed, r.decided_by) for r in s.history] == [(first, True, "script")]
    assert s.history[0].evidence_hash and "gate passed" in s.why
    later = gates.record_gate(db, gate="research_v2", passed=False, evidence={"verdict": "NO PASA"}, at=NOW + timedelta(hours=1), code_version="x")
    s = page(db, word="on", at=NOW + timedelta(hours=2)).switch
    assert (s.mode, s.typed_visible, s.gate_passed, s.gate_at) == ("shadow", False, False, NOW + timedelta(hours=1)), "the newest row decides"
    assert [r.id for r in s.history] == [later, first] and s.history[0].code_version == "x" and s.history[1].code_version is None


def test_the_history_of_the_gate_is_the_last_five_rows_of_this_gate_alone(db: psycopg.Connection[Any]) -> None:
    ids = [gates.record_gate(db, gate="research_v2", passed=k % 2 == 0, evidence={"k": k}, at=NOW + timedelta(minutes=k)) for k in range(7)]
    other = gates.record_gate(db, gate="battery", passed=True, evidence={"k": "battery"}, at=NOW + timedelta(hours=9))
    history = page(db).switch.history
    assert [r.id for r in history] == ids[::-1][:5] and other not in [r.id for r in history]


# ── freshness: what the cache holds for each topic ───────────────────────────────────────────────────────────────────

def test_each_topic_shows_its_rule_and_what_the_cache_holds_for_it(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=3))
    answer(db, "TEAM", seed.away_team_id, "availability", at=NOW - timedelta(hours=30))  # a day's freshness: expired six hours ago
    answer(db, "TEAM", seed.home_team_id, "confirmation", at=NOW - timedelta(hours=1), level=2)
    answer(db, "MATCH", world.fixtures[LAST][0], "preview", at=NOW - timedelta(hours=2), level=3, standing=False)
    for _ in range(2):  # two matches of the home team read what is known instead of searching again
        assert cache.fresh(db, "TEAM", seed.home_team_id, "availability", at=NOW, nearest_kickoff=FAR) is not None
    assert cache.fresh(db, "TEAM", seed.away_team_id, "availability", at=NOW, nearest_kickoff=FAR) is None, "an expired answer is not a reuse"
    p = page(db)
    topics = {t.topic: t for t in p.freshness.topics}
    a, c, v = topics["availability"], topics["confirmation"], topics["preview"]
    assert (a.entries, a.fresh, a.expired, a.reuses, a.newest_at, a.last_reuse_at) == (2, 1, 1, 2, NOW - timedelta(hours=3), NOW)
    assert (c.entries, c.fresh, c.expired, c.reuses, c.last_reuse_at) == (1, 1, 0, 0, None)
    assert (v.entries, v.fresh, v.expired, v.reuses, v.newest_at) == (1, 1, 0, 0, NOW - timedelta(hours=2))
    assert (a.early_hours, a.late_hours, v.early_hours, v.late_hours) == (24.0, 4.0, 24.0, 4.0) and p.freshness.late_window_hours == 12.0
    assert a.label == "quién puede jugar (bajas, dudas, sanciones)" and v.entity == "MATCH" and c.entity == "TEAM"


def test_a_key_this_code_does_not_read_is_counted_and_never_listed(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=1))
    for key in ("rk-v2:team:999:nonsense", "rk-v2:planet:5:availability", "garbage", "rk-v2:team:x:availability", "rk-v2:team:1:availability:extra",
                f"rk-v2:team:{10 ** 16}:availability"):
        cache.put(db, "entity", key, {"results": 1}, at=NOW - timedelta(hours=1), ttl=timedelta(hours=24))
    # keys of the right shape that name a topic or a kind this code does not read: several in each group, every one counted
    for key in ("rk-v2:team:11:injuries", "rk-v2:team:12:injuries", "rk-v2:club:1:availability", "rk-v2:club:2:availability"):
        cache.put(db, "entity", key, {"results": 1}, at=NOW - timedelta(hours=1), ttl=timedelta(hours=24))
    # a page of the url scope is not an answer of the entity scope, whatever its key looks like
    cache.put(db, "url", "rk-v2:team:5:availability", {"tokens": []}, at=NOW - timedelta(hours=1), ttl=timedelta(hours=24))
    p = page(db)
    assert p.freshness.unreadable == 10 and [(a.kind, a.id, a.topic) for a in p.answers] == [("TEAM", seed.home_team_id, "availability")]
    assert sum(t.entries for t in p.freshness.topics) == 1, "the unreadable ones are in no topic, and a key of another scope is nobody's"


def test_a_topic_shows_the_newest_answer_and_the_latest_reuse_of_every_kind_of_entity_that_keeps_it(world: World) -> None:
    db, seed = world.db, world.seed
    kept = (("TEAM", seed.home_team_id, 5, 3), ("PLAYER", 77, 2, 1), ("COACH", 78, 9, 2))  # (kind, entity, hours since it was kept, hours since it was reused)
    for kind, entity, kept_ago, _ in kept:
        answer(db, kind, entity, "availability", at=NOW - timedelta(hours=kept_ago))
    for kind, entity, _, reused_ago in kept:
        assert cache.fresh(db, kind, entity, "availability", at=NOW - timedelta(hours=reused_ago), nearest_kickoff=FAR) is not None
    a = {t.topic: t for t in page(db).freshness.topics}["availability"]
    assert (a.entries, a.reuses) == (3, 3)
    assert (a.newest_at, a.last_reuse_at) == (NOW - timedelta(hours=2), NOW - timedelta(hours=1)), "the newest of the three, whichever group is read first"


def test_an_answer_that_expires_at_the_very_moment_of_the_page_is_expired(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=24))  # kept for a day: it expires now
    answer(db, "TEAM", seed.away_team_id, "availability", at=NOW - timedelta(hours=24) + timedelta(seconds=1))
    p = page(db)
    a = {t.topic: t for t in p.freshness.topics}["availability"]
    assert (a.entries, a.fresh, a.expired) == (2, 1, 1)
    assert {x.id: x.fresh for x in p.answers} == {seed.home_team_id: False, seed.away_team_id: True}


# ── the answers, entity by entity ────────────────────────────────────────────────────────────────────────────────────

def test_the_answers_are_listed_newest_first_with_the_entity_named_and_what_its_claims_are_worth(world: World) -> None:
    db, seed = world.db, world.seed
    last = world.fixtures[LAST][0]
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=5), classes={"media": 3, "official": 1})
    answer(db, "MATCH", last, "preview", at=NOW - timedelta(hours=1), level=3, results=6, standing=False, classes={"unknown": 6})
    answer(db, "TEAM", seed.away_team_id, "confirmation", at=NOW - timedelta(hours=2), level=2, results=0, standing=False, classes={})
    p = page(db)
    assert [(a.kind, a.id, a.topic) for a in p.answers] == [("MATCH", last, "preview"), ("TEAM", seed.away_team_id, "confirmation"),
                                                          ("TEAM", seed.home_team_id, "availability")]
    match, away, home = p.answers
    assert match.name == f"{team_name(db, seed.home_team_id)} vs {team_name(db, seed.away_team_id)}" and match.kickoff_at == noon(LAST) + timedelta(hours=3)
    assert (match.level, match.results, match.standing, match.tiers) == (3, 6, False, {"unknown": 6})
    assert (away.name, away.kickoff_at, away.level, away.results, away.standing, away.tiers) == (team_name(db, seed.away_team_id), None, 2, 0, False, {})
    assert (home.name, home.level, home.results, home.standing, home.tiers) == (team_name(db, seed.home_team_id), 1, 4, True, {"media": 3, "official": 1})
    assert (home.fetched_at, home.expires_at, home.fresh) == (NOW - timedelta(hours=5), NOW + timedelta(hours=19), True)
    assert (home.reuses, home.last_reuse_at) == (0, None)
    # the claims of the world: 35 about each team in the week, 2 about the match; none can still be reused at this hour (24 h after 15:00 of each day)
    assert (home.claims, home.claims_fresh, away.claims, away.claims_fresh, match.claims, match.claims_fresh) == (35, 0, 35, 0, 2, 0)


def test_what_a_claim_can_still_be_reused_for_is_judged_at_the_moment_of_the_page(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=datetime(2032, 10, 19, 19, 0, tzinfo=UTC))
    p = page(db, at=datetime(2032, 10, 19, 20, 0, tzinfo=UTC), days=7)
    (home,) = p.answers
    assert (home.claims, home.claims_fresh) == (35, 5), "the five claims of the 19th were retrieved at 15:00 and live until 15:00 of the 20th"
    assert p.claims.fresh == 10 and p.claims.total == 70


def test_the_claims_of_an_entity_are_those_of_the_window_and_the_fresh_ones_those_that_outlive_the_page(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=1))
    first = datetime(2032, 10, 13, 5, 0, tzinfo=UTC)
    claim(db, seed, "edge-of-window", tier="media", host="marca.com", at=first, fresh_hours=1)  # the first moment of the window: inside it, long stale
    claim(db, seed, "before-window", tier="media", host="marca.com", at=first - timedelta(seconds=1), fresh_hours=1)  # one second before: outside
    claim(db, seed, "expires-now", tier="media", host="marca.com", at=NOW - timedelta(hours=3), fresh_hours=3)  # fresh until this very moment: not fresh
    claim(db, seed, "expires-later", tier="media", host="marca.com", at=NOW - timedelta(hours=3), fresh_hours=4)
    p = page(db)
    (home,) = p.answers
    assert (home.claims, home.claims_fresh) == (35 + 3, 1)
    assert (p.claims.total, p.claims.fresh) == (70 + 3, 1)


def test_an_answer_whose_body_is_not_what_the_writer_writes_is_listed_without_inventing_anything(world: World) -> None:
    db, seed = world.db, world.seed
    cache.put(db, "entity", cache.entity_key("TEAM", seed.home_team_id, "availability"),
              {"level": "one", "results": "many", "standing": "yes", "classes": [1, 2]}, at=NOW - timedelta(hours=1), ttl=timedelta(hours=24))
    cache.put(db, "entity", cache.entity_key("TEAM", seed.away_team_id, "availability"),
              {"level": True, "results": 2.5, "standing": None, "classes": {"media": "x", "official": 2, "social": True}}, at=NOW - timedelta(hours=2),
              ttl=timedelta(hours=24))
    odd, odder = page(db).answers
    assert (odd.level, odd.results, odd.standing, odd.tiers) == (None, None, None, {})
    assert (odder.level, odder.results, odder.standing, odder.tiers) == (None, None, None, {"official": 2})


def test_an_entity_the_page_cannot_name_is_listed_by_its_id(db: psycopg.Connection[Any]) -> None:
    answer(db, "TEAM", 987654321, "availability", at=NOW - timedelta(hours=1))
    answer(db, "MATCH", 987654322, "preview", at=NOW - timedelta(hours=2), level=3)
    answer(db, "COMPETITION", 5, "availability", at=NOW - timedelta(hours=3))
    named = [(a.kind, a.id, a.name, a.kickoff_at, a.claims) for a in page(db).answers]
    assert named == [("TEAM", 987654321, None, None, 0), ("MATCH", 987654322, None, None, 0), ("COMPETITION", 5, None, None, 0)]


def test_only_a_team_is_named_as_a_team_whatever_its_number_is(world: World) -> None:
    """The id of a player or of a coach can be the id of a team: the name belongs to the kind of entity that was asked about."""
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=1))
    answer(db, "PLAYER", seed.home_team_id, "availability", at=NOW - timedelta(hours=2))
    answer(db, "COACH", seed.home_team_id, "availability", at=NOW - timedelta(hours=3))
    assert [(a.kind, a.name) for a in page(db).answers] == [("TEAM", team_name(db, seed.home_team_id)), ("PLAYER", None), ("COACH", None)]


def test_the_list_is_the_newest_few(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    db, seed = world.db, world.seed
    monkeypatch.setattr(svc, "ANSWERS", 3)
    asked = (
        (seed.home_team_id, "availability"),
        (seed.home_team_id, "confirmation"),
        (seed.away_team_id, "availability"),
        (seed.away_team_id, "confirmation"),
    )  # four different keys: asking again for the same entity and topic replaces its answer
    for k, (team, topic) in enumerate(asked):
        answer(db, "TEAM", team, topic, at=NOW - timedelta(hours=k + 1), level=1 + k)
    assert [a.level for a in page(db).answers] == [1, 2, 3], "the three newest"


def test_an_answer_older_than_the_window_is_not_listed(world: World) -> None:
    db, seed = world.db, world.seed
    answer(db, "TEAM", seed.home_team_id, "availability", at=NOW - timedelta(hours=1), results=7)
    answer(db, "TEAM", seed.away_team_id, "availability", at=NOW - timedelta(days=9), results=99)  # the 11th at noon
    assert [a.results for a in page(db, days=8).answers] == [7], "the window of 8 days starts on the 13th"
    assert [a.results for a in page(db, days=10).answers] == [7, 99]


def test_the_first_moment_of_the_window_is_inside_it(world: World) -> None:
    db, seed = world.db, world.seed
    first = datetime(2032, 10, 13, 5, 0, tzinfo=UTC)  # midnight of the 13th in Bogotá
    answer(db, "TEAM", seed.home_team_id, "availability", at=first, results=8)
    answer(db, "TEAM", seed.away_team_id, "availability", at=first - timedelta(seconds=1), results=9)
    assert [a.results for a in page(db, days=8).answers] == [8]


# ── the claims ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_claims_of_the_world_are_counted_by_class_of_source_type_and_status(world: World) -> None:
    c = page(world.db).claims
    media = source_class("media", domain_of("https://www.marca.com/x"))
    assert (c.total, c.fresh, c.entity_scoped, c.match_scoped, c.flagged) == (70, 0, 0, 70, 0)
    assert c.by_status == NO_STATUS | {"PROBABLE": 70}
    classes = {x.key: x for x in c.by_class}
    assert classes[media].total == 70 and classes[media].by_status == NO_STATUS | {"PROBABLE": 70}
    assert [x.key for x in c.by_class if x.total] == [media]
    types = {x.key: x.total for x in c.by_type}
    assert types["OUT"] == 35 and types["OTHER"] == 35 and sum(types.values()) == 70


def test_classes_statuses_scopes_and_flags_are_told_apart(world: World) -> None:
    db, seed = world.db, world.seed
    at = NOW - timedelta(hours=4)
    claim(db, seed, "social", tier="social", host="twitter.com", at=at, claim_type="DOUBT")  # a rumour about the team, with no match
    claim(db, seed, "official", tier="official", host="uefa.com", at=at, fixture=world.fixtures[LAST][0], claim_type="SUSPENSION", subject="MATCH",
          status="CONFIRMED")
    claim(db, seed, "order", tier="media", host="marca.com", at=at, fixture=world.fixtures[LAST][1], flagged=True, fresh_hours=1)  # stale by NOW
    claim(db, seed, "old", tier="aggregator", host="sofascore.com", at=NOW - timedelta(days=30), claim_type="COACH")  # outside the window
    c = page(db).claims
    assert (c.total, c.entity_scoped, c.match_scoped, c.flagged, c.fresh) == (73, 1, 72, 1, 2), "the 30-day-old claim is not in the window"
    assert c.by_status == NO_STATUS | {"CONFIRMED": 1, "PROBABLE": 71, "RUMOR": 1}
    classes = {x.key: x for x in c.by_class}
    assert (classes["SOCIAL"].total, classes["SOCIAL"].fresh, classes["SOCIAL"].by_status["RUMOR"]) == (1, 1, 1)
    assert (classes["OFFICIAL"].total, classes["OFFICIAL"].fresh, classes["OFFICIAL"].by_status["CONFIRMED"]) == (1, 1, 1)
    assert classes["AGGREGATOR"].total == 0
    types = {x.key: x.total for x in c.by_type}
    assert (types["DOUBT"], types["SUSPENSION"], types["COACH"], types["OTHER"], types["OUT"]) == (1, 1, 0, 36, 35)


def test_a_typed_claim_with_no_class_and_no_type_is_the_unclassified_and_the_other(world: World) -> None:
    """The columns allow NULL (a row put in by hand, a vocabulary of the future): the page counts it as the class nobody classified and the type that is
    none of the others, and does not drop it."""
    db, seed = world.db, world.seed
    claim(db, seed, "odd", tier="media", host="marca.com", at=NOW - timedelta(hours=1))
    db.execute(
        "INSERT INTO ai.evidence (fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, "
        "author, published_at, retrieved_at, event_at, story_key, content_hash, payload_hash, confidence, relevance, attributes, status, status_reason, "
        "status_changed_at, claim_type, subject_type, subject_id, source_class, fresh_until) "
        "SELECT fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, author, published_at, "
        "retrieved_at, event_at, 'by-hand', 'by-hand', payload_hash, confidence, relevance, attributes, status, status_reason, status_changed_at, "
        "NULL, subject_type, subject_id, NULL, fresh_until FROM ai.evidence WHERE story_key = 't:odd'")
    c = page(db).claims
    assert c.total == 72
    assert {x.key: x.total for x in c.by_class}["UNKNOWN"] == 1 and {x.key: x.total for x in c.by_type}["OTHER"] == 37


# ── the days ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_day_shows_what_the_passes_needed_paid_borrowed_and_reused(world: World) -> None:
    p = page(world.db, days=10)
    assert [d.day for d in p.per_day] == [date(2032, 10, 20) - timedelta(days=k) for k in range(10)]
    by = {d.day: d for d in p.per_day}
    today, shadow, before = by[date(2032, 10, 20)], by[date(2032, 10, 16)], by[date(2032, 10, 11)]
    assert (today.passes, today.searches, today.demand) == (0, 0, 0)
    assert (shadow.passes, shadow.passes_v2, shadow.passes_failed, shadow.passes_cut) == (5, 5, 0, 0)
    assert (shadow.searches, shadow.demand, shadow.paid, shadow.shared, shadow.reused) == (10, 10, 0, 5, 5)
    assert (shadow.claims, shadow.claims_new, shadow.pages, shadow.pages_known) == (10, 10, 0, 0)
    assert (before.passes, before.passes_v2, before.searches, before.demand, before.claims) == (5, 0, 10, 0, 0), "before shadow only v1's searches were counted"


def test_a_pass_that_failed_or_was_cut_short_is_counted_apart(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, shape=lambda day, i, counted: {"research_v2_shadow": 1, "web_searches": 2, "v2_failed": 1} if day == LAST and i == 0 else
                  {"research_v2_shadow": 1, "web_searches": 2, "v2_skipped_budget_exa": 1} if day == LAST and i == 1 else
                  {"research_v2_on": 1, "web_searches": 1, "v2_paid": 1} if day == LAST and i == 2 else
                  {"research_v2_shadow": 1, "web_searches": 2, "v2_failed": 1, "v2_skipped_outage": 1} if day == LAST and i == 3 else
                  {"research_v2_shadow": 1, "web_searches": 2, "v2_failed": 0, "v2_skipx": 1} if day == LAST and i == 4 else counted)
    last = {d.day: d for d in page(world.db).per_day}[LAST]
    assert (last.passes, last.passes_v2, last.passes_failed, last.passes_cut) == (5, 5, 2, 1), (
        "research v2 in force counts as a pass that ran it; a pass that failed is not also cut short; a count of zero failures is not a failure, "
        "and a word that only starts like `v2_skipped_` is not a cut")
    assert (last.searches, last.paid) == (2 + 2 + 1 + 2 + 2, 1)


def test_a_figure_that_is_not_a_whole_number_is_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, counts={"research_v2_shadow": 1, "web_searches": 2.5, "v2_paid": "lots", "v2_claims": True, "v2_reused": 3,  # type: ignore[dict-item]
                                    "v2_demand": None})  # type: ignore[dict-item]
    day = {d.day: d for d in svc.overview(world.db, at=NOW, days=8, settings=settings()).data.per_day}[LAST]
    assert (day.searches, day.paid, day.claims, day.reused, day.demand) == (0, 0, 0, 15, 0)


def test_the_ledger_attributes_each_search_to_its_bogota_day_and_its_arm(world: World) -> None:
    ledger = UsageLedger(shared(world.db))
    for k in range(3):
        search(ledger, noon(date(2032, 10, 16)) + timedelta(minutes=k), "0.007", f"q{k}")
    search(ledger, datetime(2032, 10, 17, 3, 0, tzinfo=UTC), "0.007", "rk-v2:late-in-the-16th")  # 22:00 of the 16th in Bogotá
    search(ledger, datetime(2032, 10, 17, 6, 0, tzinfo=UTC), "0.007", "rk-v2:early-in-the-17th")  # 01:00 of the 17th in Bogotá
    search(ledger, noon(date(2032, 10, 16)), "0.007", "rk-v2:failed", status="failed")  # a search that failed is not one that was paid
    search(ledger, noon(date(2032, 10, 16)), "0.007", "failed-too", status="failed")
    search(ledger, noon(date(2032, 10, 3)), "0.007", "before-the-window")
    extraction(ledger, noon(date(2032, 10, 16)))
    by = {d.day: d for d in page(world.db).per_day}
    assert (by[date(2032, 10, 16)].exa_v1_usd, by[date(2032, 10, 16)].exa_v2_usd) == (D("0.021"), D("0.007"))
    assert (by[date(2032, 10, 17)].exa_v1_usd, by[date(2032, 10, 17)].exa_v2_usd) == (D("0"), D("0.007"))
    assert sum(d.exa_v1_usd for d in by.values()) == D("0.021"), "the search of the 3rd is outside the window, and a model's call is not a search"


def test_the_pages_remembered_are_research_v2s_alone_and_the_window_says_what_was_done_with_pages(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, counts={"research_v2_shadow": 1, "web_searches": 2, "v2_pages": 3, "v2_pages_known": 4, "v2_pages_unread": 1,
                                    "v2_pages_flagged": 1})
    first, second = cache.url_key("https://www.marca.com/a"), cache.url_key("https://as.com/b")
    cache.put(world.db, "url", first, {"tokens": ["TEAM:1"], "read_at": NOW.isoformat()}, at=NOW - timedelta(hours=1), ttl=timedelta(days=2))
    cache.put(world.db, "url", second, {"tokens": ["TEAM:2"], "read_at": NOW.isoformat()}, at=NOW - timedelta(days=5), ttl=timedelta(days=2))
    cache.put(world.db, "url", f"{world.fixtures[LAST][0]}:https://www.marca.com/a", {"tokens": []}, at=NOW - timedelta(hours=1), ttl=timedelta(days=2))  # v1's
    cache.put(world.db, "entity", f"{cache.KEY_VERSION}:url:{'a' * 40}", {"tokens": []}, at=NOW - timedelta(hours=1), ttl=timedelta(days=2))  # not a page
    assert cache.get(world.db, "url", first, at=NOW) is not None and cache.get(world.db, "url", first, at=NOW) is not None
    assert cache.get(world.db, "url", second, at=NOW) is None
    pages = page(world.db).pages
    assert (pages.remembered, pages.fresh, pages.reuses) == (2, 1, 2), "v1's key for a page is not research v2's"
    assert (pages.read, pages.known, pages.unread, pages.flagged) == (3 * 35, 4 * 35, 35, 35)


# ── v1 against research v2, and the gate ─────────────────────────────────────────────────────────────────────────────

def test_the_comparison_is_the_gates_own_arithmetic_over_the_window_of_the_page(world: World) -> None:
    ledger = UsageLedger(shared(world.db))
    for k in range(3):
        search(ledger, noon(date(2032, 10, 16)) + timedelta(minutes=k), "0.007", f"q{k}")
    search(ledger, noon(date(2032, 10, 16)), "0.007", "rk-v2:search:1")
    for status in ("ok", "ok", "ok", "invalid_output"):
        extraction(ledger, noon(date(2032, 10, 17)), status)
    section = page(world.db).comparison
    assert section.status is DataStatus.OK and section.data is not None
    c = section.data
    assert (c.first, c.last) == (date(2032, 10, 13), date(2032, 10, 20))
    assert (c.passes_in_shadow, c.passes_compared, c.passes_v2_failed, c.passes_v2_cut_short) == (35, 35, 0, 0)
    assert (c.searches_v1, c.searches_v2_alone, c.saved, c.saved_pct, c.reuse_pct) == (70, 35, 35, D("50.00"), D("33.33"))
    assert (c.fixtures, c.facts_v1, c.facts_v2, c.found_by_v2, c.coverage_pct, c.coverage_players_pct) == (35, 70, 70, 70, D("100.00"), D("100.00"))
    assert (c.facts_per_match_v1, c.facts_per_match_v2, c.missed_examples) == (2.0, 2.0, [])
    assert (c.exa_v1_searches, c.exa_v1_usd, c.exa_v2_searches, c.exa_v2_usd) == (3, D("0.021"), 1, D("0.007"))
    assert (c.extractor_calls, c.extractor_by_status, c.extractor_invalid_pct) == (4, {"invalid_output": 1, "ok": 3}, D("25.00"))


def test_a_window_in_which_research_v2_only_failed_is_still_a_comparison_that_says_so(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, counts={"research_v2_shadow": 1, "web_searches": 2, "v2_failed": 1})
    section = page(world.db).comparison
    assert section.status is DataStatus.OK and section.data is not None, "research v2 ran in these passes: it failed, and that is the finding"
    c = section.data
    assert (c.passes_in_shadow, c.passes_compared, c.passes_v2_failed, c.passes_v2_cut_short) == (35, 0, 35, 0)
    assert (c.searches_v1, c.searches_v2_alone, c.saved, c.saved_pct, c.reuse_pct) == (0, 0, 0, None, None), "nothing finished, nothing to compare"


def test_the_comparison_names_the_facts_of_v1_that_research_v2_did_not_find(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=2)
    c = page(world.db).comparison.data
    assert c is not None and (c.facts_v1, c.found_by_v2, c.coverage_pct, c.coverage_players_pct) == (70, 68, D("97.14"), D("94.29"))
    first_two = sorted(world.fixtures[FIRST][:2])
    assert c.missed_examples == [[f, "home", str(f), "out"] for f in first_two], "the first two matches of the window, whose striker research v2 missed"


def test_without_a_pass_under_shadow_there_is_nothing_to_compare_and_the_gate_waits(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=None)
    p = page(db)
    assert (p.comparison.status, p.comparison.code, p.comparison.data) == (DataStatus.EMPTY, "no_v2_passes", None) and p.comparison.reason
    assert p.gate.data is not None and p.gate.data.verdict == gate_research.PENDING_TIME and p.gate.data.window.stable_complete_days == 0


def test_the_gate_is_what_the_gate_says_now_and_evaluating_it_records_nothing(world: World) -> None:
    db = world.db
    before = [db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in TABLES]
    p = page(db)
    assert [db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in TABLES] == before, "the page reads"
    report = gate_research.evaluate(db, settings(), at=NOW)
    g = p.gate.data
    assert g is not None and p.gate.status is DataStatus.OK
    assert (g.verdict, g.at, g.consequence, g.pending) == (gate_research.PASS, NOW, None, [])
    assert (g.window.first, g.window.last, g.window.stable_complete_days, g.window.complete) == (FIRST, LAST, 7, True)
    assert [(k.id, k.ok, k.mark, k.revert) for k in g.checks] == [(k.id, k.ok, k.mark, k.revert) for k in report.checks]
    assert [k.detail for k in g.checks] == [k.as_json()["detail"] for k in report.checks]
    assert [k.id for k in g.checks] == ["window", "fewer_searches", "coverage", "coverage_players", "shadow_invisible", "evidence_known", "sample"]
    assert g.preview == report.preview and set(g.preview) == {"exa", "extractor"}


def test_a_failing_gate_carries_what_to_do_about_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_news=5)
    g = page(world.db).gate.data
    assert g is not None and g.verdict == gate_research.FAIL and g.consequence and "sigue en sombra" in g.consequence
    assert [k.id for k in g.checks if k.ok is False] == ["coverage"]


# ── a part that fails does not take the page down ────────────────────────────────────────────────────────────────────

def test_a_gate_that_cannot_be_evaluated_is_a_sub_answer_that_says_so_and_never_the_message(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("password=hunter2 host=10.0.0.5")

    monkeypatch.setattr(gate_research, "evaluate", broken)
    p = page(world.db)
    assert (p.gate.status, p.gate.code, p.gate.data) == (DataStatus.NOT_AVAILABLE, "gate_failed", None)
    assert p.gate.reason == "gate_failed: RuntimeError" and "hunter2" not in str(p.gate) and "10.0.0.5" not in str(p.gate)
    assert p.comparison.status is DataStatus.OK and p.comparison.data is not None, "the rest of the page is there"
    assert p.freshness.topics and p.per_day and p.claims.total == 70


def test_a_statement_that_fails_does_not_leave_the_rest_of_the_page_in_an_aborted_transaction(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    db = world.db
    real = gate_research.coverage
    calls = {"n": 0}

    def once(conn: psycopg.Connection[Any], first: date, last: date) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            conn.execute("SELECT 1 / 0")  # the database refuses: the transaction is aborted unless the part was inside a savepoint
        return real(conn, first, last)

    monkeypatch.setattr(gate_research, "coverage", once)
    p = page(db)
    assert (p.comparison.status, p.comparison.code, p.comparison.reason) == (DataStatus.NOT_AVAILABLE, "comparison_failed", "comparison_failed: DivisionByZero")
    assert p.gate.status is DataStatus.OK and p.gate.data is not None and p.gate.data.verdict == gate_research.PASS, "the gate ran after the failure"
    assert db.execute("SELECT 1").fetchone() == (1,), "and the connection is usable"
