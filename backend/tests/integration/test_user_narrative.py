"""The readers' narrative (plan UX, A11) in a real database, with a model that answers what each test needs (no network).

A validated narrative is stored with its translations and its cost in the readers' own ledger, and shown only for the very reading
it was written from - to readers with the switch on, to the Admin Console's preview in shadow -; a refused one leaves the structured
reading, its reasons recorded and never paid for again; nothing is spent without the readers' budget; PrediGol Intelligence's budget
reads the same with and without the readers' spend; a run writes the readers' tables and nothing else. The transaction is rolled
back (each match runs in a savepoint of it)."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.ai import user_budget
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError
from fbi.ai.usage import budget, shared
from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import forecast as forecast_service
from fbi.api.services import news as news_service
from fbi.api.services import reading as reading_service
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.narrative import job as un
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import AT, World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_news_api import evidence as add_evidence
from tests.integration.test_reading_api import CONTENT

pytestmark = pytest.mark.integration

RUN_AT = AT + timedelta(minutes=30)
MODEL = "claude-haiku-5-5"
SETTINGS = AiSettings(tiers={"bulk": TierModel("anthropic", MODEL)}, keys={"anthropic": "test-key-not-real"},
                      monthly_budget=Decimal("180"), daily_budget=Decimal("6"))
INJURY = "Lisandro Martínez es baja por lesión para este partido."
DOUBT = "Según Marca, Mohamed Salah está en duda por unas molestias en el tobillo."
RUMOUR = "Se dice que el portero titular no viajó con el equipo."


class Model:
    """A provider that answers from a list: an answer (a dict) or an error to raise. Records what it was asked."""

    name = "anthropic"

    def __init__(self, *answers: dict[str, Any] | ProviderError) -> None:
        self.answers = list(answers)
        self.asked: list[JsonRequest] = []

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        self.asked.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, ProviderError):
            raise answer
        return LlmResult(copy.deepcopy(answer), LlmUsage(input_tokens=6000, output_tokens=2500), "anthropic", model, 900,
                         "req-test")


@pytest.fixture()
def frozen() -> Iterator[None]:
    set_clock(FrozenClock(RUN_AT))
    yield
    set_clock(SystemClock())


def match(db: psycopg.Connection[Any], world: World, seed: Seed, *, content: dict[str, Any] | None = None  # noqa: F811
          ) -> tuple[int, int, dict[str, int]]:
    """A match with PrediGol's forecast, a packet with a market and three news items from the web (and a provider's report that
    must never reach the call), and its final pass. Returns the match, the packet and the items' ids."""
    fid = world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    world.write(fid)
    home, away = seed.home_team_id, seed.away_team_id
    seen = AT - timedelta(hours=1)
    ids = {"injury": add_evidence(db, fid, home, status="CONFIRMED", player="Lisandro Martínez", claim=INJURY,
                                  retrieved=seen),
           "doubt": add_evidence(db, fid, away, status="PROBABLE", kind="doubtful", assertion="doubtful",
                                 player="Mohamed Salah", claim=DOUBT, source="www.marca.com", url="https://www.marca.com/1",
                                 retrieved=seen),
           "rumour": add_evidence(db, fid, home, status="RUMOR", kind="news", assertion="info", claim=RUMOUR,
                                  tier="unknown", source="rumours.example", url="https://rumours.example/1", retrieved=seen),
           "provider": add_evidence(db, fid, home, status="CONFIRMED", origin="provider", claim="Parte del proveedor: baja.",
                                    source="api-football", url=None, retrieved=seen)}
    packet_evidence = [
        {"id": ids["injury"], "kind": "injury", "claim": INJURY, "side": "home", "status": "CONFIRMED", "origin": "web",
         "tier": "media", "source": "sport.es", "url": "https://www.sport.es/es/noticias/1"},
        {"id": ids["doubt"], "kind": "doubtful", "claim": DOUBT, "side": "away", "status": "PROBABLE", "origin": "web",
         "tier": "media", "source": "marca.com", "url": "https://www.marca.com/1"},
        {"id": ids["rumour"], "kind": "news", "claim": RUMOUR, "side": "home", "status": "RUMOR", "origin": "web",
         "tier": "unknown", "source": "rumours.example", "url": "https://rumours.example/1"},
        {"id": ids["provider"], "kind": "injury", "claim": "Parte del proveedor: baja.", "side": "home",
         "status": "CONFIRMED", "origin": "provider", "tier": "provider", "source": "api-football", "url": None}]
    body = {**(content or CONTENT), "evidence": packet_evidence}
    packet = int(scalar(db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
        "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s) RETURNING id",
        (fid, AT, AT + timedelta(minutes=1), "c" * 64, Jsonb(body), ["stats"]))))
    kickoff = scalar(db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)))
    db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, packet_id) "
               "VALUES (%s, %s, 'final', %s, %s, %s, 'ok', %s)",
               (fid, kickoff.date(), RUN_AT - timedelta(minutes=12), RUN_AT - timedelta(minutes=10), kickoff, packet))
    return fid, packet, ids


def S(text: str, *refs: str) -> dict[str, Any]:  # noqa: N802 - a constructor
    return {"text": text, "refs": list(refs)}


def answer(ids: dict[str, int]) -> dict[str, Any]:
    """A narrative that passes every check against the reading of ``CONTENT`` and its forecast."""
    inj, rum = f"E:{ids['injury']}", f"E:{ids['rumour']}"
    return {
        "es": {
            "summary": [S("Partido de la Premier League, jornada 9.", "P:fixture"),
                        S("PrediGol ve como más probable la victoria del Manchester United, con un 50 % sin calibrar.",
                          "P:forecast.1X2")],
            "context": [S("Manchester United es 4.º y está en la zona de plazas internacionales.", "P:stakes.home")],
            "data": [S("Manchester United suma 2,0 puntos por partido en sus últimos 5 y Liverpool 2,6.", "P:form.home",
                       "P:form.away"),
                     S("Lisandro Martínez es baja importante del Manchester United.", "P:absences.home", inj)],
            "market": [S("El mercado da un 42 % a la victoria de Liverpool, según 11 casas.", "P:market.1X2")],
            "risks": [S("Las alineaciones aún no están confirmadas.", "P:lineups"),
                      S("Hay un rumor sin confirmar sobre el portero titular del Manchester United.", "P:evidence", rum)],
            "conclusion": [S("Lo más probable según PrediGol es la victoria del Manchester United (50 %, sin calibrar).",
                             "P:forecast.1X2")],
        },
        "en": {
            "summary": [S("A Premier League match, round 9.", "P:fixture"),
                        S("PrediGol sees a Manchester United win as the most likely result, at 50 % uncalibrated.",
                          "P:forecast.1X2")],
            "context": [S("Manchester United are 4th, in the international places.", "P:stakes.home")],
            "data": [S("Manchester United average 2.0 points per match over their last 5, Liverpool 2.6.", "P:form.home",
                       "P:form.away"),
                     S("Lisandro Martínez is an important absence for Manchester United.", "P:absences.home", inj)],
            "market": [S("The market gives a Liverpool win 42 %, from 11 bookmakers.", "P:market.1X2")],
            "risks": [S("The line-ups are not confirmed yet.", "P:lineups"),
                      S("There is an unconfirmed rumour about Manchester United's first-choice goalkeeper.", "P:evidence",
                        rum)],
            "conclusion": [S("PrediGol's most likely outcome is a Manchester United win (50 %, uncalibrated).",
                             "P:forecast.1X2")],
        },
        "news": [
            {"id": ids["injury"], "headline_es": "Lisandro Martínez, baja por lesión",
             "headline_en": "Lisandro Martínez out injured", "claim_en": "Lisandro Martínez is out injured for this match."},
            {"id": ids["doubt"], "headline_es": "Mohamed Salah, en duda", "headline_en": "Mohamed Salah a doubt",
             "claim_en": "According to Marca, Mohamed Salah is doubtful with discomfort in his ankle."},
            {"id": ids["rumour"], "headline_es": "Rumor sobre el portero titular",
             "headline_en": "A rumour about the goalkeeper",
             "claim_en": "It is said that the first-choice goalkeeper did not travel with the team."},
        ],
    }


def run(db: psycopg.Connection[Any], model: Model, *, monthly: str = "30", mode: str = "on") -> un.RunReport:
    return un.run(db, SETTINGS, at=RUN_AT, monthly=Decimal(monthly), mode=mode, ledger=user_budget.UserUsageLedger(shared(db)),
                  provider=(model, MODEL))


def client(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, *, mode: str, role: str = "USER") -> TestClient:
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1")
    monkeypatch.setenv(forecast_service.USERS_SWITCH, "1")
    monkeypatch.setenv(news_service.USERS_SWITCH, "1")
    monkeypatch.setenv(reading_service.NARRATIVE_SWITCH, mode)
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def narrative(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, fid: int, *, mode: str, role: str = "USER",
              preview: bool = False) -> dict[str, Any] | None:
    r = client(db, monkeypatch, mode=mode, role=role).get(
        f"/api/v1/matches/{fid}/reading" + ("?preview=shadow" if preview else ""))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["sections"], "the facts are always there"
    shown: dict[str, Any] | None = data["narrative"]
    return shown


def count(db: psycopg.Connection[Any], table: str) -> int:
    return int(scalar(db.execute(f"SELECT count(*) FROM {table}")))


def test_a_validated_narrative_is_stored_and_shown_only_for_its_own_reading(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, packet, ids = match(db, world, seed)
    model = Model(answer(ids))
    usage_before = count(db, "ai.usage")
    report = run(db, model)
    assert report.counts["ok"] == 1 and report.counts["errors"] == 0, report.counts
    assert len(model.asked) == 1
    sent = model.asked[0].user
    assert "Parte del proveedor" not in sent, "a provider's report never reaches the call"
    for never in ("best_odds", "Bet365", "dixon_coles", "1810", "edge_vs_market"):
        assert never not in sent, never
    row = db.execute("SELECT status, packet_id, data_at, content, cost_usd, usage_ids FROM ai.user_narratives "
                     "WHERE fixture_id = %s", (fid,)).fetchone()
    assert row is not None and row[0] == "ok" and row[1] == packet and row[2] == AT
    assert [s["key"] for s in row[3]["es"]] == list(un.SECTIONS) and row[4] > 0 and len(row[5]) == 1
    assert count(db, "ai.usage") == usage_before, "nothing in Intelligence's ledger"
    spent = db.execute("SELECT purpose, tier, cost_usd FROM ai.user_usage WHERE fixture_id = %s", (fid,)).fetchall()
    assert len(spent) == 1 and spent[0][0] == "user_narrative" and spent[0][1] == "bulk" and spent[0][2] == row[4]
    langs = db.execute("SELECT lang, count(*) FROM ai.evidence_translations WHERE evidence_id = ANY(%s) GROUP BY lang "
                       "ORDER BY lang", ([ids["injury"], ids["doubt"], ids["rumour"]],)).fetchall()
    assert langs == [("en", 3), ("es", 3)]

    shown = narrative(db, monkeypatch, fid, mode="on")
    assert shown is not None and shown["version"] == "user-narrative-v1"
    assert [s["key"] for s in shown["es"]] == list(un.SECTIONS) and [s["key"] for s in shown["en"]] == list(un.SECTIONS)
    assert shown["es"][5]["sentences"][0]["refs"] == ["P:forecast.1X2"]
    assert shown["data_at"].startswith(AT.isoformat()[:16])
    assert narrative(db, monkeypatch, fid, mode="shadow") is None, "in shadow readers keep the facts"
    assert narrative(db, monkeypatch, fid, mode="shadow", role="SUPER_ADMIN", preview=True) is not None
    assert narrative(db, monkeypatch, fid, mode="off") is None

    news = client(db, monkeypatch, mode="on").get(f"/api/v1/matches/{fid}/news").json()["data"]["items"]
    confirmed = next(i for i in news if i["status"] == "CONFIRMED")
    assert confirmed["headline_es"] == "Lisandro Martínez, baja por lesión"
    assert confirmed["claims"][0]["text_en"] == "Lisandro Martínez is out injured for this match."
    hidden = client(db, monkeypatch, mode="shadow").get(f"/api/v1/matches/{fid}/news").json()["data"]["items"]
    assert all(i["headline_es"] is None and i["claims"][0]["text_en"] is None for i in hidden)

    # a newer packet changes the reading: the narrative written from the old one is not shown any more
    newer = {**CONTENT, "lineups": {"confirmed": True}}
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
               (fid, AT + timedelta(minutes=5), AT + timedelta(minutes=6), "d" * 64, Jsonb(newer), ["stats"]))
    assert narrative(db, monkeypatch, fid, mode="on") is None, "never a narrative of another reading"


def test_a_refused_narrative_leaves_the_facts_with_its_reasons_and_is_never_paid_for_again(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, _, ids = match(db, world, seed)
    bad = answer(ids)
    bad["es"]["conclusion"][0]["text"] = "La victoria del Manchester United es segura (50 %, sin calibrar)."
    worse = copy.deepcopy(bad)
    worse["en"]["market"][0]["text"] = "The market gives a Liverpool win 42 %, from 11 bookmakers: value."
    model = Model(bad, worse)
    report = run(db, model)
    assert report.counts["rejected"] == 1 and len(model.asked) == 2, report.counts
    assert "YOUR PREVIOUS ANSWER WAS REFUSED" in model.asked[1].user and "forbidden phrase" in model.asked[1].user
    row = db.execute("SELECT status, content, rejected, attempts, array_length(usage_ids, 1) FROM ai.user_narratives "
                     "WHERE fixture_id = %s", (fid,)).fetchone()
    assert row is not None and row[0] == "rejected" and row[1] is None and row[3] == 2 and row[4] == 2
    assert any("forbidden phrase" in p["why"] for p in row[2])
    assert count(db, "ai.user_usage") >= 2
    assert narrative(db, monkeypatch, fid, mode="on") is None, "the reader keeps the structured reading"
    assert db.execute("SELECT count(*) FROM ai.evidence_translations WHERE evidence_id = %s", (ids["injury"],)).fetchone() \
        == (2,), "a translation that passed its own checks is kept"
    again = run(db, Model())  # a model with no answer: asking it would fail the match
    assert again.counts["already_answered"] == 1 and again.counts["errors"] == 0


def test_a_provider_failure_is_recorded_and_tried_again_at_the_next_run(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, _, ids = match(db, world, seed)
    first = run(db, Model(ProviderError("timeout", "the provider did not answer in 90 s")))
    assert first.counts["failed"] == 1
    assert scalar(db.execute("SELECT status FROM ai.user_narratives WHERE fixture_id = %s", (fid,))) == "failed"
    second = run(db, Model(answer(ids)))
    assert second.counts["ok"] == 1
    statuses = [r[0] for r in db.execute("SELECT status FROM ai.user_narratives WHERE fixture_id = %s ORDER BY id", (fid,))]
    assert statuses == ["failed", "ok"]


def test_nothing_is_spent_without_the_readers_budget_and_the_owner_hears_of_each_threshold_once(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    match(db, world, seed)
    zero = run(db, Model(), monthly="0")
    assert zero.counts["user_over_budget"] == 1 and count(db, "ai.user_narratives") == 0
    assert run(db, Model(), mode="off").status == "off"
    db.execute("INSERT INTO ai.user_usage (at, purpose, tier, provider, model, cost_usd, status) "
               "VALUES (%s, 'user_narrative', 'bulk', 'anthropic', %s, 30, 'ok')", (RUN_AT - timedelta(hours=1), MODEL))
    spent = run(db, Model(), monthly="30")
    assert spent.counts["user_over_budget"] == 1 and spent.alerts == [50, 70, 85, 95, 100]
    keys = [r[0] for r in db.execute("SELECT dedup_key FROM audit.notifications WHERE kind = 'ai_user_budget' ORDER BY id")]
    assert keys == [f"ai_user_budget:2026-10:{t}" for t in (50, 70, 85, 95, 100)]
    assert run(db, Model(), monthly="30").alerts == [], "each threshold once a month"
    assert count(db, "ai.user_narratives") == 0


def test_the_intelligence_budget_reads_the_same_with_and_without_the_readers_spend(db: psycopg.Connection[Any]) -> None:
    before = budget(db, at=RUN_AT, settings=SETTINGS).as_json()
    db.execute("INSERT INTO ai.user_usage (at, purpose, tier, provider, model, cost_usd, status) "
               "VALUES (%s, 'user_narrative', 'bulk', 'anthropic', %s, 25, 'ok')", (RUN_AT - timedelta(hours=2), MODEL))
    assert budget(db, at=RUN_AT, settings=SETTINGS).as_json() == before
    readers = user_budget.user_budget(db, at=RUN_AT, monthly=Decimal(30))
    assert readers.spent_today == Decimal(25) and readers.state == "EXHAUSTED", "1.5 times the day's pace is spent"


def test_a_run_writes_the_readers_tables_and_nothing_else(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    _, _, ids = match(db, world, seed)
    stats = ("SELECT relid::regclass::text, n_tup_ins + n_tup_upd + n_tup_del FROM pg_stat_xact_user_tables "
             "WHERE n_tup_ins + n_tup_upd + n_tup_del > 0")
    before = dict(db.execute(stats).fetchall())
    assert run(db, Model(answer(ids))).counts["ok"] == 1
    after = dict(db.execute(stats).fetchall())
    changed = {t for t, n in after.items() if n != before.get(t, 0)}
    assert changed <= {"ai.user_narratives", "ai.user_usage", "ai.evidence_translations", "audit.notifications"}, changed
    assert {"ai.user_narratives", "ai.user_usage", "ai.evidence_translations"} <= changed


def test_the_job_records_its_run_in_the_ledger(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(reading_service.NARRATIVE_SWITCH, "shadow")
    with psycopg.connect(migrated_database) as conn:
        report = un.run_job(conn, settings=SETTINGS)
        row = conn.execute("SELECT id, status, notes FROM raw.ingestion_runs WHERE job_type = 'user_narrative' "
                           "ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None and row[1] == "completed" and row[2].startswith(report.status)
        conn.execute("DELETE FROM raw.ingestion_runs WHERE id = %s", (row[0],))
        conn.commit()
