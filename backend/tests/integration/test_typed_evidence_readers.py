"""Who reads what research v2 writes (plan IA, phase 2). Its claims are rows of ``ai.evidence`` with a ``subject_type``; while ``FBI_AI_RESEARCH_V2`` is
``shadow`` they exist for the comparison and for nobody else: not the packet (``test_research_v2_cycle``), not the set of the day, the decision layer,
the post-match review, the report of the day, the learning of the sources, nor any panel of the admin. Only ``on`` - with the evidence of its gate -
turns them into part of what the system knows.

Every reader of the table is run on the world of the post-match tests (six matches, a report that proved wrong) three times: as it is; with a typed
claim written for F5 - and ``off``, ``shadow`` or ``on`` without the gate: it answers exactly the same; and ``on`` with the gate passed: it notices the
claim. The three together hold that a reader is not blind (it would pass the second step by reading nothing) and that none leaks.

The statements are held by ``tests/unit/test_typed_evidence_guard.py`` (every ``FROM ai.evidence`` filters the claims); this test is the behaviour.
The transaction is rolled back afterwards."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.ai import gates, learning
from fbi.ai.calendar import day_bounds, local_day
from fbi.ai.evidence import EvidenceIn, store
from fbi.api.services import ai_layer, ai_v2, intelligence
from fbi.intel import decision, match_review, report
from fbi.picks import daily

from .conftest import Seed
from .test_daily_records import AT
from .test_pm_v6_equals_v2 import world
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

DAY = local_day(AT)
V1_STORY = "web-v1-F5"
V2_STORY = "web-v2-F5"


def write_v1_web_item(db: psycopg.Connection[Any], pm: Pm) -> int:
    """What v1 reads from the web for F5: an untyped item with a domain (the learning of the sources counts web items by domain)."""
    f5 = pm.f["F5"]
    team = db.execute("SELECT home_team_id FROM core.fixtures WHERE id = %s", (f5,)).fetchone()
    assert team is not None
    stored, created = store(db, EvidenceIn(
        fixture_id=f5, team_id=int(team[0]), kind="injury", claim="El técnico de F5 habló de una baja en el ataque.", origin="web",
        source_name="marca", retrieved_at=AT - timedelta(hours=2), story_key=V1_STORY, source_url="https://www.marca.com/futbol/f5-v1.html",
        published_at=AT - timedelta(hours=3), assertion="out"), at=AT - timedelta(hours=2))
    assert created
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status, fixture_id) VALUES "
               "(%s, 'web_search', 'search', 'exa', 'search', 0.005, 'ok', %s)", (AT - timedelta(hours=2), f5))
    return stored


def write_typed_claims(db: psycopg.Connection[Any], pm: Pm) -> list[int]:
    """What research v2 reads from the web for F5, from pages of the same domain as v1's item: a claim that the player the provider's report named
    (501, of the away side) is out, and one that a player of the home side (601) starts - the two kinds the panels count apart."""
    f5 = pm.f["F5"]
    teams = db.execute("SELECT home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (f5,)).fetchone()
    assert teams is not None
    ids: list[int] = []
    for team, player, kind, claim_type, assertion, claim in (
            (teams[1], 501, "injury", "OUT", "out", "Reported Out no jugará ante F5-H por lesión."),
            (teams[0], 601, "lineup", "STARTER", "starts", "El entrenador de F5-H alineará de titular al delantero 601.")):
        stored, created = store(db, EvidenceIn(
            fixture_id=f5, team_id=int(team), provider_player_id=player, kind=kind, claim=claim, origin="web", source_name="marca",
            retrieved_at=AT - timedelta(hours=2), story_key=f"{V2_STORY}-{player}", source_url=f"https://www.marca.com/futbol/f5-v2-{player}.html",
            published_at=AT - timedelta(hours=3), assertion=assertion, claim_type=claim_type,  # type: ignore[arg-type]
            subject_type="PLAYER", subject_id=player, fresh_until=AT + timedelta(hours=20)), at=AT - timedelta(hours=2))
        assert created
        ids.append(stored)
    return ids


def settings_say(monkeypatch: pytest.MonkeyPatch, word: str | None) -> None:
    values = {"FBI_AI_MODE": "shadow"} | ({} if word is None else {"FBI_AI_RESEARCH_V2": word})
    monkeypatch.setattr("fbi.ai.config.environment", lambda: values)


def passes_the_gate(db: psycopg.Connection[Any]) -> None:
    gates.record_gate(db, gate="research_v2", passed=True, at=AT, evidence={"gate": "research-v2-gate", "days": 7})


def plain(value: Any) -> Any:
    """What a reader answered, as JSON: comparable, and free of the objects that cannot be compared."""
    return json.loads(json.dumps(value, default=str, sort_keys=True))


# ── the readers: each one answers with the part of its answer that counts evidence ────────────────────────────────────

Reader = Callable[[psycopg.Connection[Any], Pm], Any]


def of_the_day_set(db: psycopg.Connection[Any], pm: Pm) -> Any:
    stub: Any = SimpleNamespace(leg=SimpleNamespace(candidate=SimpleNamespace(fixture_id=pm.f["F5"])))
    return daily.ai_view(db, [stub], at=LATE, day=False).evidence


def of_the_decision_layer(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return decision.read_world(db, [pm.f["F5"]], at=LATE).evidence


def of_the_post_match_review(db: psycopg.Connection[Any], pm: Pm) -> Any:
    got = match_review.analyse(db, pm.f["F5"])
    assert got is not None
    return got[2]["evidence"]


def of_the_report_of_the_day(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return report.build_report(db, day=DAY, at=LATE)["news"]


def of_the_learning_of_the_sources(db: psycopg.Connection[Any], pm: Pm) -> Any:
    learning.refresh_source_stats(db, day=DAY, at=LATE)
    return db.execute("SELECT domain, tier, evidence FROM ai.source_stats WHERE day = %s ORDER BY domain", (DAY,)).fetchall()


def of_the_overview_of_the_admin(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return ai_layer.overview(db, at=AT + timedelta(hours=1)).data.today


def of_the_list_of_evidence(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return [(r.id, r.claim) for r in ai_layer.evidence(db, fixture_id=pm.f["F5"], status=None, limit=50).data]


def of_the_evolution_dashboard(db: psycopg.Connection[Any], pm: Pm) -> Any:
    counts = ai_layer.dashboard(db, day=DAY).data.counts
    return {k: counts[k] for k in ("news", "injuries", "lineups")}


def of_the_efficiency_panel(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return ai_v2.efficiency(db, at=AT + timedelta(hours=1))


def of_the_research_panel(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return [(r.fixture_id, [e["id"] for e in r.evidence]) for r in ai_v2.research(db, day=DAY).data]


def of_the_day_in_predigol_ai(db: psycopg.Connection[Any], pm: Pm) -> Any:
    counts = ai_v2.day_counts(db, day=DAY)
    return {k: counts[k] for k in ("news", "injuries", "lineups")}


def of_the_intelligence_day(db: psycopg.Connection[Any], pm: Pm) -> Any:
    return intelligence.day_view(db, day=DAY).data["sources"]


READERS: dict[str, Reader] = {
    "the set of the day (picks.daily)": of_the_day_set,
    "the decision layer (intel.decision)": of_the_decision_layer,
    "the post-match review (intel.match_review)": of_the_post_match_review,
    "the report of the day (intel.report)": of_the_report_of_the_day,
    "the learning of the sources (ai.learning)": of_the_learning_of_the_sources,
    "the overview of the admin (ai_layer.overview)": of_the_overview_of_the_admin,
    "the list of evidence of the admin (ai_layer.evidence)": of_the_list_of_evidence,
    "the evolution dashboard (ai_layer.dashboard)": of_the_evolution_dashboard,
    "the efficiency panel (ai_v2.efficiency)": of_the_efficiency_panel,
    "the research panel (ai_v2.research)": of_the_research_panel,
    "the day in PrediGol AI (ai_v2.day_counts)": of_the_day_in_predigol_ai,
    "the intelligence day (intelligence.day_view)": of_the_intelligence_day,
}


@pytest.fixture()
def before(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> tuple[Pm, dict[str, Any]]:
    """The world with v1's web item, and what every reader answers about it."""
    settings_say(monkeypatch, None)
    pm = world(db, seed)
    write_v1_web_item(db, pm)
    return pm, {name: plain(read(db, pm)) for name, read in READERS.items()}


@pytest.mark.parametrize("word", [None, "off", "shadow", "on"])
def test_nobody_reads_the_claims_of_research_v2_unless_it_is_on_and_its_gate_passed(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch, word: str | None) -> None:
    pm, base = before
    write_typed_claims(db, pm)
    settings_say(monkeypatch, word)  # ``on`` is shadow: the gate has not passed
    leaks = [name for name, read in READERS.items() if plain(read(db, pm)) != base[name]]
    assert leaks == [], f"with FBI_AI_RESEARCH_V2={word}: these readers answer differently because research v2 wrote a claim"


def test_every_reader_notices_the_claims_when_research_v2_is_on_and_its_gate_passed(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    pm, base = before
    write_typed_claims(db, pm)
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    blind = [name for name, read in READERS.items() if plain(read(db, pm)) == base[name]]
    assert blind == [], "a reader that answers the same with the claim written is a reader that was never looking at it"


def test_a_gate_that_failed_after_it_passed_hides_them_again(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    pm, base = before
    write_typed_claims(db, pm)
    passes_the_gate(db)
    settings_say(monkeypatch, "on")
    gates.record_gate(db, gate="research_v2", passed=False, at=LATE, evidence={"gate": "research-v2-gate", "verdict": "NO PASA"})
    assert [name for name, read in READERS.items() if plain(read(db, pm)) != base[name]] == []


def test_the_passed_gate_alone_shows_nothing_while_the_word_is_shadow_or_off(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    pm, base = before
    write_typed_claims(db, pm)
    passes_the_gate(db)
    for word in (None, "off", "shadow"):
        settings_say(monkeypatch, word)
        assert [name for name, read in READERS.items() if plain(read(db, pm)) != base[name]] == [], word


# ── the defaults, and the columns another panel overwrites ────────────────────────────────────────────────────────────

def test_the_count_of_the_set_of_the_day_hides_the_claims_when_nobody_says_otherwise(
        db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]]) -> None:
    pm, base = before
    write_typed_claims(db, pm)
    f5 = pm.f["F5"]
    assert plain(daily.evidence_counts(db, [f5], at=LATE)) == base["the set of the day (picks.daily)"], "``typed`` is False unless it is told"
    assert plain(daily.evidence_counts(db, [f5], at=LATE, typed=False)) == base["the set of the day (picks.daily)"]
    shown = daily.evidence_counts(db, [f5], at=LATE, typed=True)
    assert sum(shown[f5].values()) == sum(daily.evidence_counts(db, [f5], at=LATE)[f5].values()) + 2


def test_the_counts_of_the_dashboard_filter_the_claims_by_themselves(db: psycopg.Connection[Any], before: tuple[Pm, dict[str, Any]]) -> None:
    """``dashboard`` overwrites ``news``, ``injuries`` and ``lineups`` with the counts of ``ai_v2.day_counts``; its own statement must not be a
    second way to see the claims the day it stops being overwritten."""
    pm, _ = before
    start, end = day_bounds(DAY)

    def counts(typed: bool) -> dict[str, int]:
        with db.cursor(row_factory=dict_row) as cur:
            cur.execute(ai_layer.DASHBOARD_SQL, {"since": start, "until": end, "typed": typed})
            row = cur.fetchone()
            assert row is not None
            return {k: int(row[k]) for k in ("news", "injuries", "lineups")}

    base = counts(False)
    assert base["news"] >= 1, "v1's web item of the world"
    write_typed_claims(db, pm)
    assert counts(False) == base
    shown = counts(True)
    assert (shown["news"] - base["news"], shown["injuries"] - base["injuries"], shown["lineups"] - base["lineups"]) == (2, 1, 1)
