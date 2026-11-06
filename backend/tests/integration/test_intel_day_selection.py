"""Plan F0, defect 12, on a real database: PrediGol Intelligence's picks of the day and its parlays, as the document says.

The document promised "up to five approved selections by score, one per match, at most two per competition", a parlay of
two approved legs from different competitions and a PICK PREMIUM stake of 1.50 u. The selector (``decision.select_day``)
had no test with a single approved selection. Here eight selections of the daily-records world (F1-F3 in one
competition, F4-F7 in the other; F7 is the next day) are decided the way a run decides them (every selection through the
real ``evaluate``, the batch through ``correlate``, each one ``store``d as of its own moment):

    selection  line   books  p     odds  state             score
    F1a        Over 2.5   8  0.62  2.10  CANDIDATO_PARLAY   81.0   the best of its match
    F1b        Over 1.5   8  0.62  2.10  CAUTELA            79.1   a second selection of the SAME match: filter 8
    F2         Over 2.5   6  0.60  2.10  CANDIDATO_PARLAY   79.0   its decision is 40 minutes old
    F3         Over 2.5   4  0.58  2.10  CANDIDATO_PARLAY   77.0
    F4         Over 2.5   7  0.66  2.00  PICK_PREMIUM       86.0   walk-forward CLV positive: the premium one
    F5         Over 2.5   5  0.64  2.05  CANDIDATO_PARLAY   78.0
    F6         Over 2.5   3  0.70  2.40  APROBADO           76.0   approved, but above the parlay odds range
    F7         Over 2.5   8  0.62  2.10  CANDIDATO_PARLAY   81.0   tomorrow's match

The transaction is rolled back afterwards."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from itertools import product
from typing import Any

import psycopg
import pytest

from fbi.intel import decision, stake
from fbi.intel.decision import Evaluated, evaluate
from tests.unit.test_decision_rules import MODEL, key_of, row
from tests.unit.test_decision_rules import world as rules_world

from .conftest import Seed
from .test_daily_records import AT, World

NOW = AT
FRESH = timedelta(minutes=5)
STALE = timedelta(minutes=40)
"""How old a decision is when the day is selected: the usual one, and one older than the day's freshness limit."""

# label, match, line, books, width, p, odds, premium?, hours to kick-off
SPEC = [
    ("F1a", "F1", "2.5", 8, 0.04, 0.62, 2.10, False, 2),
    ("F1b", "F1", "1.5", 8, 0.12, 0.62, 2.10, False, 2),
    ("F2", "F2", "2.5", 6, 0.04, 0.60, 2.10, False, 4),
    ("F3", "F3", "2.5", 4, 0.04, 0.58, 2.10, False, 6),
    ("F4", "F4", "2.5", 7, 0.04, 0.66, 2.00, True, 8),
    ("F5", "F5", "2.5", 5, 0.04, 0.64, 2.05, False, 10),
    ("F6", "F6", "2.5", 3, 0.04, 0.70, 2.40, False, 13),
    ("F7", "F7", "2.5", 8, 0.04, 0.62, 2.10, False, 30),
]


def decide(db: psycopg.Connection[Any], seed: Seed, w: World, *, ages: dict[str, timedelta] | None = None,
           only: tuple[str, ...] = (), correlated: bool = True,
           tweak: dict[str, dict[str, Any]] | None = None) -> dict[str, tuple[int, Evaluated]]:
    """Decide the specification the way ``decision.decide`` does: evaluate every selection, ``correlate`` the batch
    (filter 8), store each decision. Each one is decided AS OF the moment it is stored: ``FRESH`` before ``NOW``, or
    ``ages[label]`` (F2 is ``STALE`` unless said otherwise), and reads a price five minutes older than itself.
    Decisions made at different moments are different runs, so each moment is correlated on its own. ``tweak`` changes
    keywords of a selection's ``row`` (``{"F6": {"width": 0.30}}``)."""
    ages = {"F2": STALE} | (ages or {})
    runs: dict[timedelta, list[tuple[str, Evaluated]]] = defaultdict(list)
    for label, name, line, books, width, p, odds, premium, hours in SPEC:
        if only and label not in only:
            continue
        age = ages.get(label, FRESH)
        fid = w.fixtures[name]
        kw: dict[str, Any] = {
            "fixture": fid, "odds": odds, "p_model": p, "p_fair": min(p - 0.05, 1.2 / odds), "minutes": hours * 60,
            "books": books, "width": width, "line": Decimal(line), "price_age": age + timedelta(minutes=5)}
        r = row(**kw | (tweak or {}).get(label, {})) | {
            "pick_id": w.picks[name], "model_version_id": seed.model_version_id,
            "best_bookmaker_id": seed.bookmaker_id}
        known = replace(rules_world(fixture=fid, rule_clv=0.03 if premium else -0.01, odds=odds), at=NOW - age)
        runs[age].append((label, evaluate(known, key_of(fid, Decimal(line)), {MODEL: r})))
    out: dict[str, tuple[int, Evaluated]] = {}
    for age, decided in runs.items():
        if correlated:
            decision.correlate([e for _, e in decided])
        for label, e in decided:
            stored = decision.store(db, e, at=NOW - age)
            assert stored is not None, label
            out[label] = (stored, e)
    return out


def picks_of_the_day(db: psycopg.Connection[Any]) -> list[tuple[int, int, Decimal, int]]:
    """(rank, fixture, stake units, source decision) of today's PICKS DEL DÍA, in rank order."""
    return db.execute("SELECT s.rank, d.fixture_id, s.stake_units, (s.detail->>'source_decision')::bigint "
                      "FROM intel.day_selections s JOIN intel.decisions d ON d.id = s.decision_ids[1] "
                      "WHERE s.kind = 'pick' ORDER BY s.rank").fetchall()


def _calibrated(p_cal: float | None, label: str) -> float:
    assert p_cal is not None, f"{label} is approved, so it carries a calibrated probability"
    return p_cal


def test_the_states_of_the_world(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The specification means what it says: F4 alone is PREMIUM, filter 8 demotes F1b (the same match as the better
    scored F1a), F6 is approved but not a parlay leg, and the scores rank the selections as the table says."""
    made = decide(db, seed, World(db, seed))
    assert {k: v[1].state for k, v in made.items()} == {
        "F1a": "CANDIDATO_PARLAY", "F1b": "CAUTELA", "F2": "CANDIDATO_PARLAY", "F3": "CANDIDATO_PARLAY",
        "F4": "PICK_PREMIUM", "F5": "CANDIDATO_PARLAY", "F6": "APROBADO", "F7": "CANDIDATO_PARLAY"}
    assert "correlated_same_match" in made["F1b"][1].reasons
    assert {k for k, v in made.items() if v[1].premium} == {"F4"}
    assert {k for k, v in made.items() if v[1].parlay_eligible} == {"F1a", "F2", "F3", "F4", "F5", "F7"}
    scores = {k: v[1].score.total for k, v in made.items() if v[1].score is not None}
    assert [k for k in sorted(scores, key=lambda k: -scores[k]) if k != "F7"] == [
        "F4", "F1a", "F1b", "F2", "F5", "F3", "F6"], scores


def test_the_days_picks_are_by_score_one_per_match_at_most_two_per_competition_and_never_padded(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    made = decide(db, seed, w)
    added, _ = decision.select_day(db, at=NOW, ready=True)
    f = w.fixtures
    picks = picks_of_the_day(db)
    assert [p[1] for p in picks] == [f["F4"], f["F1"], f["F5"], f["F3"]], (
        "by score: F4, F1a (F1b is the same match), F5 and F3; F2's decision is stale, F6 would be a third of its "
        "competition, F7 plays tomorrow")
    assert [p[3] for p in picks] == [made[k][0] for k in ("F4", "F1a", "F5", "F3")], "the decisions it chose"
    assert added == len(picks) == 4 < decision.MAX_PICKS, "four is all there is: the day is never padded"
    assert [p[0] for p in picks] == [1, 2, 3, 4]
    by_competition = db.execute(
        "SELECT cs.competition_id, count(*) FROM intel.day_selections s JOIN intel.decisions d ON d.id = s.decision_ids[1]"
        " JOIN core.fixtures fx ON fx.id = d.fixture_id JOIN core.competition_seasons cs ON cs.id = "
        "fx.competition_season_id WHERE s.kind = 'pick' GROUP BY 1").fetchall()
    assert sorted(n for _, n in by_competition) == [2, 2] and max(n for _, n in by_competition) <= \
        decision.MAX_PER_COMPETITION
    stakes = {p[1]: p[2] for p in picks}
    assert stakes[f["F4"]] == Decimal(str(stake.CAPS["PICK_PREMIUM"])) == Decimal("1.5"), "the PREMIUM pick: 1.50 u"
    assert {stakes[f[m]] for m in ("F1", "F5", "F3")} == {Decimal(str(stake.CAPS["PICK_DEL_DIA"]))} == {Decimal("1.0")}
    chosen_state = db.execute("SELECT DISTINCT d.state FROM intel.day_selections s JOIN intel.decisions d "
                              "ON d.id = s.decision_ids[1] WHERE s.kind = 'pick'").fetchall()
    assert chosen_state == [("PICK_DEL_DIA",)], "a chosen selection is frozen as a new decision of its own state"
    assert decision.select_day(db, at=NOW, ready=True) == (0, 0), "chosen once, then frozen"
    assert len(picks_of_the_day(db)) == 4


def test_a_competition_may_have_more_when_the_cap_allows_it_but_never_more_than_five_picks(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    decide(db, seed, w, ages={"F2": FRESH})
    monkeypatch.setattr(decision, "MAX_PER_COMPETITION", 3)
    added, _ = decision.select_day(db, at=NOW, ready=True)
    f = w.fixtures
    picks = picks_of_the_day(db)
    assert added == len(picks) == decision.MAX_PICKS == 5
    assert [p[1] for p in picks] == [f["F4"], f["F1"], f["F2"], f["F5"], f["F3"]], (
        "F6 would fit its competition's cap, but it has the lowest score and the day already has five")


def test_two_approved_selections_of_one_match_never_both_reach_the_day(db: psycopg.Connection[Any],
                                                                       seed: Seed) -> None:
    """Filter 8 normally keeps just one approved selection per match. If two reach the table anyway (decisions of
    different runs), the day still takes only the better scored: F1a, not F1b."""
    w = World(db, seed)
    made = decide(db, seed, w, correlated=False)
    assert made["F1b"][1].state == "CANDIDATO_PARLAY", "F1b was not demoted: both selections of F1 are approved"
    decision.select_day(db, at=NOW, ready=True)
    f = w.fixtures
    picks = picks_of_the_day(db)
    assert [p[1] for p in picks] == [f["F4"], f["F1"], f["F5"], f["F3"]]
    assert [p[3] for p in picks] == [made[k][0] for k in ("F4", "F1a", "F5", "F3")], "F1a, never F1b"


@pytest.mark.parametrize(("age", "chosen"), [
    (decision.DAY_FRESH, 1),
    (decision.DAY_FRESH + timedelta(minutes=1), 0),
], ids=["30 minutes old: still fresh", "31 minutes old: stale"])
def test_a_decision_is_chosen_only_if_it_is_at_most_thirty_minutes_old(
        db: psycopg.Connection[Any], seed: Seed, age: timedelta, chosen: int) -> None:
    assert timedelta(minutes=30) == decision.DAY_FRESH
    w = World(db, seed)
    decide(db, seed, w, only=("F2",), ages={"F2": age})
    assert decision.select_day(db, at=NOW, ready=True) == (chosen, 0)


@pytest.mark.parametrize(("state", "tweak", "chosen"), [
    ("APROBADO", {}, 1),
    ("CAUTELA", {"width": 0.30}, 0),
    ("RECHAZADO", {"books": 2}, 0),
    ("INVESTIGACION", {"price_age": timedelta(hours=4)}, 0),
], ids=["approved: the control", "cautious: a too wide interval", "rejected: a thin market",
        "under investigation: a stale price"])
def test_only_approved_selections_reach_the_day(db: psycopg.Connection[Any], seed: Seed, state: str,
                                                tweak: dict[str, Any], chosen: int) -> None:
    """F6 alone, decided five minutes ago: approved it is the day's pick; cautious, rejected or under investigation
    it is not (the selections of the other states are never picks)."""
    w = World(db, seed)
    made = decide(db, seed, w, only=("F6",), tweak={"F6": tweak})
    assert made["F6"][1].state == state
    assert decision.select_day(db, at=NOW, ready=True) == (chosen, 0)


@pytest.mark.parametrize(("minutes", "chosen"), [(9, 0), (11, 1)],
                         ids=["9 minutes to kick-off: too late", "11 minutes: still in time"])
def test_a_match_about_to_kick_off_is_not_chosen(db: psycopg.Connection[Any], seed: Seed, minutes: int,
                                                chosen: int) -> None:
    """The decision was made five minutes ago, when the match was still 14 or 16 minutes away (the data filter asks for
    at least 10); the day is chosen now, and a match 10 minutes or less from kick-off is no longer a pick."""
    w = World(db, seed)
    made = decide(db, seed, w, only=("F1a",), tweak={"F1a": {"minutes": minutes}})
    assert made["F1a"][1].state == "CANDIDATO_PARLAY"
    assert decision.select_day(db, at=NOW, ready=True) == (chosen, 0)


def test_nothing_is_chosen_while_the_day_is_not_ready(db: psycopg.Connection[Any], seed: Seed) -> None:
    decide(db, seed, World(db, seed))
    assert decision.select_day(db, at=NOW, ready=False) == (0, 0)
    assert db.execute("SELECT count(*) FROM intel.day_selections").fetchone() == (0,)


def test_the_parlays_multiply_two_calibrated_probabilities_of_different_competitions(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    made = decide(db, seed, w)
    _, parlays = decision.select_day(db, at=NOW, ready=True)
    f = w.fixtures
    rows = db.execute("SELECT s.rank, s.decision_ids, s.odds, s.p_est, s.ev, s.stake_units, s.correlation, s.detail "
                      "FROM intel.day_selections s WHERE s.kind = 'parlay' ORDER BY s.rank").fetchall()
    assert parlays == len(rows) == decision.MAX_PARLAYS == 2

    # the legs: approved, parlay-eligible, decided within 30 minutes, playing today. F1b is demoted (same match as F1a),
    # F2's decision is stale, F6 is above the odds range and F7 plays tomorrow.
    ids = {k: v[0] for k, v in made.items()}
    eligible = ["F1a", "F3", "F4", "F5"]
    competition = {"F1a": "A", "F3": "A", "F4": "B", "F5": "B"}
    p = {k: _calibrated(made[k][1].p_cal, k) for k in eligible}
    odds = {k: float(made[k][1].row["best_odds"]) for k in eligible}
    options = sorted(((p[a] * p[b] * odds[a] * odds[b] - 1, a, b) for a, b in product(eligible, eligible)
                      if competition[a] == "A" and competition[b] == "B"), reverse=True)
    expected: list[tuple[str, str]] = []
    used: set[str] = set()
    for ev, a, b in options:
        if ev >= decision.PARLAY_MIN_EV and a not in used and b not in used and len(expected) < decision.MAX_PARLAYS:
            expected.append((a, b))
            used |= {a, b}
    assert expected == [("F1a", "F4"), ("F3", "F5")], "the best pair first, then the best one that does not repeat a leg"
    assert [tuple(r[1]) for r in rows] == [(ids[a], ids[b]) for a, b in expected]
    for (_rank, _legs, combined, joint, ev, units, correlation, detail), (a, b) in zip(rows, expected, strict=True):
        pa, pb = p[a], p[b]
        assert pa is not None and pb is not None
        assert float(joint) == pytest.approx(pa * pb, abs=1e-6), "the product of the two calibrated probabilities"
        assert float(combined) == pytest.approx(odds[a] * odds[b], abs=1e-3)
        assert float(ev) == pytest.approx(pa * pb * odds[a] * odds[b] - 1, abs=1e-6) and float(ev) >= decision.PARLAY_MIN_EV
        assert units <= Decimal(str(stake.PARLAY_CAP)) == Decimal("0.25"), "a parlay never stakes more than 0.25 u"
        assert correlation["pairs"] == [] and "independent across competitions" in correlation["method"]
        assert len(detail["legs"]) == 2
    legs = [{leg["fixture"] for leg in r[7]["legs"]} for r in rows]
    assert legs == [{f["F1"], f["F4"]}, {f["F3"], f["F5"]}], "one leg per competition; no match in two parlays"


# ── BE-003: the owner's competitions first (daily-set-v7, comp-priority-v1) ──────────────────────────────────────

def leagues(db: psycopg.Connection[Any], a: int, b: int) -> None:
    """Give the world's two competitions real API-Football league ids: ``a`` for F1-F3, ``b`` for F4-F7."""
    for old, new in ((97401, a), (97402, b)):
        db.execute("UPDATE core.competitions SET provider_league_id = %s WHERE provider_league_id = %s", (new, old))


def chosen(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Today's picks in rank order: (fixture, odds, p_est, ev, stake, score, source decision), then the frozen
    decision's state and numbers (state, p_cal, ev_cal, edge_cal, score, premium) and its source's (the same six)."""
    return db.execute(
        "SELECT d.fixture_id, s.odds, s.p_est, s.ev, s.stake_units, s.detail->'score', "
        "(s.detail->>'source_decision')::bigint, d.state, d.p_cal, d.ev_cal, d.edge_cal, d.score, d.premium, "
        "src.state, src.p_cal, src.ev_cal, src.edge_cal, src.score, src.premium "
        "FROM intel.day_selections s JOIN intel.decisions d ON d.id = s.decision_ids[1] "
        "JOIN intel.decisions src ON src.id = (s.detail->>'source_decision')::bigint "
        "WHERE s.kind = 'pick' ORDER BY s.rank").fetchall()


def decisions_but_the_chosen(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT id, state, p_cal, ev_cal, edge_cal, score, stake_units, premium, parlay_eligible "
                      "FROM intel.decisions WHERE checkpoint <> 'selection' ORDER BY id").fetchall()


def test_the_champions_league_goes_first_even_with_a_lower_score_and_nothing_else_changes(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    """F1-F3 become the Champions League (group 1), F4-F7 an unlisted league (group 4). By score the day was F4, F1a,
    F5, F3; with the priority it is F1a and F3 (the Champions League, best score first, its cap of two reached), then
    F4 and F5. The same four selections, frozen with the same numbers: only the order changed."""
    w = World(db, seed)
    made = decide(db, seed, w)
    f = w.fixtures
    with db.transaction(force_rollback=True):
        decision.select_day(db, at=NOW, ready=True)
        before = {r[0]: r for r in chosen(db)}
        assert list(before) == [f["F4"], f["F1"], f["F5"], f["F3"]], "the control: daily-set-v6's order"
    leagues(db, 2, 97402)
    untouched = decisions_but_the_chosen(db)
    added, _ = decision.select_day(db, at=NOW, ready=True)
    after = chosen(db)
    assert added == 4 and [r[0] for r in after] == [f["F1"], f["F3"], f["F4"], f["F5"]]
    assert [r[6] for r in after] == [made[k][0] for k in ("F1a", "F3", "F4", "F5")]
    for r in after:
        assert r == before[r[0]], "odds, probability, EV, stake and score frozen exactly as without the priority"
        assert r[7] == "PICK_DEL_DIA" and r[8:13] == r[14:19], "the frozen decision copies its source's numbers"
    assert decisions_but_the_chosen(db) == untouched, "no decision of the day was rewritten"
    rows = db.execute("SELECT rank, rule_version, detail->>'priority', (detail->>'priority_group')::int "
                      "FROM intel.day_selections WHERE kind = 'pick' ORDER BY rank").fetchall()
    assert rows == [(1, "daily-set-v7", "comp-priority-v1", 1), (2, "daily-set-v7", "comp-priority-v1", 1),
                    (3, "daily-set-v7", "comp-priority-v1", 4), (4, "daily-set-v7", "comp-priority-v1", 4)]


@pytest.mark.parametrize(("a", "b", "order"), [
    (97401, 97402, ("F4", "F1", "F5", "F3")),
    (32, 3, ("F4", "F5", "F1", "F3")),
    (3, 32, ("F1", "F3", "F4", "F5")),
    (39, 140, ("F4", "F1", "F5", "F3")),
], ids=["no priority competition: score order, as before", "qualifiers (3) after the Europa League (2)",
        "the Europa League (2) before the qualifiers (3)", "two group-1 leagues: score order"])
def test_the_groups_order_the_day_and_the_caps_still_hold(db: psycopg.Connection[Any], seed: Seed, a: int, b: int,
                                                           order: tuple[str, ...]) -> None:
    w = World(db, seed)
    decide(db, seed, w)
    if a == 39:  # the session's seed already holds 39: free it for this test (rolled back)
        db.execute("UPDATE core.competitions SET provider_league_id = 97499 WHERE provider_league_id = 39")
    leagues(db, a, b)
    decision.select_day(db, at=NOW, ready=True)
    assert [r[0] for r in chosen(db)] == [w.fixtures[m] for m in order]
    per_competition = db.execute(
        "SELECT count(*) FROM intel.day_selections s JOIN intel.decisions d ON d.id = s.decision_ids[1] "
        "JOIN core.fixtures fx ON fx.id = d.fixture_id JOIN core.competition_seasons cs "
        "ON cs.id = fx.competition_season_id WHERE s.kind = 'pick' GROUP BY cs.competition_id").fetchall()
    assert max(n for (n,) in per_competition) <= decision.MAX_PER_COMPETITION


def test_the_priority_never_takes_more_than_five(db: psycopg.Connection[Any], seed: Seed,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Three a competition and F2 fresh: six approved selections of today for five places. The Champions League's
    three go first, then the best two of the other league; F6, the lowest of group 4, stays out."""
    w = World(db, seed)
    decide(db, seed, w, ages={"F2": FRESH})
    monkeypatch.setattr(decision, "MAX_PER_COMPETITION", 3)
    leagues(db, 2, 97402)
    added, _ = decision.select_day(db, at=NOW, ready=True)
    f = w.fixtures
    assert added == decision.MAX_PICKS == 5
    assert [r[0] for r in chosen(db)] == [f["F1"], f["F2"], f["F3"], f["F4"], f["F5"]]


def test_a_day_begun_under_daily_set_v6_is_only_completed(db: psycopg.Connection[Any], seed: Seed,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """The day of the change: F4 was already frozen under daily-set-v6. daily-set-v7 counts it against the caps and
    only fills the places left, so the day never holds more than five picks nor F4 twice."""
    w = World(db, seed)
    decide(db, seed, w, only=("F4",))
    monkeypatch.setattr(decision, "RULE_DAY", decision.RULE_V6)
    assert decision.select_day(db, at=NOW, ready=True)[0] == 1
    monkeypatch.undo()
    decide(db, seed, w, only=("F1a", "F3", "F5"))
    assert decision.select_day(db, at=NOW, ready=True)[0] == 3
    f = w.fixtures
    rows = db.execute("SELECT s.rank, s.rule_version, d.fixture_id FROM intel.day_selections s "
                      "JOIN intel.decisions d ON d.id = s.decision_ids[1] WHERE s.kind = 'pick' "
                      "ORDER BY s.rank").fetchall()
    assert rows == [(1, "daily-set-v6", f["F4"]), (2, "daily-set-v7", f["F1"]), (3, "daily-set-v7", f["F5"]),
                    (4, "daily-set-v7", f["F3"])]
