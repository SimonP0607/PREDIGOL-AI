"""The page of the families in shadow (plan F10.17 and F11.11, ``fbi.api.services.families``): the pure parts, and the facts it holds about the
families without importing them.

The page cannot import ``fbi.families`` or ``fbi.familydecisions`` - a package that serves the console does not bring the research into its import
cycle (``test_architecture``) - so which families there are, how a market key maps to the rule that grades it, which steps they run in and which
versions they carry are written in the service. Here each of those is held equal to the code it describes. The query and the route, in a real
database, are in ``tests/integration/test_intel_families.py``."""

from __future__ import annotations

import typing
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.api.routers import intelligence as router
from fbi.api.services import families as svc
from fbi.api.services import family_rules
from fbi.core import decision_versions as versions
from fbi.families import forecast, score
from fbi.families.fit import NO_DISPERSION, prediction
from fbi.familydecisions import decide as fd
from fbi.familydecisions import research
from fbi.intel import factors
from fbi.market import catalogue
from fbi.market.rules import RULES_BY_MEASURE
from fbi.odds.quote_taxonomy import extracted_specs

AT = datetime(2035, 3, 3, 21, 0, tzinfo=UTC)
AVAILABLE = frozenset(catalogue.key_defs(list(extracted_specs())))


# ── what the page holds about the families, held equal to the families ───────────────────────────────────────────────────────

def test_the_families_are_the_ones_that_decide_in_the_order_the_console_shows_them() -> None:
    assert family_rules.FAMILIES == tuple(fd.SPECS) == tuple(s.family for s in forecast.SPECS)
    assert typing.get_args(router.Family) == family_rules.FAMILIES, "the route accepts exactly the families there are"
    assert typing.get_args(router.FamilyState) == svc.STATES == ("INVESTIGACION", "RECHAZADO")


def test_the_versions_are_those_of_the_cycle_of_the_families() -> None:
    assert svc.FORECAST_VERSION == forecast.VERSION == fd.FORECAST_VERSION
    assert (versions.DECISION_FAMILIES, versions.OUTCOME_FAMILIES, versions.POSTMORTEM_FAMILIES, versions.MEMORY_FAMILIES) == (
        "decision-fam-v1", "outcome-fam-v1", "pm-fam-v1", "memory-fam-v1")


def test_the_steps_are_the_ones_the_worker_hands_to_its_jobs_in_the_order_they_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})

    class Conn:
        pass

    decide = scheduler.family_decide_steps(Conn(), AT)  # type: ignore[arg-type]
    nightly = scheduler.family_nightly_steps(Conn(), AT)  # type: ignore[arg-type]
    named = [name for steps in (decide, nightly) for group in steps.values() for name, _ in group]
    assert tuple(named) == svc.STEPS
    assert set(svc.STEP_JOBS) == {"decide", "nightly"}


def test_the_defaults_of_the_page_are_the_ones_the_owner_is_told() -> None:
    """A window of two weeks, at most four months, and the twenty-five competitions and referees with the most post-mortems: changing one of them is a
    decision about what the owner reads, not a tuning."""
    assert (svc.DEFAULT_DAYS, svc.MAX_DAYS, svc.MEMORY_TOP) == (14, 120, 25)


def test_a_decision_is_never_taken_earlier_than_the_lead_the_query_allows() -> None:
    assert svc.LEAD >= fd.HORIZON, "the bound on the moment of the decision lets the index work; it may not cut a decision the horizon allows"
    assert timedelta(days=1) <= svc.STEPS_LOOKBACK and svc.STEP_RUNS >= 4, "an hourly pass is among the last four runs of a job of every quarter hour"


def test_the_measures_of_a_family_are_those_its_forecasts_are_graded_on() -> None:
    by_family: dict[str, set[str]] = {}
    for spec in forecast.SPECS:
        by_family.setdefault(spec.family, set()).update(spec.measures)
    for family, measures in by_family.items():
        assert measures <= set(family_rules.MEASURES[family]), (family, measures)
    assert "goals_halves" in family_rules.MEASURES["GOALS_HALF"], "HT/FT and the highest scoring half read both halves"
    assert set(family_rules.MEASURES) == set(family_rules.FAMILIES)
    assert all(m in RULES_BY_MEASURE for measures in family_rules.MEASURES.values() for m in measures)


def families_keys() -> dict[str, set[str]]:
    """Every market key each family states, built the way the families build them."""
    first, second = prediction(0.55, 0.40, NO_DISPERSION), prediction(0.70, 0.55, NO_DISPERSION)
    return {spec.family: {m.market_key for m in spec.build([first, second], AVAILABLE)} for spec in forecast.SPECS}


def test_every_key_a_family_states_maps_to_the_rule_the_scoreboard_grades_it_with() -> None:
    keys = families_keys()
    assert set(keys) == set(family_rules.FAMILIES) and all(keys.values()), "the test must see the keys of every family, or it proves nothing"
    assert len(keys["GOALS_HALF"]) >= 18 and any(k.startswith("CORNERS_") for k in keys["CORNERS"])
    for family, found in keys.items():
        for key in sorted(found):
            assert family_rules.measure_of(key) == score.measure_of(key), key
            rule = family_rules.rule_of(key)
            assert rule is not None and rule.liquidable and rule.measure in family_rules.MEASURES[family], (family, key)
            assert rule.key in svc.rules_for(family)


def test_a_key_the_scoreboard_cannot_read_has_no_rule_here_either() -> None:
    """Every shape a catalogue key can take - each prefix, kind, side and half - agrees with ``fbi.families.score.measure_of``: the same measure where
    it reads the key, none where it raises."""
    kinds = [abbreviation for abbreviation, _ in catalogue.KINDS.values()]
    prefixes = ["", "CORNERS_", "CARDS_", "YELLOW_", "RED_", "POINTS_", "SOT_", "SHOTS_", "FOULS_", "OFFSIDES_", "SAVES_"]
    checked = 0
    for prefix in prefixes:
        for kind in kinds:
            for side in ("", "_HOME", "_AWAY"):
                for half in ("", "_1H", "_2H"):
                    key = f"{prefix}{kind}{side}{half}"
                    try:
                        expected: str | None = score.measure_of(key)
                    except ValueError:
                        expected = None
                    assert family_rules.measure_of(key) == expected, key
                    checked += 1
    assert checked == len(prefixes) * len(kinds) * 9 and checked > 500
    for key in ("HTFT", "HSH", "HSH_HOME", "HSH_AWAY"):
        assert family_rules.measure_of(key) == score.measure_of(key) == "goals_halves"
    assert family_rules.HALVES == score.HALVES_KEYS


def test_the_rules_that_are_shown_say_what_is_measured_and_from_which_columns() -> None:
    shown = svc.rules_of_families()
    assert sorted(shown) == ["cards_lines_ft@v1", "corners_ft@v1", "goals_1h@v1", "goals_2h@v1", "goals_halves@v1", "yellow_ft@v1"]
    corners = shown["corners_ft@v1"]
    assert corners["measure"] == "corners_ft" and corners["period"] == "FT" and corners["liquidable"] is True
    assert corners["columns"] == ["corners_ft_home", "corners_ft_away"] and "corners" in corners["convention"]
    halves = shown["goals_halves@v1"]
    assert halves["columns"] == ["goals_1h_home", "goals_1h_away", "goals_2h_home", "goals_2h_away"] and halves["note"]
    assert svc.rules_for("CARDS") == ["cards_lines_ft@v1"] and svc.rules_for("GOALS_HALF") == ["goals_1h@v1", "goals_2h@v1", "goals_halves@v1"]
    assert svc.rules_for("SHOTS") == [], "a family that does not exist has no rule"


# ── what is made of the rows ─────────────────────────────────────────────────────────────────────────────────────────────────

def row(**changes: Any) -> dict[str, Any]:
    """A row of the query of the last words, as the database returns it."""
    base: dict[str, Any] = {
        "id": 7, "fixture_id": 70, "model_name": "family-corners_ft", "market_key": "CORNERS_OU", "selection": "Over", "line": Decimal("10.50"),
        "known_at": AT - timedelta(hours=23), "checkpoint": "T-23h", "kickoff_at": AT, "state": "INVESTIGACION", "odds": Decimal("2.100"),
        "n_bookmakers": 5, "p_model": Decimal("0.5600"), "p_market": Decimal("0.4700"), "ev_raw": Decimal("0.1760"), "stake_units": Decimal("0.00"),
        "reasons": ["family_research"], "revisions": 3,
        "forecast": {"forecast_id": 9, "forecast_known_at": "2035-03-02T20:00:00+00:00", "family": "CORNERS", "calibration": "UNCALIBRATED"},
        "research": None, "family": "CORNERS", "result_status": None, "profit_flat": None, "close_odds": None, "close_p_fair": None, "close_minutes_to_ko": None,
        "clv": None, "verdict": None, "quality": None, "causes": None, "actual": None, "margin": None,
        "home": "Alpha", "away": "Beta", "competition": "Premier", "country": "England"}
    return {**base, **changes}


def test_a_last_word_is_shown_with_the_rule_that_grades_it_and_nothing_it_does_not_have() -> None:
    open_one = svc.item_of(row())
    assert open_one["match"] == "Alpha - Beta" and open_one["rule"] == "corners_ft@v1" and open_one["revisions"] == 3
    assert (open_one["line"], open_one["odds"], open_one["p_model"], open_one["p_market"], open_one["stake_units"]) == (10.5, 2.1, 0.56, 0.47, 0.0)
    assert open_one["forecast"] == {"forecast_id": 9, "known_at": "2035-03-02T20:00:00+00:00", "calibration": "UNCALIBRATED"}
    assert open_one["outcome"] is None and open_one["postmortem"] is None, "it has not been settled, so it has neither an outcome nor a post-mortem"
    assert open_one["reasons"] == ["family_research"] and open_one["state"] == "INVESTIGACION"


def test_a_settled_one_carries_its_outcome_and_the_causes_its_post_mortem_found() -> None:
    causes = [{"code": "RED_CARD", "minute": 31, "side": "home", "effect": "fewer", "text": "Roja a los 31 minutos"}, {"code": "x"}, "not a cause"]
    one = svc.item_of(row(result_status="win", profit_flat=Decimal("1.1000"), close_odds=Decimal("1.950"), close_p_fair=Decimal("0.500000"),
                          close_minutes_to_ko=4, clv=Decimal("0.050000"), verdict="MERECIDO", quality="GOOD", causes=causes,
                          actual=Decimal("11.00"), margin=Decimal("0.50")))
    assert one["outcome"] == {"result": "win", "profit_flat": 1.1, "close_odds": 1.95, "close_p_fair": 0.5, "close_minutes_to_ko": 4, "clv": 0.05}
    assert one["postmortem"] == {"verdict": "MERECIDO", "quality": "GOOD", "causes": ["Roja a los 31 minutos"], "actual": 11.0, "margin": 0.5}, (
        "only the causes that say something are shown, as the owner reads them")


def test_a_bet_no_rule_can_grade_says_so_instead_of_naming_one() -> None:
    assert svc.item_of(row(market_key="OU"))["rule"] is None


# ── the request for research a decision carries ─────────────────────────────────────────────────────────────────────────────

ASKED: dict[str, Any] = {
    "version": "research-fam-v1", "family": "CARDS", "registry": "read", "served": False, "unserved": "family_shadow", "open": ["referee", "context"],
    "levels": [1, 2, 3], "searches": 3,
    "needs": [{"key": "referee", "state": "MISSING", "source": "provider", "topics": [], "levels": [], "since": None},
              {"key": "context", "state": "PARTIAL", "source": "search", "topics": ["availability", "preview"], "levels": [1, 2, 3], "since": None}],
    "factors": [{"factor": "scenarios", "version": "scenarios-v1", "status": "DESCRIPTIVE"}]}


def test_a_decision_shows_what_it_did_not_know_and_what_finding_it_out_would_cost() -> None:
    shown = svc.item_of(row(research=ASKED))["research"]
    assert shown == {
        "version": "research-fam-v1", "open": ["referee", "context"], "searches": 3, "served": False, "unserved": "family_shadow", "registry": "read",
        "needs": [{"key": "referee", "state": "MISSING", "source": "provider", "since": None},
                  {"key": "context", "state": "PARTIAL", "source": "search", "since": None}],
        "factors": [{"factor": "scenarios", "version": "scenarios-v1", "status": "DESCRIPTIVE"}]}, (
        "what the console needs, and not the topics or the levels of the tiered search: those are in the filters of the decision")


def test_a_decision_without_the_request_shows_none_and_a_malformed_one_never_breaks_the_page() -> None:
    assert svc.item_of(row())["research"] is None and svc.item_of(row(research="not a record"))["research"] is None
    assert svc.research_of([ASKED]) is None and svc.research_of(7) is None
    odd = svc.research_of({"needs": [None, "x", {"key": "referee"}], "open": "referee", "factors": {"factor": "x"}, "searches": "3", "served": "yes"})
    assert odd == {"version": None, "needs": [{"key": "referee", "state": None, "source": None, "since": None}], "open": [], "searches": 0,
                   "served": False, "unserved": None, "factors": [], "registry": None}, "a doubt is never read as a service or as a count"
    assert svc.research_of({"searches": True})["searches"] == 0  # type: ignore[index]
    assert svc.research_of({"served": True})["served"] is True  # type: ignore[index]


def test_the_record_the_page_reads_is_the_one_the_decision_writes() -> None:
    standing = {f.key: (f.version, factors.DESCRIPTIVE) for f in factors.CATALOGUE}
    for family in research.OF_FAMILY:
        _, written = research.request(family, research.Facts(None, None, "PENDING"), standing)
        shown = svc.research_of(written)
        assert shown is not None
        assert set(shown) == {"version", "needs", "open", "searches", "served", "unserved", "factors", "registry"}
        assert shown["version"] == research.VERSION and shown["open"] == written["open"] and shown["searches"] == written["searches"]
        assert shown["needs"] == [{k: n[k] for k in ("key", "state", "source", "since")} for n in written["needs"]]
        assert shown["factors"] == written["factors"] and shown["unserved"] == research.UNSERVED and shown["served"] is False
        assert shown["registry"] == written["registry"] == "read"


def totals(**rows_: tuple[str, str, str | None, str | None, int]) -> list[dict[str, Any]]:
    return [{"family": f, "state": s, "result_status": r, "verdict": v, "n": n} for f, s, r, v, n in rows_.values()]


def test_a_card_counts_the_selections_those_refused_and_what_became_of_the_selections() -> None:
    found = totals(a=("CORNERS", "INVESTIGACION", "win", "MERECIDO", 4), b=("CORNERS", "INVESTIGACION", "loss", "ERROR", 2),
                   c=("CORNERS", "INVESTIGACION", "loss", None, 1), d=("CORNERS", "INVESTIGACION", None, None, 5),
                   e=("CORNERS", "RECHAZADO", "win", None, 3), f=("CARDS", "INVESTIGACION", "push", "NULO", 1))
    card = svc.card_of("CORNERS", found, None)
    assert (card["selections"], card["rejected"], card["settled"], card["open"]) == (12, 3, 7, 5)
    assert card["results"] == {"win": 4, "loss": 3}, "the refused ones are not selections: what became of them is not what the family chose"
    assert card["verdicts"] == {"MERECIDO": 4, "ERROR": 2} and card["rules"] == ["corners_ft@v1"] and card["memory"] is None
    empty = svc.card_of("YELLOW", found, None)
    assert (empty["selections"], empty["rejected"], empty["settled"], empty["open"], empty["results"], empty["verdicts"]) == (0, 0, 0, 0, {}, {})


def test_the_cards_are_the_four_families_and_any_other_a_decision_names() -> None:
    assert svc.families_seen([]) == list(family_rules.FAMILIES)
    assert svc.families_seen(totals(a=("CARDS", "INVESTIGACION", None, None, 1), b=("ZED", "INVESTIGACION", None, None, 1),
                                    c=("ALEF", "RECHAZADO", None, None, 1))) == [*family_rules.FAMILIES, "ALEF", "ZED"]


def test_the_total_follows_the_filters_of_the_list() -> None:
    found = totals(a=("CORNERS", "INVESTIGACION", None, None, 4), b=("CORNERS", "RECHAZADO", None, None, 3), c=("CARDS", "INVESTIGACION", None, None, 2))
    assert svc.total_of(found, family=None, state=None) == 9
    assert svc.total_of(found, family="CORNERS", state=None) == 7
    assert svc.total_of(found, family=None, state="INVESTIGACION") == 6
    assert svc.total_of(found, family="CORNERS", state="RECHAZADO") == 3
    assert svc.total_of(found, family="YELLOW", state=None) == 0


def memory(entity: str, key: str) -> dict[str, Any]:
    return {"entity_type": entity, "entity_key": key}


def test_a_market_belongs_to_the_family_its_rule_belongs_to() -> None:
    assert svc.belongs(memory("family", "CORNERS"), "CORNERS") and not svc.belongs(memory("family", "CARDS"), "CORNERS")
    assert svc.belongs(memory("market", "CORNERS_OU_HOME"), "CORNERS") and not svc.belongs(memory("market", "CARDS_OU"), "CORNERS")
    assert svc.belongs(memory("market", "OU_1H"), "GOALS_HALF") and svc.belongs(memory("market", "HTFT"), "GOALS_HALF")
    assert not svc.belongs(memory("market", "OU"), "GOALS_HALF"), "the goals of the match are the pipeline's, not a family's"
    assert not svc.belongs(memory("market", "YELLOW_OU"), "CARDS"), "yellow cards are a family of their own"


# ── the steps ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(step: str, run_id: int, minutes: int, result: dict[str, Any] | None, *, job: str = "decide", ms: int | None = 40,
        errors: list[Any] | None = None, status: str = "ok") -> dict[str, Any]:
    started = AT - timedelta(minutes=minutes)
    return {"step": step, "run_id": run_id, "job": job, "started_at": started, "finished_at": started + timedelta(seconds=3), "status": status,
            "result": result, "ms": ms, "errors": errors or []}


def test_the_last_pass_of_the_decision_skips_the_runs_that_waited_for_the_hour() -> None:
    waiting = {"mode": "shadow", "waiting": 1}
    worked = {"mode": "shadow", "forecasts": 40, "fixtures": 8, "candidates": 3, "written": 2}
    found = svc.last_pass([run("families", 5, 15, waiting), run("families", 4, 30, waiting), run("families", 3, 45, worked),
                           run("families", 2, 60, {"mode": "shadow", "forecasts": 1})], "families")
    assert found is not None and found["run_id"] == 3 and found["result"] == worked and found["error"] is None
    assert (found["job"], found["status"], found["ms"]) == ("decide", "ok", 40)
    assert svc.last_pass([run("families", 5, 15, waiting)], "families") is None, "a step that only waited has not run"


def test_a_step_that_raised_is_shown_with_its_error_and_no_result() -> None:
    boom = "family_postmortems: ValueError: the post-mortem could not be written"
    found = svc.last_pass([run("family_postmortems", 8, 20, None, job="nightly", errors=["family_memory: other", boom, 3], status="partial")],
                          "family_postmortems")
    assert found is not None and found["result"] == {} and found["error"] == boom and found["status"] == "partial"


def test_the_nightly_steps_return_even_when_they_report_that_they_waited() -> None:
    """The memory reports ``waiting: 0`` in every pass: only the decision's own waiting runs are passed over."""
    found = svc.last_pass([run("family_memory", 9, 5, {"mode": "shadow", "waiting": 0, "written": 2}, job="nightly")], "family_memory")
    assert found is not None and found["result"]["written"] == 2


def test_the_steps_come_in_the_order_the_cycle_runs_them_and_only_those_that_ran() -> None:
    rows_ = [run("family_memory", 3, 10, {"mode": "shadow"}, job="nightly"), run("families", 1, 50, {"mode": "shadow", "forecasts": 2}),
             run("family_outcomes", 2, 12, {"mode": "shadow", "settled": 4}, job="nightly")]
    assert [s["step"] for s in svc.steps_of(rows_)] == ["families", "family_outcomes", "family_memory"]
    assert svc.steps_of([]) == []


def test_the_mode_is_what_the_latest_run_of_a_step_recorded() -> None:
    older = svc.last_pass([run("families", 1, 600, {"mode": "shadow", "forecasts": 3})], "families")
    newer = svc.last_pass([run("family_outcomes", 2, 30, {"mode": "off"}, job="nightly")], "family_outcomes")
    failed = svc.last_pass([run("family_memory", 3, 5, None, job="nightly", errors=["family_memory: boom"], status="partial")], "family_memory")
    assert older is not None and newer is not None and failed is not None
    assert svc.mode_of([older]) == "shadow"
    assert svc.mode_of([older, newer, failed]) == "off", "the newest run that stamped a mode says it; a run that raised stamped none"
    assert svc.mode_of([failed]) is None and svc.mode_of([]) is None
