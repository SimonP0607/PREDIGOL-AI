"""The AI layer's prices and settings: what a call costs (cache, long prompts, a promotion's end), what an unknown
model is charged at, and that the settings never expose a key nor switch a model on by themselves."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.ai import costs
from fbi.ai.config import AiSettings
from fbi.ai.pricing import PRICES, approx_tokens, price_of, search_cost, token_cost


def test_a_call_is_priced_per_million_tokens_with_the_cached_share_at_the_cache_price() -> None:
    # Haiku 5.5: 0.10 in, 0.50 out, 0.01 cached (USD per 1M)
    assert token_cost("anthropic", "claude-haiku-5-5", input_tokens=6000, output_tokens=700) == Decimal("0.000950")
    cached = token_cost("anthropic", "claude-haiku-5-5", input_tokens=6000, output_tokens=700, cached_tokens=4000)
    assert cached == Decimal("0.000590")  # 2000 fresh x 0.10 + 4000 x 0.01 + 700 x 0.50
    # more cached tokens than input tokens cannot make a call cheaper than free input
    assert token_cost("anthropic", "claude-haiku-5-5", input_tokens=100, output_tokens=0, cached_tokens=900) \
        == Decimal("0.000001")


def test_a_cache_write_costs_125_percent_for_five_minutes_and_double_for_an_hour() -> None:
    # Plan Maestro IA, section 28 (verified 24 Oct 2026). Sonnet 5.5: 2 in, 10 out, 0.10 read (USD per 1M)
    base = {"input_tokens": 10_000, "output_tokens": 0}
    plain = token_cost("anthropic", "claude-sonnet-5-5", **base)
    five = token_cost("anthropic", "claude-sonnet-5-5", cache_write_5m_tokens=10_000, **base)
    hour = token_cost("anthropic", "claude-sonnet-5-5", cache_write_1h_tokens=10_000, **base)
    assert (plain, five, hour) == (Decimal("0.020000"), Decimal("0.025000"), Decimal("0.040000"))
    # a real mix: 2,000 fresh + 6,000 read + 1,500 written for five minutes + 500 for an hour + 800 written out
    mixed = token_cost("anthropic", "claude-sonnet-5-5", input_tokens=10_000, output_tokens=800, cached_tokens=6_000,
                       cache_write_5m_tokens=1_500, cache_write_1h_tokens=500)
    assert mixed == Decimal((2_000 * 2 + 6_000 * 0.10 + 1_500 * 2 * 1.25 + 500 * 2 * 2 + 800 * 10) / 1e6).quantize(
        Decimal("0.000001"))
    # a provider with no write surcharge charges a write as plain input
    assert token_cost("openai", "gpt-6-luna", input_tokens=1000, output_tokens=0, cache_write_1h_tokens=1000) \
        == token_cost("openai", "gpt-6-luna", input_tokens=1000, output_tokens=0)
    # more written tokens than the call read cannot make it dearer than the input it had
    assert token_cost("anthropic", "claude-sonnet-5-5", input_tokens=100, output_tokens=0,
                      cache_write_5m_tokens=900) == token_cost("anthropic", "claude-sonnet-5-5", input_tokens=100,
                                                               output_tokens=0, cache_write_5m_tokens=100)


def test_a_batch_call_costs_half_of_everything_it_reads_and_writes() -> None:
    kw = {"input_tokens": 12_000, "output_tokens": 900, "cached_tokens": 4_000, "cache_write_5m_tokens": 2_000}
    live = token_cost("anthropic", "claude-sonnet-5-5", **kw)
    batch = token_cost("anthropic", "claude-sonnet-5-5", batch=True, **kw)
    assert batch == (live / 2).quantize(Decimal("0.000001"))
    assert token_cost("anthropic", "claude-opus-5-5", input_tokens=0, output_tokens=0, batch=True) == Decimal(0)


def test_long_prompts_and_ended_promotions_pay_their_own_prices() -> None:
    short = token_cost("anthropic", "claude-haiku-5-5", input_tokens=100_000, output_tokens=0)
    long = token_cost("anthropic", "claude-haiku-5-5", input_tokens=100_001, output_tokens=0)
    assert short == Decimal("0.010000") and long > 4 * short
    during = token_cost("gemini", "gemini-3.8-flash", input_tokens=1_000_000, output_tokens=0, at=date(2026, 12, 31))
    after = token_cost("gemini", "gemini-3.8-flash", input_tokens=1_000_000, output_tokens=0, at=date(2027, 1, 1))
    assert (during, after) == (Decimal("0.750000"), Decimal("1.500000"))


def test_an_unknown_model_is_budgeted_at_the_most_expensive_known_price() -> None:
    price, known = price_of("openai", "gpt-unknown-9")
    assert not known
    assert price.output == max(p.output for p in PRICES.values())
    dated, known = price_of("anthropic", "claude-haiku-5-5-20261001")  # a dated snapshot of a known model
    assert known and dated.input == Decimal("0.10")


def test_searches_and_token_estimates() -> None:
    assert search_cost("exa", 1000) == Decimal("15.000000")  # 7 a search + the text of up to 8 pages at 1 per 1,000
    assert search_cost("brave", 1) == Decimal("0.005000")
    assert search_cost("nobody-knows", 1000) == Decimal("30.000000")  # unknown backend: the dearest
    text = "x" * 4000
    assert approx_tokens(text) == 1000
    assert approx_tokens(text, "anthropic") == 1300  # the newer Claude tokenizer counts about 30 % more


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    import os

    for k in list(os.environ):
        if k.startswith(("FBI_AI_", "FBI_ANALYST_", "EXA_API_KEY")):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env of the machine running the tests (the owner's holds real keys)
    return monkeypatch


def test_without_configuration_the_layer_is_in_shadow_and_calls_no_model(clean_env: pytest.MonkeyPatch) -> None:
    s = AiSettings.from_env()
    assert s.mode == "shadow" and not s.llm_configured and s.search is None
    assert s.missing() == ["FBI_AI_MODEL_ANALYSIS", "FBI_AI_MODEL_BULK", "FBI_AI_MODEL_FINAL"]
    # the soft daily target defaults to the month over thirty days
    assert (s.daily_budget, s.monthly_budget) == (Decimal("0.67"), Decimal("20"))
    assert (s.daily_max_factor, s.max_web_first, s.max_web_pre, s.max_watch_per_day) == (Decimal(2), 20, 12, 8)


def test_the_owners_budget_and_the_daily_target(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FBI_AI_MONTHLY_BUDGET_USD", "150")
    s = AiSettings.from_env()
    assert (s.monthly_budget, s.daily_budget) == (Decimal("150"), Decimal("5.00"))
    clean_env.setenv("FBI_AI_DAILY_BUDGET_USD", "3.50")  # the older name still counts...
    assert AiSettings.from_env().daily_budget == Decimal("3.50")
    clean_env.setenv("FBI_AI_DAILY_TARGET_USD", "5")  # ...but the new one wins
    assert AiSettings.from_env().daily_budget == Decimal("5")
    assert AiSettings.from_env().public()["daily_target_usd"] == "5"


def test_the_earlier_analyst_model_never_switches_the_decision_layer_on(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FBI_ANALYST_API_KEY", "sk-legacy")
    clean_env.setenv("FBI_ANALYST_MODEL", "claude-haiku-4-5")
    s = AiSettings.from_env()
    assert not s.llm_configured, "an old setting must not start paid calls the owner did not choose"
    clean_env.setenv("FBI_AI_MODEL_ANALYSIS", "anthropic:claude-haiku-5-5")
    s = AiSettings.from_env()
    assert s.llm_configured and s.tier("analysis") is not None and s.tier("final") is None


def test_a_tier_needs_its_providers_key_and_the_public_view_has_no_key(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FBI_AI_MODEL_BULK", "openai:gpt-6-luna")
    clean_env.setenv("FBI_AI_MODEL_FINAL", "nonsense")
    clean_env.setenv("FBI_AI_MODE", "ENFORCE")
    s = AiSettings.from_env()
    assert s.mode == "enforce" and s.tier("bulk") is None and "FBI_AI_KEY_OPENAI" in s.missing()
    clean_env.setenv("FBI_AI_KEY_OPENAI", "sk-secret-value")
    s = AiSettings.from_env()
    assert s.tier("bulk") is not None
    public = repr(s.public()) + repr(s)
    assert "sk-secret-value" not in public
    assert s.public()["tiers"]["bulk"] == {"provider": "openai", "model": "gpt-6-luna", "key_present": True}


def test_phase_0_switches_default_to_auto_and_each_variable_rolls_its_own_back(clean_env: pytest.MonkeyPatch) -> None:
    s = AiSettings.from_env()
    assert {n: s.switch(n) for n in ("cache", "batch", "native_schema", "brief_material", "budget_v3")} \
        == dict.fromkeys(("cache", "batch", "native_schema", "brief_material", "budget_v3"), "auto")
    assert s.switch("a-typo") == "off", "an unknown switch is never on"
    clean_env.setenv("FBI_AI_CACHE", "0")
    clean_env.setenv("FBI_AI_BATCH", "OFF")
    clean_env.setenv("FBI_AI_NATIVE_SCHEMA", "1")
    clean_env.setenv("FBI_AI_BRIEF_MATERIAL", "maybe")
    clean_env.setenv("FBI_AI_BUDGET_V3", "false")
    s = AiSettings.from_env()
    assert (s.switch("cache"), s.switch("batch"), s.switch("native_schema"), s.switch("brief_material"),
            s.switch("budget_v3")) == ("off", "off", "on", "auto", "off")
    assert s.public()["switches"]["cache"] == "off"


def test_the_budget_envelopes_have_safe_defaults_and_the_lab_key_is_never_shown(
        clean_env: pytest.MonkeyPatch) -> None:
    s = AiSettings.from_env()
    # LAB: no money until the owner sets it; Exa, the joint ceiling and the reserve: the approved values
    assert (s.lab_monthly_budget, s.exa_monthly_budget, s.joint_ceiling, s.reserve) \
        == (Decimal(0), Decimal("35"), Decimal("190"), Decimal("10"))
    assert s.labelled(lab=False) == ("PREDIGOL", "worker-prod") and s.labelled(lab=True) == ("PREDIGOL-LAB", "worker-lab")
    assert s.batch_min_lead_minutes == 240 and not s.public()["lab_key_present"]
    clean_env.setenv("FBI_AI_KEY_ANTHROPIC_LAB", "sk-lab-secret")
    clean_env.setenv("FBI_AI_LAB_MONTHLY_BUDGET_USD", "15")
    clean_env.setenv("FBI_AI_EXA_MONTHLY_BUDGET_USD", "40")
    clean_env.setenv("FBI_AI_BATCH_MIN_LEAD_MINUTES", "5")
    s = AiSettings.from_env()
    assert s.lab_keys == {"anthropic": "sk-lab-secret"} and "anthropic" not in s.keys, "the LAB key is not production's"
    assert (s.lab_monthly_budget, s.exa_monthly_budget, s.batch_min_lead_minutes) == (Decimal(15), Decimal(40), 30)
    shown = repr(s) + repr(s.public())
    assert "sk-lab-secret" not in shown and s.public()["lab_key_present"] is True


def test_bad_numbers_fall_back_to_the_defaults_and_an_unknown_mode_to_shadow(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FBI_AI_DAILY_BUDGET_USD", "lots")
    clean_env.setenv("FBI_AI_MAX_LLM_REVIEWS_PER_DAY", "-5")
    clean_env.setenv("FBI_AI_MODE", "yolo")
    s = AiSettings.from_env()
    assert s.daily_budget == Decimal("0.67") and s.max_llm_reviews_per_day == 0 and s.mode == "shadow"


def test_the_simulation_prices_a_day_and_the_worst_case_takes_every_cap() -> None:
    w = costs.Workload(matches=90, shortlist=20, llm_reviews=12, deep_reviews=2, web_fixtures=6,
                       postmortem_narratives=10, pattern_calls=1 / 7)
    eco = next(p for p in costs.PROFILES if p.name == "economico")
    sim = costs.simulate(w, eco, day=date(2026, 10, 8))
    # 10 Haiku reviews + 2 Sonnet reviews + 6 extractions + 10 post-mortems + patterns + 6 Exa searches
    expected = (10 * (6000 * 0.10 + 700 * 0.50) + 2 * (6000 * 2 + 700 * 10) + 6 * (2500 * 0.10 + 600 * 0.50)
                + 10 * (2500 * 0.10 + 450 * 0.50) + (12000 * 0.10 + 900 * 0.50) / 7) / 1e6 + 6 * 0.015
    assert sim["day_usd"] == pytest.approx(expected, abs=1e-4)
    assert sim["month_usd"] == pytest.approx(30 * sim["day_usd"], abs=0.01)
    worst = costs.worst_case(AiSettings(), w)
    assert (worst.llm_reviews, worst.deep_reviews, worst.web_fixtures) == (60, 10, 12)
    assert costs.simulate(worst, eco, day=date(2026, 10, 8))["day_usd"] > sim["day_usd"]


def test_gemini_searches_inside_the_free_allowance_cost_nothing() -> None:
    w = costs.Workload(matches=90, shortlist=20, llm_reviews=0, deep_reviews=0, web_fixtures=12)
    gem = next(p for p in costs.PROFILES if p.name == "equilibrado_gemini")
    assert costs.simulate(w, gem, day=date(2026, 10, 8))["per_day"]["searches"] == 0.0


def test_the_env_file_counts_like_the_process_environment_and_the_process_wins(clean_env: pytest.MonkeyPatch) -> None:
    # host mode (scripts/dev-up) exports nothing: the owner's keys live in .env, which pydantic reads - so must we
    Path(".env").write_text("FBI_AI_MODEL_ANALYSIS=anthropic:claude-sonnet-5-5\nFBI_AI_KEY_ANTHROPIC=sk-ant-from-file\n"
                            "FBI_AI_MONTHLY_BUDGET_USD=75\nEXA_API_KEY=exa-from-file\n# a comment\n", encoding="utf-8")
    s = AiSettings.from_env()
    assert s.tier("analysis") is not None and s.monthly_budget == Decimal("75")
    assert s.search == "exa" and s.search_configured
    assert "sk-ant-from-file" not in repr(s.public()) + repr(s)
    clean_env.setenv("FBI_AI_MONTHLY_BUDGET_USD", "60")
    assert AiSettings.from_env().monthly_budget == Decimal("60")

    from fbi.analyst import search as web
    from fbi.core.env import environment

    assert web.configured()
    assert environment("missing.env").get("FBI_AI_KEY_ANTHROPIC") is None  # no file is no file
