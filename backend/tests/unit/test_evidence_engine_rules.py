"""``evidence-engine-v1`` (IA-012): the rules, pure - the tiers, the status ladder, the confidence (never lowered by more corroboration), the
validity per topic, the contradictions, the learned credibility and the strict as-of reading of a stored status."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.ai.evidence import STALE_AFTER
from fbi.evidence import engine
from fbi.evidence import rules as r

AT = datetime(2026, 11, 6, 18, tzinfo=UTC)
H = timedelta(hours=1)
D = timedelta(days=1)


def tiered(**kw: Any) -> r.Tiered:
    args: dict[str, Any] = {"origin": "web", "kind": "injury", "domain": None, "registry_tier": None, "source_class": None, "flagged": False,
                            "dated": True}
    return r.tier_of(**(args | kw))


# ── tiers ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_tiers_follow_the_rules_in_order() -> None:
    assert tiered(origin="provider", kind="lineup").tier == "A"
    assert tiered(origin="provider", kind="injury").tier == "B"
    assert tiered(origin="owner").tier == "B"
    assert tiered(domain="premierleague.com").tier == "A"
    assert tiered(domain="fcf.com.co").tier == "A"
    assert tiered(domain="marca.com").tier == "B" and tiered(domain="amp.marca.com").tier == "B", "a host takes its listed suffix's tier"
    assert tiered(domain="fabrizioromano.com").tier == "B"
    assert tiered(domain="antena2.com").tier == "C"
    assert tiered(domain="transfermarkt.com").tier == "D" and tiered(domain="x.com").tier == "D"
    assert tiered(domain="never-heard-of.example").tier == "D"
    assert tiered(domain=None).tier == "D"


def test_a_page_that_reads_like_an_order_is_d_whatever_its_domain() -> None:
    assert tiered(domain="premierleague.com", flagged=True).tier == "D"
    assert tiered(origin="provider", kind="lineup", flagged=True).tier == "D"


def test_an_official_page_without_a_date_counts_as_b() -> None:
    t = tiered(domain="laliga.com", dated=False)
    assert t.tier == "B" and "without a publication date" in t.reason


def test_the_registry_tiers_a_domain_the_lists_do_not_have() -> None:
    assert tiered(domain="club-nuevo.example", registry_tier="club").tier == "A"
    assert tiered(domain="periodico.example", registry_tier="media").tier == "C"
    assert tiered(domain="periodico.example", registry_tier="media", source_class="RELIABLE_MEDIA").tier == "B"
    assert tiered(domain="tips.example", registry_tier="aggregator").tier == "D"
    assert tiered(domain="nadie.example", registry_tier="unknown").tier == "D"


def test_the_domain_lists_are_versioned_by_their_digest() -> None:
    assert r.domains_digest() == r.DOMAINS_DIGEST, "a domain list changed: bump tiers-v1 and DOMAINS_DIGEST together"
    assert set(r.DOMAIN_TIERS.values()) == set(r.TIERS)


def test_the_rules_digest_is_stable_and_twelve_hex() -> None:
    assert r.rules_digest() == r.rules_digest() and len(r.rules_digest()) == 12


# ── the ladder ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("outlets", "status"), [
    ({}, "RUMOR"),
    ({f"agg{i}": "D" for i in range(6)}, "RUMOR"),
    ({"local": "C"}, "REPORTADO"),
    ({"marca.com": "B"}, "REPORTADO"),
    ({"local1": "C", "local2": "C"}, "REPORTADO"),
    ({"marca.com": "B", "local": "C"}, "CONFIRMADO"),
    ({"marca.com": "B", "as.com": "B"}, "CONFIRMADO"),
    ({"l1": "C", "l2": "C", "l3": "C"}, "CONFIRMADO"),
    ({"laliga.com": "A"}, "OFICIAL"),
    ({"marca.com": "B", "agg": "D"}, "REPORTADO"),
])
def test_the_status_ladder(outlets: dict[str, str], status: str) -> None:
    assert r.status_of(outlets)[0] == status


def sup(i: int, outlet: str, tier: r.Tier, cred: float | None = None, age: timedelta = H) -> r.Support:
    return r.Support(i, outlet, tier, r.TIER_PRIOR[tier] if cred is None else cred, AT - age)


def test_one_outlet_counts_once_however_many_pages() -> None:
    one = r.decide("injury", [sup(1, "marca.com", "B"), sup(2, "marca.com", "B"), sup(3, "marca.com", "B")], at=AT)
    assert one.status == "REPORTADO"
    assert one.support == r.TIER_PRIOR["B"]


def test_aggregators_count_once_in_the_support() -> None:
    many = r.decide("injury", [sup(i, f"agg{i}", "D") for i in range(5)], at=AT)
    single = r.decide("injury", [sup(0, "agg0", "D")], at=AT)
    assert many.support == single.support and many.status == "RUMOR"
    assert many.confidence <= r.STATUS_CAP["RUMOR"]


def test_the_confidence_formula() -> None:
    d = r.decide("injury", [sup(1, "marca.com", "B", 0.8, age=timedelta(0)), sup(2, "local", "C", 0.6, age=timedelta(0))], at=AT)
    assert d.status == "CONFIRMADO" and d.freshness == 1.0
    assert d.support == pytest.approx(1 - 0.2 * 0.4)
    assert d.confidence == pytest.approx(min(0.9, 0.92))


def test_more_corroboration_never_lowers_the_confidence_nor_the_status() -> None:
    rng = random.Random(20261106)
    tiers: list[r.Tier] = ["A", "B", "C", "D"]
    topics = list(r.TOPICS)
    for _ in range(20000):
        topic = rng.choice(topics)
        window = r.VALIDITY[topic]
        base = [r.Support(i, f"o{rng.randrange(6)}", rng.choice(tiers), round(rng.random(), 3), AT - window * rng.random() * 1.3)
                for i in range(rng.randrange(1, 6))]
        extra = r.Support(99, f"o{rng.randrange(9)}", rng.choice(tiers), round(rng.random(), 3), AT - window * rng.random() * 1.3)
        before, after = r.decide(topic, base, at=AT), r.decide(topic, [*base, extra], at=AT)
        if before.expired and after.expired:
            continue
        assert after.confidence >= before.confidence, (topic, base, extra)
        assert r.STATUSES.index(after.status) >= r.STATUSES.index(before.status) or before.expired, (topic, base, extra)


def test_a_rumour_never_exceeds_its_cap_whatever_the_record_of_its_source() -> None:
    d = r.decide("injury", [sup(1, "agg", "D", 0.99, age=timedelta(0))], at=AT)
    assert d.status == "RUMOR" and d.confidence == r.STATUS_CAP["RUMOR"]


# ── validity ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_injury_window_is_the_packets_stale_after() -> None:
    assert r.VALIDITY["injury"] == STALE_AFTER
    assert set(r.VALIDITY) == set(r.TOPICS)


def test_freshness_halves_every_half_window_and_is_zero_once_expired() -> None:
    w = r.VALIDITY["injury"]
    assert r.freshness("injury", AT, AT) == 1.0
    assert r.freshness("injury", AT - w / 2, AT) == 0.5
    assert r.freshness("injury", AT - w, AT) == 0.25
    assert not r.expired("injury", AT - w, AT)
    assert r.expired("injury", AT - w - timedelta(seconds=1), AT) and r.freshness("injury", AT - w - timedelta(seconds=1), AT) == 0.0


def test_an_expired_claim_is_reported_as_expired_with_no_confidence() -> None:
    old = r.decide("lineup", [sup(1, "laliga.com", "A", age=timedelta(days=3))], at=AT)
    assert old.expired and old.confidence == 0.0 and old.status == "OFICIAL" and old.live_ids == ()
    mixed = r.decide("lineup", [sup(1, "laliga.com", "A", age=timedelta(days=3)), sup(2, "local", "C")], at=AT)
    assert not mixed.expired and mixed.status == "REPORTADO" and mixed.live_ids == (2,), "only live items count"


def test_the_topics() -> None:
    assert r.topic_of("injury") == "injury" and r.topic_of("doubtful") == "injury"
    assert r.topic_of("suspension") == "suspension" and r.topic_of("lineup") == "lineup" and r.topic_of("coach") == "coach_change"
    assert r.topic_of("news", "El técnico habló en rueda de prensa") == "press_conference"
    assert r.topic_of("injury", "dijo en rueda de prensa que no juega") == "injury", "who plays stays who plays"
    assert r.topic_of("weather", "lluvia") == "other"


# ── credibility ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_credibility_is_the_prior_without_history_and_learned_with_it() -> None:
    assert r.credibility("C", 0, 0) == r.Credibility(0.6, "prior", 0.6)
    learned = r.credibility("C", 9, 10)
    assert learned.basis == "learned" and learned.value == pytest.approx((10 * 0.6 + 9) / 20)
    assert r.credibility("D", 0, 30).value == pytest.approx(3 / 40)


def sheet(starters: set[int], bench: set[int] = frozenset()) -> r.SquadSheet:  # type: ignore[assignment]
    return r.SquadSheet(11, AT, frozenset(starters), frozenset(bench))


def test_a_past_claim_is_resolved_by_the_line_up_then_the_report_then_a_higher_tier() -> None:
    assert r.resolve("out", sheet=sheet({1, 2}), listing=None, player_id=9) == "corroborated"
    assert r.resolve("out", sheet=sheet({1, 2}, {9}), listing=None, player_id=9) == "refuted"
    assert r.resolve("starts", sheet=sheet({9}), listing=None, player_id=9) == "corroborated"
    assert r.resolve("starts", sheet=sheet({1}, {9}), listing=None, player_id=9) == "refuted"
    missing = r.Listing("LISTED", True, AT)
    assert r.resolve("out", sheet=None, listing=missing, player_id=9) == "corroborated"
    assert r.resolve("available", sheet=None, listing=missing, player_id=9) == "refuted"
    assert r.resolve("out", sheet=None, listing=r.Listing("LISTED", False, AT), player_id=9) is None, "a doubt is not an absence"
    assert r.resolve("out", sheet=None, listing=None, player_id=9, higher=["out"]) == "corroborated"
    assert r.resolve("out", sheet=None, listing=None, player_id=9, higher=["available"]) == "refuted"
    assert r.resolve("out", sheet=None, listing=None, player_id=9) is None


# ── contradictions ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_incompatible_assertions() -> None:
    assert r.incompatible("out", "available") and r.incompatible("starts", "out")
    assert not r.incompatible("doubtful", "starts") and not r.incompatible("out", "out")


def test_claim_vs_provider() -> None:
    assert r.against_provider("out", 9, sheet=sheet({9}), listing=None) == ["CP1"]
    assert r.against_provider("out", 9, sheet=sheet({1}, {9}), listing=None) == ["CP1"], "the bench is in the line-up"
    assert r.against_provider("starts", 9, sheet=sheet({1}, {9}), listing=None) == ["CP2"]
    assert r.against_provider("available", 9, sheet=None, listing=r.Listing("LISTED", True, AT)) == ["CP3"]
    assert r.against_provider("out", None, sheet=sheet({9}), listing=None) == [], "a player the provider does not identify"
    assert r.against_provider("out", 9, sheet=sheet({1}), listing=None) == []


def test_the_net_confidence() -> None:
    assert r.net(0.8, provider=["CP1"]) == 0.0
    assert r.net(0.8, opposing=[0.5]) == pytest.approx(0.4)
    assert r.net(0.8, provider=["CP3"]) == pytest.approx(0.8 * 0.2)
    assert r.net(0.8) == 0.8


def item(i: int, assertion: str, outlet: str, tier: r.Tier, *, player: int | None = 9, team: int = 11, kind: str = "injury",
         age: timedelta = H, generation: str = "v1", stored: str | None = None, fixture: int | None = 70) -> engine.Item:
    return engine.Item(i, generation, fixture, team, player, "", kind, r.topic_of(kind), assertion, "web", outlet, outlet, tier, "t", AT - age,
                       AT - age, stored)


def creds(items: list[engine.Item]) -> dict[tuple[str, str], r.Credibility]:
    return {(i.outlet, i.tier): r.credibility(i.tier, 0, 0) for i in items}


def test_claims_are_grouped_and_contradict_each_other_and_the_provider() -> None:
    items = [item(1, "out", "marca.com", "B"), item(2, "out", "as.com", "B"), item(3, "available", "local.example", "C"),
             item(4, "out", "x.com", "D", player=10)]
    claims, found = engine.build_claims(items, creds(items), at=AT, fixture_id=70, home=11, away=12,
                                        sheets={(70, 11): sheet({10, 1})}, listings={})
    by_key = {c.key: c for c in claims}
    out9 = by_key["player:11:9|injury|out"]
    assert out9.decided.status == "CONFIRMADO" and [i.evidence_id for i in out9.items] == [1, 2]
    assert {c.rule for c in found} == {"CC1", "CP1"}
    cc = next(c for c in found if c.rule == "CC1")
    assert cc.claims == ("player:11:9|injury|available", "player:11:9|injury|out") and cc.evidence_ids == (1, 2, 3)
    avail = by_key["player:11:9|injury|available"]
    assert avail.confidence_net == pytest.approx(avail.decided.confidence * (1 - out9.decided.confidence), abs=1e-4)
    out10 = by_key["player:11:10|injury|out"]
    assert out10.contradictions == ("CP1",) and out10.confidence_net == 0.0
    assert out9.side == "home"


def test_an_expired_claim_contradicts_nothing() -> None:
    items = [item(1, "out", "marca.com", "B", age=timedelta(days=12)), item(2, "available", "local.example", "C")]
    claims, found = engine.build_claims(items, creds(items), at=AT, fixture_id=70, home=11, away=12, sheets={}, listings={})
    assert found == () and any(c.decided.expired for c in claims)


def test_contra_v1_c07_is_reused_on_the_stored_statuses() -> None:
    items = [item(1, "out", "marca.com", "B", stored="CONTRADICTORY"), item(2, "available", "as.com", "B", stored="CONTRADICTORY"),
             item(3, "out", "x.com", "D", player=10, stored="RUMOR")]
    found = engine.contra_v1(items, fixture_id=70, home=11, away=12, kickoff=AT + D, at=AT)
    assert [(c.rule, c.subject, c.evidence_ids) for c in found] == [("C07", "player:9", (1, 2))]
    assert engine.contra_v1(items[2:], fixture_id=70, home=11, away=12, kickoff=AT + D, at=AT) == ()


def test_the_counts_say_v1_and_v2_apart() -> None:
    items = [item(1, "out", "marca.com", "B"), item(2, "out", "as.com", "B", generation="v2")]
    claims, found = engine.build_claims(items, creds(items), at=AT, fixture_id=70, home=11, away=12, sheets={}, listings={})
    rep = engine.Report(70, AT, AT + D, (11, "H"), (12, "A"), claims, found, tuple(items))
    c = rep.counts()
    assert c["generations"] == {"v1_evidences": 1, "v2_claims": 1}
    assert c["by_tier"]["B"] == 2 and c["by_status"]["CONFIRMADO"] == 1 and c["by_topic"]["injury"] == 1 and c["expired"] == 0
    doc = rep.as_json()
    assert doc["shadow"] is True and doc["claims"][0]["sources"][0]["credibility"]["basis"] == "prior"


# ── learned credibility, as of ──────────────────────────────────────────────────────────────────────────────────────

def test_credibility_is_learned_from_other_matches_only() -> None:
    past = [item(1, "out", "local.example", "C", fixture=50, age=D * 5), item(2, "out", "local.example", "C", fixture=51, age=D * 4, player=8),
            item(3, "out", "local.example", "C", fixture=70, age=H)]
    sheets = {(50, 11): sheet({1, 2}), (51, 11): sheet({8}), (70, 11): sheet({1})}
    got = engine.learn_credibility(past, past, wanted=[("local.example", "C")], exclude_fixture=70, team_fixtures={}, sheets=sheets,
                                   listings={})
    cred = got[("local.example", "C")]
    assert (cred.corroborated, cred.resolved) == (1, 2), "the claim about the match being read does not vouch for its source"
    assert cred.value == pytest.approx((10 * 0.6 + 1) / 12, abs=1e-4)


def test_a_higher_tier_claim_corroborates_and_an_equal_one_does_not() -> None:
    claim = item(1, "out", "local.example", "C", fixture=50, age=D * 5)
    official = item(2, "out", "club.example", "A", fixture=50, age=D * 5)
    peer = item(3, "out", "other.example", "C", fixture=50, age=D * 5)
    wanted = [("local.example", "C")]
    assert engine.learn_credibility([claim], [claim, official], wanted=wanted, exclude_fixture=70, team_fixtures={}, sheets={},
                                    listings={})[wanted[0]].resolved == 1
    assert engine.learn_credibility([claim], [claim, peer], wanted=wanted, exclude_fixture=70, team_fixtures={}, sheets={},
                                    listings={})[wanted[0]].basis == "prior"


def test_a_claim_of_no_match_is_judged_by_the_team_s_next_match() -> None:
    claim = item(1, "out", "local.example", "C", fixture=None, age=D * 5)
    team_fixtures = {11: [(AT - D * 3, 60), (AT - D * 20, 40)]}
    got = engine.learn_credibility([claim], [claim], wanted=[("local.example", "C")], exclude_fixture=70, team_fixtures=team_fixtures,
                                   sheets={(60, 11): sheet({9})}, listings={})
    assert got[("local.example", "C")].resolved == 1 and got[("local.example", "C")].corroborated == 0


# ── the stored status, as of ────────────────────────────────────────────────────────────────────────────────────────

def test_the_stored_status_is_read_as_it_stood_at_the_moment() -> None:
    t0, t1 = AT - D, AT
    history = [{"status": "PROBABLE", "reason": "one media", "from": t0.isoformat(), "until": t1.isoformat()}]
    assert engine.status_as_of("CONTRADICTORY", t1, history, AT + H) == "CONTRADICTORY"
    assert engine.status_as_of("CONTRADICTORY", t1, history, AT - H) == "PROBABLE"
    assert engine.status_as_of("CONTRADICTORY", t1, history, t0 - H) is None, "not yet decided"
    assert engine.status_as_of("CONTRADICTORY", t1, "garbage", AT - H) is None
