"""The download of the published picks (plan PM, PM-14-08) against a database: the file is the table, only the published, behind
its two switches, and its calibration carries its uncertainty."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import transparency_export, transparency_picks
from fbi.api.switches import TRANSPARENCY, TRANSPARENCY_EXPORT
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from tests.integration.signed_in import SAME_SITE, signed_in

from .test_transparency import AT, TZ, World, world  # noqa: F401  (the fixture)


def client(db: psycopg.Connection[Any], role: str, monkeypatch: pytest.MonkeyPatch, *, page: str | None,
           export: str | None) -> TestClient:
    for name, value in ((TRANSPARENCY, page), (TRANSPARENCY_EXPORT, export)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def table_of(db: psycopg.Connection[Any]) -> list[Any]:
    seen: list[Any] = []
    cursor: str | None = None
    while True:
        page = transparency_picks.published_picks(db, tz=TZ, limit=7, cursor=cursor, at=AT)
        seen.extend(page.data)
        cursor = page.meta.next_cursor
        if cursor is None:
            return seen


def test_the_file_is_the_table_row_for_row(db: psycopg.Connection[Any], world: World) -> None:  # noqa: F811
    shown = table_of(db)
    file = transparency_export.all_picks(db, tz=TZ, at=AT)
    assert file == shown and len(file) == 36, "the same picks, in the same order, as the table pages through"
    lines = list(csv.reader(io.StringIO(transparency_export.picks_csv(file, tz=TZ, language="en")[1:])))
    assert len(lines) == 37
    head = lines[0]
    assert [r[head.index("published_odds")] for r in lines[1:]] == [str(p.odds) for p in shown]
    assert [r[head.index("home")] for r in lines[1:]] == [p.home for p in shown]


def test_never_a_pick_that_was_not_published(db: psycopg.Connection[Any], world: World) -> None:  # noqa: F811
    file = transparency_export.all_picks(db, tz=TZ, at=AT)
    assert max(p.odds for p in file) < 6, "the evaluation items (all at 6.00) are not in it"
    assert len(file) == transparency_picks.published_picks(db, tz=TZ, limit=1, at=AT).meta.total


def test_the_calibration_says_how_sure_it_is(db: psycopg.Connection[Any], world: World) -> None:  # noqa: F811
    cal = transparency_export.calibration(db, tz=TZ, at=AT)
    assert cal["min_sample"] == 25 and cal["picks_won_or_lost"] >= 25
    hit = cal["hit_rate"]
    assert hit is not None and hit["interval_95"]["from"] <= hit["observed"] <= hit["interval_95"]["to"]
    for b in cal["bins"]:
        assert b["n"] >= cal["min_bin"] and b["interval_95"]["from"] <= b["observed"] <= b["interval_95"]["to"]


def test_the_download_is_off_until_its_switch_and_follows_the_page(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    set_clock(FrozenClock(AT))
    try:
        url = "/api/v1/transparency/export"
        assert client(db, "USER", monkeypatch, page="1", export=None).get(url).status_code == 404, "the switch is off"
        assert client(db, "USER", monkeypatch, page=None, export="1").get(url).status_code == 404, "the page is closed"
        assert client(db, "USER", monkeypatch, page=None, export="1").get("/api/v1/auth/me").json()["transparency_export"] is True
        assert client(db, "USER", monkeypatch, page="1", export=None).get("/api/v1/auth/me").json()["transparency_export"] is False
        assert client(db, "USER", monkeypatch, page=None, export=None).get(f"{url}?preview=shadow").status_code == 403
        owner = client(db, "SUPER_ADMIN", monkeypatch, page=None, export=None).get(f"{url}?preview=shadow")
        assert owner.status_code == 200, "the owner reviews it before opening it"
        opened = client(db, "USER", monkeypatch, page="1", export="1")
        csv_file = opened.get(url)
        assert csv_file.status_code == 200 and csv_file.headers["content-type"].startswith("text/csv")
        assert "attachment" in csv_file.headers["content-disposition"] and csv_file.headers["cache-control"] == "no-store"
        assert csv_file.content == owner.content, "the owner's review is the readers' file"
        body = opened.get(f"{url}?format=json").json()
        assert body["count"] == 36 and len(body["picks"]) == 36 and "calibration" in body
        assert "roi" not in json.dumps(body).lower().replace("return on investment", "")
        calib = opened.get(f"{url}?part=calibration")
        assert calib.status_code == 200 and calib.text.splitlines()[0].lstrip("﻿").startswith("range_from")
        assert opened.get(f"{url}?format=xml").status_code == 422
    finally:
        set_clock(SystemClock())
