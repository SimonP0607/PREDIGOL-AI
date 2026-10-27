"""The adaptive budget v3 (Plan Maestro IA, section 26) on a built month: August 2032, fourteen closed days of ten matches with a
market each, and today (Sunday 15 Aug, noon in Bogotá) the fifteenth.

* the month is PROJECTED (unit cost x the matches expected) and the state follows the projection;
* the reserve of US$10 is kept for production until the last five days;
* production, the LAB and Exa are three envelopes that never move one another's figures;
* the LAB runs a day whole or not at all, and yields to production;
* a spent limit stops the workspace for a cooldown that grows, then one call tries again;
* the alerts of each envelope, and of the projection, are recorded once;
* rolled back (``FBI_AI_BUDGET_V3=0``) it is the V2 arithmetic with one total.

No network, no key: the ledger is written by hand. One transaction, rolled back."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from fbi.ai import budget_v3
from fbi.ai.collectors import collect_web
from fbi.ai.config import AiSettings, TierModel
from fbi.ai.usage import UsageLedger, budget, check_alerts, shared

from .conftest import Seed

D = Decimal
NOW = datetime(2032, 8, 15, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá, a Sunday
TODAY = date(2032, 8, 15)
SONNET = TierModel("anthropic", "claude-sonnet-5-5")


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"mode": "shadow", "tiers": {"analysis": SONNET, "bulk": SONNET}, "keys": {"anthropic": "k"},
                            "lab_keys": {"anthropic": "kl"}, "monthly_budget": D(185), "daily_budget": D("6.17"),
                            "lab_monthly_budget": D(55), "joint_ceiling": D(190), "reserve": D(10),
                            "exa_monthly_budget": D(35)}
    return AiSettings(**(base | kw))


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=UTC)


def plan(db: psycopg.Connection[Any], day: date, with_market: int, *, total: int | None = None,
         stage: str = "opened") -> None:
    db.execute("INSERT INTO ai.day_plans (day, stage, created_at, version, fixtures_total, fixtures_with_market, universe) "
               "VALUES (%s, %s, %s, 'day-v1', %s, %s, '[]'::jsonb)",
               (day, stage, noon(day) - timedelta(hours=12), with_market if total is None else total, with_market))


def spend(db: psycopg.Connection[Any], at: datetime, usd: str | Decimal, *, workspace: str | None = "PREDIGOL",
          search: bool = False) -> None:
    UsageLedger(shared(db)).record(
        at=at, purpose="web_search" if search else "pick_review", tier="search" if search else "analysis",
        provider="exa" if search else "anthropic", model="exa" if search else SONNET.model, usage=None, cost=D(usd),
        status="ok", workspace=None if search else workspace)


def month(db: psycopg.Connection[Any], *, unit: str, spent_today: str = "2.00", matches: int = 10,
          today_matches: int | None = None) -> None:
    """Fourteen closed days of ``matches`` matches with a market, each costing ``unit`` a match; today the fifteenth, with
    ``today_matches`` of them (the plan of a day is append-only: a different day is a different world, not an edit)."""
    for n in range(1, 15):
        day = date(2032, 8, n)
        plan(db, day, matches)
        spend(db, noon(day), D(unit) * matches)
    plan(db, TODAY, matches if today_matches is None else today_matches)
    if D(spent_today) > 0:
        spend(db, NOW - timedelta(hours=2), spent_today)


def limit_hit(db: psycopg.Connection[Any], at: datetime, *, workspace: str = "PREDIGOL", kind: str = "workspace_limit") -> None:
    db.execute("INSERT INTO ai.limit_hits (at, provider, workspace, kind, http_status) VALUES (%s, 'anthropic', %s, %s, %s)",
               (at, workspace, kind, 400 if kind == "workspace_limit" else 429))


def test_the_month_is_projected_from_the_unit_cost_and_the_matches_expected(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    b = budget(db, at=NOW, settings=settings())
    # 14 closed days x 5.00 = 70 + 2.00 today = 72; today still has 10 x 0.50 - 2.00 = 3.00; 16 days after it x 5.00 = 80
    assert b.version == "v3" and b.projected == D(155)
    assert b.spent_month == D(72) and b.spent_today == D(2) and b.state == "NORMAL" and b.reasons == ()
    assert b.projection_ratio == 155 / 185


def test_the_days_allocation_shares_what_is_left_less_the_reserve(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    b = budget(db, at=NOW, settings=settings())
    # 185 - 70 = 115 left before today; 10 kept back; 105 over 17 days (today included) = 6.1765 a day; all days weigh the same
    assert b.reserve_locked == D(10) and b.days_left == 17
    assert b.daily == D("6.1765") and b.cap == D("9.2648") and b.pace == D(105) / 17
    assert b.load == 1.0


def test_a_busy_day_gets_more_than_the_average_but_never_more_than_twice_it(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50", today_matches=25)  # a Champions night: 25 matches against a typical 10
    busy = budget(db, at=NOW, settings=settings())
    # the days left expect 25 + 16 x 10 = 185 matches: today weighs 25 x 17 / 185 = 2.297, held at the factor, 2
    assert busy.load == 2.0 and busy.daily == D("12.3400"), "twice the average would be 12.35: the soft target's ceiling holds it"


def test_a_quiet_day_keeps_half_the_average(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50", today_matches=1)
    quiet = budget(db, at=NOW, settings=settings())
    # 1 x 17 / (1 + 160) = 0.106, held at half
    assert quiet.load == 0.5 and quiet.daily == D("3.0882"), "a quiet day keeps half the average"


def test_a_day_between_the_two_gets_its_share_of_what_is_left(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50", today_matches=15)
    mid = budget(db, at=NOW, settings=settings())
    # 15 x 17 / (15 + 160) = 1.457: between half and twice the average, so it is not held at either
    assert round(mid.load, 3) == 1.457 and abs(mid.daily - D(9)) < D("0.001"), "6.1765 x 1.457 = 9.00 (the weight is kept to 4 digits)"


def test_the_calendar_decides_the_next_seven_days_and_the_same_weekday_the_rest(db: psycopg.Connection[Any], seed: Seed) -> None:
    month(db, unit="0.50")
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    n = 0
    for day, count in ((date(2032, 8, 16), 6), (date(2032, 8, 17), 10)):
        for _ in range(count):
            n += 1
            db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                       "kickoff_at) VALUES (%s, %s, %s, %s, %s)",
                       (9_100_000 + n, seed.season_id, seed.home_team_id, seed.away_team_id,
                        noon(day) + timedelta(hours=3, minutes=n)))
    b = budget(db, at=NOW, settings=settings())
    # 16 Aug: 6, 17 Aug: 10, 18-22 Aug: nothing scheduled, 23-31 Aug (9 days): the median of their weekday, 10 each
    # (share of fixtures that get a market: 1). After today: (6 + 10 + 90) x 0.50 = 53 -> 72 + 3 + 53
    assert b.projected == D(128)
    loads = budget_v3.forecast(db, at=NOW).loads
    assert [loads[date(2032, 8, d)] for d in (15, 16, 17, 18, 22, 23, 31)] == [10, 6, 10, 0, 0, 10, 10]


def test_a_calendar_with_nothing_scheduled_at_all_is_a_gap_in_the_data_not_a_week_without_football(
        db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    assert budget(db, at=NOW, settings=settings()).projected == D(155), "the same weekday's median fills the whole month"


def test_the_prepared_plan_of_a_day_counts_when_it_knows_more_than_the_calendar(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    month(db, unit="0.50")
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
               "VALUES (9200001, %s, %s, %s, %s)", (seed.season_id, seed.home_team_id, seed.away_team_id,
                                                    noon(date(2032, 8, 16))))
    plan(db, date(2032, 8, 16), 14, stage="prepared")
    assert budget_v3.forecast(db, at=NOW).loads[date(2032, 8, 16)] == 14


def test_a_projection_just_over_95_percent_adjusts_without_touching_the_main_path(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.58", spent_today="1.00")
    b = budget(db, at=NOW, settings=settings())
    assert b.projected == D("179.8") and b.state == "AJUSTE" and b.reasons == ("projection_over_95",)
    assert b.allows("final") and b.allows("analysis") and b.allows("search"), "the main path keeps every tier"
    assert b.adjusting and b.marginal_allowed(), "AJUSTE changes nothing of the depth: it saves on duplicates and uses Batch"
    assert b.as_json()["state"] == "AJUSTE" and b.as_json()["version"] == "v3"


def test_a_projection_over_the_envelope_reduces_the_paid_depth(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.62", spent_today="1.00")
    b = budget(db, at=NOW, settings=settings())
    assert b.projected == D("192.2") and b.state == "REDUCED" and b.reasons == ("projection_over_100",)
    assert not b.allows("final") and b.allows("analysis") and b.allows("bulk")
    assert not b.marginal_allowed(), "no paid depth for a match without candidates"


def test_the_reserve_is_released_in_the_last_five_days(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    assert budget(db, at=NOW, settings=settings()).reserve_locked == D(10)
    late = budget(db, at=datetime(2032, 8, 28, 17, 0, tzinfo=UTC), settings=settings())  # 28, 29, 30 and 31 Aug: four days
    assert late.days_left == 4 and late.reserve_locked == 0


def test_the_months_spend_stops_everything_and_the_rules_decide(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    spend(db, NOW - timedelta(hours=1), "120.00")
    b = budget(db, at=NOW, settings=settings())
    assert b.state == "EXHAUSTED" and b.reasons == ("month_spent",)
    assert not any(b.allows(t) for t in ("bulk", "analysis", "final", "search"))


def test_a_day_that_passed_its_hard_cap_stops_and_one_past_125_percent_goes_cheap(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50", spent_today="7.80")  # 6.1765 allocated: 126 % of it, under the cap of 9.2648
    cheap = budget(db, at=NOW, settings=settings())
    assert cheap.state == "CHEAP_ONLY" and cheap.reasons == ("day_allocation_125",)
    assert cheap.allows("bulk") and not cheap.allows("analysis") and not cheap.allows("search")
    spend(db, NOW - timedelta(minutes=30), "2.00")
    assert budget(db, at=NOW, settings=settings()).reasons == ("day_cap",)


def test_a_spent_provider_limit_stops_the_workspace_for_a_growing_cooldown_and_then_one_call_tries(
        db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    limit_hit(db, NOW - timedelta(minutes=10))
    b = budget(db, at=NOW, settings=settings())
    assert b.state == "EXHAUSTED" and b.reasons == ("api_limit",)
    assert b.limit_until == NOW + timedelta(minutes=20), "30 minutes from the hit"
    assert budget(db, at=NOW + timedelta(minutes=19), settings=settings()).state == "EXHAUSTED"
    after = budget(db, at=NOW + timedelta(minutes=21), settings=settings())
    assert after.state == "NORMAL" and after.limit_until is None, "half open: one call may try again"
    limit_hit(db, NOW + timedelta(minutes=22))  # and it was refused again: twice in the window, an hour
    again = budget(db, at=NOW + timedelta(minutes=23), settings=settings())
    assert again.state == "EXHAUSTED" and again.limit_until == NOW + timedelta(minutes=82)
    assert budget(db, at=NOW + timedelta(hours=13), settings=settings()).state == "NORMAL", "a day later it is forgotten"


def test_the_labs_limit_does_not_stop_production_but_the_accounts_tier_cap_stops_both(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    limit_hit(db, NOW - timedelta(minutes=5), workspace="PREDIGOL-LAB")
    assert budget(db, at=NOW, settings=settings()).state == "NORMAL"
    limit_hit(db, NOW - timedelta(minutes=4), workspace="PREDIGOL-LAB", kind="tier_cap")
    assert budget(db, at=NOW, settings=settings()).reasons == ("api_limit",), "the account's cap is everyone's"


def test_the_labs_and_exas_money_never_moves_productions_figures(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    before = budget(db, at=NOW, settings=settings())
    spend(db, NOW - timedelta(days=3), "40.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(days=2), "22.00", search=True)
    after = budget(db, at=NOW, settings=settings())
    assert (after.spent_month, after.projected, after.daily, after.state) == (
        before.spent_month, before.projected, before.daily, before.state)
    rolled_back = budget(db, at=NOW, settings=settings(switches={"budget_v3": "off"}))
    assert rolled_back.version == "v2" and rolled_back.spent_month == D(72) + 62, \
        "rolled back it is the old one total: Exa and the LAB inside the same number"


def test_the_analysts_cap_counts_production_only_under_v3(db: psycopg.Connection[Any], monkeypatch: Any) -> None:
    from fbi.analyst import budget as analyst_budget

    month(db, unit="0.50")
    spend(db, NOW - timedelta(days=3), "40.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(days=2), "22.00", search=True)
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {})
    assert analyst_budget.spent_this_month(db, at=NOW) == D(72)
    monkeypatch.setattr("fbi.ai.config.environment", lambda: {"FBI_AI_BUDGET_V3": "0"})
    assert analyst_budget.spent_this_month(db, at=NOW) == D(72) + 62


def test_the_lab_runs_a_day_whole_within_what_production_leaves_it(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    lab = budget_v3.lab_day(db, at=NOW, settings=settings())
    # production projects 155 at dawn; the joint ceiling 190 leaves 35 of the LAB's 55
    assert lab.allocation == D(35) and lab.allowed and lab.can_spend and lab.reason == "ok" and lab.remaining == D(35)
    spend(db, NOW - timedelta(days=2), "3.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(days=1), "30.00", workspace="PREDIGOL-LAB")
    typical = budget_v3.lab_day(db, at=NOW, settings=settings())
    assert typical.typical_day == D("16.5") and not typical.allowed and typical.reason == "allocation_spent", \
        "2 left of the allocation cannot cover a typical day of 16.50: the LAB does not start a day it cannot finish"
    assert typical.remaining == D(2) and not typical.can_spend


def test_the_labs_verdict_holds_the_whole_day_even_as_production_spends(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50", spent_today="0")
    morning = budget_v3.lab_day(db, at=NOW - timedelta(hours=11), settings=settings())
    spend(db, NOW - timedelta(hours=2), "4.00")
    evening = budget_v3.lab_day(db, at=NOW + timedelta(hours=6), settings=settings())
    assert (morning.allowed, morning.allocation) == (evening.allowed, evening.allocation) == (True, D(35))


def test_the_lab_yields_to_production_in_a_heavy_month_and_never_changes_its_model(db: psycopg.Connection[Any]) -> None:
    month(db, unit="1.00", spent_today="4.00")
    lab = budget_v3.lab_day(db, at=NOW, settings=settings())
    assert lab.allocation == 0 and not lab.allowed and lab.reason == "yields_to_production"


def test_a_lab_without_an_envelope_or_with_a_spent_limit_does_not_run(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    assert budget_v3.lab_day(db, at=NOW, settings=settings(lab_monthly_budget=D(0))).reason == "no_envelope"
    limit_hit(db, NOW - timedelta(minutes=5), workspace="PREDIGOL-LAB")
    assert budget_v3.lab_day(db, at=NOW, settings=settings()).reason == "api_limit"


def test_exa_has_its_own_envelope_and_a_share_of_it_each_day(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    spend(db, NOW - timedelta(days=5), "20.00", search=True)
    exa = budget_v3.exa_budget(db, at=NOW, settings=settings())
    # 15 left over 17 days = 0.88 a day; twice that is the day's cap
    assert exa.allowed and exa.spent_month == D(20)
    assert round(exa.daily, 6) == round(D(15) / 17, 6) and round(exa.cap, 6) == round(D(30) / 17, 6)
    spend(db, NOW - timedelta(hours=1), "1.75", search=True)
    assert budget_v3.exa_budget(db, at=NOW, settings=settings()).reason == "day_cap"
    spend(db, NOW - timedelta(days=1), "13.30", search=True)
    assert budget_v3.exa_budget(db, at=NOW, settings=settings()).reason == "month_spent"
    assert budget_v3.exa_budget(db, at=NOW, settings=settings(exa_monthly_budget=D(0))).reason == "no_envelope"


def test_a_web_search_is_not_made_when_exas_envelope_is_spent(db: psycopg.Connection[Any], seed: Seed) -> None:
    month(db, unit="0.50")
    spend(db, NOW - timedelta(days=1), "35.00", search=True)
    asked: list[str] = []

    def search(query: str, at: datetime) -> list[Any]:
        asked.append(query)
        return []

    out = collect_web(db, settings(search="exa"), seed.fixture_id, at=NOW, ledger=UsageLedger(shared(db)), search=search)
    assert out.skipped == "budget_exa" and asked == [], "Exa's money is spent: no search, and Claude's budget is untouched"
    rolled_back = collect_web(db, settings(search="exa", switches={"budget_v3": "off"}), seed.fixture_id, at=NOW,
                              ledger=UsageLedger(shared(db)), search=search)
    assert rolled_back.skipped != "budget_exa"


def alerts_of(db: psycopg.Connection[Any], where: str = "TRUE") -> list[tuple[Any, ...]]:
    """Every alert with its scope and kind, from both tables (``ai.budget_alerts_all``)."""
    return db.execute(f"SELECT scope, kind, threshold FROM ai.budget_alerts_all WHERE {where} "
                      "ORDER BY scope, kind, threshold").fetchall()


def test_each_envelope_alerts_once_and_the_projection_too(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.58", spent_today="1.00")  # production: 81.2 + 1 = 82.2 of 185 (44 %); projected 179.8 (97 %)
    spend(db, NOW - timedelta(days=3), "8.00", workspace="PREDIGOL-LAB")  # 8 of 15: 53 %
    spend(db, NOW - timedelta(days=2), "25.00", search=True)  # 25 of 35: 71 %
    lab15 = settings(lab_monthly_budget=D(15))
    first = check_alerts(db, at=NOW, settings=lab15)
    assert alerts_of(db) == [("exa", "month", 50), ("exa", "month", 70), ("lab", "month", 50), ("production", "projection", 95)]
    assert sorted(first) == [50, 50, 70, 95]
    assert check_alerts(db, at=NOW, settings=lab15) == [], "each is recorded once a month"
    spend(db, NOW - timedelta(minutes=30), "12.00")  # production: 94.2 of 185 (51 %); the projection passes 100 %
    assert check_alerts(db, at=NOW, settings=lab15) == [50, 100]
    assert alerts_of(db, "scope = 'production'") == [("production", "month", 50), ("production", "projection", 95),
                                                     ("production", "projection", 100)]
    row = db.execute("SELECT spent_usd, budget_usd FROM ai.envelope_alerts WHERE scope = 'production' AND kind = 'projection' "
                     "AND threshold = 95").fetchone()
    assert row == (D("179.8000"), D(185)), "a projection alert records the projection against the envelope"


def test_production_s_month_alert_lives_in_the_table_the_earlier_code_uses(db: psycopg.Connection[Any]) -> None:
    """One table, one key, both generations of code: the alert the new budget raises is a row of ``ai.budget_alerts`` as the
    earlier release wrote it, and the other envelopes' alerts are not there - the earlier code finds nothing it cannot read."""
    month(db, unit="0.58", spent_today="1.00")
    spend(db, NOW - timedelta(days=3), "8.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(days=2), "25.00", search=True)
    spend(db, NOW - timedelta(minutes=30), "12.00")  # production: 94.2 of 185 (51 %); the projection passes 100 %
    lab15 = settings(lab_monthly_budget=D(15))
    check_alerts(db, at=NOW, settings=lab15)
    assert db.execute("SELECT threshold FROM ai.budget_alerts ORDER BY threshold").fetchall() == [(50,)]
    assert db.execute("SELECT scope, kind, threshold FROM ai.envelope_alerts ORDER BY scope, kind, threshold").fetchall() \
        == [("exa", "month", 50), ("exa", "month", 70), ("lab", "month", 50), ("production", "projection", 95),
            ("production", "projection", 100)]


def test_production_s_month_alert_raised_by_the_earlier_code_is_not_raised_again(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.58", spent_today="1.00")
    spend(db, NOW - timedelta(minutes=30), "12.00")  # production: 94.2 of 185 (51 %)
    earlier = NOW - timedelta(hours=1)
    db.execute("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
               "VALUES (%s, 50, %s, 82, 185)", (date(2032, 8, 1), earlier))  # the statement of the release before the plan
    new = check_alerts(db, at=NOW, settings=settings())
    assert 50 not in new, "production's 50 % exists once, whichever code raised it"
    assert db.execute("SELECT created_at, spent_usd FROM ai.budget_alerts").fetchall() == [(earlier, D(82))]


def test_the_notifier_words_the_alerts_of_both_tables(db: psycopg.Connection[Any]) -> None:
    from fbi.notify.service import collect

    month(db, unit="0.58", spent_today="1.00")
    spend(db, NOW - timedelta(days=3), "8.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(days=2), "25.00", search=True)
    spend(db, NOW - timedelta(minutes=30), "12.00")
    check_alerts(db, at=NOW, settings=settings(lab_monthly_budget=D(15)))
    keys = {d.dedup_key for d in collect(db, at=NOW) if d.kind == "ai_budget"}
    assert keys == {"ai_budget:2032-08:50",  # production's month: keyed and worded as it always was
                    "ai_budget:2032-08:exa:month:50", "ai_budget:2032-08:exa:month:70", "ai_budget:2032-08:lab:month:50",
                    "ai_budget:2032-08:production:projection:95", "ai_budget:2032-08:production:projection:100"}


def test_rolled_back_the_alerts_are_the_old_ones_of_the_one_total(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.58", spent_today="1.00")
    spend(db, NOW - timedelta(days=2), "25.00", search=True)
    check_alerts(db, at=NOW, settings=settings(switches={"budget_v3": "off"}))
    assert alerts_of(db) == [("production", "month", 50)], "107 of 185 in one total, Exa inside it - and no projection alert"
