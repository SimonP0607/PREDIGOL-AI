"""PrediGol's forecast of a match over HTTP (plan F5): who sees it, what a user is never shown, and the three answers - forecast, value,
pick - kept apart where the Admin Console puts them side by side."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import forecast as service
from fbi.forecasting import match_forecast as mf
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.integration.test_match_forecast import AT, CUT, KO, SHEET, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], role: str, monkeypatch: pytest.MonkeyPatch, *, users: bool) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1" if users else "0")
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def url(fid: int, preview: bool = False) -> str:
    return f"/api/v1/matches/{fid}/forecast" + ("?preview=shadow" if preview else "")


def forecast_world(world: World, *, champion: bool = True) -> int:  # noqa: F811
    """A match that both goal models priced, whose total has a champion calibrator and a recent price."""
    fid = world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    if champion:
        world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
        world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(minutes=40))
    world.write(fid)
    return fid


def markets_of(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["market"]: m for m in body["data"]["forecast"]["data"]}


def test_a_user_gets_nothing_until_the_owner_decides_and_then_only_the_forecast(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = forecast_world(world)

    off = client(db, "USER", monkeypatch, users=False).get(url(fid))
    assert off.status_code == 200
    assert off.json()["status"] == "not_available" and off.json()["data"] is None and off.json()["reason"], "said, not left blank"

    on = client(db, "USER", monkeypatch, users=True).get(url(fid))
    assert on.status_code == 200
    body = on.json()
    assert body["status"] == "ok" and body["data"]["fixture_id"] == fid
    assert body["data"]["value"] is None and body["data"]["picks"] is None, "no value and no pick beside it"
    assert body["data"]["forecast"]["status"] == "ok"
    markets = markets_of(body)
    assert list(markets) == ["1X2", "OU", "BTTS"], "the result first, then the total, then both teams to score"
    assert {m: markets[m]["calibration"] for m in markets} == {"1X2": "UNCALIBRATED", "OU": "CALIBRATED", "BTTS": "UNCALIBRATED"}
    assert {m: markets[m]["basis"] for m in markets} == {"1X2": "no_champion", "OU": "champion", "BTTS": "no_champion"}
    for market, m in markets.items():
        outcomes = m["outcomes"]
        assert sum(float(o["probability"]) for o in outcomes) == pytest.approx(1.0, abs=1e-5), market
        assert [o["selection"] for o in outcomes] == list(next(s for (k, _), s in SHEET.items() if k == market))
        assert sum(1 for o in outcomes if o["likely"]) == 1 and max(outcomes, key=lambda o: float(o["probability"]))["likely"]
        assert all(o["low"] is not None and float(o["low"]) <= float(o["probability"]) <= float(o["high"]) for o in outcomes)
        assert all(o["fair_odds"] is None and o["model_probability"] is None for o in outcomes), (
            "a user is never shown a number that reads as odds to take")
    assert all(m["model"] is None for m in markets.values()), "an internal model's name is not a reader's word (A9)"
    assert {o["selection"] for o in markets["1X2"]["outcomes"] if o["likely"]} == {"Home"}
    assert body["meta"]["data_as_of"] is not None

    # the preview is not a user's to ask for, whether or not users see the forecast
    for users in (False, True):
        refused = client(db, "USER", monkeypatch, users=users).get(url(fid, preview=True))
        assert refused.status_code == 403, "403 for an account without the shadow-preview permission"
        assert "fair_odds" not in refused.text and "Home" not in refused.text


def test_without_its_line_the_switch_is_on_since_a9_and_an_unreadable_value_hides(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    """Plan UX, A9: the owner approved showing the forecast; ``FBI_FORECAST_USERS=0`` hides it again without a deploy, and a
    value the switch cannot read hides it too (showing less is the safer reading of a line someone wrote)."""
    fid = forecast_world(world)
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    reader = TestClient(app, headers=SAME_SITE)
    monkeypatch.delenv(service.USERS_SWITCH, raising=False)
    assert reader.get(url(fid)).json()["status"] == "ok"
    for value, status in (("0", "not_available"), ("off", "not_available"), ("si", "not_available"), ("", "ok"),
                          ("ON", "ok")):
        monkeypatch.setenv(service.USERS_SWITCH, value)
        assert reader.get(url(fid)).json()["status"] == status, value


def test_the_admin_preview_lays_the_forecast_beside_the_value_and_the_picks(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = forecast_world(world, champion=False)
    admin = client(db, "SUPER_ADMIN", monkeypatch, users=False)

    plain = admin.get(url(fid))  # without the preview the admin sees what a user would: the switch decides
    assert plain.json()["status"] == "not_available"

    body = admin.get(url(fid, preview=True)).json()
    assert body["status"] == "ok"
    data = body["data"]
    markets = markets_of(body)
    home = next(o for o in markets["1X2"]["outcomes"] if o["selection"] == "Home")
    assert float(home["probability"]) == pytest.approx(0.50) and home["likely"] is True
    assert float(home["fair_odds"]) == pytest.approx(2.0, abs=0.005), "1 / 0.50, admin only"
    assert float(home["model_probability"]) == pytest.approx(0.50)
    assert markets["1X2"]["model"] == "dixon_coles", "the owner's preview names the model that priced it"
    assert data["value"]["status"] == "empty" and data["value"]["code"] == "no_evaluation", "no price evaluated, so no value"
    assert data["picks"]["status"] == "empty" and data["picks"]["code"] == "no_pick", "and no pick: a forecast is not one"

    # the decision layer's own word about the same selection arrives in its own section, not inside the forecast
    kickoff = db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)).fetchone()
    assert kickoff is not None
    db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
        "model_name, odds, p_model, p_cal, p_market, edge_cal, ev_cal, filters, state, reasons, context_status, input_hash) "
        "VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', 'Home', 0, 'dixon_coles', 1.28, 0.80, 0.80, 0.77, 0.03, -0.0, %s, 'RECHAZADO', "
        "ARRAY['price too short'], 'PENDING', 'forecast-api')", (kickoff[0] - timedelta(hours=3), fid, kickoff[0], Jsonb([])))
    again = admin.get(url(fid, preview=True)).json()["data"]
    assert again["value"]["status"] == "ok"
    (row,) = again["value"]["data"]
    assert (row["market"], row["selection"], row["state"], float(row["odds"])) == ("1X2", "Home", "RECHAZADO", 1.28)
    assert row["reasons"] == ["price too short"]
    assert again["picks"]["status"] == "empty", "a rejected selection is not a pick, and the forecast did not make it one"
    assert [o["selection"] for o in again["forecast"]["data"][0]["outcomes"] if o["likely"]] == ["Home"]


def test_a_match_without_a_forecast_says_why(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    admin = client(db, "SUPER_ADMIN", monkeypatch, users=True)

    def why(fid: int) -> tuple[str, str, str | None]:
        data = admin.get(url(fid, preview=True)).json()["data"]["forecast"]
        return data["status"], data["code"], data["reason"]

    nothing = world.fixture()
    status, code, reason = why(nothing)
    assert (status, code) == ("not_available", "no_forecast_yet") and reason

    unfit = world.fixture()
    world.predict_all(unfit, "dixon_coles")
    world.data_class("PRODUCT_ONLY")
    world.write(unfit)
    assert why(unfit)[:2] == ("not_available", "data_not_fit")

    world.data_class("MODEL_READY")
    sick = world.fixture()
    world.predict_all(sick, "dixon_coles")
    world.quarantine(sick)
    world.write(sick)
    assert why(sick)[:2] == ("not_available", "quarantined")

    assert admin.get(url(999_999_999, preview=True)).status_code == 404
    assert client(db, "USER", monkeypatch, users=True).get(url(nothing)).json()["data"]["forecast"]["code"] == "no_forecast_yet"


def test_the_forecast_shown_is_the_newest_known_at_the_moment_asked(db: psycopg.Connection[Any], world: World) -> None:  # noqa: F811
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.write(fid)
    world.predict(fid, "dixon_coles", "OU", "2.5", {"Over": 0.70, "Under": 0.30}, cutoff=CUT + timedelta(hours=1))
    world.write(fid, AT + timedelta(hours=3))

    def over(at: Any) -> float:
        body = service.match_forecast(db, fid, preview=True, at=at).data
        assert body is not None
        (market,) = body.forecast.data
        return float(next(o.probability for o in market.outcomes if o.selection == "Over"))

    assert over(AT + timedelta(hours=1)) == pytest.approx(0.62), "what was said then"
    assert over(AT + timedelta(hours=4)) == pytest.approx(0.70), "and what was said later"
    assert not service.match_forecast(db, fid, preview=True, at=AT - timedelta(hours=1)).data.forecast.data  # type: ignore[union-attr]


def test_the_api_reads_what_the_worker_writes() -> None:
    assert service.VERSION == mf.VERSION
    assert service.NOT_FIT == mf.NOT_FIT
    assert set(service.MARKET_ORDER) == set(mf.FAMILIES), "every market the worker forecasts has a place in the page"
    assert service.USERS_SWITCH == "FBI_FORECAST_USERS"
