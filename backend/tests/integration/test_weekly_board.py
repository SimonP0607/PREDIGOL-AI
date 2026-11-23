"""PM-12-01 on a real database: the weekly board reads, for each finished match with PrediGol's forecast, the market's newest Shin set
before kick-off and the provider's newest forecast before kick-off (never one taken after it), scores them on the same matches, is
appended once per week, and the owner's route answers 404 while its switch is off and the stored board with it on."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest

from fbi.api.problem import ApiError
from fbi.api.services import evaluation_board as svc
from fbi.core.calendar import local_day
from fbi.coverage import model_segments as sg
from fbi.coverage import weekly_board as wb
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_model_segments import competition, forecast, played

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 21, 12, tzinfo=UTC)
WEEK = (date(2026, 11, 9), date(2026, 11, 15))
_ids = count(94_000)


def consensus(db: psycopg.Connection[Any], fid: int, as_of: datetime, p: tuple[float, float, float], book: int) -> None:
    for sel, q in zip(("Home", "Draw", "Away"), p, strict=True):
        db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, "
                   "n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', %s, 0, %s, 'shin', %s, 4, 1.05, 2.0, %s)",
                   (fid, sel, as_of, q, book))


def provider(db: psycopg.Connection[Any], seed: Seed, fid: int, observed: datetime, pct: tuple[int, int, int]) -> None:
    db.execute("INSERT INTO core.provider_predictions (fixture_id, observed_at, percent_home, percent_draw, percent_away, payload_hash, "
               "normalizer_version) VALUES (%s, %s, %s, %s, %s, %s, 'n')", (fid, observed, *pct, seed.payload_hash))


def test_the_board_of_a_week_and_the_owners_route(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    _comp, cs = competition(db)
    teams = (seed.home_team_id, seed.away_team_id)
    played_in_week = since = with_provider = 0
    for k in range(40):
        fid, ko = played(db, cs, teams, k, (1, 0) if k % 2 else (0, 0))
        y = 0 if k % 2 else 1
        p = [0.2, 0.2, 0.2]
        p[y] = 0.6
        forecast(db, seed, fid, ko - timedelta(hours=3), (p[0], p[1], p[2]))
        consensus(db, fid, ko - timedelta(hours=40), (0.9, 0.05, 0.05), seed.bookmaker_id)   # older
        consensus(db, fid, ko - timedelta(hours=1), (0.4, 0.3, 0.3), seed.bookmaker_id)     # the newest before kick-off
        consensus(db, fid, ko + timedelta(minutes=5), (0.98, 0.01, 0.01), seed.bookmaker_id)  # after kick-off: never read
        if k % 4 == 0:
            provider(db, seed, fid, ko - timedelta(hours=6), (45, 45, 10))
            provider(db, seed, fid, ko + timedelta(hours=1), (1, 1, 98))                      # after kick-off: never read
        played_in_week += WEEK[0] <= local_day(ko) <= WEEK[1]
        since += local_day(ko) >= sg.FIRST_DAY
        with_provider += k % 4 == 0 and local_day(ko) >= sg.FIRST_DAY

    rep = wb.report(db, at=AT, week=WEEK)
    one = next(m for m in rep["markets"] if m["market"] == "1X2")
    cum = one["cumulative"]
    assert since >= 20 and with_provider >= 5
    assert cum["matches"] == since and cum["common"] == with_provider
    assert cum["with_each"] == {"modelo": since, "mercado": since, "proveedor": with_provider}
    by = {s["source"]: s for s in cum["sources"]}
    # k % 4 == 0: a draw (0-0), so the newest Shin set says 0.3 and the provider 0.45 for what happened
    assert by["mercado"]["log_loss"]["value"] == pytest.approx(-math.log(0.3), abs=1e-6)
    assert by["proveedor"]["log_loss"]["value"] == pytest.approx(-math.log(0.45), abs=1e-6)
    assert one["week"]["matches"] == played_in_week and rep["period_from"] == "2026-11-09"
    words = {(d["b"], d["metric"]): (d["verdict"], d["n"]) for d in cum["pairs"]}
    assert words[("mercado", "log_loss")] == ("insuficiente" if since < wb.MIN_PAIRED else "modelo_mejor", since)

    report_id = wb.store(db, rep, code_version="c")
    assert report_id is not None and wb.store(db, rep, code_version="c") is None

    monkeypatch.delenv("FBI_EVALUATION_BOARD", raising=False)
    with pytest.raises(ApiError):
        svc.board(db)
    monkeypatch.setenv("FBI_EVALUATION_BOARD", "1")
    got = svc.build(db)
    assert got.weekly is not None and got.weekly.report_id == report_id and got.weekly.period_to == WEEK[1]
    assert got.weekly.markets[0].cumulative.common == with_provider and got.segments is None

    seg = sg.report(db, at=AT, start=sg.FIRST_DAY)
    seg_id = sg.store(db, seg, code_version="c")
    after = svc.build(db)
    assert after.segments is not None and after.segments.report_id == seg_id and after.segments.reproduced is True
    mine = [c for c in after.segments.competitions if c.competition_id == _comp]
    assert mine and mine[0].verdict == "insuficiente" and mine[0].n == since and mine[0].name == "L"
    assert scalar(db.execute("SELECT count(*) FROM analytics.evaluation_reports WHERE kind = 'weekly'")) >= 1
