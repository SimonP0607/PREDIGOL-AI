"""AD-J05, AD-J07, AD-J09 (IA-132 to IA-134) against a real database: C-04's private route reads parlay-v6's kept rows and parlay-v5's
history, C-08's route reads the evaluations of one match, both refuse a reader; and with FBI_MATCH_INTELLIGENCE on the public ``state``
of ``/parlays/{kind}`` and ``featured_analyses`` of ``/home`` travel - «ninguno» and ``sin_publicados`` on a database with nothing
published - while with it off neither key exists."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.api.contracts.intelligence.parlays import ParlaySetStatePrivate
from fbi.api.contracts.intelligence.post_evaluation import PostMatchEvaluation
from fbi.api.services import featured, parlay_states
from fbi.evalpass import store
from fbi.tracking.parlay_v6_shadow import CHAINS
from tests.integration.conftest import Seed
from tests.integration.test_selection_evaluation import client, world

pytestmark = pytest.mark.integration


def kept_parlays(db: psycopg.Connection[Any], seed: Seed) -> tuple[int, Any]:
    now = db.execute("SELECT now()").fetchone()[0]  # type: ignore[index]
    day = db.execute("SELECT (now() AT TIME ZONE 'America/Bogota')::date").fetchone()[0]  # type: ignore[index]
    ko = now + timedelta(hours=5)
    fid = int(db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                         "VALUES (880301, %s, %s, %s, %s) RETURNING id",
                         (seed.season_id, seed.home_team_id, seed.away_team_id, ko)).fetchone()[0])  # type: ignore[index]
    pid = int(db.execute(
        "INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, max_legs, n_legs, n_candidates, window_from, window_to, "
        "combined_odds, p_joint, p_joint_se, p_joint_low, p_product, p_market_joint, fair_odds, accumulated_margin, expected_value, "
        "expected_value_low, expected_log_growth, simulations, seed, known_at) VALUES (%s, 'parlay-v6', 'daily', %s, 'built', 3, 2, 3, "
        "%s, %s, 3.42, 0.3061, 0.0015, 0.2712, 0.3192, 0.2754, 3.2669, 0.0581, 0.0469, -0.0725, 0.0001, 100000, 7, %s) RETURNING id",
        (CHAINS, day, now - timedelta(hours=1), now + timedelta(hours=20), now - timedelta(minutes=30))).fetchone()[0])  # type: ignore[index]
    for n, (market, selection, line) in enumerate((("1X2", "Home", 0), ("OU", "Over", 2.5)), start=1):
        db.execute("INSERT INTO intel.parlay_v6_legs (parlay_id, leg_no, chain_key, confirmed_id, confirmed_at, fixture_id, kickoff_at, "
                   "market_key, selection, line, odds, n_bookmakers, p_model, p_low, p_market, source, source_id) VALUES "
                   "(%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, 1.85, 5, 0.58, 0.54, 0.53, 'intel.decisions_v2', 1)",
                   (pid, n, f"{CHAINS}|{fid}|{market}|{selection}|{line:.2f}", now - timedelta(hours=1), fid, ko, market, selection, line))
    db.execute("INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, none_reason, max_legs, n_legs, n_candidates, "
               "window_from, window_to, inputs, known_at) VALUES (%s, 'parlay-v6', 'multiday', %s, 'none', 'un_solo_candidato', 3, 0, 1, "
               "%s, %s, %s, %s)", (CHAINS, day, now - timedelta(hours=1), now + timedelta(hours=72), Jsonb({"refused": {"sin_valor": 4}}),
                                   now - timedelta(minutes=30)))
    db.execute("INSERT INTO picks.parlays (kind, day, source, rule_version, status, min_legs, max_legs, window_from, window_to, created_at) "
               "VALUES ('daily', %s, 'evaluation', 'parlay-v5', 'LOST', 5, 5, %s, %s, %s)",
               (day, now - timedelta(hours=1), now + timedelta(hours=23), now - timedelta(hours=1)))
    return pid, day


def test_c04_private_reads_parlay_v6_beside_the_product_and_parlay_v5(db: psycopg.Connection[Any], seed: Seed) -> None:
    pid, day = kept_parlays(db, seed)
    owner, reader = client(db, "SUPER_ADMIN"), client(db, "USER")
    assert reader.get("/api/v1/admin/intelligence/parlays").status_code == 403
    got = owner.get("/api/v1/admin/intelligence/parlays", params={"from": day.isoformat(), "to": day.isoformat()})
    assert got.status_code == 200, got.text
    c04 = ParlaySetStatePrivate.model_validate(got.json()["data"])
    assert c04.contract == "C-04" and c04.projection == "private"
    by = {(c.source, c.kind): c for c in c04.parlays.items}
    live = by[("en_vivo", "daily")]
    assert live.status == "ninguno" and live.rule.version == "parlay-v5" and live.published  # nothing qualified: «ninguno», said
    built = by[("intel.parlays_v6", "daily")]
    assert (built.stored_id, built.status, built.result, len(built.legs.items)) == (pid, "armado", "pendiente", 2)
    assert not built.published and built.rule.max_legs == 3
    none = by[("intel.parlays_v6", "multiday")]
    assert none.status == "ninguno" and none.none_detail == "un_solo_candidato" and none.refused[0].code == "sin_valor"
    assert [(h.kind, h.source, h.status, h.parlays) for h in c04.v5_history.items] == [("daily", "evaluation", "LOST", 1)]
    assert owner.get("/api/v1/admin/intelligence/parlays", params={"from": "2026-01-01", "to": "2026-03-01"}).status_code == 422


def test_c08_answers_the_owner_for_one_match_and_refuses_a_reader(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    store.write(db, store.evaluations(db, [w["fixture"]]), code_version="test")
    owner, reader = client(db, "SUPER_ADMIN"), client(db, "USER")
    path = f"/api/v1/admin/intelligence/evaluations/{w['fixture']}"
    assert reader.get(path).status_code == 403
    got = owner.get(path)
    assert got.status_code == 200, got.text
    c08 = PostMatchEvaluation.model_validate(got.json()["data"])
    assert c08.contract == "C-08" and c08.match.id == w["fixture"] and c08.notice_es == "Un acierto no valida el mercado."
    by = {s.market: s for s in c08.selections.items}
    assert set(by) == {"OU", "1X2"} and by["OU"].price.verdict == "MERECIDO"
    assert [f.status for f in by["OU"].evidence.facts.items] == ["contradicho", "sostenido", "sostenido"]
    assert by["1X2"].parity == "difiere" and by["1X2"].anticipated.taken
    assert all(s.validation_cell.startswith("decision-v1|core|") for s in c08.selections.items)
    assert owner.get("/api/v1/admin/intelligence/evaluations/987654321").status_code == 404


def test_the_public_fields_travel_only_with_the_switch(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    reader = client(db, "USER")
    monkeypatch.setattr(parlay_states, "match_intelligence_on", lambda: False)
    monkeypatch.setattr(featured, "match_intelligence_on", lambda: False)
    off_parlay, off_home = reader.get("/api/v1/parlays/daily"), reader.get("/api/v1/home")
    assert off_parlay.status_code == 200 and off_home.status_code == 200, (off_parlay.text, off_home.text)
    assert "state" not in off_parlay.json()["data"] and "featured_analyses" not in off_home.json()["data"]
    monkeypatch.setattr(parlay_states, "match_intelligence_on", lambda: True)
    monkeypatch.setattr(featured, "match_intelligence_on", lambda: True)
    state = reader.get("/api/v1/parlays/multiday").json()["data"]["state"]
    assert state["projection"] == "public" and [c["status"] for c in state["parlays"]["items"]] == ["ninguno"]
    home = reader.get("/api/v1/home").json()["data"]["featured_analyses"]
    assert home["contract"] == "C-12" and home["items"] == {"items": [], "missing_reason": "sin_publicados"}
