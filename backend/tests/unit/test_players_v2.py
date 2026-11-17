"""``player-engine-v2`` (IA-129, AD-B08), without a database: every player market is expected minutes x rate per 90 x the start probability
of ``lineup-estimate-v1``; never 90 sure minutes; with no chance of playing the probability is 0; with the official sheet the start is 0
or 1; the forecasts are rebuilt the same from what was known at their moment; the walk-forward evaluation states its samples and its
verdicts; the worker's job is off by default; E6's dry run decides only «pendiente» or «recuento completo» and reads no score."""

from __future__ import annotations

import ast
import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fbi.players import availability as av
from fbi.players import backtest as bt
from fbi.players import e6, v2
from fbi.players import families as fam
from fbi.players import lineup_estimate as le
from fbi.players import rates as rt
from fbi.players.history import Fixture, History, Match, PlayerMatch, SheetLine

T0 = datetime(2026, 3, 1, 18, tzinfo=UTC)
HOME, AWAY, COMP = 1, 2, 77
ROOT = Path(__file__).resolve().parents[2]


def squad(team: int) -> list[int]:
    return [team * 100 + i for i in range(16)]


def season(n: int = 30, seed: int = 5, minutes: int = 90) -> list[Match]:
    """Two teams every week: eleven regulars (one rotated a third of the time), five on the bench; forwards shoot."""
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        lines = []
        for side, team in (("home", HOME), ("away", AWAY)):
            men = squad(team)
            xi = men[:11] if rnd.random() >= 0.33 else [*men[:10], men[11]]
            for i, pid in enumerate(men):
                started = pid in xi
                mins = minutes if started else (20 if rnd.random() < 0.5 else 0)
                pos = "G" if i == 0 else ("F" if i >= 8 else "M")
                shots = rnd.randint(0, 3) if mins and pos == "F" else (rnd.randint(0, 1) if mins else 0)
                lines.append(PlayerMatch.make(pid, side, started and mins > 0, mins, pos,
                                              {"goals": 0, "assists": 0, "shots": shots, "shots_on": min(shots, rnd.randint(0, 2)),
                                               "fouls": rnd.randint(0, 2) if mins else 0, "cards": 0, "saves": 2 if pos == "G" else 0}))
        ko = T0 + timedelta(days=7 * k)
        out.append(Match(10_000 + k, ko, COMP, HOME, AWAY, ko + timedelta(hours=3), tuple(lines)))
    return out


def history(matches: list[Match]) -> History:
    h = History()
    for m in matches:
        h.add(m, bt.LINES_BY_STAT)
    return h


def estimate(p_start: float, p_sub: float = 0.0, *, minutes_start: float = 80.0, basis: str = le.BASE_MINUTES,
             position: str = "F") -> le.Estimate:
    return le.Estimate(1, HOME, 108, position, p_start, p_sub, minutes_start, 20.0, basis, 10, 0.8, True, None, None, None, (),
                       le.SIN_CALIBRAR)


def rate(per90: float = 1.0) -> rt.Rate:
    return rt.Rate("shots_on", per90, per90, per90, per90, 1.0, 1.0, 12.0)


SHOTS_ON = fam.BY_KEY["player_shots_on"]


def test_doc1_example_one_on_target_per_90_is_63_and_53_at_85_percent_of_starting() -> None:
    full, at85 = v2.rule_example()
    assert round(full, 2) == 0.63
    assert round(at85, 2) == 0.54 and int(at85 * 100) == 53


def test_no_chance_of_playing_is_a_probability_of_zero_and_no_conditional() -> None:
    rows = v2.forecast_player(estimate(0.0, 0.0, basis=le.BASE_CONFIRMED_OUT), rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0,
                              phi=0.0, lineup_confirmed=False)
    assert rows and all(r.p_over == 0.0 and r.p_over_if_plays is None and r.mean == 0.0 for r in rows)


def test_the_start_probability_scales_the_unconditional_figure_not_the_conditional_one() -> None:
    sure = v2.forecast_player(estimate(1.0), rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0, phi=0.0, lineup_confirmed=True)[0]
    half = v2.forecast_player(estimate(0.5), rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0, phi=0.0, lineup_confirmed=False)[0]
    assert half.p_over == pytest.approx(0.5 * sure.p_over)
    assert half.p_over_if_plays == pytest.approx(sure.p_over_if_plays)


def test_never_ninety_sure_minutes_the_minutes_come_from_his_starts() -> None:
    h = history(season(minutes=60))
    m = av.minutes_profile(h, HOME, 108, "F")
    assert m.if_start < 75, "a man who plays an hour when he starts is not priced for 90 minutes"
    e = le.estimate(h, av.StartModel(), fixture_id=1, team_id=HOME, player_id=108, position="F", competition_id=COMP)
    assert e.minutes_start == pytest.approx(m.if_start)
    r = v2.forecast_player(e, rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0, phi=0.0, lineup_confirmed=False)[0]
    ninety = v2.p_over(1.0, 0.0, p_start=e.p_start, minutes_start=90.0, p_sub=e.p_sub, minutes_sub=e.minutes_sub)
    assert r.p_over < ninety


def test_with_the_official_sheet_the_start_is_zero_or_one() -> None:
    h = history(season())
    sheet = {108: SheetLine(108, None, "F", True), 112: SheetLine(112, None, "F", False)}
    for pid in (108, 112, 109):
        e = le.estimate(h, av.StartModel(), fixture_id=1, team_id=HOME, player_id=pid, position="F", competition_id=COMP, sheet=sheet)
        assert e.p_start in (0.0, 1.0)
        for r in v2.forecast_player(e, rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0, phi=0.0, lineup_confirmed=True):
            assert r.p_start in (0.0, 1.0) and r.start_basis in (av.CONFIRMED_STARTER, av.CONFIRMED_BENCH, av.NOT_IN_LINEUP)
    off = le.estimate(h, av.StartModel(), fixture_id=1, team_id=HOME, player_id=109, position="F", competition_id=COMP, sheet=sheet)
    assert off.basis == av.NOT_IN_LINEUP and off.p_play == 0.0


def _doc(matches: list[Match], at: datetime) -> dict[str, Any]:
    engine = bt.Engine(matches, {})
    engine.walk(at, record_from=at, train_from=at - le.TRAIN)
    engine.prepare(at)
    fx = Fixture(99_999, at + timedelta(hours=20), COMP, HOME, AWAY, "A", "B", "scheduled")
    sides = {side: {"team_id": team, "confirmed": False,
                    "estimates": le.estimate_side(engine.h, engine.model, fixture_id=fx.fixture_id, team_id=team, competition_id=COMP,
                                                  states={}, facts={})}
             for side, team in (("home", HOME), ("away", AWAY))}
    return {"fixture": fx, "sides": sides, "history": engine.h, "dispersion": dict(engine.phi), "history_matches": engine.h.matches}


def test_the_forecasts_are_rebuilt_the_same_from_what_was_known_at_their_moment() -> None:
    matches = season(40)
    at = T0 + timedelta(days=7 * 30, hours=-30)
    doc = _doc(matches, at)
    a = v2.forecast_fixture(doc, at=at, phi=doc["dispersion"])
    later_doc = _doc(season(45), at)  # the same season and five more weeks after the moment: they change nothing
    b = v2.forecast_fixture(later_doc, at=at, phi=later_doc["dispersion"])
    assert a and [r.input_hash() for r in a] == [r.input_hash() for r in b]
    keys = {(r.provider_player_id, r.family, r.line) for r in a}
    assert len(keys) == len(a), "one row per player, family and line"
    assert all(r.known_at == at and r.seal == le.SIN_CALIBRAR and fam.applies(fam.BY_KEY[r.family], r.position) for r in a)
    assert {r.family for r in a if r.position == "G"} == {"keeper_saves"}
    assert all(0.0 <= r.p_over <= 1.0 and r.p_over <= r.p_play + 1e-9 for r in a)


def test_the_full_engine_estimates_exactly_as_the_estimate_engine_does() -> None:
    matches = season(40)
    at = T0 + timedelta(days=7 * 32)
    full = bt.Engine(matches, {})
    cut = le.EstimateEngine(matches, {})
    for e in (full, cut):
        e.walk(at, record_from=at, train_from=at - le.TRAIN)
        e.prepare(at)
    assert full.model == cut.model
    for team in (HOME, AWAY):
        a = le.estimate_side(full.h, full.model, fixture_id=1, team_id=team, competition_id=COMP, states={}, facts={})
        b = le.estimate_side(cut.h, cut.model, fixture_id=1, team_id=team, competition_id=COMP, states={}, facts={})
        assert a == b
    assert any(v > 0 for v in full.phi.values()) or full.refits > 0


def test_the_evaluation_states_its_samples_and_is_deterministic() -> None:
    matches = season(60)
    start, end = T0 + timedelta(days=7 * 40), T0 + timedelta(days=7 * 60)
    a = v2.evaluate(matches, {}, start=start, end=end)
    b = v2.evaluate(matches, {}, start=start, end=end)
    assert a == b
    assert a["version"] == v2.VERSION and a["estimate_version"] == le.VERSION and a["shadow"] is True
    assert a["fixtures_evaluated"] == 20 and a["candidates"] > 0
    assert set(a["verdicts"]) == {f.key for f in fam.FAMILIES}
    assert set(a["verdicts"].values()) <= set(v2.VERDICTS)
    shots = next(f for f in a["families"] if f["family"] == "player_shots")
    main = shots["lines"]["0.5"]
    assert main["unconditional"]["n"] > 0 and main["verdict"] == v2.INSUFICIENTE, "a toy season is never enough"
    assert all(f["status"] == fam.SHADOW for f in a["families"])


def test_a_verdict_needs_its_sample_and_an_interval_below_zero() -> None:
    enough = {"n": bt.MIN_PLAYER_MATCHES, "log_loss_diff": -0.01, "log_loss_diff_se": 0.001}
    assert v2.verdict_of(enough, events_main=bt.MIN_EVENTS)[0] == v2.MEJORA
    assert v2.verdict_of(enough | {"log_loss_diff_se": 0.01}, events_main=bt.MIN_EVENTS)[0] == v2.NO_MEJORA
    assert v2.verdict_of(enough, events_main=bt.MIN_EVENTS - 1)[0] == v2.INSUFICIENTE
    assert v2.verdict_of(enough | {"n": 10}, events_main=bt.MIN_EVENTS)[0] == v2.INSUFICIENTE


def test_the_worker_job_is_off_by_default_and_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker import scheduler

    from fbi.ops.run_watchdog import timeout_for
    from fbi.shadowjobs import player_forecast as job

    assert job.mode({}) == "off" and job.mode({job.SWITCH: "on"}) == "off" and job.mode({job.SWITCH: " Shadow "}) == "shadow"
    assert job.every_minutes({}) == 5 and job.every_minutes({"FBI_PLAYER_ENGINE_V2_MINUTES": "99"}) == 5
    tree = ast.parse(Path(scheduler.__file__).read_text())
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode" \
                and isinstance(node.test.left.func.value, ast.Name) and node.test.left.func.value.id == "pfs":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == job.JOB for n in ast.walk(body))
    assert guarded and job.JOB in scheduler.WORKER_JOB_TYPES
    assert timeout_for(job.JOB) == timedelta(minutes=20)
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._player_forecast_shadow_now()
    monkeypatch.setenv(job.SWITCH, "shadow")
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    scheduler._player_forecast_shadow_now()


def test_the_stored_row_matches_the_columns_of_the_migration() -> None:
    from fbi.shadowjobs import player_forecast as job

    r = v2.forecast_player(estimate(0.85), rate(), SHOTS_ON, opponent_id=AWAY, known_at=T0, phi=0.1, lineup_confirmed=False)[0]
    row = job.row_of(r, evaluation="E1", kickoff=T0 + timedelta(hours=20), history_matches=40, code_version="x")
    columns = [c.strip() for c in job.INSERT_SQL.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")]
    assert all(c in row for c in columns), [c for c in columns if c not in row]
    assert row["version"] == "player-engine-v2" and row["estimate_version"] == "lineup-estimate-v1" and len(row["input_hash"]) == 64
    migration = (ROOT / "migrations" / "versions" / "0163_player_forecasts.py").read_text()
    assert all(c in migration for c in columns)


def test_e6_dry_run_decides_pending_or_full_count_and_never_evaluates_early() -> None:
    d = e6.decide({"A": 600, "B": 2400}, date(2026, 11, 17))
    assert d.state == e6.PENDING and d.missing == {"A": 900, "B": 0}
    assert e6.decide({"A": 1500, "B": 1500}, date(2026, 11, 17)).state == e6.FULL_COUNT
    assert e6.decide({}, date(2027, 3, 31)).state == e6.DEADLINE_REACHED
    assert e6.decide({}, date(2026, 12, 1)).as_json()["protocol"] == "proto-int-a08-v1"


def test_e6_dry_run_reads_no_score_and_its_protocol_is_the_registered_one() -> None:
    from fbi.research import protocol

    sql = e6.DRY_RUN_SQL.lower()
    for word in ("fixture_results", "goals", "reg_goals", "score", "predictions", "consensus"):
        assert word not in sql, word
    p = protocol.require(e6.KEY)
    assert p.version == e6.PROTOCOL_VERSION
    assert "1.500" in p.min_sample and "31-mar-2027" in p.stopping
