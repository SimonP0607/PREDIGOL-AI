"""Mis picks completo over HTTP (plan UX, B5, section 30) - a real database, the transaction rolled back.

Reader A (Bogotá, Spanish) saved 61 picks in two leagues - «Knowledge League» and «Copa Andina Ñandú» (whose teams are
«Atlético Medellín» and «Deportivo Ñandú») -:

    1X2   40 settled in Knowledge League (20 won and 20 lost at 2.00; four of them with their own price, 2.40, in the 2-3
          range; one of the won ones from a pick of PrediGol), and 2 pending in the coming days
    OU    12 settled in Copa Andina (won, lost, half won, half lost, pushed and voided, two of each, at 1.40 and 1.90)
    BTTS   7 pending in Copa Andina, at 3.50 and 6.00

with the closing consensus of some of the started matches (and, never read, one taken after kick-off, one of another
de-vig method and one of a match not played yet). Reader B saved picks on the same matches: A never sees them.

«Criterio de terminado: "Todo" completo y paginado, filtros y desglose iguales a consultas independientes, el aviso de muestra
visible y el CSV solo con datos propios.» Every figure here is checked against a query written in the test, not the service's.
"""

from __future__ import annotations

import csv
import dataclasses
import io
import math
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.security import MEMBERSHIP_READS, optional_principal
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.knowledge_world import KICKOFF, NOW, World
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration


class Reader:
    """Reader A's saved picks and what the test needs to check them."""

    def __init__(self, w: World) -> None:
        self.w = w
        cur = w.cur
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type) "
                    "VALUES (98975, 'Copa Andina Ñandú', 'Perú', 'league', 'club', 'domestic_league') RETURNING id")
        self.copa = int(scalar(cur))
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2034) RETURNING id", (self.copa,))
        self.copa_season = int(scalar(cur))
        cur.execute("SELECT competition_id FROM core.competition_seasons WHERE id = %s", (w.season,))
        self.league = int(scalar(cur))
        self.andean: list[int] = []
        for i, name in enumerate(("Atlético Medellín", "Deportivo Ñandú")):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (989760 + i, name))
            self.andean.append(int(scalar(cur)))
        self.users = {}
        for key, email in (("a", "b5-reader-a@test.local"), ("b", "b5-reader-b@test.local")):
            cur.execute("INSERT INTO auth.users (email, display_name, password_hash, timezone, language) VALUES "
                        "(%s, %s, '$argon2id$x', 'America/Bogota', 'es') RETURNING id", (email, key))
            self.users[key] = int(scalar(cur))
        self.ids: dict[str, list[int]] = {"1X2": [], "OU": [], "BTTS": []}

    def copa_match(self, kickoff: Any) -> int:
        self.w.n += 1
        self.w.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                           "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                           (9897500 + self.w.n, self.copa_season, self.andean[0], self.andean[1], kickoff))
        return int(scalar(self.w.cur))

    def save(self, user: str, fid: int, market: str, selection: str, line: float, *, odds: float | None, status: str = "PENDING",
             profit: float | None = None, user_odds: float | None = None, pick: int | None = None, saved: Any = None) -> int:
        kickoff = scalar(self.w.cur.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fid,)))
        self.w.cur.execute(
            "INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, pick_id, odds, user_odds, snapshot, "
            "saved_at, status, profit_units, settled_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '{}', %s, %s, %s, %s) RETURNING id",
            (self.users[user], fid, market, selection, line, "predigol_pick" if pick else "market", pick, odds, user_odds,
             saved or kickoff - timedelta(hours=3), status, profit, None if status == "PENDING" else kickoff + timedelta(hours=2)))
        record = int(scalar(self.w.cur))
        if user == "a":
            self.ids[market].append(record)
        return record


@pytest.fixture()
def reader(db: psycopg.Connection[Any], seed: Seed) -> Iterator[Reader]:
    w = World(db, seed)
    r = Reader(w)
    # 1X2 in Knowledge League: 20 matches in the past, Home and Away saved on each - one won and one lost
    for n in range(20):
        kickoff = KICKOFF - timedelta(days=n)
        fid = w.match(kickoff, goals=(1, 0))
        own = 2.4 if n < 2 else None  # four of them with the reader's own price, in the 2-3 range
        pick = w.pick(fid, "1X2", "Home", 0, odds=2.0, kickoff=kickoff) if n == 5 else None
        r.save("a", fid, "1X2", "Home", 0, odds=2.0, status="WIN", profit=1.0 if own is None else 1.4, user_odds=own, pick=pick)
        r.save("a", fid, "1X2", "Away", 0, odds=2.0, status="LOSS", profit=-1.0, user_odds=own)
        r.save("b", fid, "1X2", "Draw", 0, odds=3.1, status="LOSS", profit=-1.0)
        if n < 6:  # the closing consensus of six matches; the first also after kick-off and by another method
            w.quote(fid, "1X2", "Home", 0, 0.52, kickoff - timedelta(minutes=30))
            w.quote(fid, "1X2", "Home", 0, 0.55, kickoff - timedelta(minutes=20))
            w.quote(fid, "1X2", "Away", 0, 0.30, kickoff - timedelta(minutes=20))
            if n == 0:
                w.quote(fid, "1X2", "Home", 0, 0.99, kickoff + timedelta(minutes=5))
                w.quote(fid, "1X2", "Home", 0, 0.01, kickoff - timedelta(minutes=10), method="proportional")
    # 1X2 pending, in the coming days (one with a consensus that is not a close yet)
    for n in range(2):
        kickoff = NOW + timedelta(days=1 + n)
        fid = w.match(kickoff, goals=None, status="NS", group="scheduled", settled=None)
        r.save("a", fid, "1X2", "Home", 0, odds=1.6)
        w.quote(fid, "1X2", "Home", 0, 0.6, kickoff - timedelta(hours=1))
    # OU in Copa Andina: two of each settlement, at 1.40 (lt1.5) and 1.90 (1.5-2)
    plan = [("WIN", 0.4), ("WIN", 0.9), ("LOSS", -1.0), ("LOSS", -1.0), ("HALF_WIN", 0.2), ("HALF_WIN", 0.45),
            ("HALF_LOSS", -0.5), ("HALF_LOSS", -0.5), ("PUSH", 0.0), ("PUSH", 0.0), ("VOID", 0.0), ("VOID", 0.0)]
    for n, (status, profit) in enumerate(plan):
        fid = r.copa_match(KICKOFF - timedelta(days=30 + n))
        r.save("a", fid, "OU", "Over", 2.5, odds=1.4 if n % 2 == 0 else 1.9, status=status, profit=profit)
        r.save("b", fid, "OU", "Under", 2.5, odds=2.0, status="WIN", profit=1.0)
    # BTTS pending in Copa Andina, at 3.50 and 6.00
    for n in range(7):
        fid = r.copa_match(NOW + timedelta(days=3 + n))
        r.save("a", fid, "BTTS", "Yes", 0, odds=3.5 if n < 4 else 6.0)
    set_clock(FrozenClock(NOW))
    yield r
    set_clock(SystemClock())


def client(db: psycopg.Connection[Any], user_id: int, *, language: str = "es") -> TestClient:
    app = create_app()
    who = dataclasses.replace(principal("USER", user_id=user_id), timezone="America/Bogota", language=language)
    app.dependency_overrides[optional_principal] = lambda: who
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def walk(c: TestClient, **params: Any) -> tuple[list[dict[str, Any]], int]:
    """Every page of Mis picks under a filter, following the cursor: the records in order, and the total said."""
    records: list[dict[str, Any]] = []
    cursor: str | None = None
    total = -1
    for _ in range(100):
        r = c.get("/api/v1/me/picks", params={**params, "limit": 7, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        records.extend(body["data"])
        total = body["meta"]["total"]
        cursor = body["meta"].get("next_cursor")
        if not cursor:
            return records, total
    raise AssertionError("the cursor never ended")


def independent(db: psycopg.Connection[Any], user: int, where: str = "true", params: tuple[Any, ...] = ()) -> list[int]:
    """The reader's saved picks under a condition, by a query of this test - in the list's order."""
    rows = db.execute(
        "SELECT u.id FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id "
        "JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id "
        "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id "
        f"WHERE u.user_id = %s AND ({where}) ORDER BY f.kickoff_at DESC, u.id DESC", (user, *params)).fetchall()
    return [int(x[0]) for x in rows]


def test_every_filter_lists_exactly_the_records_an_independent_query_finds(db: psycopg.Connection[Any], reader: Reader) -> None:
    c = client(db, reader.users["a"])
    a = reader.users["a"]
    day = (KICKOFF - timedelta(days=3)).astimezone(ZoneInfo("America/Bogota")).date()
    cases: list[tuple[dict[str, Any], str, tuple[Any, ...]]] = [
        ({}, "true", ()),
        ({"result": "won"}, "u.status IN ('WIN', 'HALF_WIN')", ()),
        ({"result": "lost"}, "u.status IN ('LOSS', 'HALF_LOSS')", ()),
        ({"result": "push"}, "u.status = 'PUSH'", ()),
        ({"result": "void"}, "u.status = 'VOID'", ()),
        ({"result": "pending"}, "u.status = 'PENDING'", ()),
        ({"market": "OU"}, "u.market_key = 'OU'", ()),
        ({"competition": reader.copa}, "c.id = %s", (reader.copa,)),
        ({"origin": "predigol"}, "u.origin = 'predigol_pick'", ()),
        ({"origin": "mine"}, "u.origin = 'market'", ()),
        ({"band": "lt1.5"}, "COALESCE(u.user_odds, u.odds) < 1.5", ()),
        ({"band": "2-3"}, "COALESCE(u.user_odds, u.odds) >= 2 AND COALESCE(u.user_odds, u.odds) < 3", ()),
        ({"band": "5+"}, "COALESCE(u.user_odds, u.odds) >= 5", ()),
        ({"since": day.isoformat(), "until": day.isoformat()},
         "(f.kickoff_at AT TIME ZONE 'America/Bogota')::date = %s", (day,)),
        ({"q": "medellin"}, "c.id = %s", (reader.copa,)),  # «Atlético Medellín», found without its accent
        ({"q": "ÑANDÚ"}, "c.id = %s", (reader.copa,)),
        ({"q": "knowledge 3"}, "false", ()),  # the words are matched as written, in order
        ({"q": "100%"}, "false", ()),  # a % is a character, not a wildcard
        ({"market": "1X2", "result": "won", "band": "2-3"},
         "u.market_key = '1X2' AND u.status IN ('WIN', 'HALF_WIN') AND COALESCE(u.user_odds, u.odds) >= 2 "
         "AND COALESCE(u.user_odds, u.odds) < 3", ()),
    ]
    for params, where, values in cases:
        records, total = walk(c, **params)
        expected = independent(db, a, where, values)
        assert [r["id"] for r in records] == expected, params
        assert total == len(expected), params
    # «Todo»: every record, page after page, with the real total - and none of reader B's
    records, total = walk(c)
    assert total == 61 == len(records) == len({r["id"] for r in records})
    assert not {r["id"] for r in records} & set(independent(db, reader.users["b"]))


def test_a_filter_the_list_cannot_apply_is_refused(db: psycopg.Connection[Any], reader: Reader) -> None:
    c = client(db, reader.users["a"])
    for params in ({"since": "2034-05-03", "until": "2034-05-01"}, {"band": "1-2"}, {"result": "half"}, {"market": "XX"},
                   {"q": "x" * 61}, {"competition": 0}):
        r = c.get("/api/v1/me/picks", params=params)
        assert r.status_code == 422, params
    assert c.get("/api/v1/me/picks/summary", params={"since": "2034-05-03", "until": "2034-05-01"}).json()["error"]["code"] \
        == "invalid_filter"


def tally_of(db: psycopg.Connection[Any], ids: list[int]) -> dict[str, Any]:
    """Counts, units and ROI of saved picks by a query of this test: a flat unit per settled pick, a void returns it."""
    row = db.execute(
        "SELECT count(*), count(*) FILTER (WHERE status = 'PENDING'), count(*) FILTER (WHERE status = 'WIN'), "
        "count(*) FILTER (WHERE status = 'LOSS'), count(*) FILTER (WHERE status = 'HALF_WIN'), "
        "count(*) FILTER (WHERE status = 'HALF_LOSS'), count(*) FILTER (WHERE status = 'PUSH'), "
        "count(*) FILTER (WHERE status = 'VOID'), "
        "count(*) FILTER (WHERE status NOT IN ('PENDING', 'VOID') AND profit_units IS NOT NULL), "
        "COALESCE(sum(profit_units) FILTER (WHERE status <> 'PENDING'), 0) "
        "FROM picks.user_picks WHERE id = ANY(%s)", (ids,)).fetchone()
    assert row is not None
    total, pending, won, lost, half_won, half_lost, push, void, settled, units = row
    return {"total": total, "pending": pending, "won": won, "lost": lost, "half_won": half_won, "half_lost": half_lost,
            "push": push, "void": void, "settled": settled, "units": Decimal(units)}


def test_the_totals_and_the_breakdown_equal_independent_queries_with_their_sample(db: psycopg.Connection[Any],
                                                                                   reader: Reader) -> None:
    c = client(db, reader.users["a"])
    a = reader.users["a"]
    s = c.get("/api/v1/me/picks/summary").json()["data"]
    assert (s["min_sample"], s["conclusive"], s["timezone"]) == (25, 100, "America/Bogota")
    every = independent(db, a)
    expect = tally_of(db, every)
    t = s["tally"]
    for key in ("total", "pending", "won", "lost", "half_won", "half_lost", "push", "void", "settled"):
        assert t[key] == expect[key], key
    assert expect["settled"] == 50  # 40 1X2 and 10 OU (the two voids are not stakes)
    assert Decimal(t["units"]) == expect["units"].quantize(Decimal("0.01"))
    assert Decimal(t["roi"]) == (expect["units"] / 50).quantize(Decimal("0.0001"))
    assert Decimal(t["margin"]) == Decimal(1 / math.sqrt(50)).quantize(Decimal("0.0001"))  # ±14 points with 50
    wins, decided = expect["won"] + expect["half_won"], expect["won"] + expect["half_won"] + expect["lost"] + expect["half_lost"]
    assert Decimal(t["hit_rate"]) == (Decimal(wins) / decided).quantize(Decimal("0.0001"))
    assert t["sample"] == "inconclusive"  # 25..99: the page says the sample does not allow a conclusion yet
    # by kind of bet: most saved first; 1X2 has 40 settled (shown), OU 10 (counts only), BTTS none settled
    markets = {m["market"]: m for m in s["markets"]}
    assert [m["market"] for m in s["markets"]] == ["1X2", "OU", "BTTS"]
    for market, row in markets.items():
        ids = independent(db, a, "u.market_key = %s", (market,))
        e = tally_of(db, ids)
        assert (row["total"], row["settled"]) == (e["total"], e["settled"]), market
    assert markets["1X2"]["sample"] == "inconclusive" and markets["1X2"]["units"] is not None
    assert markets["OU"]["sample"] == "counts_only" and markets["OU"]["units"] is None and markets["OU"]["roi"] is None
    assert markets["OU"]["margin"] is None and markets["OU"]["hit_rate"] is None
    # by league, and the rows add up to the whole
    assert sum(r["total"] for r in s["competitions"]) == t["total"]
    assert {r["competition"]["id"] for r in s["competitions"]} == {reader.league, reader.copa}
    # by odds range: the reader's own price counts (2.40 moves four 1X2 picks to 2-3); a range with nothing is left out
    bands = {b["band"]: b["total"] for b in s["bands"]}
    for band, where in (("lt1.5", "COALESCE(u.user_odds, u.odds) < 1.5"),
                        ("1.5-2", "COALESCE(u.user_odds, u.odds) >= 1.5 AND COALESCE(u.user_odds, u.odds) < 2"),
                        ("2-3", "COALESCE(u.user_odds, u.odds) >= 2 AND COALESCE(u.user_odds, u.odds) < 3"),
                        ("3-5", "COALESCE(u.user_odds, u.odds) >= 3 AND COALESCE(u.user_odds, u.odds) < 5"),
                        ("5+", "COALESCE(u.user_odds, u.odds) >= 5")):
        assert bands.get(band, 0) == len(independent(db, a, where)), band
    assert [b["band"] for b in s["bands"]] == [b for b in ("lt1.5", "1.5-2", "2-3", "3-5", "5+") if bands.get(b)]
    # the choices of the filter come from the reader's own picks only
    assert s["options"]["markets"] == ["1X2", "OU", "BTTS"]
    assert [x["name"] for x in s["options"]["competitions"]] == ["Copa Andina Ñandú", "Knowledge League"]
    assert {d["key"]: d["version"] for d in s["definitions"]} == {"roi": "flat-1u", "sample": "se-v1", "line_value": "clv-v1"}


def test_the_totals_follow_the_filter_and_below_25_settled_give_only_counts(db: psycopg.Connection[Any], reader: Reader) -> None:
    c = client(db, reader.users["a"])
    s = c.get("/api/v1/me/picks/summary", params={"market": "OU"}).json()["data"]
    assert s["filter"] == {"result": None, "market": "OU", "competition": None, "origin": None, "band": None, "since": None,
                           "until": None, "search": None, "active": 1}
    t = s["tally"]
    assert (t["total"], t["settled"], t["sample"]) == (12, 10, "counts_only")
    assert t["units"] is None and t["roi"] is None and t["margin"] is None and t["hit_rate"] is None
    assert (t["won"], t["lost"], t["half_won"], t["half_lost"], t["push"], t["void"]) == (2, 2, 2, 2, 2, 2)
    empty = c.get("/api/v1/me/picks/summary", params={"q": "nadie"}).json()["data"]
    assert empty["tally"]["total"] == 0 and empty["markets"] == [] and empty["bands"] == []
    assert empty["options"]["markets"] == ["1X2", "OU", "BTTS"], "the choices stay the reader's whole"


def test_the_line_value_of_each_started_pick_and_of_the_whole(db: psycopg.Connection[Any], reader: Reader) -> None:
    c = client(db, reader.users["a"])
    records, _ = walk(c, market="1X2")
    by_id = {r["id"]: r for r in records}
    closes = db.execute(
        "SELECT u.id, COALESCE(u.user_odds, u.odds), (SELECT m.p_fair FROM market.market_consensus m WHERE m.fixture_id = u.fixture_id "
        "AND m.market_key = u.market_key AND m.selection = u.selection AND m.line = u.line AND m.devig_method = 'shin' "
        "AND m.as_of < f.kickoff_at ORDER BY m.as_of DESC LIMIT 1), f.kickoff_at <= %s "
        "FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id WHERE u.user_id = %s AND u.market_key = '1X2'",
        (NOW, reader.users["a"])).fetchall()
    with_close = 0
    for record, price, p_close, started in closes:
        got = by_id[record]
        if not started or p_close is None:
            assert got["p_close"] is None and got["line_value"] is None, record
            continue
        with_close += 1
        assert Decimal(got["p_close"]) == Decimal(p_close)
        assert Decimal(got["line_value"]) == (Decimal(price) * Decimal(p_close) - 1).quantize(Decimal("0.0001"))
    assert with_close == 12  # six matches, Home and Away: the late and the proportional quotes are never the close
    assert Decimal(by_id[reader.ids["1X2"][0]]["p_close"]) == Decimal("0.55")
    lv = c.get("/api/v1/me/picks/summary").json()["data"]["line_value"]
    assert (lv["version"], lv["n"], lv["minutes"]) == ("clv-v1", 12, 20)
    assert lv["mean"] is None and lv["positive"] is None, "below 25 picks with a close: only how many"


def test_the_csv_holds_the_readers_own_picks_under_the_filter_and_nothing_a_spreadsheet_would_run(
        db: psycopg.Connection[Any], reader: Reader) -> None:
    db.execute("UPDATE core.teams SET name = '=HYPERLINK(\"http://x\")' WHERE id = %s", (reader.andean[1],))
    c = client(db, reader.users["a"])
    r = c.get("/api/v1/me/picks/export", params={"market": "OU"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="predigol-mis-picks-')
    assert r.headers["cache-control"] == "no-store"
    body = r.content.decode("utf-8")
    assert body.startswith("﻿")
    rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert rows[0][:6] == ["guardado", "inicio", "liga", "pais", "local", "visitante"]
    lines = rows[1:]
    assert len(lines) == 12 == len(independent(db, reader.users["a"], "u.market_key = 'OU'"))
    assert {line[6] for line in lines} == {"OU"} and {line[7] for line in lines} == {"Over"}, "reader B saved Under: never here"
    assert all(line[5] == "'=HYPERLINK(\"http://x\")" for line in lines), "a formula is written as text"
    assert {line[13] for line in lines} == {"Ganado", "Perdido", "Medio ganado", "Medio perdido", "Devuelto", "Anulado"}
    assert all(line[1].endswith("-05:00") for line in lines), "the times in the reader's time zone"
    english = client(db, reader.users["a"], language="en").get("/api/v1/me/picks/export").content.decode("utf-8")
    head, *rest = list(csv.reader(io.StringIO(english.lstrip("﻿"))))
    assert head[0] == "saved_at" and len(rest) == 61
    assert {line[9] for line in rest} == {"PrediGol", "Your selection"}


def test_the_parlays_csv_has_one_line_per_leg_of_the_readers_own_parlays(db: psycopg.Connection[Any], reader: Reader) -> None:
    fixtures = [int(x[0]) for x in db.execute(
        "SELECT DISTINCT fixture_id FROM picks.user_picks WHERE user_id = %s AND market_key = 'BTTS' LIMIT 3",
        (reader.users["a"],)).fetchall()]
    for user, name in (("a", "+cmd"), ("b", "B's parlay")):
        parlay = scalar(db.execute("INSERT INTO picks.user_parlays (user_id, name, created_at, combined_odds, validation) VALUES "
                                   "(%s, %s, %s, 12.25, '{}') RETURNING id", (reader.users[user], name, NOW)))
        for n, fid in enumerate(fixtures[: 3 if user == "a" else 2], start=1):
            db.execute("INSERT INTO picks.user_parlay_legs (user_parlay_id, leg_no, fixture_id, market_key, selection, line, odds, "
                       "snapshot) VALUES (%s, %s, %s, 'BTTS', 'Yes', 0, 3.5, '{}')", (parlay, n, fid))
    body = client(db, reader.users["a"]).get("/api/v1/me/parlays/export").content.decode("utf-8")
    head, *lines = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
    assert head[:5] == ["parlay", "nombre", "creado", "cuota_combinada", "estado"]
    assert len(lines) == 3 and {line[1] for line in lines} == {"'+cmd"}
    assert [line[7] for line in lines] == ["1", "2", "3"]


def test_a_limited_membership_still_reads_its_totals_and_its_files() -> None:
    for path in ("/api/v1/me/picks/summary", "/api/v1/me/picks/export", "/api/v1/me/parlays/export"):
        assert path in MEMBERSHIP_READS
    paths = create_app().openapi()["paths"]
    for path in ("/api/v1/me/picks/summary", "/api/v1/me/picks/export", "/api/v1/me/parlays/export"):
        assert set(paths[path]) == {"get"}, "to read only"


def test_the_history_gives_only_counts_below_25_settled_and_the_margin_from_there(db: psycopg.Connection[Any],
                                                                               reader: Reader) -> None:
    c = client(db, reader.users["a"])
    h = c.get("/api/v1/me/history", params={"period": "all"}).json()["data"]
    assert (h["min_sample"], h["conclusive"]) == (25, 100)
    mine = h["groups"]["my_picks"]
    assert mine["staked_units"] == "50" or Decimal(mine["staked_units"]) == 50
    assert mine["roi"] is not None and mine["profit_units"] is not None and mine["hit_rate"] is not None
    assert mine["margin"] == pytest.approx(1 / math.sqrt(50), abs=1e-4) and mine["conclusive"] is False
    week = c.get("/api/v1/me/history", params={"period": "7d"}).json()["data"]["groups"]["my_picks"]
    assert Decimal(week["staked_units"]) < 25
    assert week["roi"] is None and week["profit_units"] is None and week["hit_rate"] is None and week["margin"] is None
    assert week["won"] + week["lost"] + week["pending"] >= 1, "the counts stay"
