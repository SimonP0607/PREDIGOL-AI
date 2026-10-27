"""The cycle with the research of an entity (plan IA, phase 2; ``FBI_AI_RESEARCH_V2``): ``off`` is the cycle of before, ``shadow`` runs v2 AFTER v1 in
the same pass and changes nothing v1 decides, ``on`` replaces v1's research - and only with the gate.

The world is ``test_daily_records.World`` (six matches on 1 Aug 2032; F6 is the one read here, with a player in the squad of its home side).
No network and no key: the model is ``FakeProvider`` (it answers each kind of request in its shape, v1's items and v2's claims), the search a function.
One transaction: the baseline of every comparison is a savepoint that is rolled back, so «what v1 does without v2» and «what v1 does beside v2» start
from the same world.

What is held:

* ``off``: no v2 count, no typed claim, no call of v2's agent, no search of v2 - the cycle as it was;
* ``shadow``: everything v1 wrote, asked and answered is what it is without v2 (items, statuses, the packet the model read, the brief and the
  reviews it answered, the counts the allowance of the day reads); v2 reads the search v1 paid (it is shared, not paid twice), writes its claims
  typed, and its numbers are the ``v2_*`` counts; nothing it wrote is in a packet;
* ``on`` without the gate is ``shadow``; ``on`` with it: v1's research does not run, v2's searches and items are the pass's web numbers and the
  packet the model reads holds v2's claim;
* a failure of v2 is noted and changes nothing: beside v1 the cycle stays ``ok``, instead of v1 it is ``partial``."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import entity_research, gates
from fbi.ai.collectors import SearchFn
from fbi.ai.config import AiSettings
from fbi.ai.cycle import CycleReport, run_analysis_cycle
from fbi.ai.evidence import STALE_AFTER, EvidenceIn, store
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared
from fbi.analyst.search import SearchResult

from .conftest import Seed
from .test_ai_decision_layer import Savepoints, brief_reply, review_reply
from .test_ai_research_requests import ASK, PRE, expected, match_without_a_candidate
from .test_daily_records import AT, World

pytestmark = pytest.mark.integration

MODEL = "claude-haiku-5-5"
PLAYER = 96001
PLAYER_NAME = "Delantero Seis"


@dataclass
class Setting:
    db: psycopg.Connection[Any]
    world: World
    f6: int
    home: int
    away: int


@pytest.fixture()
def setting(db: psycopg.Connection[Any], seed: Seed) -> Iterator[Setting]:
    world = World(db, seed)
    f6 = world.fixtures["F6"]
    home, away = db.execute("SELECT home_team_id, away_team_id FROM core.fixtures WHERE id = %s", (f6,)).fetchone()  # type: ignore[misc]
    db.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, first_seen_at, last_seen_at, payload_hash) "
               "VALUES (%s, %s, %s, %s, %s, 'h')", (home, PLAYER, PLAYER_NAME, AT - timedelta(days=30), AT - timedelta(days=1)))
    yield Setting(db, world, f6, int(home), int(away))


PAGE_TEXT = f"{PLAYER_NAME} no jugará ante F6-A por lesión muscular. El técnico de F6-H confirmó la baja."


def web(query: str, at: datetime) -> list[SearchResult]:
    return [SearchResult("https://www.marca.com/futbol/f6-baja.html", "F6-H: baja en el ataque", "www.marca.com",
                         (at - timedelta(hours=3)).isoformat(), at.isoformat(), PAGE_TEXT)]


V1_ITEM = {"result_id": "R1", "side": "home", "player": PLAYER_NAME, "kind": "injury", "assertion": "out",
           "claim": f"{PLAYER_NAME} no jugará por lesión muscular.", "published_at": None}


def claims(r: Any) -> dict[str, Any]:
    """The claim extractor, scripted: a claim for every listed player the page names (a quote that is in the page)."""
    body = json.loads(r.user)
    out: list[dict[str, Any]] = []
    for p in body["pages"]:
        for s in body["subjects"]:
            if s["kind"] == "PLAYER" and s["name"] in p["text"]:
                sentence = next(x.strip() for x in p["text"].split(".") if s["name"] in x)
                out.append({"subject_kind": "PLAYER", "subject_id": s["id"], "claim_type": "OUT", "applies_to": "THIS_MATCH", "quote": sentence,
                            "page_id": p["id"], "published_on": ""})
    return {"contract": "claim-v1", "claims": out}


def model() -> FakeProvider:
    def answer(r: Any) -> dict[str, Any]:
        if r.schema_name == "submit_brief":
            return brief_reply()
        if r.schema_name == "submit_items":
            return {"items": [V1_ITEM]}
        if r.schema_name == "submit_claims":
            return claims(r)
        return review_reply("APPROVE")

    return FakeProvider(answer, name="anthropic")


def run(s: Setting, mode: str, ai: FakeProvider, *, only: list[int] | None = None, at: datetime = AT, search: SearchFn = web,
        **over: Any) -> CycleReport:
    conn: Any = Savepoints(s.db)
    return run_analysis_cycle(conn, at=at, settings=AiSettings(mode="shadow", research_v2=mode, **over),  # type: ignore[arg-type]
                              ledger=UsageLedger(shared(conn._conn)), only_fixtures=only or [s.f6], search=search, provider=(ai, MODEL))


def pass_counts(db: psycopg.Connection[Any], fixture: int, kind: str = "first") -> dict[str, int]:
    row = db.execute("SELECT counts FROM ai.fixture_passes WHERE fixture_id = %s AND pass = %s", (fixture, kind)).fetchone()
    assert row is not None, f"{fixture} had no {kind} pass"
    return {str(k): int(v) for k, v in row[0].items()}


def evidence(db: psycopg.Connection[Any], *, typed: bool) -> list[dict[str, Any]]:
    cond = "subject_type IS NOT NULL" if typed else "subject_type IS NULL"
    with db.cursor() as cur:
        cur.execute(f"SELECT id, fixture_id, team_id, provider_player_id, kind, origin, status, status_reason, source_tier, claim, subject_type, "
                    f"subject_id FROM ai.evidence WHERE {cond} ORDER BY id")
        names = [c.name for c in cur.description or []]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def without_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in r.items() if k != "id"} for r in rows]


def packet_of(db: psycopg.Connection[Any], fixture: int) -> dict[str, Any]:
    row = db.execute("SELECT content FROM ai.match_packets WHERE fixture_id = %s ORDER BY as_of DESC, id DESC LIMIT 1", (fixture,)).fetchone()
    assert row is not None
    return dict(row[0])


def read_by_the_model(ai: FakeProvider, fixture: int) -> dict[str, Any]:
    """The packet in the newest brief request the model was given for the match."""
    bodies = [json.loads(r.user) for r in ai.requests if r.schema_name == "submit_brief"]
    return [b["packet"] for b in bodies if b["packet"]["fixture"]["id"] == fixture][-1]


def ledger(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT purpose, status, agent, input_hash FROM ai.usage ORDER BY id").fetchall()


def v2_ledger(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return [r for r in ledger(db) if r[2] == "claim_extractor" or str(r[3] or "").startswith(entity_research.LEDGER_PREFIX)]


def ids(evid: list[dict[str, Any]]) -> list[int]:
    return [int(e["id"]) for e in evid]


def asked(ai: FakeProvider) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in ai.requests:
        out[r.schema_name] = out.get(r.schema_name, 0) + 1
    return out


def passed_gate(db: psycopg.Connection[Any]) -> None:
    gates.record_gate(db, gate="research_v2", passed=True, at=AT - timedelta(days=1), evidence={"gate": "research-v2-gate", "days": 7})


# ── off: the cycle of before ────────────────────────────────────────────────────────────────────────────────────────

def test_off_is_the_cycle_of_before(setting: Setting) -> None:
    ai = model()
    report = run(setting, "off", ai)
    assert report.status == "ok", report.errors
    assert not [k for k in report.counts if k.startswith(("v2_", "research_v2"))], "the cycle does not know research v2"
    assert evidence(setting.db, typed=True) == [] and v2_ledger(setting.db) == []
    assert len(evidence(setting.db, typed=False)) == 1, "v1 read the page"
    assert "submit_claims" not in asked(ai) and asked(ai)["submit_items"] == 1
    counts = pass_counts(setting.db, setting.f6)
    assert counts["web_searches"] == 1 and counts["web_items"] == 1 and not [k for k in counts if k.startswith("v2_")]


# ── shadow: beside v1, nothing v1 decides moves ─────────────────────────────────────────────────────────────────────

def test_shadow_changes_nothing_v1_wrote_asked_or_answered(setting: Setting) -> None:
    db = setting.db
    db.execute("SAVEPOINT baseline")
    before_model = model()
    before_report = run(setting, "off", before_model)
    before = {"v1": without_ids(evidence(db, typed=False)), "packet": without_ids_in_packet(packet_of(db, setting.f6)),
              "read": without_ids_in_packet(read_by_the_model(before_model, setting.f6)), "counts": web_counts(pass_counts(db, setting.f6)),
              "asked": {k: v for k, v in asked(before_model).items() if k != "submit_claims"}, "status": before_report.status,
              "decisions": decisions(db)}
    db.execute("ROLLBACK TO SAVEPOINT baseline")

    ai = model()
    report = run(setting, "shadow", ai)
    after = {"v1": without_ids(evidence(db, typed=False)), "packet": without_ids_in_packet(packet_of(db, setting.f6)),
             "read": without_ids_in_packet(read_by_the_model(ai, setting.f6)), "counts": web_counts(pass_counts(db, setting.f6)),
             "asked": {k: v for k, v in asked(ai).items() if k != "submit_claims"}, "status": report.status, "decisions": decisions(db)}
    assert after == before, "what v1 wrote, what the model read and what it answered, and the counts of the allowance: as without v2"
    assert asked(ai)["submit_claims"] == 1, "and v2 asked its extractor, once"
    assert evidence(db, typed=True), "its claims are written"


def web_counts(counts: dict[str, int]) -> dict[str, int]:
    """What the allowance of the day reads. The mark of the research the pass ran under (``research_v2_shadow``) is the one count meant to differ."""
    return {k: v for k, v in counts.items()
            if k.startswith(("web_", "research_", "brief_", "reviews", "candidates", "marginal")) and not k.startswith("research_v2")}


def without_ids_in_packet(packet: dict[str, Any]) -> dict[str, Any]:
    out = dict(packet)
    out["evidence"] = [{k: v for k, v in e.items() if k != "id"} for e in packet.get("evidence", [])]
    return out


def decisions(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT fixture_id, market_key, selection, engine, decision FROM ai.pick_reviews ORDER BY fixture_id, market_key, selection, "
                      "engine, reviewed_at, id").fetchall()


def test_shadow_shares_the_search_v1_paid_and_writes_its_claims_typed(setting: Setting) -> None:
    db = setting.db
    ai = model()
    report = run(setting, "shadow", ai)
    assert report.status == "ok", report.errors
    assert report.counts["research_v2_shadow"] == 1 and "research_v2_on" not in report.counts
    counts = pass_counts(db, setting.f6)
    assert counts["web_searches"] == 1, "the allowance of the day counts v1's search, as always"
    assert (counts["v2_demand"], counts["v2_shared"], counts.get("v2_paid", 0)) == (1, 1, 0), "v1 paid first: v2 read the same answer"
    assert (counts["v2_pages"], counts["v2_claims"], counts["v2_new"], counts["v2_stored_match"]) == (1, 1, 1, 1)
    assert {k: report.counts[k] for k in counts if k.startswith("v2_")} == {k: v for k, v in counts.items() if k.startswith("v2_")}, \
        "the cycle's report holds what the pass held"
    rows = evidence(db, typed=True)
    assert len(rows) == 1
    assert (rows[0]["fixture_id"], rows[0]["team_id"], rows[0]["provider_player_id"]) == (setting.f6, setting.home, PLAYER), \
        "THIS_MATCH: the claim belongs to the match, to the side of the player and to the player"
    assert (rows[0]["subject_type"], rows[0]["subject_id"], rows[0]["kind"]) == ("PLAYER", PLAYER, "injury")
    assert (rows[0]["status"], rows[0]["origin"], rows[0]["source_tier"]) == ("PROBABLE", "web", "media"), "and its status was decided in the pass"
    assert [r[0:3] for r in v2_ledger(db)] == [("evidence_extraction", "ok", "claim_extractor")], "one call of v2's agent; no search of its own"
    assert len(evidence(db, typed=False)) == 1, "v1 still has its own item"


def test_nothing_v2_wrote_is_in_a_packet_in_shadow_and_all_of_it_is_when_it_is_on(setting: Setting) -> None:
    db = setting.db
    ai = model()
    run(setting, "shadow", ai)
    typed = ids(evidence(db, typed=True))
    assert typed
    in_packet = {int(e["id"]) for e in packet_of(db, setting.f6)["evidence"]}
    assert not in_packet & set(typed), "the packet the cycle stored does not hold what v2 wrote"
    assert {int(e["id"]) for e in read_by_the_model(ai, setting.f6)["evidence"]}.isdisjoint(typed), "nor the one the model was given"
    from fbi.ai.packet import PacketBuilder

    hidden = PacketBuilder(db).build(setting.f6, at=AT + timedelta(minutes=1))
    shown = PacketBuilder(db, typed_evidence=True).build(setting.f6, at=AT + timedelta(minutes=1))
    assert hidden is not None and shown is not None
    assert not {int(e["id"]) for e in hidden.content["evidence"]} & set(typed)
    assert set(typed) <= {int(e["id"]) for e in shown.content["evidence"]}, "turned on, the same packet builder shows them"
    assert {int(e["id"]) for e in hidden.content["evidence"]} <= {int(e["id"]) for e in shown.content["evidence"]}


def test_on_without_the_evidence_of_its_gate_is_shadow(setting: Setting) -> None:
    ai = model()
    report = run(setting, "on", ai)
    assert report.counts["research_v2_shadow"] == 1 and "research_v2_on" not in report.counts
    assert len(evidence(setting.db, typed=False)) == 1, "v1 still researched"
    assert pass_counts(setting.db, setting.f6)["web_searches"] == 1 and pass_counts(setting.db, setting.f6)["v2_shared"] == 1


# ── on, with the gate: v2 replaces v1 ───────────────────────────────────────────────────────────────────────────────

def test_on_with_the_gate_replaces_v1s_research_and_the_model_reads_what_v2_wrote(setting: Setting) -> None:
    db = setting.db
    passed_gate(db)
    ai = model()
    report = run(setting, "on", ai)
    assert report.status == "ok", report.errors
    assert report.counts["research_v2_on"] == 1 and "research_v2_shadow" not in report.counts
    assert evidence(db, typed=False) == [], "v1's research did not run"
    asks = asked(ai)
    assert "submit_items" not in asks and asks["submit_claims"] == 1
    counts = pass_counts(db, setting.f6)
    assert (counts["web_searches"], counts["web_items"], counts["web_new"]) == (1, 1, 1), "v2's numbers ARE the pass's web numbers"
    assert (counts["v2_demand"], counts["v2_paid"], counts.get("v2_shared", 0)) == (1, 1, 0), "nobody paid before it: it paid"
    searches = [r for r in ledger(db) if r[0] == "web_search"]
    assert len(searches) == 1 and str(searches[0][3]).startswith(entity_research.LEDGER_PREFIX)
    typed = evidence(db, typed=True)
    assert len(typed) == 1
    seen = read_by_the_model(ai, setting.f6)["evidence"]
    assert [e["id"] for e in seen] == [typed[0]["id"]] and PLAYER_NAME in seen[0]["claim"], "the model reads what v2 wrote"
    assert [int(e["id"]) for e in packet_of(db, setting.f6)["evidence"]] == [typed[0]["id"]]


def test_the_passed_gate_does_not_turn_shadow_or_off_into_anything(setting: Setting) -> None:
    passed_gate(setting.db)
    ai = model()
    run(setting, "shadow", ai)
    assert len(evidence(setting.db, typed=False)) == 1 and "submit_items" in asked(ai)
    assert ids(evidence(setting.db, typed=True)) and not {int(e["id"]) for e in packet_of(setting.db, setting.f6)["evidence"]} & set(
        ids(evidence(setting.db, typed=True)))


def test_a_gate_that_fails_again_takes_on_back_to_shadow(setting: Setting) -> None:
    passed_gate(setting.db)
    gates.record_gate(setting.db, gate="research_v2", passed=False, at=AT - timedelta(hours=1), evidence={"gate": "research-v2-gate", "verdict": "NO PASA"})
    report = run(setting, "on", model())
    assert report.counts["research_v2_shadow"] == 1 and len(evidence(setting.db, typed=False)) == 1


# ── failure: noted, never raised ────────────────────────────────────────────────────────────────────────────────────

def boom(*args: Any, **kwargs: Any) -> Any:
    raise RuntimeError("the database lost its mind")


def test_a_failure_of_v2_beside_v1_is_noted_and_the_cycle_stays_ok(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entity_research, "collect", boom)
    ai = model()
    report = run(setting, "shadow", ai)
    assert report.status == "ok" and report.counts["v2_failed"] == 1
    assert any("research v2" in e and "RuntimeError" in e for e in report.errors)
    assert len(evidence(setting.db, typed=False)) == 1, "v1 did its work"
    counts = pass_counts(setting.db, setting.f6)
    assert counts["web_searches"] == 1 and counts["v2_failed"] == 1, "and the pass was recorded as done, with v2's failure in it"
    assert evidence(setting.db, typed=True) == []


def test_a_failure_of_v2_instead_of_v1_leaves_the_match_without_research_and_says_partial(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    passed_gate(setting.db)
    monkeypatch.setattr(entity_research, "collect", boom)
    report = run(setting, "on", model())
    assert report.status == "partial" and report.counts["v2_failed"] == 1
    assert evidence(setting.db, typed=False) == [] and evidence(setting.db, typed=True) == []
    counts = pass_counts(setting.db, setting.f6)
    assert counts["v2_failed"] == 1, "the pass says v2 failed, so a comparison does not read «v2 found nothing»"
    assert not [k for k in counts if k.startswith("web_")], "and no research is recorded in it: nothing replaced v1's"
    assert setting.db.execute("SELECT count(*) FROM ai.match_briefs WHERE fixture_id = %s", (setting.f6,)).fetchone() == (1,), "the match was still analysed"


def test_the_statuses_of_what_v2_knows_are_decided_again_in_every_cycle_it_is_not_off(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = entity_research.refresh_for

    def spy(conn: Any, fixture_id: int, *, at: datetime) -> dict[str, int]:
        calls.append(fixture_id)
        return real(conn, fixture_id, at=at)

    monkeypatch.setattr(entity_research, "refresh_for", spy)
    run(setting, "off", model())
    assert calls == [], "off: nothing"
    run(setting, "shadow", model(), at=AT + timedelta(minutes=15))
    assert calls == [setting.f6], "beside v1: once per match inside the evidence horizon (the pass itself decides again after reading)"


def test_a_refresh_that_fails_never_stops_the_cycle(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(entity_research, "refresh_for", boom)
    report = run(setting, "shadow", model())
    assert report.status == "ok" and report.counts["v2_failed"] >= 1
    assert len(evidence(setting.db, typed=False)) == 1 and pass_counts(setting.db, setting.f6)["web_searches"] == 1


# ── what the brief asked for: v2 reads it with the levels of its topic, and when it fails the request is unserved ────

class OfficialWord:
    """The search: what was asked, and an answer only for the official statements of F6 (the second level)."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, query: str, at: datetime) -> list[SearchResult]:
        self.queries.append(query)
        return web(query, at) if "F6-H" in query and "comunicado oficial" in query else []

    def of_f6(self) -> list[str]:
        return [q for q in self.queries if "F6-H" in q]


def asker(fixture: int) -> FakeProvider:
    """A model that asks for research in the brief of ``fixture`` (and of no other match) until the brief it reads says it asked."""
    def answer(r: Any) -> dict[str, Any]:
        if r.schema_name == "submit_brief":
            body = json.loads(r.user)
            mine = body["packet"]["fixture"]["id"] == fixture and not body["previous_research"]
            return brief_reply(research=[ASK] if mine else [])
        if r.schema_name == "submit_items":
            return {"items": [V1_ITEM]}
        if r.schema_name == "submit_claims":
            return claims(r)
        return review_reply("APPROVE")

    return FakeProvider(answer, name="anthropic")


QUIET: dict[str, Any] = {"max_web_first": 0, "max_web_pre": 2}
"""The first pass reads no web (the brief asks); the pre pass reads it for one match."""


def test_what_the_brief_asked_is_read_by_v2_with_the_levels_of_its_topic_when_it_replaces_v1(setting: Setting) -> None:
    db = setting.db
    passed_gate(db)
    f6 = match_without_a_candidate(setting.world)
    ai, found = asker(f6), OfficialWord()
    first = run(setting, "on", ai, search=found, **QUIET)
    assert found.queries == [] and first.counts["research_requested"] == 1
    pre = run(setting, "on", ai, at=PRE, search=found, **QUIET)
    assert found.of_f6() == expected(db, f6, 2), "the first two levels: team news, then the official statements"
    counts = pass_counts(db, f6, "pre")
    assert (counts["research_asked"], counts["research_searched"], counts["web_searches"]) == (1, 1, 2), counts
    assert not [k for k in counts if k.startswith("research_unserved")] and "v2_failed" not in counts
    assert (pre.counts["research_asked"], pre.counts["research_searched"]) == (1, 1) and pre.status == "ok"
    assert len(evidence(db, typed=True)) == 1 and evidence(db, typed=False) == []


def test_a_request_v2_failed_to_read_is_unserved_and_the_pass_says_why(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    db = setting.db
    passed_gate(db)
    f6 = match_without_a_candidate(setting.world)
    ai, found = asker(f6), OfficialWord()
    run(setting, "on", ai, search=found, **QUIET)
    monkeypatch.setattr(entity_research, "collect", boom)
    pre = run(setting, "on", ai, at=PRE, search=found, **QUIET)
    counts = pass_counts(db, f6, "pre")
    assert counts["research_asked"] == 1 and counts["research_unserved_research_failed"] == 1 and counts["v2_failed"] == 1, counts
    assert "research_searched" not in counts and not [k for k in counts if k.startswith("web_")]
    assert pre.counts["research_unserved_research_failed"] == 1 and "research_searched" not in pre.counts and pre.status == "partial"
    assert found.queries == [], "nobody read the web"


def test_beside_v1_a_failure_of_v2_does_not_unserve_what_v1_read(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    db = setting.db
    f6 = match_without_a_candidate(setting.world)
    ai, found = asker(f6), OfficialWord()
    run(setting, "shadow", ai, search=found, **QUIET)
    monkeypatch.setattr(entity_research, "collect", boom)
    pre = run(setting, "shadow", ai, at=PRE, search=found, **QUIET)
    counts = pass_counts(db, f6, "pre")
    assert (counts["research_asked"], counts["research_searched"], counts["web_searches"]) == (1, 1, 2), "v1 served the request"
    assert counts["v2_failed"] == 1 and not [k for k in counts if k.startswith("research_unserved")]
    assert pre.status == "ok" and found.of_f6() == expected(db, f6, 2)


# ── who pays the allowance of the day ───────────────────────────────────────────────────────────────────────────────

def pays_for_two(*args: Any, **kwargs: Any) -> entity_research.CollectedV2:
    """A pass of v2 that paid for two searches of its own, read three claims and kept one as new."""
    return entity_research.CollectedV2(searches=2, extracted=3, created=1, cost_usd=0.02, demand=2, paid=2, pages=2, kept=3)


def test_beside_v1_what_v2_pays_is_not_the_allowance_of_the_day_and_instead_of_v1_it_is(setting: Setting, monkeypatch: pytest.MonkeyPatch) -> None:
    db = setting.db
    db.execute("SAVEPOINT baseline")
    run(setting, "off", model())
    without = pass_cost(db, setting.f6)
    db.execute("ROLLBACK TO SAVEPOINT baseline")

    monkeypatch.setattr(entity_research, "collect", pays_for_two)
    shadow = run(setting, "shadow", model())
    beside = pass_counts(db, setting.f6)
    assert beside["web_searches"] == 1 and beside["web_items"] == 1 and beside["web_new"] == 1, "v1's, as without v2"
    assert (beside["v2_demand"], beside["v2_paid"], beside["v2_claims"], beside["v2_new"]) == (2, 2, 3, 1), "v2's, apart"
    assert (shadow.counts["web_searches"], shadow.counts["web_items"]) == (1, 1) and shadow.counts["v2_paid"] == 2
    assert pass_cost(db, setting.f6) - without == Decimal("0.02"), "what v2 paid is in the cost of the pass"

    db.execute("ROLLBACK TO SAVEPOINT baseline")
    passed_gate(db)
    instead = run(setting, "on", model())
    replaced = pass_counts(db, setting.f6)
    assert (replaced["web_searches"], replaced["web_items"], replaced["web_new"]) == (2, 3, 1), "v2's numbers ARE the pass's web numbers"
    assert (instead.counts["web_searches"], instead.counts["web_items"]) == (2, 3) and instead.counts["v2_paid"] == 2


def pass_cost(db: psycopg.Connection[Any], fixture: int) -> Decimal:
    row = db.execute("SELECT cost_usd FROM ai.fixture_passes WHERE fixture_id = %s AND pass = 'first'", (fixture,)).fetchone()
    assert row is not None
    return Decimal(str(row[0]))


# ── the packet: how old a claim of v2 may be, and v1's rows as they were ────────────────────────────────────────────────

def written(s: Setting, story: str, *, published: datetime | None, retrieved: datetime, typed: bool) -> int:
    """An evidence of the match as research v2 (typed) or v1 (untyped) would have written it."""
    item = EvidenceIn(fixture_id=s.f6, team_id=s.home, kind="injury", claim=f"{PLAYER_NAME} no jugará ({story}).", origin="web", source_name="marca",
                      retrieved_at=retrieved, story_key=story, source_url=f"https://www.marca.com/futbol/{story}.html", published_at=published,
                      assertion="out", provider_player_id=PLAYER if typed else None, claim_type="OUT" if typed else None,
                      subject_type="PLAYER" if typed else None, subject_id=PLAYER if typed else None,
                      fresh_until=retrieved + timedelta(days=1) if typed else None)
    stored, created = store(s.db, item, at=retrieved)
    assert created
    return stored


def in_the_packet(s: Setting, *, typed_evidence: bool) -> set[int]:
    from fbi.ai.packet import PacketBuilder

    packet = PacketBuilder(s.db, typed_evidence=typed_evidence).build(s.f6, at=AT)
    assert packet is not None
    return {int(e["id"]) for e in packet.content["evidence"]}


def test_a_claim_of_v2_is_in_the_packet_only_while_it_is_not_stale_by_its_page_or_by_the_day_it_was_read(setting: Setting) -> None:
    hour = timedelta(hours=1)
    fresh = written(setting, "fresh", published=AT - timedelta(days=9), retrieved=AT - hour, typed=True)
    just_inside = written(setting, "inside", published=AT - STALE_AFTER + timedelta(minutes=1), retrieved=AT - hour, typed=True)
    old_page = written(setting, "old-page", published=AT - timedelta(days=11), retrieved=AT - hour, typed=True)
    on_the_limit = written(setting, "on-the-limit", published=AT - STALE_AFTER, retrieved=AT - hour, typed=True)
    undated_and_old = written(setting, "undated-old", published=None, retrieved=AT - timedelta(days=11), typed=True)
    undated_and_new = written(setting, "undated-new", published=None, retrieved=AT - hour, typed=True)
    assert in_the_packet(setting, typed_evidence=True) == {fresh, just_inside, undated_and_new}, \
        "by the date of the page, or by the day it was read when it has none; the limit itself is out"
    assert {old_page, on_the_limit, undated_and_old}.isdisjoint(in_the_packet(setting, typed_evidence=True))
    assert in_the_packet(setting, typed_evidence=False) == set(), "and none of it when nobody said so"


def test_what_v1_wrote_is_in_the_packet_as_it_always_was_whatever_research_v2_does(setting: Setting) -> None:
    """The age limit and the filter are for the claims of research v2: an item of v1 is read as before, old or new, with the builder told or not."""
    old = written(setting, "v1-old", published=None, retrieved=AT - timedelta(days=30), typed=False)
    new = written(setting, "v1-new", published=AT - timedelta(hours=5), retrieved=AT - timedelta(hours=1), typed=False)
    typed = written(setting, "v2-new", published=AT - timedelta(hours=5), retrieved=AT - timedelta(hours=1), typed=True)
    assert in_the_packet(setting, typed_evidence=False) == {old, new}
    assert in_the_packet(setting, typed_evidence=True) == {old, new, typed}


# ── the gate: the mark each pass carries and the measure that reads it ──────────────────────────────────────────────────

def test_the_pass_says_which_research_it_ran_under_and_the_gate_reads_it(setting: Setting) -> None:
    """The cycle writes the mark in each pass and ``fbi.ai.gate_research`` reads the days and the figures from what the cycle really wrote: no mark with
    the switch ``off``, the mark of shadow beside v1 (and v1's and v2's figures are the ones the gate compares), and for ``on`` - with its gate - the other
    mark, the one that makes the day no day of the comparison. The figures of ``test_gate_research`` are written by hand; these are the cycle's."""
    from fbi.ai import gate_research as gr
    from fbi.ai.calendar import local_day

    db = setting.db
    day, tomorrow = local_day(AT), AT + timedelta(days=1)
    db.execute("SAVEPOINT baseline")

    run(setting, "off", model())
    assert not [k for k in pass_counts(db, setting.f6) if k.startswith("research_v2")], "the pass of before says nothing about research v2"
    window = gr.window_of(db, at=tomorrow, through=day)
    assert window.stable_days == 0 and f"{day} had" not in window.anchored_by and "1 of 1 passes ran without research v2 in shadow" in window.anchored_by
    assert gr.searches(db, day, day).passes == 0 and gr.coverage(db, day, day).fixtures == 0
    db.execute("ROLLBACK TO SAVEPOINT baseline")

    run(setting, "shadow", model())
    counts = pass_counts(db, setting.f6)
    assert counts["research_v2_shadow"] == 1 and "research_v2_on" not in counts
    window = gr.window_of(db, at=tomorrow, through=day)
    assert (window.stable_days, window.anchor) == (1, day), "the day of the pass is a day of shadow"
    s = gr.searches(db, day, day)
    assert (s.passes, s.compared, s.failed, s.cut_short) == (1, 1, 0, 0)
    assert s.v1 == counts["web_searches"] == 1 and s.v2_alone == counts.get("v2_paid", 0) + counts["v2_shared"] == 1, "the figures are the pass's own"
    coverage = gr.coverage(db, day, day)
    fact = (setting.f6, "home", "seis", "out")
    assert coverage.fixtures == 1 and coverage.v1 == frozenset({fact}) and coverage.v2 == frozenset({fact}), \
        "the player v1 found out is the player research v2 found out: the same fact, from what each wrote"
    assert coverage.rate == Decimal("1.0000") and coverage.rate_players == Decimal("1.0000") and coverage.missed == []
    db.execute("ROLLBACK TO SAVEPOINT baseline")

    passed_gate(db)
    run(setting, "on", model())
    counts = pass_counts(db, setting.f6)
    assert counts["research_v2_on"] == 1 and "research_v2_shadow" not in counts
    window = gr.window_of(db, at=tomorrow, through=day)
    assert window.stable_days == 0 and "1 of 1 passes ran without research v2 in shadow (1 of them with research v2 instead of v1)" in window.anchored_by
    assert gr.searches(db, day, day).passes == 0, "research v2 instead of v1 is not a comparison of the two"
