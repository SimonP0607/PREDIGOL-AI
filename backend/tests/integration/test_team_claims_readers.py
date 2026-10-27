"""What research v2 knows about a TEAM reaches the readers that choose evidence by match (plan IA, phase 2, finding H4 of the independent review).

A claim of research v2 that says nothing of a particular match (``applies_to`` ``UNSPECIFIED``: a report of injuries, «X is out», whatever match asks) is
stored with ``fixture_id`` NULL and the team (``fbi.ai.extract_v2.to_evidence``). The packet shows it to the model of every match of the team while it
is fresh. The four readers that choose evidence by ``fixture_id`` - the decision layer, the set of the day, the post-match review and the report of the
day - did not: with research v2 ``on`` the model would have read «X is out» and the context, the set, the review and the report would not have known it
existed. They take the claims of the teams from ``fbi.ai.team_claims`` now. What is held here, on the world of the post-match tests (six matches, a
report that proved wrong) and, for the context, on the world of the decision layer:

* nothing moves while research v2 is not ``on`` with the evidence of its gate: not one of the twelve readers of the table answers differently;
* with ``on`` the four notice the claims, and they notice the ones the packet shows - the same ones - at the moment each one looks from: the decision
  and the set of the day at the moment they ask; the review and the report at the kick-off of the match (they look back);
* the ones that look forward (the decision, the set of the day) leave out what the server set aside, as the packet does; the ones that look back (the
  review, the report) keep it: a report that the line-up proved wrong is set aside BECAUSE it proved wrong, and a review that left it out would judge
  the sources by their hits alone;
* a claim older than ten days, one about a team that does not play, one read after the moment: none of them is part of the match;
* the decision layer's context goes from LIMITED to FULL with the claim and the score of the selection goes up with it, and goes back down when the
  claim is set aside.

The statements are held by ``tests/unit/test_team_claims.py`` and ``tests/unit/test_typed_evidence_guard.py``; this test is the behaviour. The
transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import packet
from fbi.ai.evidence import STALE_AFTER, EvidenceIn, store
from fbi.intel import calibration, decision, match_review, report
from fbi.picks import daily

from . import test_intel
from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT
from .test_pm_v6_equals_v2 import world
from .test_postmortem_v6 import LATE, Pm
from .test_typed_evidence_readers import (
    DAY,
    READERS,
    passes_the_gate,
    plain,
    settings_say,
    write_v1_web_item,
)

pytestmark = pytest.mark.integration

THE_FOUR = ("the set of the day (picks.daily)", "the decision layer (intel.decision)", "the post-match review (intel.match_review)",
            "the report of the day (intel.report)")


def sides(db: psycopg.Connection[Any], pm: Pm, name: str = "F5") -> tuple[int, int]:
    row = db.execute("SELECT home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (pm.f[name],)).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


def team_claim(db: psycopg.Connection[Any], *, team: int, player: int, claim: str, kind: str = "injury", claim_type: str = "OUT", assertion: str = "out",
               retrieved: datetime = AT - timedelta(hours=2), published: datetime | None = AT - timedelta(hours=3), fixture: int | None = None) -> int:
    """A claim about a player of a team that belongs to no match - what the extractor writes for a report that says nothing of a match (``applies_to``
    ``UNSPECIFIED``): no ``fixture_id``, the team, the page's own date and the standing of a media outlet. ``fixture``: tied to a match after all."""
    stored, created = store(db, EvidenceIn(
        fixture_id=fixture, team_id=team, provider_player_id=player, kind=kind, claim=claim, origin="web", source_name="marca.com", source_tier="media",
        retrieved_at=retrieved, story_key=f"w2:e:PLAYER:{player}:{claim_type}", source_url=f"https://www.marca.com/futbol/equipo-{player}.html",
        published_at=published, assertion=assertion, claim_type=claim_type, subject_type="PLAYER", subject_id=player,  # type: ignore[arg-type]
        fresh_until=retrieved + timedelta(hours=20)), at=retrieved)
    assert created
    return stored


def write_team_claims(db: psycopg.Connection[Any], pm: Pm) -> list[int]:
    """The two kinds the panels count apart, about the two teams of F5 and about no match: the player the provider's report named (501, away) is out, and a
    player of the home side (601) starts."""
    home, away = sides(db, pm)
    return [team_claim(db, team=away, player=501, claim="Reported Out no jugará ante F5-H por lesión."),
            team_claim(db, team=home, player=601, claim="El entrenador de F5-H alineará de titular al delantero 601.", kind="lineup",
                       claim_type="STARTER", assertion="starts")]


@pytest.fixture()
def before(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> tuple[Pm, dict[str, Any]]:
    """The world with v1's web item for F5, and what every reader answers about it."""
    settings_say(monkeypatch, None)
    pm = world(db, seed)
    write_v1_web_item(db, pm)
    return pm, {name: plain(read(db, pm)) for name, read in READERS.items()}


# ── nothing moves unless research v2 is on and its gate passed ───────────────────────────────────────────────────────

@pytest.mark.parametrize("word", [None, "off", "shadow", "on"])
def test_the_claims_about_a_team_are_read_by_nobody_unless_research_v2_is_on_and_its_gate_passed(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch, word: str | None) -> None:
    pm, base = before
    write_team_claims(db, pm)
    settings_say(monkeypatch, word)  # ``on`` is shadow: the gate has not passed
    leaks = [name for name, read in READERS.items() if plain(read(db, pm)) != base[name]]
    assert leaks == [], f"with FBI_AI_RESEARCH_V2={word}: these readers answer differently because research v2 wrote a claim about a team"


def test_the_passed_gate_alone_shows_nothing_while_the_word_is_shadow_or_off(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    pm, base = before
    write_team_claims(db, pm)
    passes_the_gate(db)
    for word in (None, "off", "shadow"):
        settings_say(monkeypatch, word)
        assert [name for name, read in READERS.items() if plain(read(db, pm)) != base[name]] == [], word


# ── with on, the four notice them ────────────────────────────────────────────────────────────────────────────────────

def test_the_four_readers_that_choose_evidence_by_match_notice_the_claims_about_its_teams_when_research_v2_is_on(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    pm, base = before
    write_team_claims(db, pm)
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    blind = [name for name in THE_FOUR if plain(READERS[name](db, pm)) == base[name]]
    assert blind == [], "a reader that answers the same with the claims written is a reader that never looked at them"


def test_the_set_of_the_day_counts_the_claims_about_a_team_only_when_it_is_told_to_and_the_decision_layer_reads_none_by_default(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]]) -> None:
    pm, _ = before
    f5 = pm.f["F5"]
    base = sum(daily.evidence_counts(db, [f5], at=LATE)[f5].values())
    assert base == 2, "the provider's report and v1's web item"
    ids = write_team_claims(db, pm)
    assert sum(daily.evidence_counts(db, [f5], at=LATE)[f5].values()) == base, "``typed`` is False unless it is told"
    assert sum(daily.evidence_counts(db, [f5], at=LATE, typed=True)[f5].values()) == base + 2
    seen = {int(i) for row in decision.read_world(db, [f5], at=LATE).evidence[f5] for i in row["ids"]}
    assert set(ids) & seen == set(), "``typed`` is read from the settings: with no word nothing of research v2 is part of the world"


def test_the_post_match_review_judges_a_report_about_a_team_that_the_line_up_proved_wrong(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """The provider's report said player 501 was out (F5, away) and he started; research v2 read the same on the web, about the team and no match. The
    review judges both reports."""
    pm, _ = before
    out, _starter = write_team_claims(db, pm)
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    got = match_review.analyse(db, pm.f["F5"])
    assert got is not None
    judged = {e["evidence_id"]: e for e in got[2]["evidence"]}
    assert out in judged, "the claim of research v2 about the team is judged like the report of a match"
    assert judged[out]["verdict"] == "wrong" and judged[out]["side"] == "away" and judged[out]["origin"] == "web"
    assert sum(1 for e in judged.values() if e["verdict"] == "wrong") == 2, "the provider's report and the claim of the web, both wrong"


# ── the same claims as the packet, from the same moment ────────────────────────────────────────────────────────────

def packet_sees(db: psycopg.Connection[Any], pm: Pm, *, at: datetime) -> set[int]:
    """What the packet of F5 shows the model at ``at`` with research v2 on: the ids of its evidence block."""
    home, away = sides(db, pm)
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(packet.EVIDENCE_SQL, {"fixture": pm.f["F5"], "teams": [home, away], "at": at, "typed": True, "stale": STALE_AFTER})
        return {int(r["id"]) for r in cur.fetchall()}


def the_decision_sees(db: psycopg.Connection[Any], pm: Pm, *, at: datetime) -> set[int]:
    return {int(i) for row in decision.read_world(db, [pm.f["F5"]], at=at).evidence.get(pm.f["F5"], []) for i in row["ids"]}


def the_review_judges(db: psycopg.Connection[Any], pm: Pm) -> set[int]:
    got = match_review.analyse(db, pm.f["F5"])
    assert got is not None
    return {int(e["evidence_id"]) for e in got[2]["evidence"]}


def the_report_counts(db: psycopg.Connection[Any]) -> int:
    return sum(int(r["n"]) for r in report.build_report(db, day=DAY, at=LATE)["news"])


def the_set_counts(db: psycopg.Connection[Any], pm: Pm, *, at: datetime) -> int:
    return sum(daily.evidence_counts(db, [pm.f["F5"]], at=at, typed=True).get(pm.f["F5"], {}).values())


def test_the_readers_and_the_packet_agree_on_which_claims_about_a_team_belong_to_a_match(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Seven claims about teams, one of each way to be left out or kept, and what each reader makes of them."""
    pm, _ = before
    home, away = sides(db, pm)
    f7_home, _ = sides(db, pm, "F7")  # plays the next day: another team as far as F5 and the day of F5 are concerned
    later_than = LATE + timedelta(hours=2)
    base_set, base_report = the_set_counts(db, pm, at=LATE), the_report_counts(db)
    assert (base_set, base_report) == (2, 2), "the provider's report and v1's web item"
    visible = [team_claim(db, team=away, player=501, claim="Reported Out no jugará ante F5-H por lesión."),
               team_claim(db, team=home, player=601, claim="El entrenador de F5-H alineará de titular al delantero 601.", kind="lineup",
                          claim_type="STARTER", assertion="starts")]
    stale = team_claim(db, team=home, player=602, claim="El delantero 602 se perderá el resto del mes por una rotura.", published=AT - timedelta(days=12))
    elsewhere = team_claim(db, team=f7_home, player=701, claim="El defensa 701 no jugará el domingo por lesión.")
    another_match = team_claim(db, team=home, player=604, claim="El volante 604 se perderá el partido de F6 por una lesión.", fixture=pm.f["F6"])
    later = team_claim(db, team=away, player=502, claim="El volante 502 es duda para el partido por una molestia.", kind="doubtful", claim_type="DOUBT",
                       assertion="doubt", retrieved=LATE + timedelta(hours=1), published=LATE + timedelta(minutes=30))
    set_aside = team_claim(db, team=home, player=603, claim="El lateral 603 está fuera por suspensión según el club.")
    db.execute("UPDATE ai.evidence SET status = 'OUTDATED', status_reason = 'superseded in the test', status_changed_at = %s WHERE id = %s", (AT, set_aside))
    written = {*visible, stale, elsewhere, another_match, later, set_aside}
    passes_the_gate(db)
    settings_say(monkeypatch, "on")

    # the model reads the two standing claims of the teams: nothing of the stale one, the other team's, the one tied to another match, the later one
    # or the one set aside
    assert packet_sees(db, pm, at=LATE) & written == set(visible)
    # the decision layer and the set of the day look forward from the moment they ask: the same two
    assert the_decision_sees(db, pm, at=LATE) & written == set(visible)
    assert the_set_counts(db, pm, at=LATE) == base_set + 2
    # ... and what was read after the moment is part of it from the moment it was read on, here as in the packet
    assert the_decision_sees(db, pm, at=later_than) & written == {*visible, later}
    assert packet_sees(db, pm, at=later_than) & written == {*visible, later}
    assert the_set_counts(db, pm, at=later_than) == base_set + 3
    # the review and the report look back from the kick-off: what was read after the match is nothing of the match, and what the server set aside is kept
    assert the_review_judges(db, pm) & written == {visible[0], set_aside}, "(the injury reports: the claim that a player starts is not a report to judge)"
    assert the_report_counts(db) == base_report + 4, "the two standing claims, the one set aside and the one tied to F6 - that one is F6's own"


def test_a_claim_set_aside_is_judged_by_the_review_with_the_status_the_server_gave_it(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """The line-up that proves a report wrong is what sets it aside (``refresh_typed_statuses``): the review must still judge it, or it would judge the
    sources by their hits alone."""
    pm, _ = before
    out, _starter = write_team_claims(db, pm)
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    db.execute("UPDATE ai.evidence SET status = 'OUTDATED', status_reason = 'the player started in a later confirmed line-up of the team', "
               "status_changed_at = %s WHERE id = %s", (AT + timedelta(hours=9), out))
    got = match_review.analyse(db, pm.f["F5"])
    assert got is not None
    judged = {e["evidence_id"]: e for e in got[2]["evidence"]}
    assert judged[out]["verdict"] == "wrong" and judged[out]["status"] == "OUTDATED"
    assert out not in the_decision_sees(db, pm, at=LATE) and out not in packet_sees(db, pm, at=LATE), "forward, it is not read any more"


def test_a_claim_about_a_team_that_plays_two_matches_that_day_is_counted_once_by_the_report(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """``count(DISTINCT e.id)``: the join gives the claim to each match of the team, and the report counts the claim, not the pairs."""
    pm, _ = before
    home, _away = sides(db, pm)
    base = the_report_counts(db)
    # a second match of the same home team the same Bogotá day, a few hours after F5
    row = db.execute("SELECT competition_season_id, kickoff_at FROM core.fixtures WHERE id = %s", (pm.f["F5"],)).fetchone()
    assert row is not None
    other = scalar(db.execute("SELECT id FROM core.teams WHERE id <> %s ORDER BY id LIMIT 1", (home,)))
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s)",
               (9990001, row[0], home, other, row[1] + timedelta(hours=1)))
    team_claim(db, team=home, player=601, claim="El entrenador de F5-H alineará de titular al delantero 601.", kind="lineup", claim_type="STARTER",
               assertion="starts")
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    assert the_report_counts(db) == base + 1


# ── the context of the decision and its score ────────────────────────────────────────────────────────────────────────

def test_the_context_of_a_decision_and_its_score_follow_a_claim_about_a_team_of_the_match(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason the finding is «high»: with research v2 ``on`` the model reads «X is out» and the decision layer, which says how much of the match the
    system knows (FULL, PARTIAL, LIMITED) and scores the selection by it, would not have: the context stays LIMITED and the score ten points of context
    short by seven. A selection of a match the AI has read (a first pass) and found nothing outside the numbers: LIMITED; with one claim from a media
    outlet about a team of the match - and no match in it - FULL."""
    settings_say(monkeypatch, None)
    test_intel.small_gates(monkeypatch)
    w = test_intel.IntelWorld(db, seed)
    at = test_intel.AT
    w.history()
    calibration.run_calibration(db, at=at - timedelta(hours=1), commit=False)  # the champion calibrator the score needs
    fid = w.fixture(at + timedelta(hours=5))
    w.pick(fid, "OU", "Over", "2.5", p_model=0.66, p_market=0.50, odds=2.10, created=at - timedelta(minutes=30))
    w.consensus(fid, "OU", "Over", "2.5", p_fair=0.50, best=2.10, as_of=at - timedelta(minutes=10))
    db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
               "SELECT id, (kickoff_at AT TIME ZONE 'America/Bogota')::date, 'first', %s, %s, kickoff_at, 'ok', %s FROM core.fixtures WHERE id = %s",
               (at - timedelta(minutes=20), at - timedelta(minutes=15), Jsonb({"web_searches": 0}), fid))
    home = int(scalar(db.execute("SELECT home_team_id FROM core.fixtures WHERE id = %s", (fid,))))

    def evaluated() -> decision.Evaluated:
        _, out = decision.decide(db, at=at, write=False)
        mine = [e for e in out if e.key[0] == fid]
        assert len(mine) == 1
        return mine[0]

    alone = evaluated()
    assert alone.context.status == "LIMITED" and alone.context.evidence == {} and alone.score is not None
    claim = team_claim(db, team=home, player=9001, claim="El delantero 9001 no jugará este fin de semana por una lesión muscular.", retrieved=at - timedelta(hours=2),
                       published=at - timedelta(hours=3))
    for word in (None, "off", "shadow", "on"):  # ``on`` without the evidence of its gate is shadow
        settings_say(monkeypatch, word)
        now = evaluated()
        assert now.score is not None
        assert (now.context.status, now.context.evidence_ids, now.score.total) == (alone.context.status, [], alone.score.total), word
    passes_the_gate(db)
    for word in (None, "off", "shadow"):  # the gate alone shows nothing
        settings_say(monkeypatch, word)
        assert evaluated().context.status == "LIMITED", word
    settings_say(monkeypatch, "on")
    full = evaluated()
    assert full.context.status == "FULL" and full.context.evidence == {"web:PROBABLE": 1} and full.context.evidence_ids == [claim]
    assert full.score is not None and full.score.total > alone.score.total, "the context counts ten points of a hundred: FULL 1.0 against LIMITED 0.3"
    assert round(full.score.total - alone.score.total, 2) == 7.0

    # set aside by the server, the decision layer looks forward and does not read it, as the packet does not show it
    db.execute("UPDATE ai.evidence SET status = 'OUTDATED', status_reason = 'superseded in the test', status_changed_at = %s WHERE id = %s", (at, claim))
    back = evaluated()
    assert back.context.status == "LIMITED" and back.context.evidence_ids == [] and back.score is not None and back.score.total == alone.score.total
