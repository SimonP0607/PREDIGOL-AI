"""The unified deep research on a built world (IA-087, ``fbi.ai.unified_research``): what the road reads and writes in the database.

The world of ``test_ai_research_entities`` (Alfa FC - Beta FC, a squad for each club; Gama FC - Alfa FC three days after) with a squad of 40
for Alfa (the 30 of research v2 cannot name the 35th), and a policy that authorises and signs ONE source (``diario.example``). No network, no
key: the model is a scripted provider. One transaction, rolled back.

* the road reads the search answers v1 cached, without counting a reuse (``hits`` does not move) and without searching;
* only the authorised source is sent; one call per page; the LAB pays, under the ledger prefix ``rk-u1:``;
* a page with the same fingerprint under another address, or for the next match, is not paid again;
* ``ai.evidence`` is not touched; the comparison with v1 is in the counts.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import cache, collectors, source_policy, unified_research
from fbi.ai.config import AiSettings
from fbi.ai.evidence import EvidenceIn, store
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.source_registry import Source, parse_authority
from fbi.ai.usage import UsageLedger, shared
from fbi.analyst.search import SearchResult

from .conftest import Seed
from .test_ai_research_entities import AT, MODEL, STRIKER, World, build, page

pytestmark = pytest.mark.integration

FAR = 91040
TEXT = ("Delantero Uno no jugará ante Beta FC por lesión muscular, confirmó el club.\n\n"
        + "El equipo entrenó a puerta cerrada y la directiva presentó la nueva camiseta de la temporada en un acto con aficionados. " * 6
        + "\n\nZuluaga Lejano se perderá el partido por sanción tras su quinta amarilla.")
AUTH = page("https://diario.example/alfa-bajas", "Alfa FC: dos bajas", TEXT)
COPY = page("https://espejo.example/alfa-bajas?utm_source=x", "Alfa FC: dos bajas", TEXT)
PENDING = page("https://www.futbolred.com/beta", "Beta FC", "Extremo Dos es duda para el partido ante Alfa FC.")


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    w = build(db, kickoff_a=AT + timedelta(hours=20))
    with db.cursor() as cur:
        for n in range(3, 41):
            pid = 91000 + n
            name = "Zuluaga Lejano" if pid == FAR else f"Jugador Relleno{n:02d}"
            cur.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, first_seen_at, last_seen_at, payload_hash) "
                        "VALUES (%s, %s, %s, %s, %s, 'h')", (w.alfa, pid, name, AT - timedelta(days=30), AT - timedelta(days=1)))
    return w


def policy() -> source_policy.SourcePolicy:
    def src(sid: str, domain: str, state: str) -> Source:
        return Source(sid, domain, domain, "B", "prensa_deportiva", state, "permitido", "permitido", "hechos", "resumen",
                      parse_authority("lesiones:informa; sanciones:informa; alineaciones:informa"), None)

    return source_policy.SourcePolicy([src("t-diario", "diario.example", "verificada_autorizada"),
                                       src("t-espejo", "espejo.example", "verificada_autorizada"),
                                       src("t-futbolred", "futbolred.com", "verificada_pendiente_derechos")], [],
                                      signed=["t-diario", "t-espejo"], directory_version="t", exclusion_version="t", origin="test")


def reader(asked: list[str]) -> FakeProvider:
    def script(r: JsonRequest) -> dict[str, Any]:
        asked.append(r.schema_name)
        doc = json.loads(r.user)
        text = doc["page"]["text"]
        claims = []
        for s in doc["subjects"]:
            if s["kind"] == "PLAYER" and s["name"] in text:
                sentence = next(x.strip() for x in text.replace("\n", " ").split(".") if s["name"] in x)
                kind = "SUSPENSION" if "sanción" in sentence else "OUT"
                claims.append({"subject": s["ref"], "claim_type": kind, "applies_to": "THIS_MATCH", "quote": sentence})
        return {"contract": "claim-v2", "call": doc["call"], "claims": claims}

    return FakeProvider(script, name="anthropic")


def settings() -> AiSettings:
    return AiSettings(mode="shadow", research_unified="shadow", lab_monthly_budget=Decimal(10))


def run(w: World, fixture: int, results: list[SearchResult] | None, asked: list[str]) -> unified_research.Outcome:
    return unified_research.collect(w.db, settings(), fixture, at=AT, ledger=UsageLedger(shared(w.db)), provider=(reader(asked), MODEL),
                                    policy=policy(), results=results)


def evidence_count(db: psycopg.Connection[Any]) -> int:
    return int(db.execute("SELECT count(*) FROM ai.evidence").fetchone()[0])  # type: ignore[index]


def test_only_the_authorised_page_is_sent_and_nothing_reaches_ai_evidence(world: World) -> None:
    asked: list[str] = []
    before = evidence_count(world.db)
    got = run(world, world.a, [AUTH, PENDING], asked)
    assert asked == ["submit_claims_v2"], "one call: the authorised page; the pending source is never sent"
    assert got.counts["xu_page_read"] == 1 and got.counts["xu_page_not_authorised"] == 1
    assert got.counts["xu_claims"] == 2, got.counts
    assert got.counts["xu_candidates_beyond_30"] >= 1, "the whole squad, not v2's thirty"
    assert evidence_count(world.db) == before
    rows = world.db.execute("SELECT workspace, input_hash FROM ai.usage WHERE purpose = 'evidence_extraction'").fetchall()
    assert len(rows) == 1 and rows[0][0] == "PREDIGOL-LAB" and str(rows[0][1]).startswith(unified_research.LEDGER_PREFIX)
    stored = world.db.execute("SELECT payload FROM ai.research_cache WHERE scope = 'url' AND key LIKE %s",
                              (unified_research.KEY_PREFIX + "%",)).fetchall()
    assert len(stored) == 1 and stored[0][0]["store"] == "facts" and {c["id"] for c in stored[0][0]["claims"]} == {STRIKER, FAR}
    assert got.counts["xu_rung_DECLARACION"] == 1 and got.counts["xu_rung_REPORTE"] == 1, "«confirmó el club» is the club's word, reported"


def test_the_same_page_is_paid_once_under_any_address_and_for_any_match(world: World) -> None:
    asked: list[str] = []
    run(world, world.a, [AUTH], asked)
    again = run(world, world.a, [COPY], asked)
    later = run(world, world.b, [AUTH], asked)
    assert asked == ["submit_claims_v2"], "one fingerprint, one call"
    assert again.counts["xu_page_reused"] == 1 and later.counts["xu_page_reused"] == 1
    payload = world.db.execute("SELECT payload FROM ai.research_cache WHERE scope = 'url' AND key LIKE %s",
                               (unified_research.KEY_PREFIX + "%",)).fetchone()[0]  # type: ignore[index]
    assert set(payload["read_for"]) == {world.a, world.b} and len(payload["urls"]) == 2 and payload["first_seen_at"] == AT.isoformat()


def test_the_road_reads_v1s_cached_search_without_counting_a_reuse(world: World) -> None:
    from fbi.ai.entity_research import load_match

    match = load_match(world.db, world.a, at=AT)
    assert match is not None
    query = collectors.queries_for(match.home.name, match.away.name, match.kickoff_at, match.country, match.competition, levels=1)[0]
    key = collectors.search_key(query, "early", 1)
    cache.put(world.db, "search", key, {"query": query, "level": 1, "results": [AUTH.as_json()]}, at=AT - timedelta(hours=1),
              ttl=timedelta(hours=24))
    asked: list[str] = []
    got = run(world, world.a, None, asked)
    hits = world.db.execute("SELECT hits FROM ai.research_cache WHERE scope = 'search' AND key = %s", (key,)).fetchone()[0]  # type: ignore[index]
    assert got.counts["xu_pages"] == 1 and hits == 0


def test_the_comparison_with_v1_is_in_the_counts(world: World) -> None:
    store(world.db, EvidenceIn(fixture_id=world.a, team_id=world.alfa, kind="injury", claim="Zuluaga Lejano no jugará por sanción.",
                               origin="web", source_name="x.example", retrieved_at=AT - timedelta(hours=2), source_url="https://x.example/1",
                               published_at=AT - timedelta(hours=3), story_key=f"web:{world.a}:home:zuluaga:injury:out", assertion="out",
                               event_at=AT + timedelta(hours=20), confidence=0.5, relevance=0.6,
                               attributes={"player_name": "Zuluaga Lejano", "extract_version": "extract-v1"}), at=AT - timedelta(hours=2))
    got = run(world, world.a, [AUTH], [])
    assert got.counts["xu_v1_players"] == 1 and got.counts["xu_v1_full"] == 1 and got.counts["xu_v1_capped"] == 0
    assert got.counts["xu_v1_windows"] == 1 and got.counts["xu_v1_found"] == 1


def test_the_owners_readers_run_read_only_on_the_world(world: World) -> None:
    from fbi.ai import unified_readers

    store(world.db, EvidenceIn(fixture_id=world.a, team_id=world.alfa, kind="injury", claim="Zuluaga Lejano no jugará por sanción.",
                               origin="web", source_name="diario.example", retrieved_at=AT - timedelta(hours=2), source_url=AUTH.url,
                               published_at=AT - timedelta(hours=3), story_key=f"web:{world.a}:home:zuluaga:injury:out", assertion="out",
                               event_at=AT + timedelta(hours=20), confidence=0.5, relevance=0.6,
                               attributes={"player_name": "Zuluaga Lejano", "extract_version": "extract-v1"}), at=AT - timedelta(hours=2))
    cache.put(world.db, "search", "k-test", {"query": "q", "level": 1, "results": [AUTH.as_json()]}, at=AT - timedelta(hours=1),
              ttl=timedelta(days=30))
    run(world, world.a, [AUTH], [])
    since, until = AT - timedelta(days=2), AT + timedelta(hours=1)
    with world.db.transaction():
        world.db.execute("SET TRANSACTION READ ONLY")
        assert unified_readers.report(world.db, since=since, until=until)["pages_remembered"] == 1
        linked = unified_readers.linking(world.db, since=since, until=until, at=AT)
        assert linked["facts"]["club"] == {"players": 1, "unidentified_full": 0, "unidentified_30": 1}
        win = unified_readers.windows(world.db, since=since, until=until, at=AT)
        assert win["linked"] == 1 and win["named_in_windows"] == 1 and win["named_in_700"] == 0
        replayed = unified_readers.replay(world.db, since=since, until=until, policy=policy())
        assert replayed["facts"] >= 1
