"""The estimated starters (IA-094, AD-D04, ``lineup-estimate-v1``), without a database: a confirmed absence never starts, a doubt is a
feature and not a rule, a fact «titular» moves the odds by its rung and a rumour does not, the official line-up replaces everything,
nothing learned after the moment counts, every figure is ``sin_calibrar`` until the owner signs a competition, and the measurement
against the official line-ups (with the baseline «the same XI as the previous match») is deterministic and walks forward."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.people import availability as people
from fbi.players import availability as av
from fbi.players import lineup_estimate as le
from fbi.players.history import History, Match, PlayerMatch, SheetLine

T0 = datetime(2026, 8, 1, 18, tzinfo=UTC)
HOME, AWAY, COMP = 1, 2, 77


def squad(team: int) -> list[int]:
    return [team * 100 + i for i in range(16)]


def season(n: int = 24, seed: int = 3) -> list[Match]:
    """Two teams that play each other every week: eleven regulars (one of them rotated out a third of the time) and five on the bench."""
    rnd = random.Random(seed)
    out = []
    for k in range(n):
        lines = []
        for side, team in (("home", HOME), ("away", AWAY)):
            men = squad(team)
            xi = men[:11]
            if rnd.random() < 0.33:
                xi = [*men[:10], men[11]]
            for pid in men:
                started = pid in xi
                minutes = 90 if started else (20 if rnd.random() < 0.5 else 0)
                lines.append(PlayerMatch.make(pid, side, started, minutes, "M", {"goals": 0}))
        ko = T0 + timedelta(days=7 * k)
        out.append(Match(10_000 + k, ko, COMP, HOME, AWAY, ko + timedelta(hours=3), tuple(lines)))
    return out


def history(matches: list[Match]) -> History:
    h = History()
    for m in matches:
        h.add(m, {})
    return h


def state(pid: int, status: str, basis: str) -> people.State:
    return people.State(pid, str(pid), status, basis, "x", T0, 1)  # type: ignore[arg-type]


def test_a_confirmed_absence_never_starts_and_a_doubt_or_one_outlet_is_only_a_feature() -> None:
    h = history(season())
    model = av.StartModel()
    regular = squad(HOME)[0]
    kw: dict[str, Any] = {"fixture_id": 1, "team_id": HOME, "player_id": regular, "position": "M", "competition_id": COMP}
    free = le.estimate(h, model, **kw)
    assert free.basis == le.BASE_MINUTES and free.p_start > 0.8 and free.sample == 10
    for basis in ("oficial", "proveedor", "dos_origenes"):
        out = le.estimate(h, model, state=state(regular, "baja", basis), **kw)
        assert (out.p_start, out.p_play, out.basis, out.absence_basis) == (0.0, 0.0, le.BASE_CONFIRMED_OUT, basis)
    assert le.estimate(h, model, state=state(regular, "sancionado", "proveedor"), **kw).p_start == 0.0
    one_outlet = le.estimate(h, model, state=state(regular, "baja", "un_medio"), **kw)
    assert one_outlet.basis == le.BASE_MINUTES and one_outlet.p_start > 0, "one outlet alone is a doubt, never a rule"
    assert le.is_doubtful(state(regular, "duda", "oficial")) and not le.is_doubtful(state(regular, "disponible", "proveedor"))


def test_a_fact_moves_the_odds_by_its_rung_and_a_rumour_moves_nothing() -> None:
    h = history(season())
    rotated = squad(HOME)[10]
    kw: dict[str, Any] = {"fixture_id": 1, "team_id": HOME, "player_id": rotated, "position": "M", "competition_id": COMP}
    base = le.estimate(h, av.StartModel(), **kw)
    seen = T0

    def fact(rung: str) -> le.StarterFact:
        return le.StarterFact(rotated, rung, 9, seen)

    assert le.estimate(h, av.StartModel(), facts=[fact("rumor")], **kw).p_start == base.p_start
    ps = [le.estimate(h, av.StartModel(), facts=[fact(r)], **kw).p_start for r in ("un_medio", "dos_origenes", "oficial")]
    assert base.p_start < ps[0] < ps[1] < ps[2] < 1
    odds = base.p_start / (1 - base.p_start)
    assert ps[2] == pytest.approx(odds * 9 / (1 + odds * 9))
    both = le.estimate(h, av.StartModel(), facts=[fact("un_medio"), fact("oficial")], **kw)
    assert both.fact_rung == "oficial" and both.basis == le.BASE_FACT, "the highest rung counts, once"
    assert le.with_fact(0.0, "oficial") == 0.0 and le.with_fact(1.0, "oficial") == 1.0


def test_the_official_line_up_replaces_everything() -> None:
    h = history(season())
    a, b, c = squad(HOME)[0], squad(HOME)[12], squad(HOME)[15]
    sheet = [SheetLine(b, None, "M", True), SheetLine(a, None, "M", False)]
    est = le.estimate_side(h, av.StartModel(), fixture_id=1, team_id=HOME, competition_id=COMP, states={a: state(a, "baja", "oficial")},
                           facts={c: [le.StarterFact(c, "oficial", 1, T0)]}, sheet=sheet)
    by = {e.provider_player_id: e for e in est}
    assert set(by) == {a, b} and by[b].p_start == 1.0 and by[b].basis == av.CONFIRMED_STARTER
    assert by[a].p_start == 0.0 and by[a].basis == av.CONFIRMED_BENCH


def test_only_facts_known_by_the_moment_and_saying_he_starts_count() -> None:
    at = T0 + timedelta(hours=1)
    rows: list[dict[str, Any]] = [{"id": 1, "provider_player_id": 5, "assertion": "starts", "status": "CONFIRMED", "source_tier": "club", "origin": "web",
             "retrieved_at": T0, "published_at": T0},
            {"id": 2, "provider_player_id": 5, "assertion": "starts", "status": "PROBABLE", "source_tier": "media", "origin": "web",
             "retrieved_at": at + timedelta(seconds=1), "published_at": T0},                                   # learned later
            {"id": 3, "provider_player_id": 6, "assertion": "out", "status": "CONFIRMED", "source_tier": "club", "origin": "web",
             "retrieved_at": T0, "published_at": T0},                                                          # not a start
            {"id": 4, "provider_player_id": None, "assertion": "starts", "status": "CONFIRMED", "source_tier": "club", "origin": "web",
             "retrieved_at": T0, "published_at": T0},                                                          # nobody identified
            {"id": 5, "provider_player_id": 7, "claim_type": "STARTER", "status": "RUMOR", "source_tier": "aggregator", "origin": "web",
             "subject_type": "PLAYER", "retrieved_at": T0, "published_at": T0},
            {"id": 6, "provider_player_id": 8, "assertion": "starts", "status": "CONFIRMED", "source_tier": "provider", "origin": "provider",
             "retrieved_at": T0, "published_at": T0}]                                                          # the provider's sheet
    facts = le.facts_from_rows(rows, at=at)
    assert {p: [(f.rung, f.evidence_id, f.typed) for f in v] for p, v in facts.items()} == {5: [("oficial", 1, False)],
                                                                                            7: [("rumor", 5, True)]}


def test_every_figure_is_sin_calibrar_until_the_owner_signs_a_competition() -> None:
    assert not le.CALIBRATED and le.seal_of(COMP) == le.SIN_CALIBRAR
    est = le.estimate(history(season()), av.StartModel(), fixture_id=1, team_id=HOME, player_id=squad(HOME)[0], position="M",
                      competition_id=COMP)
    assert est.seal == le.SIN_CALIBRAR and est.as_json()["version"] == le.VERSION == "lineup-estimate-v1"
    assert "reason" not in str(est.as_json()), "no health detail travels with an estimate"


def test_the_providers_listing_becomes_ia_091s_state_as_of_the_moment() -> None:
    obs: dict[tuple[int, int], list[tuple[datetime, str, str | None]]] = {(1, 5): [(T0, "LISTED", "Missing Fixture"), (T0 + timedelta(hours=2), "CLEARED", None)],
           (1, 6): [(T0, "LISTED", "Questionable")]}
    early = people.resolve(le.provider_states(obs, 1, [5, 6, 7], T0 + timedelta(hours=1)))
    assert {p: (s.status, s.basis) for p, s in early.items()} == {5: ("baja", "proveedor"), 6: ("duda", "proveedor")}
    late = people.resolve(le.provider_states(obs, 1, [5, 6], T0 + timedelta(hours=3)))
    assert set(late) == {6}


def test_the_measurement_walks_forward_beats_nothing_by_construction_and_is_the_same_twice() -> None:
    matches = season(30)
    start = matches[20].kickoff - timedelta(hours=1)
    end = matches[-1].kickoff + timedelta(hours=1)
    official = {(m.fixture_id, side): frozenset(p.player_id for p in m.lines if p.side == side and p.started)
                for m in matches if m.kickoff >= start for side in ("home", "away")}
    doc = le.measure(matches, {}, start=start, end=end, official=official)
    again = le.measure(matches, {}, start=start, end=end, official=official)
    assert doc == again
    t = doc["total"]
    assert t["sides"] == 2 * sum(1 for m in matches if m.kickoff >= start) and t["n"] >= 11 * t["sides"]
    assert t["starters"] == 11 * t["sides"] and t["unseen_starters"] == 0
    assert 0 <= t["brier"] <= 1 and 0 <= t["brier_baseline"] <= 1
    assert t["brier"] < t["brier_baseline"], "with one rotation a third of the time, the recent share beats «the same XI as last time»"
    assert 0.8 <= t["top11_precision"] <= 1 and t["baseline_xi_precision"] <= 1
    comps = doc["competitions"]
    assert comps["n"] == 1 and comps["detail"][COMP]["beats_baseline"]
    assert t["sides"] < le.MIN_SIDES and comps["with_sample"] == 0 and comps["beating_baseline"] == [], \
        "a competition below the preregistered sample has no verdict"
    assert le.brier_gain(doc) == pytest.approx(t["brier_baseline"] - t["brier"], abs=1e-5)


def test_the_measurement_knows_nothing_of_the_match_it_estimates() -> None:
    """Changing who started the estimated match changes the score, never the estimate: the walk adds a match only once it was known."""
    matches = season(26)
    last = matches[-1]
    start, end = last.kickoff - timedelta(hours=1), last.kickoff + timedelta(hours=1)
    flipped = Match(last.fixture_id, last.kickoff, last.competition_id, last.home_team_id, last.away_team_id, last.available_at,
                    tuple(PlayerMatch.make(p.player_id, p.side, not p.started, p.minutes, p.position, {"goals": 0}) for p in last.lines))
    official = {(last.fixture_id, "home"): frozenset(squad(HOME)[:11])}
    a = le.measure(matches, {}, start=start, end=end, official=official)
    b = le.measure([*matches[:-1], flipped], {}, start=start, end=end, official=official)
    assert a["total"]["brier"] == b["total"]["brier"] and a["total"]["mean_p"] == b["total"]["mean_p"]


# -- the worker's job ----------------------------------------------------------------------------------------------------------------

def test_the_job_is_off_unless_it_says_shadow_and_has_the_windows_of_e1_and_e4() -> None:
    from fbi.shadowjobs import lineup_estimate as job

    assert job.mode({}) == "off" and job.mode({"FBI_LINEUP_ESTIMATE": "on"}) == "off" and job.mode({"FBI_LINEUP_ESTIMATE": "shadow"}) == "shadow"
    assert job.every_minutes({}) == 5 and job.every_minutes({"FBI_LINEUP_ESTIMATE_MINUTES": "99"}) == 5
    ko = T0 + timedelta(days=1)
    assert [job.evaluation_due(ko, ko - d) for d in (timedelta(hours=25), timedelta(hours=13), timedelta(hours=11),
                                                     timedelta(minutes=15), timedelta(minutes=9))] == [None, "E1", None, "E4", None]


def test_the_worker_schedules_the_job_only_in_the_shadow_and_it_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import ast
    from pathlib import Path

    from apps.worker import scheduler

    from fbi.ops.run_watchdog import timeout_for
    from fbi.shadowjobs import lineup_estimate as job

    tree = ast.parse(Path(scheduler.__file__).read_text())
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode" \
                and isinstance(node.test.left.func.value, ast.Name) and node.test.left.func.value.id == "les":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == "lineup_estimate_shadow" for n in ast.walk(body))
    assert guarded and "lineup_estimate_shadow" in scheduler.WORKER_JOB_TYPES
    assert timeout_for("lineup_estimate_shadow") == timedelta(minutes=20)
    monkeypatch.delenv(job.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._lineup_estimate_shadow_now()
    monkeypatch.setenv(job.SWITCH, "shadow")
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    scheduler._lineup_estimate_shadow_now()


def test_the_starters_of_a_match_are_read_from_its_sheet_when_asked() -> None:
    """The statistics said 14,3 starters per side where the sheets said 10,8 (production, 17-nov-2026): ``prefer_sheet`` reads the sheet."""
    from fbi.players.history import rows_to_matches

    def r(pid: int, is_sub: bool | None, is_starter: bool | None) -> tuple[object, ...]:
        return (1, T0, COMP, HOME, AWAY, pid, "home", 30, is_sub, is_starter, "M", None, 0, 0, 0, 0, 0, 0, 0, None, T0 + timedelta(hours=3))

    rows = [r(1, False, False), r(2, False, True), r(3, None, True), r(4, True, None)]
    stats = {p.player_id: p.started for p in rows_to_matches(rows)[0].lines}
    sheet = {p.player_id: p.started for p in rows_to_matches(rows, prefer_sheet=True)[0].lines}
    assert stats == {1: True, 2: True, 3: True, 4: False}, "player-engine-v1 as it was"
    assert sheet == {1: False, 2: True, 3: True, 4: False}
