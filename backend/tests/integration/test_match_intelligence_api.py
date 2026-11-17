"""C-01, the match's contract (AD-J02, IA-066), against a real database: the two projections served from what PrediGol already
stored - the forecast, the packet, the decision layer's shadow, the day's sets and the match's web items - and nothing private
in the public one."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.contracts.intelligence.match import MatchIntelligence, MatchIntelligencePrivate
from fbi.api.contracts.intelligence.projection import leaks
from fbi.api.deps import get_db
from fbi.api.switches import MATCH_INTELLIGENCE
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import AT, KO, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE, raise_server_exceptions=False)


def stored_match(db: psycopg.Connection[Any], world: World) -> int:  # noqa: F811
    """A match with a forecast (the total calibrated, the rest not), a packet, two shadow decisions and one web item."""
    fid = world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(minutes=40))
    world.write(fid)
    content = {"stakes": {"home": {"rank": 2, "rule": "stakes-v5", "zone": "europe", "gap_up": 3, "zone_above": "title",
                                   "gap_down": 4, "zone_below": None, "pressure": "europe", "remaining": 5, "settled": False}},
               "form": {"home": {"n": 5, "sequence": "WWDLW", "ppg": 2.0, "gf_pg": 1.8, "ga_pg": 1.0}}}
    db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
               "VALUES (%s, 'packet-v9', %s, %s, %s, %s)",
               (fid, AT - timedelta(minutes=10), AT - timedelta(minutes=10), hashlib.sha256(b"c01").hexdigest(), Jsonb(content)))
    for selection, state in (("Home", "RECHAZADO"), ("Away", "CAUTELA")):
        db.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
                   "selection, line, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, input_hash) "
                   "VALUES ('decision-v1', %s, 'T-24h', %s, %s, '1X2', %s, 0, 'dixon_coles', 2.10, 0.50, 0.48, 0.47, '[]', %s, "
                   "'PENDING', %s)", (AT - timedelta(minutes=5), fid, KO, selection, state, f"c01-{selection}"))
    db.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
               "selection, line, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, input_hash) "
               "VALUES ('decision-fam-v1', %s, 'T-24h', %s, %s, 'CORNERS', 'Over', 9.5, 'nb', 1.90, 0.55, 0.55, 0.50, '[]', "
               "'INVESTIGACION', 'PENDING', 'c01-fam')", (AT - timedelta(minutes=5), fid, KO))
    db.execute("INSERT INTO ai.evidence (fixture_id, kind, claim, origin, source_name, source_url, source_tier, published_at, "
               "retrieved_at, story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at) "
               "VALUES (%s, 'injury', 'El club confirmó la baja del portero para el partido del sábado.', 'web', "
               "'club.invalid', 'https://club.invalid/nota', 'club', %s, %s, 's-c01', %s, 0.9, 0.9, 'CONFIRMED', 'test', %s)",
               (fid, AT - timedelta(hours=5), AT - timedelta(hours=4), hashlib.sha256(b"e").hexdigest(), AT - timedelta(hours=4)))
    return fid


def url(fid: int, *, private: bool = False) -> str:
    return f"/api/v1/admin/intelligence/matches/{fid}/intelligence" if private else f"/api/v1/matches/{fid}/intelligence"


def test_the_public_route_answers_404_while_the_owner_keeps_it_off(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = stored_match(db, world)
    monkeypatch.delenv(MATCH_INTELLIGENCE, raising=False)
    answer = client(db, "USER").get(url(fid))
    assert answer.status_code == 404 and answer.json()["error"]["code"] == "not_found"
    assert "RECHAZADO" not in answer.text


def test_a_reader_gets_only_what_is_published_and_the_owner_gets_the_shadow(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = stored_match(db, world)
    monkeypatch.setenv(MATCH_INTELLIGENCE, "1")
    public = client(db, "USER").get(url(fid))
    assert public.status_code == 200, public.text
    data = public.json()["data"]
    MatchIntelligence.model_validate(data)
    assert data["projection"] == "public" and data["contract"] == "C-01"
    assert leaks(data, public_schema=MatchIntelligence.model_json_schema(mode="serialization"),
                 private_schema=MatchIntelligencePrivate.model_json_schema(mode="serialization")) == []
    for word in ("RECHAZADO", "CAUTELA", "raw_probability", "CORNERS", "decision-v1", "decision-fam-v1"):
        assert word not in public.text, word
    seals = {(f["market"], f["outcome"]): f["probability"]["calibration"] for f in data["probabilities"]["items"]}
    assert seals[("OU", "over")] == "calibrada" and seals[("1X2", "home")] == "sin_calibrar"
    assert len(seals) == 7
    assert data["selections"] == {"items": [], "missing_reason": "sin_publicados"}, "nothing was ever published"
    [home] = data["context"]["items"]
    assert (home["zone"], home["above"], home["below"]) == ("europe", {"zone": "title", "points": 3},
                                                           {"zone": "none", "points": 4})
    assert data["form"]["items"][0]["sequence"] == "WWDLW"
    [cited] = data["citations"]["items"]
    assert cited["confirmation"] == "oficial" and cited["source"]["url"] == "https://club.invalid/nota"
    assert data["official_lineup"]["missing_reason"] == "aun_no_disponible"
    assert data["scenarios"] == {"missing_reason": "no_entregado", "expected_piece": "AD-B02"}

    assert client(db, "USER").get(url(fid, private=True)).status_code == 403

    private = client(db, "SUPER_ADMIN").get(url(fid, private=True))
    assert private.status_code == 200, private.text
    owner = private.json()["data"]
    MatchIntelligencePrivate.model_validate(owner)
    assert owner["projection"] == "private"
    states = {s["selection"]: s["decision_state"] for s in owner["selections"]["items"]}
    assert states == {"Home": "RECHAZADO", "Away": "CAUTELA"}, "the pipeline's layer only: the families' row is research"
    assert all(s["public_state"] is None and not s["published"] for s in owner["selections"]["items"])
    home_figure = next(f for f in owner["probabilities"]["items"] if (f["market"], f["outcome"]) == ("1X2", "home"))
    assert home_figure["raw_probability"]["calibration"] == "sin_calibrar"
    assert owner["evidence"]["items"][0]["status"] == "CONFIRMED"
    assert owner["packet"]["version"] == "packet-v9"
    # the private one carries everything the public one does, unchanged
    for key, value in data.items():
        if key not in ("projection", "freshness", "probabilities"):
            assert json.dumps(owner[key], sort_keys=True) == json.dumps(value, sort_keys=True) or key == "selections", key


def test_an_unknown_match_is_not_found_in_either_projection(
        db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MATCH_INTELLIGENCE, "1")
    assert client(db, "USER").get(url(2**40)).status_code == 404
    assert client(db, "SUPER_ADMIN").get(url(2**40, private=True)).status_code == 404
