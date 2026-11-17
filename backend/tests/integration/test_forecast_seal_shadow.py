"""The stable seal (AD-B03, ``seal-v1``) written in shadow beside ``forecast-v1``, in a real database.

What production showed (16-nov-2026): the champion of a market takes the de-vigged consensus as an input, ``forecast-v1`` only takes one
captured in the last six hours, and the consensus of a match is captured a few times a day; so the pass six hours after a capture writes
the same model number UNCALIBRATED and the next capture makes it CALIBRATED again. Here: the shadow version keeps the seal while the
champion and a price within the window exist, records the price it used, writes nothing new when nothing changed, says ``needs_price``
when there has never been a price, is not written with the switch off, and cannot cost ``forecast-v1`` anything when it fails."""

from __future__ import annotations

from datetime import timedelta
from itertools import pairwise
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.forecasting import match_forecast as mf
from fbi.forecasting import seal
from tests.integration.test_match_forecast import AT, SHEET, World, world  # noqa: F401  (the fixture)

pytestmark = pytest.mark.integration

PARAMS = {"a": 0.0, "b": 0.5, "c": 0.5}


@pytest.fixture()
def shadow_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(seal.SWITCH, raising=False)  # the default in code: shadow


def labels(db: psycopg.Connection[Any], fid: int, version: str) -> list[tuple[Any, str, str, Any]]:
    """(known_at, calibration, basis, market_as_of) of each set of the 1X2, in time order."""
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT DISTINCT known_at, calibration, basis, market_as_of FROM models.match_forecasts "
                    "WHERE fixture_id = %s AND version = %s AND market_key = '1X2' AND selection = 'Home' ORDER BY known_at",
                    (fid, version))
        return [(r["known_at"], r["calibration"], r["basis"], r["market_as_of"]) for r in cur.fetchall()]


def flips(rows: list[tuple[Any, str, str, Any]]) -> int:
    return sum(1 for a, b in pairwise(rows) if a[1] != b[1])


def test_the_seal_stays_while_the_price_ages_and_forecast_v1_still_flips(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                        shadow_on: None) -> None:
    world.champion("1X2", "poisson", "logit2", PARAMS)
    fid = world.fixture()
    world.predict_all(fid, "poisson", only=("1X2",))
    captured = AT - timedelta(minutes=30)
    world.consensus(fid, "1X2", "0", {"Home": 0.45, "Draw": 0.28, "Away": 0.27}, as_of=captured)
    first = world.write(fid)  # the price is fresh: both calibrated
    assert first.calibrated == 1 and first.shadow is not None and first.shadow.calibrated == 1
    world.write(fid, AT + timedelta(hours=7))  # seven hours later: no price of the last six hours
    world.write(fid, AT + timedelta(hours=20))
    world.consensus(fid, "1X2", "0", {"Home": 0.46, "Draw": 0.28, "Away": 0.26}, as_of=AT + timedelta(hours=21))
    world.write(fid, AT + timedelta(hours=21, minutes=15))  # a new capture
    v1 = labels(db, fid, mf.VERSION)
    shadow = labels(db, fid, seal.SHADOW_VERSION)
    assert [r[1] for r in v1] == ["CALIBRATED", "UNCALIBRATED", "CALIBRATED"], "the alternation that UX saw, reproduced"
    assert v1[1][2] == "needs_price"
    assert flips(v1) == 2
    assert all(r[1] == "CALIBRATED" and r[2] == "champion" for r in shadow), "the champion and a price exist: the seal stays"
    assert flips(shadow) == 0
    assert shadow[0][3] == captured, "the price it used is kept with the reading (its age is known_at - market_as_of)"
    assert len(shadow) <= len(v1), "nothing new is written for the hours in which nothing changed"


def test_never_a_price_is_needs_price_in_both_and_a_price_past_the_window_too(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                            shadow_on: None) -> None:
    world.champion("1X2", "poisson", "logit2", PARAMS)
    fid = world.fixture()
    world.predict_all(fid, "poisson", only=("1X2",))
    report = world.write(fid)
    assert report.shadow is not None and report.shadow.uncalibrated == {"needs_price": 1}
    old = world.fixture()
    world.predict_all(old, "poisson", only=("1X2",))
    world.consensus(old, "1X2", "0", {"Home": 0.45, "Draw": 0.28, "Away": 0.27},
                    as_of=AT - seal.STABLE_MARKET_AGE - timedelta(minutes=1))
    world.write(old)
    assert [r[1:3] for r in labels(db, old, seal.SHADOW_VERSION)] == [("UNCALIBRATED", "needs_price")], \
        "a price older than the window is no price"


def test_without_a_champion_it_is_no_champion(db: psycopg.Connection[Any], world: World, shadow_on: None) -> None:  # noqa: F811
    fid = world.fixture()
    world.predict_all(fid, "poisson", only=("BTTS",))
    report = world.write(fid)
    assert report.shadow is not None and report.shadow.uncalibrated == {"no_champion": 1}


def test_the_shadow_is_not_written_with_the_switch_off(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(seal.SWITCH, "off")
    fid = world.fixture()
    world.predict_all(fid, "poisson")
    report = world.write(fid)
    assert report.markets_written == len(SHEET) and report.shadow is None
    assert labels(db, fid, seal.SHADOW_VERSION) == []
    assert "shadow" not in report.summary()


def test_a_defect_in_the_shadow_costs_forecast_v1_nothing(db: psycopg.Connection[Any], world: World, shadow_on: None,  # noqa: F811
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    real = mf._write_version

    def broken(conn: psycopg.Connection[Any], report: mf.MatchForecastReport, ids: list[int], **kw: Any) -> None:
        if kw["version"] == seal.SHADOW_VERSION:
            real(conn, report, ids, **kw)  # writes, then fails: the savepoint must take its rows back
            raise RuntimeError("boom")
        real(conn, report, ids, **kw)

    monkeypatch.setattr(mf, "_write_version", broken)
    fid = world.fixture()
    world.predict_all(fid, "poisson")
    report = world.write(fid)
    assert report.markets_written == len(SHEET) and report.shadow is None
    assert report.shadow_error is not None and "boom" in report.shadow_error and "failed" in report.summary()
    assert labels(db, fid, seal.SHADOW_VERSION) == [], "the shadow's rows went with its savepoint"
    assert len(labels(db, fid, mf.VERSION)) == 1


def test_forecast_v1_reads_back_only_its_own_rows(db: psycopg.Connection[Any], world: World, shadow_on: None) -> None:  # noqa: F811
    world.champion("1X2", "poisson", "logit2", PARAMS)
    fid = world.fixture()
    world.predict_all(fid, "poisson", only=("1X2",))
    world.consensus(fid, "1X2", "0", {"Home": 0.45, "Draw": 0.28, "Away": 0.27}, as_of=AT - timedelta(minutes=30))
    world.write(fid)
    stored = mf._read_stored(db, [fid], AT)
    shadow = mf._read_stored(db, [fid], AT, version=seal.SHADOW_VERSION)
    assert set(stored) == set(shadow) and all(v.calibration == "CALIBRATED" for v in shadow.values())
    with db.cursor() as cur:
        cur.execute("SELECT count(DISTINCT input_hash) FROM models.match_forecasts WHERE fixture_id = %s", (fid,))
        assert cur.fetchone() == (2,), "the version is part of each reading's fingerprint"
