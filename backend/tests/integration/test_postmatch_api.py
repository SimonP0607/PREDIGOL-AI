"""Postpartido over HTTP (plan UX, B4): what a finished match did to what the reader saved and to PrediGol's published picks - a real database,
the transaction rolled back.

The match (``knowledge_world``): home 2-1, finished, settled. Its picks:

    W  1X2 Home      published  win     post-mortem pm-v6: won  - a man sent off (against the other side), an early goal, the chances
    L  OU Under 2.5  published  loss    post-mortem pm-v6: lost - the early goal and a penalty against it (class NORMAL_VARIANCE)
    C  BTTS Yes      published  win     post-mortem pm-v6 says lost: written before the result was corrected - not used
    N  1X2 Away      published  loss    no post-mortem yet
    P  BTTS No       published  -       not settled yet (a post-mortem that says lost is not used while it waits)
    S  1X2 Draw      shadow     loss    post-mortem pm-v6 - only in the owner's preview

Reader A saved W (from the pick) and Over 2.5 (from the market); reader B saved Away. «Criterio de terminado: un partido terminado explica
resultado, liquidación, cierre del mercado y pronóstico frente a resultado» - the result and the forecast are their own answers (knowledge,
forecast); this one is the settlement of what was saved and why each published pick ended as it did.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.security import optional_principal
from fbi.api.services import knowledge as knowledge_service
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.knowledge_world import KICKOFF, NOW, SETTLED, World
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration

JUDGED = {"verdict", "loss_class", "decision_quality", "quality", "review_verdict", "review_decision", "clv", "price_move", "answers",
          "evidence", "close_odds", "text", "roles", "review_id", "decision_id", "class", "MERECIDO", "VARIANZA"}
"""What a post-mortem judges or keeps for the owner: never a key, never a word of a reader's answer."""


class Match:
    def __init__(self, w: World) -> None:
        self.w = w
        self.fid = w.match(KICKOFF, goals=(2, 1))
        self.picks: dict[str, int] = {}
        self.users: dict[str, int] = {}

    def pick(self, name: str, market: str, selection: str, line: float, result: str | None, *, status: str = "qualified") -> int:
        pick = self.w.pick(self.fid, market, selection, line, result=result, profit=1.1 if result == "win" else -1.0)
        if status != "shadow":
            self.w.cur.execute("UPDATE picks.picks SET status = %s, qualification = '{\"qualified\": true}'::jsonb WHERE id = %s",
                               (status, pick))
        self.picks[name] = pick
        return pick

    def postmortem(self, market: str, selection: str, line: float, outcome: str, causes: list[dict[str, Any]], *,
                   loss_class: str | None = None, verdict: str = "MERECIDO", p_close: float | None = 0.52) -> None:
        self.w.cur.execute(
            "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, causes, answers, "
            "evidence, market_key, selection, line, roles, review_decision, review_verdict, loss_class, odds, close_odds, p_model, p_market, "
            "p_close, price_move, clv) VALUES (NULL, %s, %s, 'pm-v6', %s, 'GOOD', %s, %s, %s, '{}'::jsonb, %s, %s, %s, ARRAY['daily_pick'], "
            "'APPROVE', 'approved_won', %s, 2.1, 1.95, 0.55, 0.5, %s, 0.03, 0.04)",
            (self.fid, SETTLED + timedelta(hours=10), outcome, verdict, Jsonb(causes),
             Jsonb({"suerte_o_decision": verdict, "aprendizaje": "MERECIDO: nada que cambiar"}), market, selection, line, loss_class,
             p_close))

    def user(self, name: str) -> int:
        uid = int(scalar(self.w.cur.execute(
            "INSERT INTO auth.users (email, display_name, password_hash) VALUES (%s, %s, '$argon2id$x') RETURNING id",
            (f"postmatch-{name}@test.local", name))))
        self.users[name] = uid
        return uid

    def save(self, user: str, market: str, selection: str, line: float, *, status: str, profit: float | None,
             pick: str | None = None) -> None:
        self.w.cur.execute(
            "INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, pick_id, odds, snapshot, saved_at, status, "
            "profit_units, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s, 2.100, '{}', %s, %s, %s, %s)",
            (self.users[user], self.fid, market, selection, line, "predigol_pick" if pick else "market",
             self.picks[pick] if pick else None, KICKOFF - timedelta(hours=2), status, profit,
             None if status == "PENDING" else SETTLED))


RED = {"code": "red_card", "minute": 60, "side": "away", "effect": "for", "text": "Roja al visitante en el 60' (a favor de la selección)"}
EARLY_FOR = {"code": "early_goal", "minute": 12, "side": "home", "effect": "for", "text": "Gol temprano (home) en el 12'"}
XG = {"code": "xg_supported", "xg_home": 1.87, "xg_away": 0.91, "score": "2-1", "effect": "for", "text": "xG 1.87-0.91: el juego respaldaba"}
EARLY_AGAINST = {"code": "early_goal", "minute": 12, "side": "home", "effect": "against", "text": "Gol temprano (home) en el 12'"}
PENALTY = {"code": "penalty_scored", "minute": 70, "side": "away", "effect": "against", "text": "Penalti convertido (away) en el 70'"}


@pytest.fixture()
def match(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> Iterator[Match]:
    monkeypatch.delenv(knowledge_service.USERS_SWITCH, raising=False)
    m = Match(World(db, seed))
    m.pick("W", "1X2", "Home", 0, "win")
    m.pick("L", "OU", "Under", 2.5, "loss")
    m.pick("C", "BTTS", "Yes", 0, "win")
    m.pick("N", "1X2", "Away", 0, "loss")
    m.pick("P", "BTTS", "No", 0, None)
    m.pick("S", "1X2", "Draw", 0, "loss", status="shadow")
    m.postmortem("1X2", "Home", 0, "won", [XG, EARLY_FOR, RED, {"code": "invented_code", "effect": "for", "text": "x"}])
    m.postmortem("OU", "Under", 2.5, "lost", [PENALTY, EARLY_AGAINST], loss_class="NORMAL_VARIANCE", verdict="VARIANZA")
    m.postmortem("BTTS", "Yes", 0, "lost", [EARLY_AGAINST], loss_class="MODEL_ERROR", verdict="ERROR")
    m.postmortem("1X2", "Draw", 0, "lost", [RED], loss_class="NORMAL_VARIANCE", verdict="VARIANZA")
    m.postmortem("BTTS", "No", 0, "lost", [EARLY_AGAINST], loss_class="NORMAL_VARIANCE", verdict="VARIANZA")
    m.user("a")
    m.user("b")
    m.save("a", "1X2", "Home", 0, status="WIN", profit=1.1, pick="W")
    m.save("a", "OU", "Over", 2.5, status="WIN", profit=0.95)
    m.save("b", "1X2", "Away", 0, status="LOSS", profit=-1.0)
    set_clock(FrozenClock(NOW))
    yield m
    set_clock(SystemClock())


def client(db: psycopg.Connection[Any], user_id: int, role: str = "USER") -> TestClient:
    app = create_app()
    who = principal(role, user_id=user_id)
    app.dependency_overrides[optional_principal] = lambda: who
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def postmatch(c: TestClient, fid: int, **params: Any) -> Any:
    r = c.get(f"/api/v1/matches/{fid}/postmatch", params=params)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def by_pick(data: Any, m: Match) -> dict[str, dict[str, Any]]:
    names = {v: k for k, v in m.picks.items()}
    return {names[p["pick_id"]]: p for p in data["published"]}


def keys_of(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in keys_of(v)}
    if isinstance(value, list):
        return {k for v in value for k in keys_of(v)}
    return set()


def test_each_published_pick_says_how_it_ended_and_why(match: Match) -> None:
    body = postmatch(client(match.w.db, match.users["a"]), match.fid)
    assert body["status"] == "ok"
    data = body["data"]
    assert (data["version"], data["finished"]) == ("postmatch-v1", True)
    picks = by_pick(data, match)
    assert set(picks) == {"W", "L", "C", "N", "P"}, "the shadow pick is the owner's preview only"
    w = picks["W"]
    assert (w["result"], w["analysed"], Decimal(w["p_model"]), Decimal(w["p_close"])) == ("win", True, Decimal("0.55"), Decimal("0.52"))
    assert [c["code"] for c in w["causes"]] == ["red_card", "early_goal", "xg_supported"], "the most telling first; an unknown code left out"
    assert w["causes"][0] == {"code": "red_card", "effect": "for", "minute": 60, "side": "away", "n": None, "cards": None,
                              "referee_avg": None, "xg_home": None, "xg_away": None, "score": None}
    assert w["causes"][2]["xg_home"] == 1.87 and w["causes"][2]["score"] == "2-1"
    lost = picks["L"]
    assert lost["result"] == "loss" and [c["code"] for c in lost["causes"]] == ["penalty_scored", "early_goal"]
    stale = picks["C"]
    assert (stale["result"], stale["analysed"], stale["causes"], stale["p_close"]) == ("win", False, [], None), \
        "a post-mortem that saw another outcome than the settlement's is not used"
    assert (picks["N"]["analysed"], picks["N"]["causes"]) == (False, [])


def test_a_reader_sees_only_what_they_saved_with_its_settlement(match: Match) -> None:
    mine = postmatch(client(match.w.db, match.users["a"]), match.fid)["data"]["saved"]
    assert [(s["market_key"], s["selection"], s["status"], Decimal(s["profit_units"])) for s in mine] == [
        ("1X2", "Home", "WIN", Decimal("1.1")), ("OU", "Over", "WIN", Decimal("0.95"))]
    assert mine[0]["origin"] == "predigol_pick" and mine[0]["pick_id"] == match.picks["W"]
    theirs = postmatch(client(match.w.db, match.users["b"]), match.fid)["data"]
    assert [(s["selection"], s["status"]) for s in theirs["saved"]] == [("Away", "LOSS")]
    assert theirs["published"] == postmatch(client(match.w.db, match.users["a"]), match.fid)["data"]["published"], \
        "the published picks and their why are the same for every reader"


def test_nothing_the_post_mortem_judges_reaches_a_reader(match: Match) -> None:
    for preview in (False, True):
        params = {"preview": "shadow"} if preview else {}
        role = "SUPER_ADMIN" if preview else "USER"
        body = postmatch(client(match.w.db, match.users["a"], role), match.fid, **params)
        found = keys_of(body) & JUDGED
        assert not found, f"keys of what a post-mortem judges in the answer: {found}"
        text = json.dumps(body)
        for word in ("MERECIDO", "VARIANZA", "NORMAL_VARIANCE", "MODEL_ERROR", "approved_won", "a favor de la selección", "respaldaba",
                     "aprendizaje", "intel."):
            assert word not in text, word


def test_the_owners_preview_adds_the_shadow_pick(match: Match) -> None:
    owner = client(match.w.db, match.users["a"], "SUPER_ADMIN")
    picks = by_pick(postmatch(owner, match.fid, preview="shadow")["data"], match)
    assert set(picks) == {"W", "L", "C", "N", "P", "S"} and picks["S"]["status"] == "shadow"
    r = client(match.w.db, match.users["a"]).get(f"/api/v1/matches/{match.fid}/postmatch", params={"preview": "shadow"})
    assert r.status_code == 403


def test_a_match_with_nothing_published_or_saved_and_one_not_over(match: Match) -> None:
    bare = match.w.match(KICKOFF - timedelta(days=1), home=2, away=3, goals=(0, 0))
    data = postmatch(client(match.w.db, match.users["b"]), bare)["data"]
    assert (data["finished"], data["saved"], data["published"]) == (True, [], [])
    later = match.w.match(NOW + timedelta(days=1), home=2, away=3, goals=None, status="NS", group="scheduled")
    data = postmatch(client(match.w.db, match.users["b"]), later)["data"]
    assert (data["finished"], data["published"]) == (False, [])
    assert client(match.w.db, match.users["b"]).get("/api/v1/matches/987654321/postmatch").status_code == 404


def test_the_knowledge_switch_hides_it_too(match: Match, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(knowledge_service.USERS_SWITCH, "0")
    body = postmatch(client(match.w.db, match.users["a"]), match.fid)
    assert (body["status"], body["data"]) == ("not_available", None)
    owner = postmatch(client(match.w.db, match.users["a"], "SUPER_ADMIN"), match.fid, preview="shadow")
    assert owner["status"] == "ok" and owner["data"]["published"]


def test_a_pending_settlement_is_not_explained_yet(match: Match) -> None:
    picks = by_pick(postmatch(client(match.w.db, match.users["a"]), match.fid)["data"], match)
    assert (picks["P"]["result"], picks["P"]["analysed"], picks["P"]["causes"]) == (None, False, [])
