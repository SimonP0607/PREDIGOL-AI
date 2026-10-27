"""Research v2 (plan, phase 2) - the rules that decide the status of a CLAIM, held on the pure function (``fbi.ai.evidence.classify``).

They come from the independent review of the Phase 2 code (27 Oct 2026), and each is a way in which a claim of research v2 could be given a
status it had not earned once research v2 is ``on``:

* a claim about a player that belongs to no match («he is out») and a claim about the same player for this match («he is available») are about
  the same person: they meet, whatever scope the model gave them (C07), and the provider's own report is part of that comparison;
* a claim that a confirmed line-up of the team has since disproved (he started) stays disproved for the next match, whatever line-up that match
  has or lacks;
* a story is as strong as the reports of it that still stand: a report too old to count does not corroborate a current one, and two addresses of
  the same outlet are one outlet.

What v1 wrote keeps the rule it always had: every test below that says so builds untyped rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.ai.evidence import Lineup, Row, classify

AT = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=20)
PLAYER = 99
TEAM = 10


def row(i: int, *, domain: str | None = None, tier: str = "media", assertion: str = "out", kind: str = "injury", fixture: int | None = None,
        hours_ago: float = 5, retrieved_hours_ago: float | None = None, story: str | None = None, outlet: str | None = None,
        typed: bool = True, origin: str = "web", player: int = PLAYER, team: int = TEAM, attributes: dict[str, Any] | None = None) -> Row:
    when = AT - timedelta(hours=hours_ago)
    retrieved = AT - timedelta(hours=hours_ago if retrieved_hours_ago is None else retrieved_hours_ago)
    scope = "e" if fixture is None else f"f{fixture}"
    return Row(i, fixture, team, player, "jugador", kind, origin, tier, domain or f"site{i}.com", assertion, when, retrieved,
               story or f"w2:{scope}:PLAYER:{player}:{assertion}:{i}", "PROBABLE", attributes or {}, typed=typed, outlet=outlet)


def decide(rows: list[Row], *, across: bool = True, lineups: list[Lineup] | None = None, starters: dict[int, set[int]] | None = None) -> dict[int, str]:
    out = classify(rows, kickoff=KO, at=AT, lineup_starters=starters or {}, absences_checked_at=None, across_scopes=across, lineups=lineups or [])
    return {i: s for i, (s, _) in out.items()}


# ── the same person, whatever scope the model gave the claim ───────────────────────────────────────────────────────────────

def test_a_claim_without_a_match_and_a_claim_for_this_match_about_the_same_player_contradict_each_other() -> None:
    """The review's snippet: two outlets say «out» (no match), two say «available» (this match). Decided by scope they are four CONFIRMED claims
    that say opposite things about one man; the model's ``applies_to`` would decide whether C07 applies. Decided by person they contradict."""
    story_out, story_back = "w2:e:PLAYER:99:OUT", "w2:f1:PLAYER:99:AVAILABLE"
    rows = [row(1, domain="marca.com", story=story_out), row(2, domain="as.com", story=story_out),
            row(3, domain="elpais.com", assertion="available", fixture=1, story=story_back),
            row(4, domain="sport.es", assertion="available", fixture=1, story=story_back)]
    assert set(decide(rows, across=False).values()) == {"CONFIRMED"}, "decided by scope: the hole the review found"
    assert set(decide(rows).values()) == {"CONTRADICTORY"}


def test_a_newer_report_settles_an_older_claim_of_the_other_scope() -> None:
    old_out = row(1, domain="eltiempo.com", hours_ago=30)
    new_back = row(2, domain="elpais.com", assertion="available", fixture=1, hours_ago=3, tier="club", story="w2:f1:PLAYER:99:AVAILABLE")
    out = decide([old_out, new_back])
    assert out[1] == "OUTDATED" and out[2] == "CONFIRMED"


def test_the_providers_newer_report_outdates_an_older_claim_of_the_web_as_it_does_in_v1() -> None:
    """A typed claim decided apart from the provider's report would stay PROBABLE beside a newer report that says the opposite."""
    web = row(1, domain="eltiempo.com", assertion="available", hours_ago=30)
    provider = row(2, tier="provider", origin="provider", domain="api-football.com", fixture=1, hours_ago=2, typed=False, story="provider:1:99")
    out = decide([web, provider])
    assert out[1] == "OUTDATED" and out[2] == "PROBABLE"


def test_two_players_do_not_meet() -> None:
    out = decide([row(1, player=1, domain="marca.com"), row(2, player=2, assertion="available", domain="as.com", fixture=1)])
    assert out == {1: "PROBABLE", 2: "PROBABLE"}


def test_what_v1_wrote_is_still_grouped_by_match() -> None:
    """The default is the rule v1 always had: the same player of two different matches are two subjects."""
    one = row(1, fixture=1, typed=False, domain="marca.com", story="web:1:out")
    other = row(2, fixture=2, typed=False, assertion="available", domain="as.com", story="web:2:available")
    assert decide([one, other], across=False) == {1: "PROBABLE", 2: "PROBABLE"}


# ── a line-up that disproved a claim keeps disproving it ───────────────────────────────────────────────────────────────────

def lineup(*, team: int = TEAM, starters: tuple[int, ...] = (PLAYER, 1, 2), hours_ago: float = 24) -> Lineup:
    return Lineup(team, frozenset(starters), AT - timedelta(hours=hours_ago))


def test_a_player_who_started_after_the_claim_was_read_is_not_absent_for_the_next_match_either() -> None:
    claim = row(1, retrieved_hours_ago=30, hours_ago=31)
    assert decide([claim])[1] == "PROBABLE", "without the line-up of the other match: the claim stands (this is how it came back)"
    out = classify([claim], kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None, across_scopes=True, lineups=[lineup()])
    assert out[1] == ("OUTDATED", "the player started in a later confirmed line-up of the team")


def test_a_claim_read_after_that_line_up_is_a_new_fact_and_stands() -> None:
    claim = row(1, retrieved_hours_ago=5, hours_ago=6)  # the line-up is from 24 hours ago: he may have been hurt in that match
    assert decide([claim], lineups=[lineup()])[1] == "PROBABLE"


def test_only_a_line_up_of_the_same_team_with_the_player_in_the_eleven_disproves_it() -> None:
    claim = row(1, retrieved_hours_ago=30, hours_ago=31)
    assert decide([claim], lineups=[lineup(team=11)])[1] == "PROBABLE", "another team's eleven"
    assert decide([claim], lineups=[lineup(starters=(1, 2, 3))])[1] == "PROBABLE", "he was not in it"


def test_a_good_news_claim_is_not_disproved_by_a_start() -> None:
    back = row(1, assertion="available", retrieved_hours_ago=30, hours_ago=31)
    assert decide([back], lineups=[lineup()])[1] == "PROBABLE"


def test_a_claim_for_this_match_is_not_decided_by_the_line_up_of_another_one() -> None:
    """«He is out for this match», read before the previous match was played, may be true even if he started that one (he got hurt in it)."""
    claim = row(1, fixture=1, retrieved_hours_ago=30, hours_ago=31)
    assert decide([claim], lineups=[lineup()])[1] == "PROBABLE"


def test_the_eleven_of_this_match_still_decides_as_before() -> None:
    claim = row(1, retrieved_hours_ago=2, hours_ago=3)
    out = classify([claim], kickoff=KO, at=AT, lineup_starters={TEAM: {PLAYER}}, absences_checked_at=None, across_scopes=True, lineups=[])
    assert out[1] == ("OUTDATED", "the player is in the confirmed starting line-up")


# ── what corroborates and what does not ────────────────────────────────────────────────────────────────────────────────────

def test_a_report_too_old_to_count_does_not_corroborate_a_current_one() -> None:
    """One current outlet and a report of another outlet from fifteen days ago: the old one is outdated, and one outlet is one outlet."""
    story = "w2:e:PLAYER:99:OUT"
    today, old = row(1, domain="marca.com", hours_ago=2, story=story), row(2, domain="as.com", hours_ago=24 * 15, story=story)
    out = decide([today, old])
    assert out[2] == "OUTDATED" and out[1] == "PROBABLE"


def test_v1_keeps_counting_the_reports_of_its_story_as_it_always_did() -> None:
    story = "web:1:home:jugador:injury:out"
    today = row(1, fixture=1, typed=False, domain="marca.com", hours_ago=2, story=story)
    old = row(2, fixture=1, typed=False, domain="as.com", hours_ago=24 * 15, story=story)
    out = decide([today, old], across=False)
    assert out[1] == "CONFIRMED", "not research v2's: the rule of v1 did not change"


def test_two_addresses_of_one_outlet_are_one_outlet() -> None:
    story = "w2:e:PLAYER:99:OUT"
    plain = row(1, domain="marca.com", outlet="marca.com", story=story)
    mobile = row(2, domain="amp.marca.com", outlet="marca.com", story=story)
    assert decide([plain, mobile]) == {1: "PROBABLE", 2: "PROBABLE"}
    other = row(3, domain="as.com", outlet="as.com", story=story)
    assert set(decide([plain, mobile, other]).values()) == {"CONFIRMED"}


def test_a_typed_row_with_no_registered_outlet_is_its_own_outlet() -> None:
    story = "w2:e:PLAYER:99:OUT"
    a, b = row(1, domain="a.example.com", story=story), row(2, domain="b.example.com", story=story)
    assert set(decide([a, b]).values()) == {"CONFIRMED"}, "with no outlet written, the host is the outlet (what v1 does)"
