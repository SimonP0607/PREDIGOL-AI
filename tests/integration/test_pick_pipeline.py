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
from fbi.picks.rules import CURRENT_RULE
from fbi.predictions.forecast import forecast_upcoming
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, signed_in

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
        cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive,"
                    " line_is_signed) VALUES "
                    "('OU','Over/Under',2,true,true,false),"
                    "('BTTS','Both teams to score',2,false,true,false),"
                    "('AH','Asian Handicap',2,true,false,true) "
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
        cur.execute("DELETE FROM models.model_versions WHERE version LIKE '%%@pipetes' OR version LIKE '%%@pipenew'")
        cur.execute("DELETE FROM models.model_registry r WHERE NOT EXISTS "
                    "(SELECT 1 FROM models.model_versions v WHERE v.model_id = r.id)")
        cur.execute("DELETE FROM raw.ingestion_payloads "
                    "WHERE hash IN ('pipeline-odds', 'pipeline-odds-early')")
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
    assert method == "shin" and rule == CURRENT_RULE.version, (
        "the pick names the exact rule that selected it, so a backtest of one "
        "rule version is never contaminated by another"
    )
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

        with TestClient(signed_in(create_app()), headers=SAME_SITE) as client:
            body = client.get("/api/v1/admin/picks").json()
            perf = client.get("/api/v1/admin/performance").json()
            match = client.get(f"/api/v1/admin/matches/{target}").json()["data"]
            audit = client.get(f"/api/v1/admin/matches/{target}/audit").json()["data"]
    finally:
        mp.undo()
        reset_cache()
    d = body["data"]
    assert d["publishing_enabled"] is False and d["rule"]["version"] == CURRENT_RULE.version
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


def test_a_model_re_versioned_by_a_code_change_is_judged_once(db: psycopg.Connection,
                                                               league: dict[str, object]) -> None:
    """25 Sep 2026, first real capture: three versions of one Elo model (the worker restarted
    on three commits) each had a forecast, and one price became three identical shadow picks.
    One model, one judgement per price - through its newest forecast - and the economic summary
    counts a bet once even where old rows repeat it."""
    target = int(league["target"])  # type: ignore[call-overload]
    books: list[int] = league["books"]  # type: ignore[assignment]
    forecast_upcoming(db, at=AT, code_version="pipetest")
    forecast_upcoming(db, at=AT + timedelta(minutes=30), code_version="pipenew")  # same inputs, new version
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT m.name, count(DISTINCT p.model_version_id) FROM models.predictions p "
                    "JOIN models.model_versions v ON v.id = p.model_version_id "
                    "JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = %s GROUP BY m.name",
                    (target,))
        versions: dict[str, int] = dict(cur.fetchall())
        assert versions == {"poisson": 2, "dixon_coles": 2}, "the premise: two versions of each model forecast"
        cur.execute("SELECT p.p_calibrated FROM models.predictions p JOIN models.model_versions v ON "
                    "v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = %s "
                    "AND m.name = 'poisson' AND p.market_key = '1X2' AND p.selection = 'Home' "
                    "AND v.version LIKE '%%@pipenew'", (target,))
        p_home = float(scalar(cur))
        long_home = (Decimal("1.15") / Decimal(str(p_home))).quantize(Decimal("0.01"))
        for book in books:
            rest = Decimal("1.07") - 1 / long_home
            _snapshot(cur, target, book, "Home", long_home)
            _snapshot(cur, target, book, "Draw", (1 / (rest * Decimal("0.45"))).quantize(Decimal("0.01")))
            _snapshot(cur, target, book, "Away", (1 / (rest * Decimal("0.55"))).quantize(Decimal("0.01")))
    recompute_from_snapshots(db, fixture_ids=[target])
    db.commit()

    run_id = RunLedger(db).open("shadow_picks")
    picks = evaluate_captures(db, run_id=run_id, code_version="pipenew")
    db.commit()
    assert picks.candidates == 6, "3 selections x 2 models - not x 4 versions"
    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT v.version LIKE '%%@pipenew' FROM picks.pick_candidates c "
                    "JOIN models.predictions p ON p.id = c.prediction_id "
                    "JOIN models.model_versions v ON v.id = p.model_version_id WHERE c.fixture_id = %s", (target,))
        assert cur.fetchall() == [(True,)], "judged through the newest forecast of each model"
        cur.execute("SELECT v.model_id, p.selection, count(*) FROM picks.picks p "
                    "JOIN models.model_versions v ON v.id = p.model_version_id WHERE p.fixture_id = %s "
                    "GROUP BY 1, 2 HAVING count(*) > 1", (target,))
        assert cur.fetchall() == [], "one pick per model and selection at one price"
        cur.execute("SELECT count(*) FROM picks.picks WHERE fixture_id = %s", (target,))
        n_picks = int(scalar(cur))
    assert n_picks >= 1

    # rows written before the fix repeat a bet (the old version's candidate and pick, as on the
    # machine): the economic summary still counts it once
    from fbi.api.repositories.analytics import settled_summary

    with db.cursor() as cur:
        cur.execute("SELECT p.id, p.candidate_id, p.market_key, p.selection, v.model_id FROM picks.picks p "
                    "JOIN models.model_versions v ON v.id = p.model_version_id WHERE p.fixture_id = %s "
                    "ORDER BY p.id LIMIT 1", (target,))
        first, cand, market, selection, model_id = cur.fetchone()  # type: ignore[misc]
        cur.execute("SELECT p.id, p.model_version_id FROM models.predictions p "
                    "JOIN models.model_versions v ON v.id = p.model_version_id WHERE p.fixture_id = %s "
                    "AND p.market_key = %s AND p.selection = %s AND v.model_id = %s AND v.version LIKE '%%@pipetes'",
                    (target, market, selection, model_id))
        old_prediction, old_version = cur.fetchone()  # type: ignore[misc]
        cur.execute("""
            INSERT INTO picks.pick_candidates (run_id, fixture_id, prediction_id, market_key, selection, line,
                bookmaker_id, market_odds, p_calibrated, p_market_fair, edge, price_edge, ev, ev_adjusted, decision,
                rejection_reason, decision_rule_version, odds_captured_at, odds_payload_hash, consensus_method,
                consensus_as_of, data_cutoff_ts)
            SELECT run_id, fixture_id, %s, market_key, selection, line, bookmaker_id, market_odds, p_calibrated,
                   p_market_fair, edge, price_edge, ev, ev_adjusted, decision, rejection_reason,
                   decision_rule_version, odds_captured_at, odds_payload_hash, consensus_method, consensus_as_of,
                   data_cutoff_ts
            FROM picks.pick_candidates WHERE id = %s RETURNING id""", (old_prediction, cand))
        old_cand = int(scalar(cur))
        cur.execute("""
            INSERT INTO picks.picks (candidate_id, fixture_id, market_key, selection, line, model_version_id,
                calibrator_id, feature_set_hash, data_cutoff_ts, decision_rule_version, code_version, bookmaker_id,
                market_odds, odds_captured_at, p_model, p_calibrated, p_calibrated_lo, p_calibrated_hi, p_market_fair,
                fair_odds, edge, price_edge, ev, ev_adjusted, kelly_fraction, stake_units, selection_reason, mode,
                prediction_id, odds_payload_hash, consensus_method, consensus_as_of, stake_policy, qualification,
                status)
            SELECT %s, fixture_id, market_key, selection, line, %s, calibrator_id, feature_set_hash, data_cutoff_ts,
                   decision_rule_version, code_version, bookmaker_id, market_odds, odds_captured_at, p_model,
                   p_calibrated, p_calibrated_lo, p_calibrated_hi, p_market_fair, fair_odds, edge, price_edge, ev,
                   ev_adjusted, kelly_fraction, stake_units, selection_reason, mode, %s, odds_payload_hash,
                   consensus_method, consensus_as_of, stake_policy, qualification, status
            FROM picks.picks WHERE id = %s""", (old_cand, old_version, old_prediction, first))
        cur.execute("SELECT count(*) FROM picks.picks WHERE fixture_id = %s", (target,))
        assert int(scalar(cur)) == n_picks + 1, "the premise: a repeated bet in the rows"
    summary = settled_summary(db)
    assert int(summary["pending"]) == n_picks, "the repeated bet is one bet, not two"


EARLY = AT - timedelta(hours=1)
"""An earlier capture, so the line is known BEFORE the forecast.

This is how production works and the test has to match it: the model prices the
lines the market has quoted, read from the stored snapshots, and the engine then
refuses to compare that forecast with any price captured before it. A line is
therefore established by one capture and judged against a later one - which is
exactly what a four-day window ladder from T-4320 to T-180 provides.
"""


def _ah_snapshot(cur: psycopg.Cursor, fixture_id: int, book: int, sel: str,
                 line: str, odds: str, *, at: datetime, payload: str) -> None:
    cur.execute(
        "INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, "
        " selection, line, odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
        "VALUES (%s,%s,'AH',%s,%s,%s,%s,%s,'prematch',%s)",
        (fixture_id, book, sel, Decimal(line), Decimal(odds), at,
         int((KO - at).total_seconds() // 60), payload),
    )


def test_a_whole_asian_handicap_line_reaches_a_pick_with_its_push(
    db: psycopg.Connection, league: dict[str, object]
) -> None:
    """The end of the chain for a line that can push.

    A whole handicap is the case that was impossible before tonight: the market
    was not modelled, the consensus did not pair it, and a de-vigged two-way
    probability would have been compared against an unconditional one. All four
    links are checked here on one row.

    Everything is real except the clock: the prices are placed after the
    forecast, because the engine refuses to compare a forecast with a price
    captured before it and the provider happened to be quoting nothing for
    tonight's fixtures.
    """
    target = int(league["target"])  # type: ignore[call-overload]
    books: list[int] = league["books"]  # type: ignore[assignment]

    # An earlier capture establishes which lines the market quotes. Home -1
    # pairs with Away +1 - the measured convention - and the two prices make a
    # believable book (1/1.95 + 1/1.90 = 1.039).
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, "
            " http_status, file_path, bytes) "
            "VALUES ('pipeline-odds-early', %s, '/odds', %s, 200, 'x', 1) "
            "ON CONFLICT DO NOTHING",
            (int(league["capture_run"]), EARLY),  # type: ignore[call-overload]
        )
        for book in books:
            _ah_snapshot(cur, target, book, "Home", "-1", "1.97",
                         at=EARLY, payload="pipeline-odds-early")
            _ah_snapshot(cur, target, book, "Away", "1", "1.88",
                         at=EARLY, payload="pipeline-odds-early")
    db.commit()

    forecast_upcoming(db, at=AT, code_version="pipetest")
    db.commit()

    # ...and a later capture is what the forecast is judged against.
    with db.cursor() as cur:
        for book in books:
            _ah_snapshot(cur, target, book, "Home", "-1", "1.95",
                         at=CAPTURED, payload="pipeline-odds")
            _ah_snapshot(cur, target, book, "Away", "1", "1.90",
                         at=CAPTURED, payload="pipeline-odds")
    db.commit()

    instants, rows = recompute_from_snapshots(db, fixture_ids=[target])
    db.commit()
    assert instants == 2 and rows > 0, "one consensus per capture"

    with db.cursor() as cur:
        cur.execute(
            "SELECT selection, line, p_fair, overround FROM market.market_consensus "
            "WHERE fixture_id = %s AND market_key = 'AH' AND devig_method = 'shin' "
            "  AND as_of = %s ORDER BY selection",
            (target, CAPTURED),
        )
        consensus = cur.fetchall()
    assert len(consensus) == 2, "both sides of the pair, at opposite lines"
    assert {(str(s), str(line)) for s, line, _, _ in consensus} == {
        ("Away", "1.00"), ("Home", "-1.00")
    }
    assert sum(float(p) for _, _, p, _ in consensus) == pytest.approx(1.0, abs=1e-9), (
        "a de-vigged pair sums to 1, which is why it is conditional on the bet "
        "being settled"
    )
    assert all(1.0 < float(o) < 1.25 for _, _, _, o in consensus)

    with db.cursor() as cur:
        cur.execute(
            "SELECT p_calibrated, p_push, p_lo, p_hi FROM models.predictions "
            "WHERE fixture_id = %s AND market_key = 'AH' AND selection = 'Home' "
            "  AND line = -1 AND backtest_session_id IS NULL LIMIT 1",
            (target,),
        )
        prediction = cur.fetchone()
    assert prediction is not None, "the model priced the quoted line"
    p_win, p_push = float(prediction[0]), float(prediction[1])
    assert p_push > 0, "a whole line can push, and the model says by how much"
    assert prediction[2] is not None and prediction[3] is not None, "a quoted line carries its interval (GATE E)"
    assert float(prediction[2]) <= p_win <= float(prediction[3]) and float(prediction[2]) < float(prediction[3])

    ledger = RunLedger(db)
    run = ledger.open("shadow_picks")
    report = evaluate_captures(db, run_id=run, code_version="pipetest")
    db.commit()
    assert report.candidates > 0

    with db.cursor() as cur:
        cur.execute(
            "SELECT p_calibrated, p_push, p_market_fair, edge, ev, market_odds "
            "FROM picks.pick_candidates "
            "WHERE fixture_id = %s AND market_key = 'AH' AND selection = 'Home' "
            "  AND line = -1",
            (target,),
        )
        candidate = cur.fetchone()
    assert candidate is not None, "the handicap line became a candidate"
    stored_p, stored_push, fair, edge, ev, odds = (float(x) for x in candidate)

    # The comparison was made on the CONDITIONAL probability, which is what the
    # market's de-vigged number is.
    assert stored_push == pytest.approx(p_push, abs=1e-6)
    assert stored_p == pytest.approx(p_win / (1 - p_push), abs=1e-5), (
        "stored as P(win | settled), comparable with p_market_fair"
    )
    assert edge == pytest.approx(stored_p - fair, abs=1e-5)

    # ...while the expected value used the unconditional pair, because the stake
    # is risked whether the bet pushes or not.
    expected_ev = p_win * (odds - 1) - (1 - p_win - p_push)
    assert ev == pytest.approx(expected_ev, abs=1e-5)

    # And it is not the same number the two-way formula would have given.
    two_way_ev = stored_p * (odds - 1) - (1 - stored_p)
    assert abs(ev - two_way_ev) > 1e-4, (
        "the push changes the expected value; if these agreed, it was ignored"
    )


def test_a_whole_line_pick_keeps_its_interval_on_its_own_footing(
    db: psycopg.Connection, league: dict[str, object]
) -> None:
    """A whole handicap's pick stores P(win | settled) - and its interval must be on that
    footing too. Stored unconditional, the upper bound sat below the conditional point; the
    table's interval check refused the row and, with it, every pipeline run (4 Oct 2026,
    from the day quoted lines got intervals). The price here is generous on purpose, so the
    rule selects the line and the pick row is actually written."""
    target = int(league["target"])  # type: ignore[call-overload]
    books: list[int] = league["books"]  # type: ignore[assignment]
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
            "VALUES ('pipeline-odds-early', %s, '/odds', %s, 200, 'x', 1) ON CONFLICT DO NOTHING",
            (int(league["capture_run"]), EARLY),  # type: ignore[call-overload]
        )
        for book in books:
            _ah_snapshot(cur, target, book, "Home", "-1", "1.97", at=EARLY, payload="pipeline-odds-early")
            _ah_snapshot(cur, target, book, "Away", "1", "1.88", at=EARLY, payload="pipeline-odds-early")
    db.commit()
    forecast_upcoming(db, at=AT, code_version="pipetest")
    db.commit()
    with db.cursor() as cur:
        for book in books:
            _ah_snapshot(cur, target, book, "Home", "-1", "4.20", at=CAPTURED, payload="pipeline-odds")
            _ah_snapshot(cur, target, book, "Away", "1", "1.27", at=CAPTURED, payload="pipeline-odds")
    db.commit()
    recompute_from_snapshots(db, fixture_ids=[target])
    db.commit()

    ledger = RunLedger(db)
    run = ledger.open("shadow_picks")
    report = evaluate_captures(db, run_id=run, code_version="pipetest")
    db.commit()
    assert report.selected > 0, "the premise: the generous price is selected"
    with db.cursor() as cur:
        cur.execute("SELECT p_calibrated, p_push, p_lo, p_hi FROM models.predictions WHERE fixture_id = %s AND "
                    "market_key = 'AH' AND selection = 'Home' AND line = -1 AND backtest_session_id IS NULL LIMIT 1",
                    (target,))
        pred = cur.fetchone()
        cur.execute("SELECT p_calibrated, p_calibrated_lo, p_calibrated_hi, p_push FROM picks.picks WHERE "
                    "fixture_id = %s AND market_key = 'AH' AND selection = 'Home' AND line = -1", (target,))
        pick = cur.fetchone()
    assert pred is not None and pick is not None, "the whole-line pick was written"
    p, lo, hi, push = (float(x) for x in pick)
    assert push > 0 and lo <= p <= hi, "the interval brackets the point, on one footing"
    settled = 1 - float(pred[1])
    assert lo == pytest.approx(float(pred[2]) / settled, abs=2e-6)
    assert hi == pytest.approx(min(1.0, float(pred[3]) / settled), abs=2e-6)
    assert p == pytest.approx(float(pred[0]) / settled, abs=2e-6)
