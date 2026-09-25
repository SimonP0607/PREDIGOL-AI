"""End to end, with no provider call: results -> forecast -> captured prices -> consensus
-> candidate -> shadow pick -> settlement. Every link is checked for its lineage and
for the order of events (a forecast must precede the price it is judged against)."""

from __future__ import annotations

import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import psycopg
import pytest

from fbi.ingestion.ledger import RunLedger
from fbi.market.consensus import recompute_from_snapshots
from fbi.picks.engine import evaluate_captures, settle_open_picks
from fbi.predictions.forecast import forecast_upcoming
from tests.integration.helpers import scalar

KO = datetime(2026, 10, 3, 14, 0, tzinfo=UTC)
AT = KO - timedelta(hours=26)          # the forecast
CAPTURED = KO - timedelta(minutes=1439)  # the price, later than the forecast
N_TEAMS = 10


@pytest.fixture()
def league(db: psycopg.Connection, seed: object, migrated_database: str) -> Iterator[dict[str, object]]:
    rng = np.random.default_rng(42)
    strength = rng.normal(0, 0.3, N_TEAMS)
    ids: dict[str, object] = {"dsn": migrated_database.replace("postgresql://", "postgresql+psycopg://")}
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "is_tracked) VALUES (88039, 'Pipeline League', 'league', 'club', 'domestic_league', true) "
                    "RETURNING id")
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2026, true) "
                    "RETURNING id", (comp,))
        season = scalar(cur)
        teams = []
        for i in range(N_TEAMS):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                        (88101 + i, f"Pipeline {i}"))
            teams.append(scalar(cur))
        pid = 88000
        start = AT - timedelta(days=300)
        n = 0
        for rnd in range(2):
            for h in range(N_TEAMS):
                for a in range(N_TEAMS):
                    if h == a:
                        continue
                    ko = start + timedelta(days=(n // 5) * 3, minutes=n % 5)
                    n += 1
                    pid += 1
                    gh = int(rng.poisson(math.exp(0.35 + strength[h] - strength[a])))
                    ga = int(rng.poisson(math.exp(0.05 + strength[a] - strength[h])))
                    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                                "away_team_id, kickoff_at, status_short, status_group) VALUES (%s,%s,%s,%s,%s,'FT',"
                                "'finished') RETURNING id", (pid, season, teams[h], teams[a], ko))
                    fid = scalar(cur)
                    cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) "
                                "VALUES (%s,%s,%s)", (fid, gh, ga))
            assert rnd >= 0
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                    "kickoff_at) VALUES (88999, %s, %s, %s, %s) RETURNING id", (season, teams[0], teams[1], KO))
        ids["target"] = scalar(cur)
        books = []
        for pb, name in ((99901, "Book A"), (99902, "Book B")):
            cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                        (pb, name))
            books.append(scalar(cur))
        ids["books"] = books
        cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
                    "('OU','Over/Under',2,true,true),('BTTS','Both teams to score',2,false,true) "
                    "ON CONFLICT DO NOTHING RETURNING key")
        ids["added_markets"] = [r[0] for r in cur.fetchall()]
        cur.execute(
            "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, "
            "test_from, test_to, config, selection, primary_baseline, n_targets, dataset_hash, code_version, status, "
            "finished_at) VALUES ('pipeline','walk_forward',%s,2024,2025,'2025-08-01','2026-05-31',%s,%s,"
            "'pinnacle/closing/shin',100,'h','c','completed',now()) RETURNING id",
            ([comp], json.dumps({"history_days": 730}),
             json.dumps({k: {"chosen": {"xi": 0.002, "penalty": 1.0}} for k in ("poisson", "dixon_coles")})))
        ids["session"] = scalar(cur)
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                    "VALUES ('odds_capture','odds_capture','completed',now()) RETURNING id")
        run = scalar(cur)
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, "
                    "bytes) VALUES ('pipeline-odds', %s, '/odds', %s, 200, 'x', 1)", (run, CAPTURED))
        ids.update(comp=comp, season=season, teams=teams, capture_run=run)
    db.commit()
    yield ids
    db.rollback()
    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.notifications")
        cur.execute("DELETE FROM picks.picks WHERE fixture_id = %s", (ids["target"],))
        cur.execute("DELETE FROM picks.pick_candidates WHERE fixture_id = %s", (ids["target"],))
        cur.execute("DELETE FROM market.market_consensus WHERE fixture_id = %s", (ids["target"],))
        cur.execute("DELETE FROM market.odds_snapshots WHERE fixture_id = %s", (ids["target"],))
        cur.execute("DELETE FROM models.predictions WHERE fixture_id = %s", (ids["target"],))
        cur.execute("DELETE FROM features.feature_sets WHERE fixture_id IN (SELECT id FROM core.fixtures "
                    "WHERE competition_season_id = %s)", (ids["season"],))
        cur.execute("DELETE FROM core.fixtures WHERE competition_season_id = %s", (ids["season"],))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id BETWEEN 88101 AND 88199")
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (ids["season"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["comp"],))
        cur.execute("DELETE FROM analytics.backtest_sessions WHERE id = %s", (ids["session"],))
        cur.execute("DELETE FROM models.model_versions WHERE version LIKE '%%@pipetes'")
        cur.execute("DELETE FROM models.model_registry r WHERE NOT EXISTS "
                    "(SELECT 1 FROM models.model_versions v WHERE v.model_id = r.id)")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash = 'pipeline-odds'")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE id = %s OR job_type = 'shadow_picks'", (ids["capture_run"],))
        cur.execute("DELETE FROM market.bookmakers WHERE provider_bookmaker_id IN (99901, 99902)")
        cur.execute("DELETE FROM market.markets WHERE key = ANY(%s)", (ids["added_markets"],))
    db.commit()


def _snapshot(cur: psycopg.Cursor, fixture_id: int, book: int, sel: str, odds: Decimal) -> None:
    cur.execute(
        "INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
        "captured_at, minutes_to_ko, source, payload_hash) VALUES (%s,%s,'1X2',%s,0,%s,%s,1439,'prematch',"
        "'pipeline-odds')", (fixture_id, book, sel, odds, CAPTURED))


def test_a_captured_price_becomes_a_traceable_shadow_pick_and_settles_on_90_minutes(
    db: psycopg.Connection, league: dict[str, object]
) -> None:
    target = int(league["target"])  # type: ignore[call-overload]
    books: list[int] = league["books"]  # type: ignore[assignment]

    # 1. forecast, a day before kick-off
    report = forecast_upcoming(db, at=AT, code_version="pipetest")
    db.commit()
    assert report.predicted["poisson"] >= 1 and report.predicted["dixon_coles"] >= 1
    assert "elo_ologit" in report.skipped_models, "too few Elo-labelled results: said, not faked"
    again = forecast_upcoming(db, at=AT + timedelta(hours=1), code_version="pipetest")
    db.commit()
    assert again.written == 0 and again.unchanged >= 2, "no new information, no new forecast"
    with db.cursor() as cur:
        cur.execute("SELECT p.p_calibrated FROM models.predictions p JOIN models.model_versions v ON "
                    "v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = %s "
                    "AND m.name = 'poisson' AND p.market_key = '1X2' AND p.selection = 'Home'", (target,))
        p_home = float(scalar(cur))

    # 2. two books with a margin each, one of them long on the home side
    long_home = (Decimal("1.15") / Decimal(str(p_home))).quantize(Decimal("0.01"))
    short_home = (Decimal("0.93") / Decimal(str(p_home))).quantize(Decimal("0.01"))
    with db.cursor() as cur:
        for book, home in ((books[0], long_home), (books[1], short_home)):
            rest = Decimal("1.07") - 1 / home  # the book sums to 1.07: a 7% margin
            _snapshot(cur, target, book, "Home", home)
            _snapshot(cur, target, book, "Draw", (1 / (rest * Decimal("0.45"))).quantize(Decimal("0.01")))
            _snapshot(cur, target, book, "Away", (1 / (rest * Decimal("0.55"))).quantize(Decimal("0.01")))
    assert recompute_from_snapshots(db, fixture_ids=[target])[1] == 9
    db.commit()

    # 3. candidates and shadow picks
    run_id = RunLedger(db).open("shadow_picks")
    picks = evaluate_captures(db, run_id=run_id, code_version="pipetest")
    db.commit()
    assert picks.instants == 1 and picks.candidates >= 3
    assert picks.selected >= 1 and picks.qualified == 0
    rerun = evaluate_captures(db, run_id=run_id, code_version="pipetest")
    db.commit()
    assert rerun.candidates == 0 and rerun.already_evaluated == picks.candidates, "evaluated once per price"
    with db.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.status, p.selection, p.bookmaker_id, p.market_odds, p.data_cutoff_ts, p.odds_captured_at, "
            "p.odds_payload_hash, p.prediction_id IS NOT NULL, p.consensus_method, p.decision_rule_version, "
            "p.qualification, p.calibrator_id, p.mode FROM picks.picks p WHERE p.fixture_id = %s ORDER BY p.id",
            (target,))
        rows = cur.fetchall()
    home_picks = [r for r in rows if r[2] == "Home"]
    assert home_picks, "the long home price was selected"
    (pick_id, status, _, book, odds, cutoff, captured, payload, has_prediction, method, rule, qual, calib,
     mode) = home_picks[0]
    assert status == "shadow" and mode == "shadow" and calib is None
    assert book == books[0] and odds == long_home, "the best price, with its bookmaker"
    assert cutoff < captured == CAPTURED and payload == "pipeline-odds" and has_prediction
    assert method == "shin" and rule == "shadow-rule-v1"
    assert qual["qualified"] is False and "no stored walk-forward backtest" in qual["reasons"][0]
    with db.cursor() as cur:
        cur.execute("SELECT decision, count(*) FROM picks.pick_candidates WHERE fixture_id = %s GROUP BY decision",
                    (target,))
        decisions: dict[str, int] = dict(cur.fetchall())
        assert decisions.get("rejected", 0) >= 1, "the draw and away prices are rejected, with a reason"
        cur.execute("SELECT to_status FROM picks.pick_events WHERE pick_id = %s ORDER BY at", (pick_id,))
        assert [r[0] for r in cur.fetchall()] == ["shadow"]
        cur.execute("SELECT result_status FROM picks.pick_results WHERE pick_id = %s", (pick_id,))
        assert scalar(cur) == "pending"

    # 4. postponed first: stays pending with the reason
    with db.cursor() as cur:
        cur.execute("UPDATE core.fixtures SET status_short = 'PST', status_group = 'postponed' WHERE id = %s", (target,))
    first = settle_open_picks(db, run_id=run_id)
    db.commit()
    assert first.settled == 0 and first.needs_review >= 1
    with db.cursor() as cur:
        cur.execute("SELECT result_status, review_reason FROM picks.pick_results WHERE pick_id = %s", (pick_id,))
        st, why = cur.fetchone() or ("", "")
        assert st == "pending" and "postponed" in why

    # 5. played: 1-1 at 90 minutes, 2-1 after extra time -> the home bet LOSES on 90 minutes
    with db.cursor() as cur:
        cur.execute("UPDATE core.fixtures SET status_short = 'AET', status_group = 'finished' WHERE id = %s", (target,))
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, et_goals_home, et_goals_away)"
                    " VALUES (%s, 2, 1, 1, 0)", (target,))
    second = settle_open_picks(db, run_id=run_id)
    db.commit()
    assert second.settled == len(rows)
    with db.cursor() as cur:
        cur.execute("SELECT r.result_status, r.profit_units, r.settlement_basis, r.rule_version, p.status "
                    "FROM picks.pick_results r JOIN picks.picks p ON p.id = r.pick_id WHERE r.pick_id = %s", (pick_id,))
        assert cur.fetchone() == ("loss", Decimal("-1.0000"), "regulation_90", "settle-v1", "settled")
        cur.execute("SELECT to_status FROM picks.pick_events WHERE pick_id = %s ORDER BY at, id", (pick_id,))
        assert [r[0] for r in cur.fetchall()] == ["shadow", "settled"]
    assert settle_open_picks(db, run_id=run_id).open_picks == 0, "settled picks are not settled again"

    # 6. and the API tells the same story, with the lineage
    from fastapi.testclient import TestClient

    from fbi.core.config import reset_cache

    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", str(league["dsn"]))
    reset_cache()
    try:
        from fbi.api.app import create_app

        with TestClient(create_app()) as client:
            body = client.get("/api/v1/picks").json()
            perf = client.get("/api/v1/performance").json()
            match = client.get(f"/api/v1/matches/{target}").json()["data"]
            audit = client.get(f"/api/v1/matches/{target}/audit").json()["data"]
    finally:
        mp.undo()
        reset_cache()
    d = body["data"]
    assert d["publishing_enabled"] is False and d["rule"]["version"] == "shadow-rule-v1"
    assert d["lifecycle"]["settled"] == len(rows) and d["lifecycle"]["candidates"] == picks.candidates
    api_pick = next(p for p in d["picks"]["data"] if p["id"] == pick_id)
    assert api_pick["status"] == "settled" and api_pick["result_status"] == "loss"
    assert api_pick["odds_payload_hash"] == "pipeline-odds" and api_pick["calibrated"] is False
    assert [e["to_status"] for e in api_pick["events"]] == ["shadow", "settled"]
    assert d["rejection_reasons"], "why prices were rejected is counted"
    assert perf["status"] == "insufficient_data", "one settled shadow pick is not a performance record"
    assert {p["kind"] for p in match["predictions"]["data"]} == {"forecast"}

    # 6b. and the audit trail reconstructs the chain from stored links alone
    steps = {s["key"]: s for s in audit["steps"]}
    for key in ("features", "models", "predictions", "market", "picks", "settlement"):
        assert steps[key]["state"] == "recorded", f"{key}: {steps[key]['detail']}"
    items = {(i["kind"], i["ref"]): i for s in audit["steps"] for i in s["items"]}
    pick_item = items[("pick", str(pick_id))]
    candidate_link = next(x for x in pick_item["links"] if x.startswith("pick_candidate:"))
    candidate = items[tuple(candidate_link.split(":", 1))]
    assert "payload:pipeline-odds" in candidate["links"], "the price a candidate was judged on is named"
    prediction_link = next(x for x in candidate["links"] if x.startswith("prediction:"))
    prediction = items[tuple(prediction_link.split(":", 1))]
    assert prediction["facts"]["cutoff_before_kickoff"] is True and prediction["facts"]["kind"] == "forecast"
    assert any(x.startswith("model_version:") for x in prediction["links"])
    assert any(x.startswith("feature_set:") for i in steps["predictions"]["items"] for x in i["links"]), \
        "the Elo forecast names the feature set it read"
    assert items[("settlement", str(pick_id))]["facts"]["result_status"] == "loss"
    assert f"pick:{pick_id}" in items[("settlement", str(pick_id))]["links"]

    # 7. the bot: informs once per event, never as advice, and never leaks its token
    import httpx

    from fbi.notify.service import TelegramChannel, run_notifier

    sent: list[dict] = []

    def telegram(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    channel = TelegramChannel("123:secret-token", "42", transport=httpx.MockTransport(telegram))
    first_run = run_notifier(db, channel)
    assert first_run.sent == first_run.new >= 3, "pick created, pick settled, first capture"
    texts = [m["text"] for m in sent]
    assert any("research only, not a bet" in t for t in texts)
    assert any("settled: loss" in t for t in texts)
    assert all("secret-token" not in t for t in texts)
    repeat = run_notifier(db, channel)
    assert repeat.new == 0 and repeat.sent == 0, "one message per event"
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit.notifications WHERE status = 'sent' AND channel = 'telegram'")
        assert scalar(cur) == first_run.sent

    def down(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    with db.cursor() as cur:
        cur.execute("DELETE FROM audit.notifications")
    db.commit()
    failing = run_notifier(db, TelegramChannel("123:secret-token", "42", transport=httpx.MockTransport(down)))
    assert failing.failed == failing.new
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT last_error FROM audit.notifications WHERE status = 'failed'")
        errors = [r[0] for r in cur.fetchall()]
        assert errors == ["telegram answered HTTP 401"], "the reason, without the token"
        cur.execute("UPDATE audit.notifications SET status = 'queued', last_error = NULL")
    db.commit()
    quiet = run_notifier(db, None)
    assert quiet.skipped == failing.new and quiet.sent == 0
