"""The readers' chronicle (plan UX, A11 and UX-025) in a real database, with a model that answers what each test needs (no network).

A validated chronicle is stored with its translations and its cost in the readers' own ledger, and shown only while the story it
was written from is the story the data tell - to readers with the switch on, to the Admin Console's preview in shadow -; the
market, the line-ups or a newer packet with the same story do not hide it, a new absence or a new result does; a match without the
last results of both sides has no story and is not written; a refused one leaves the structured reading, its reasons recorded and
never paid for again; nothing is spent without the readers' budget; PrediGol Intelligence's budget reads the same with and without
the readers' spend; a run writes the readers' tables and nothing else. The transaction is rolled back (each match runs in a
savepoint of it)."""

from __future__ import annotations

import copy
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count as counter
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


HOME_RESULTS = ((2, 1, "home", "Mainz"), (0, 0, "away", "Brighton"), (1, 3, "home", "Tottenham"))
AWAY_RESULTS = ((3, 0, "away", "Chelsea"), (2, 2, "home", "Everton"), (1, 0, "away", "Newcastle"))
MEETINGS = [{"goals_home_side": 2, "goals_away_side": 2, "days_ago": 190, "home_side_was": "home",
             "competition": "Premier League"},
            {"goals_home_side": 0, "goals_away_side": 1, "days_ago": 380, "home_side_was": "away",
             "competition": "Premier League"}]
STORY: dict[str, Any] = {
    **CONTENT,
    "fixture": {**CONTENT["fixture"], "competition_tier": 1},
    "absences": {"home": {"players": [{"name": "Lisandro Martínez", "key": True, "type": "Missing Fixture",
                                       "reason": "Hamstring Injury"},
                                      {"name": "Tom Heaton", "key": False, "type": "Questionable", "reason": "Knock"}]},
                 "away": {"players": []}},
    "h2h": {**CONTENT["h2h"], "meetings": MEETINGS},
}
"""The packet of a match with a story: the reading's blocks, two named absences with the provider's reasons and two meetings."""


_teams = counter(880_001)
_matches = counter(990_001)


def history(db: psycopg.Connection[Any], seed: Seed, *, home: int = 3, away: int = 3) -> None:
    """The last results of both sides, settled before the packet's moment: a past match for each, against an opponent of its own."""
    for team, results in ((seed.home_team_id, HOME_RESULTS[:home]), (seed.away_team_id, AWAY_RESULTS[:away])):
        for i, (gf, ga, venue, opponent) in enumerate(results, start=1):
            rival = int(scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                          (next(_teams), opponent))))
            kickoff = AT - timedelta(days=7 * i)
            home_id, away_id = (team, rival) if venue == "home" else (rival, team)
            goals = (gf, ga) if venue == "home" else (ga, gf)
            fid = int(scalar(db.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                (next(_matches), seed.season_id, home_id, away_id, kickoff))))
            db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, %s, %s, %s)",
                       (fid, *goals, kickoff + timedelta(hours=2)))


def match(db: psycopg.Connection[Any], world: World, seed: Seed, *, content: dict[str, Any] | None = None,  # noqa: F811
          past: bool = True, kind: str = "final", ko: datetime | None = None) -> tuple[int, int, dict[str, int]]:
    """A match with PrediGol's forecast, the last results of both sides, a packet with a market, two absences, two meetings and
    three news items from the web (and a provider's report that must never reach the call), and a pass of Intelligence on it.
    Returns the match, the packet and the items' ids."""
    fid = world.fixture(ko) if ko is not None else world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    world.write(fid)
    if past:
        history(db, seed)
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
    body = {**(content or STORY), "evidence": packet_evidence}
    packet = int(scalar(db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
        "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s) RETURNING id",
        (fid, AT, AT + timedelta(minutes=1), "c" * 64, Jsonb(body), ["stats"]))))
    kickoff = scalar(db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)))
    db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, packet_id) "
               "VALUES (%s, %s, %s, %s, %s, %s, 'ok', %s)",
               (fid, kickoff.date(), kind, RUN_AT - timedelta(minutes=12), RUN_AT - timedelta(minutes=10), kickoff, packet))
    return fid, packet, ids


def S(text: str, *refs: str) -> dict[str, Any]:  # noqa: N802 - a constructor
    return {"text": text, "refs": list(refs)}


def answer(ids: dict[str, int]) -> dict[str, Any]:
    """A chronicle that passes every check against the story of ``STORY`` and its news."""
    inj, doubt, rum = f"E:{ids['injury']}", f"E:{ids['doubt']}", f"E:{ids['rumour']}"
    return {
        "es": {
            "summary": [S("Partido de la Premier League, jornada 9: el Manchester United se juega las plazas europeas y el "
                          "Liverpool, el título.", "P:fixture", "P:stakes.home", "P:stakes.away")],
            "home": [S("El Manchester United viene de ganar 2-1 al Mainz en casa, tras empatar 0-0 con el Brighton y caer 1-3 "
                       "ante el Tottenham.", "P:results.home.1", "P:results.home.2", "P:results.home.3"),
                     S("Lisandro Martínez, titular habitual, es baja por una lesión en el isquiotibial y Tom Heaton es duda por "
                       "un golpe.", "P:absences.home.1", "P:absences.home.2"),
                     S("Según sport.es, la baja de Lisandro Martínez está confirmada.", inj),
                     S("Bruno Fernandes es su máximo goleador, con 4 goles en 810 minutos.", "P:dossier.players.home"),
                     S("En casa suma 3 victorias y 1 empate en 4 partidos.", "P:dossier.teams.home")],
            "away": [S("El Liverpool llega tras ganar 3-0 en el campo del Chelsea, empatar 2-2 con el Everton y vencer 1-0 al "
                       "Newcastle.", "P:results.away.1", "P:results.away.2", "P:results.away.3"),
                     S("Mohamed Salah, su máximo goleador, suma 7 goles en 900 minutos.", "P:dossier.players.away"),
                     S("Según marca.com, Mohamed Salah es duda por unas molestias en el tobillo.", doubt),
                     S("Fuera de casa suma 2 victorias, 1 empate y 1 derrota en 4 partidos.", "P:dossier.teams.away")],
            "h2h": [S("Los últimos cruces fueron un 2-2 hace 6 meses y una victoria del Liverpool por 0-1 hace 12 meses.",
                      "P:h2h.meeting.1", "P:h2h.meeting.2"),
                    S("En el balance de 8 cruces hay 2 victorias del Manchester United, 3 empates y 3 del Liverpool.",
                      "P:h2h")],
            "risks": [S("Hay un rumor sin confirmar sobre el portero titular del Manchester United.", rum),
                      S("Tom Heaton es duda para el Manchester United.", "P:absences.home.2")],
        },
        "en": {
            "summary": [S("A Premier League match in round 9: Manchester United play for the European places and Liverpool for "
                          "the title.", "P:fixture", "P:stakes.home", "P:stakes.away")],
            "home": [S("Manchester United come off a 2-1 home win over Mainz, after a 0-0 draw at Brighton and a 1-3 defeat to "
                       "Tottenham.", "P:results.home.1", "P:results.home.2", "P:results.home.3"),
                     S("Lisandro Martínez, a regular starter, is out with a hamstring injury and Tom Heaton is a doubt after a "
                       "knock.", "P:absences.home.1", "P:absences.home.2"),
                     S("According to sport.es, Lisandro Martínez's absence is confirmed.", inj),
                     S("Bruno Fernandes is its top scorer, with 4 goals in 810 minutes.", "P:dossier.players.home"),
                     S("At home it has 3 wins and 1 draw in 4 matches.", "P:dossier.teams.home")],
            "away": [S("Liverpool arrive after a 3-0 win at Chelsea, a 2-2 draw with Everton and a 1-0 win at Newcastle.",
                       "P:results.away.1", "P:results.away.2", "P:results.away.3"),
                     S("Mohamed Salah, its top scorer, has 7 goals in 900 minutes.", "P:dossier.players.away"),
                     S("According to marca.com, Mohamed Salah is a doubt with discomfort in his ankle.", doubt),
                     S("Away from home it has 2 wins, 1 draw and 1 defeat in 4 matches.", "P:dossier.teams.away")],
            "h2h": [S("The last meetings were a 2-2 draw 6 months ago and a Liverpool win by 0-1 12 months ago.",
                      "P:h2h.meeting.1", "P:h2h.meeting.2"),
                    S("Over 8 meetings there are 2 Manchester United wins, 3 draws and 3 Liverpool wins.", "P:h2h")],
            "risks": [S("There is an unconfirmed rumour about Manchester United's first-choice goalkeeper.", rum),
                      S("Tom Heaton is a doubt for Manchester United.", "P:absences.home.2")],
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


def run(db: psycopg.Connection[Any], model: Model, *, monthly: str = "30", mode: str = "on",
        later: timedelta = timedelta(0)) -> un.RunReport:
    return un.run(db, SETTINGS, at=RUN_AT + later, monthly=Decimal(monthly), mode=mode, ledger=user_budget.UserUsageLedger(shared(db)),
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


def newer_packet(db: psycopg.Connection[Any], fid: int, minutes: int, **changes: Any) -> None:
    """A packet rebuilt ``minutes`` after the first, with the same blocks but the ones ``changes`` replaces."""
    content = db.execute("SELECT content FROM ai.match_packets WHERE fixture_id = %s ORDER BY as_of DESC, id DESC LIMIT 1",
                         (fid,)).fetchone()
    assert content is not None
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
               "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
               (fid, AT + timedelta(minutes=minutes), AT + timedelta(minutes=minutes + 1), f"{minutes:x}" * 64,
                Jsonb({**content[0], **changes}), ["stats"]))


def test_a_validated_chronicle_is_stored_and_shown_only_while_its_story_is_the_same(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, packet, ids = match(db, world, seed)
    model = Model(answer(ids))
    usage_before = count(db, "ai.usage")
    report = run(db, model)
    assert report.counts["ok"] == 1 and report.counts["errors"] == 0, report.counts
    assert len(model.asked) == 1
    sent = model.asked[0].user
    assert "Mainz" in sent and "Hamstring Injury" in sent and "Lisandro Martínez" in sent, "the story is what it is told"
    assert "Parte del proveedor" not in sent, "a provider's report never reaches the call"
    for never in ("best_odds", "Bet365", "dixon_coles", "poisson", "1810", "edge_vs_market", "p_fair", "P:forecast", "P:market"):
        assert never not in sent, never
    row = db.execute("SELECT status, packet_id, data_at, content, cost_usd, usage_ids, reading_hash, version "
                     "FROM ai.user_narratives WHERE fixture_id = %s", (fid,)).fetchone()
    assert row is not None and row[0] == "ok" and row[1] == packet and row[2] == AT and row[7] == "user-narrative-v2"
    assert [s["key"] for s in row[3]["es"]] == list(un.SECTIONS) and row[4] > 0 and len(row[5]) == 1
    assert row[3]["sources"] == [{"name": "sport.es"}, {"name": "marca.com"}, {"name": "rumours.example"}]
    basis = reading_service.reading_basis(db, fid, at=RUN_AT)
    assert row[6] == reading_service.story_hash(db, basis), "the chronicle is tied to the story, not to a packet"
    assert count(db, "ai.usage") == usage_before, "nothing in Intelligence's ledger"
    spent = db.execute("SELECT purpose, tier, cost_usd FROM ai.user_usage WHERE fixture_id = %s", (fid,)).fetchall()
    assert len(spent) == 1 and spent[0][0] == "user_narrative" and spent[0][1] == "bulk" and spent[0][2] == row[4]
    langs = db.execute("SELECT lang, count(*) FROM ai.evidence_translations WHERE evidence_id = ANY(%s) GROUP BY lang "
                       "ORDER BY lang", ([ids["injury"], ids["doubt"], ids["rumour"]],)).fetchall()
    assert langs == [("en", 3), ("es", 3)]

    shown = narrative(db, monkeypatch, fid, mode="on")
    assert shown is not None and shown["version"] == "user-narrative-v2"
    assert [s["key"] for s in shown["es"]] == list(un.SECTIONS) and [s["key"] for s in shown["en"]] == list(un.SECTIONS)
    assert len(shown["es"][1]["sentences"]) == 5 and shown["es"][1]["sentences"][0]["refs"][0] == "P:results.home.1"
    assert shown["sources"] == [{"name": "sport.es"}, {"name": "marca.com"}, {"name": "rumours.example"}]
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

    # the data are rebuilt all day: a newer packet with the same story (the line-ups, the market moved) keeps the chronicle
    moved = {**STORY["market"], "selections": [{**s, "p_fair": 0.3} for s in STORY["market"]["selections"]]}
    newer_packet(db, fid, 5, lineups={"confirmed": True}, market=moved)
    still = narrative(db, monkeypatch, fid, mode="on")
    assert still is not None and still["es"] == shown["es"], "a newer packet with the same story: the same chronicle"
    # ... and a new absence is a new story: never the chronicle of another one
    three = {"home": {"players": [*STORY["absences"]["home"]["players"], {"name": "Harry Maguire", "key": True,
                                                                         "type": "Missing Fixture", "reason": "Calf Injury"}]},
             "away": {"players": []}}
    newer_packet(db, fid, 8, absences=three)
    assert narrative(db, monkeypatch, fid, mode="on") is None, "never a chronicle of another story"


def test_a_result_settled_after_the_chronicle_makes_a_new_story(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, _, ids = match(db, world, seed)
    assert run(db, Model(answer(ids))).counts["ok"] == 1
    assert narrative(db, monkeypatch, fid, mode="on") is not None
    late = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
        "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
        (next(_matches), seed.season_id, seed.home_team_id, seed.away_team_id, AT - timedelta(hours=3)))))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 1, 1, %s)",
               (late, AT + timedelta(minutes=3)))
    newer_packet(db, fid, 2)  # the packet built before the result was settled, as_of AT + 2 min: the same story
    assert narrative(db, monkeypatch, fid, mode="on") is not None
    newer_packet(db, fid, 6)  # built after: the result is in the story
    assert narrative(db, monkeypatch, fid, mode="on") is None


def test_a_match_without_the_last_results_of_both_sides_has_no_story_and_no_call(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, _, _ = match(db, world, seed, past=False)
    history(db, seed, home=3, away=1)
    model = Model()
    report = run(db, model)
    assert report.counts["thin"] == 1 and not model.asked and count(db, "ai.user_narratives") == 0, report.counts
    assert narrative(db, monkeypatch, fid, mode="on") is None


def test_any_pass_of_intelligence_is_enough_to_be_narrated(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    _, _, ids = match(db, world, seed, kind="first")
    report = run(db, Model(answer(ids)))
    assert report.counts["ok"] == 1, report.counts


def test_the_money_goes_to_the_nearest_match_first_and_the_rest_waits_for_the_next_run(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    monkeypatch.setattr(un, "MAX_PER_RUN", 1)
    far, _, ids_far = match(db, world, seed)
    near, _, ids_near = match(db, world, seed, past=False, ko=AT + timedelta(hours=25))
    one = run(db, Model(answer(ids_near)))
    assert one.counts["ok"] == 1 and one.counts["left_for_next_run"] == 1, one.counts
    assert db.execute("SELECT fixture_id FROM ai.user_narratives").fetchall() == [(near,)]
    two = run(db, Model(answer(ids_far)))
    assert two.counts["ok"] == 1, two.counts
    assert sorted(r[0] for r in db.execute("SELECT fixture_id FROM ai.user_narratives").fetchall()) == sorted([far, near])


def test_a_refused_chronicle_leaves_the_facts_with_its_reasons_and_is_never_paid_for_again(
        db: psycopg.Connection[Any], world: World, seed: Seed, monkeypatch: pytest.MonkeyPatch, frozen: None) -> None:  # noqa: F811
    fid, _, ids = match(db, world, seed)
    bad = answer(ids)
    bad["es"]["summary"][0]["text"] = "Partido de la Premier League, jornada 9: el resultado es seguro para el Manchester United."
    worse = copy.deepcopy(bad)
    worse["en"]["risks"][1]["text"] = "Tom Heaton is a doubt for Manchester United: value."
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
    soon = run(db, Model())
    assert soon.counts["due"] == 0, "a refusal is not tried again for two hours"
    again = run(db, Model(), later=un.RECHECK_AFTER + timedelta(minutes=1))  # a model with no answer: asking it would fail the match
    assert again.counts["already_answered"] == 1 and again.counts["errors"] == 0


def test_a_chronicle_that_says_more_than_the_facts_allow_is_refused(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    _, _, ids = match(db, world, seed)
    long = answer(ids)
    for lang in ("es", "en"):
        long[lang]["h2h"] = long[lang]["h2h"] * 2  # four sentences where the facts allow two
    report = run(db, Model(long, copy.deepcopy(long)))
    assert report.counts["rejected"] == 1, report.counts
    why = [p["why"] for p in db.execute("SELECT rejected FROM ai.user_narratives").fetchone()[0]]  # type: ignore[index]
    assert any("at most 2" in w for w in why), why


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
