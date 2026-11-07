"""The Evidence Engine in shadow (``evidence-engine-v1``, IA-012) on the real schema.

THE WORLD: a competition, a season, two teams and two matches of their own - not the seed's match, which the session's tests share. The seed
gives only the ingestion payload the provider's line-ups and injury reports point at. The match being read kicks off at ``KO``; the moment of
the reading is ``AT`` (three hours before). A past match of the same home side, a week earlier, is the history a local outlet's credibility is
learned from.

What is stored about the match:

* E1 marca.com and E2 as.com (v1, web): player 501 of the home side is OUT. E7 the provider's injury report says the same (v1, provider).
* E3 antena2.com (research v2, typed): player 501 is AVAILABLE - the opposite. The server later (at ``AT - 1h``) set E1 and E3 CONTRADICTORY.
* E4 caracol.com.co (v1, web): player 502 is OUT - and the provider's line-up, fetched at ``AT - 1h``, has him in the eleven.
* E5 marca.com (v1, web): retrieved AFTER the moment of the reading - it must not be seen.
* E6 x.com (research v2, a claim of the away side that belongs to no match): player 601 is OUT.
* E8 marca.com (v1, web): player 503 OUT, twelve days old - expired.
* E9 marca.com (research v2, typed): player 504 STARTS - the provider lists him missing, and the line-up does not have him in the eleven.

The transaction is rolled back afterwards; nothing here is committed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_evidence

from fbi.ai.calendar import day_bounds
from fbi.evidence import engine
from fbi.evidence import rules as r

from .conftest import Seed

KO = datetime(2026, 10, 20, 19, tzinfo=UTC)
AT = KO - timedelta(hours=3)
PAST_KO = KO - timedelta(days=7)
H = timedelta(hours=1)


def put(db: psycopg.Connection[Any], table: str, values: dict[str, Any], *, returning: bool = True) -> int | None:
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    cur = db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})" + (" RETURNING id" if returning else ""), list(values.values()))
    if not returning:
        return None
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def put_id(db: psycopg.Connection[Any], table: str, values: dict[str, Any]) -> int:
    out = put(db, table, values)
    assert out is not None
    return out


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        competition = put_id(db, "core.competitions", {"provider_league_id": 996001, "name": "Evidence League", "type": "league",
                                                       "entity_scope": "club", "competition_type": "domestic_league"})
        season = put_id(db, "core.competition_seasons", {"competition_id": competition, "season": 2026})
        self.home = put_id(db, "core.teams", {"provider_team_id": 996001, "name": "Evidence Home"})
        self.away = put_id(db, "core.teams", {"provider_team_id": 996002, "name": "Evidence Away"})
        self.fixture = put_id(db, "core.fixtures", {"provider_fixture_id": 9960001, "competition_season_id": season, "home_team_id": self.home,
                                                    "away_team_id": self.away, "kickoff_at": KO})
        self.past = put_id(db, "core.fixtures", {"provider_fixture_id": 9960002, "competition_season_id": season, "home_team_id": self.home,
                                                 "away_team_id": self.away, "kickoff_at": PAST_KO, "status_short": "FT",
                                                 "status_group": "finished"})
        self.n = 0

    def evidence(self, *, fixture: int | None, team: int, player: int | None, kind: str, assertion: str, domain: str | None,
                 retrieved: datetime, published: datetime | None = None, origin: str = "web", tier: str = "media",
                 typed: str | None = None, status: str = "PROBABLE") -> int:
        self.n += 1
        values: dict[str, Any] = {
            "fixture_id": fixture, "team_id": team, "provider_player_id": player, "kind": kind,
            "claim": f"Item {self.n} of the evidence world about player {player}", "origin": origin,
            "source_name": domain or "API-Football /injuries", "source_url": None if domain is None else f"https://{domain}/n/{self.n}",
            "source_domain": domain, "source_tier": tier, "published_at": published, "retrieved_at": retrieved,
            "story_key": f"ev-world:{self.n}", "content_hash": hashlib.sha256(str(self.n).encode()).hexdigest(), "confidence": Decimal("0.5"),
            "relevance": Decimal("0.6"), "attributes": Jsonb({"assertion": assertion}), "status": status, "status_reason": "world",
            "status_changed_at": retrieved}
        if typed is not None:
            values |= {"claim_type": typed, "subject_type": "PLAYER", "subject_id": player, "source_class": "LOCAL_MEDIA"}
        return put_id(self.db, "ai.evidence", values)

    def lineup(self, fixture: int, side: str, *, fetched: datetime, starters: list[int], bench: list[int] = ()) -> None:  # type: ignore[assignment]
        put(self.db, "core.fixture_lineups", {"fixture_id": fixture, "team_side": side, "source": "api-football", "formation": "4-4-2",
                                              "payload_hash": self.seed.payload_hash, "fetched_at": fetched}, returning=False)
        for pid in starters:
            self._player(fixture, side, pid, True)
        for pid in bench:
            self._player(fixture, side, pid, False)

    def _player(self, fixture: int, side: str, pid: int, starter: bool) -> None:
        put(self.db, "core.fixture_lineup_players", {"fixture_id": fixture, "team_side": side, "source": "api-football",
                                                     "provider_player_id": pid, "is_starter": starter}, returning=False)

    def listed(self, fixture: int, pid: int, *, observed: datetime) -> None:
        put(self.db, "core.player_availability_obs", {
            "fixture_id": fixture, "source": "api-football", "provider_player_id": pid, "observed_at": observed, "status": "LISTED",
            "provider_fixture_id": 9960001, "provider_team_id": 996001, "player_name": "P", "absence_type": "Missing Fixture", "reason": "Injury",
            "payload_hash": self.seed.payload_hash, "origin": "answer", "normalizer_version": "t"}, returning=False)


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, Any]:
    w = World(db, seed)
    f, home, away = w.fixture, w.home, w.away
    ids = {
        "e1": w.evidence(fixture=f, team=home, player=501, kind="injury", assertion="out", domain="marca.com", retrieved=AT - 4 * H,
                         published=AT - 5 * H),
        "e2": w.evidence(fixture=f, team=home, player=501, kind="injury", assertion="out", domain="as.com", retrieved=AT - 4 * H),
        "e3": w.evidence(fixture=f, team=home, player=501, kind="injury", assertion="available", domain="antena2.com", retrieved=AT - 2 * H,
                         typed="AVAILABLE"),
        "e4": w.evidence(fixture=f, team=home, player=502, kind="injury", assertion="out", domain="caracol.com.co", retrieved=AT - 3 * H),
        "e5": w.evidence(fixture=f, team=home, player=505, kind="injury", assertion="out", domain="marca.com", retrieved=AT + H),
        "e6": w.evidence(fixture=None, team=away, player=601, kind="injury", assertion="out", domain="x.com", retrieved=AT - 24 * H,
                         tier="social", typed="OUT"),
        "e7": w.evidence(fixture=f, team=home, player=501, kind="injury", assertion="out", domain=None, origin="provider", tier="provider",
                         retrieved=AT - 6 * H),
        "e8": w.evidence(fixture=f, team=home, player=503, kind="injury", assertion="out", domain="marca.com", retrieved=AT - timedelta(days=12)),
        "e9": w.evidence(fixture=f, team=home, player=504, kind="lineup", assertion="starts", domain="marca.com", retrieved=AT - 2 * H,
                         typed="STARTER"),
        # the history of caracol.com.co: a week ago it said 701 was out, and the line-up of that match did not have him
        "h1": w.evidence(fixture=w.past, team=home, player=701, kind="injury", assertion="out", domain="caracol.com.co",
                         retrieved=PAST_KO - 24 * H),
    }
    w.lineup(w.past, "home", fetched=PAST_KO - H, starters=[1, 2, 3, 502])
    w.lineup(f, "home", fetched=AT - H, starters=[1, 2, 502], bench=[504])
    w.listed(f, 504, observed=AT - 5 * H)
    db.execute("UPDATE ai.evidence SET status = 'CONTRADICTORY', status_reason = 'contradicted', status_changed_at = %s WHERE id = ANY(%s)",
               (AT - H, [ids["e1"], ids["e3"]]))
    return {"w": w, **ids}


def claim(report: engine.Report, key: str) -> engine.Claim:
    return next(c for c in report.claims if c.key == key)


def test_the_claims_of_a_match_with_their_status_confidence_and_validity(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    rep = engine.evidence_for(db, w.fixture, at=AT)
    assert rep is not None
    out501 = claim(rep, f"player:{w.home}:501|injury|out")
    assert {i.evidence_id for i in out501.items} == {world["e1"], world["e2"], world["e7"]}
    assert out501.decided.status == "CONFIRMADO" and not out501.decided.expired
    assert {i.outlet: i.tier for i in out501.items} == {"marca.com": "B", "as.com": "B", "provider": "B"}
    assert 0 < out501.decided.confidence <= r.STATUS_CAP["CONFIRMADO"]
    expired = claim(rep, f"player:{w.home}:503|injury|out")
    assert expired.decided.expired and expired.decided.confidence == 0.0
    rumour = claim(rep, f"player:{w.away}:601|injury|out")
    assert rumour.decided.status == "RUMOR" and rumour.side == "away" and rumour.items[0].generation == "v2", "a team's claim of no match"
    assert rep.counts()["generations"] == {"v1_evidences": 5, "v2_claims": 3}


def test_nothing_recorded_after_the_moment_is_read(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    now = engine.evidence_for(db, w.fixture, at=AT)
    before = engine.evidence_for(db, w.fixture, at=AT - 90 * timedelta(minutes=1))
    assert now is not None and before is not None
    seen = {i.evidence_id for i in now.items}
    assert world["e5"] not in seen, "retrieved after the moment"
    assert world["e1"] in seen and world["e3"] in seen
    rules_now = {c.rule for c in now.contradictions}
    rules_before = {c.rule for c in before.contradictions}
    assert {"CC1", "CP1", "CP2", "CP3", "C07"} <= rules_now
    assert "CP1" not in rules_before and "CP2" not in rules_before, "the line-up was fetched after the earlier moment"
    assert "C07" not in rules_before, "the server decided the contradiction after the earlier moment"
    assert "CP3" in rules_before, "the injury report was already known"
    stored = {i.evidence_id: i.stored_status for i in before.items}
    assert stored[world["e1"]] == "PROBABLE", "the status as it stood then, from the history"


def test_the_contradictions(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    rep = engine.evidence_for(db, w.fixture, at=AT)
    assert rep is not None
    by_rule = {c.rule: c for c in rep.contradictions}
    assert set(by_rule["CC1"].evidence_ids) == {world["e1"], world["e2"], world["e3"], world["e7"]}
    assert by_rule["CP1"].subject == f"player:{w.home}:502"
    assert by_rule["C07"].subject == "player:501" and set(by_rule["C07"].evidence_ids) == {world["e1"], world["e3"]}
    out502 = claim(rep, f"player:{w.home}:502|injury|out")
    assert out502.confidence_net == 0.0 and "CP1" in out502.contradictions
    starts504 = claim(rep, f"player:{w.home}:504|lineup|starts")
    assert set(starts504.contradictions) == {"CP2", "CP3"} and starts504.confidence_net == 0.0
    available = claim(rep, f"player:{w.home}:501|injury|available")
    assert available.confidence_net < available.decided.confidence


def test_a_source_s_credibility_is_learned_from_its_history(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    rep = engine.evidence_for(db, w.fixture, at=AT)
    assert rep is not None
    caracol = claim(rep, f"player:{w.home}:502|injury|out").credibility[("caracol.com.co", "C")]
    assert caracol.basis == "learned" and (caracol.corroborated, caracol.resolved) == (1, 1)
    assert caracol.value == pytest.approx((r.PRIOR_WEIGHT * r.TIER_PRIOR["C"] + 1) / (r.PRIOR_WEIGHT + 1), abs=1e-4)
    marca = claim(rep, f"player:{w.home}:501|injury|out").credibility[("marca.com", "B")]
    assert marca.basis == "prior", "marca.com has no resolved claim about another match"
    early = engine.evidence_for(db, w.fixture, at=PAST_KO - 2 * H)
    assert early is not None and {i.evidence_id for i in early.items} == {world["e8"]}, "only what was retrieved by then"


def test_the_day_and_the_command(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    day = date(2026, 10, 20)
    start, end = day_bounds(day)
    assert start <= KO < end, "the kick-off is on that day in Bogotá"
    summary = engine.day_summary(db, day, at=AT)
    mine = next(m for m in summary["matches"] if m["fixture_id"] == w.fixture)
    assert mine["generations"] == {"v1_evidences": 5, "v2_claims": 3}
    assert mine["expired"] == 1 and mine["contradictions"]["CP1"] == 1
    assert summary["shadow"] is True and summary["counts"]["generations"]["v1_evidences"] >= 5
    doc, code = ia_evidence.show(db, w.fixture, at=AT)
    assert code == ia_evidence.OK and doc["fixture_id"] == w.fixture and doc["not_derived"]
    text = ia_evidence.render_show(doc)
    assert "CONFIRMADO" in text and "EXPIRED" in text and "CP1" in text
    assert "matches" in ia_evidence.render_day(summary)
    missing, code = ia_evidence.show(db, 987654321, at=AT)
    assert code == ia_evidence.CANNOT and "unknown" in missing["error"]


def test_reading_writes_nothing(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    w = world["w"]
    snapshot = "SELECT id, status, status_reason, status_changed_at, last_seen_at, seen_count FROM ai.evidence ORDER BY id"
    before = db.execute(snapshot).fetchall()
    engine.evidence_for(db, w.fixture, at=AT)
    engine.day_summary(db, date(2026, 10, 20), at=AT)
    assert db.execute(snapshot).fetchall() == before
