"""IA-137 (AD-K05): every dollar of the month given to one capability, the repeated inputs ("pay once"), the cut of a new piece at 95 % of
its cap (failing closed) and the warnings at 80 and 95 % proved in each envelope. Pure: no database, no API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import budget_v3, cache, capability_budget, capability_costs
from fbi.ai.capability_budget import piece_allows
from fbi.ai.capability_costs import Row, Totals, capability_of, report
from fbi.ai.config import AiSettings
from fbi.chronicle import v4_job
from fbi.news import pipeline, writer

D = Decimal


def row(prompt: str | None, purpose: str | None = "other", *, scope: str = "production", tier: str = "analysis", agent: str | None = None,
        usd: str = "1", calls: int = 1, ledger: str = "usage", **kw: Any) -> Row:
    return Row(ledger, scope, prompt, purpose, tier, agent, calls, D(usd), **kw)


def settings(**kw: Any) -> AiSettings:
    base: dict[str, Any] = {"monthly_budget": D(185), "lab_monthly_budget": D(55), "exa_monthly_budget": D(35), "joint_ceiling": D(190)}
    return AiSettings(**(base | kw))


# ── attribution ───────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("r", "expected"), [
    (row("chronicle-v4", "match_brief", tier="bulk"), "chronicle_v4"),                       # the register first
    (row("battery-v4", scope="lab"), "battery_v4"),
    (row("news-text-v1", scope="lab", tier="bulk"), "news_text_shadow"),
    (row("review-v2", "pick_review"), "production.review"),                                 # then IA-034's paths
    (row("brief-v8", "match_brief", tier="bulk"), "production.brief"),
    (row(None, "web_search", scope="exa", tier="search"), "research.search"),
    (row("extract-v4", "evidence_extraction", tier="bulk"), "research.extraction"),
    (row("match-v5", "other", scope="lab", agent="match"), "deliberation.match_agent"),
    (row("stats-v4", "other", scope="lab"), "deliberation.stats_agent"),                     # an agent's prompt without the agent column
    (row("council-opus-v1", scope="lab"), "deliberation.escalation"),
    (row("user-narrative-v3", "user_narrative", ledger="readers", tier="bulk"), "chronicles.chronicle"),
    (row("pick-why-v1", tier="bulk"), "narrator.pick_why"),                                  # a known owner IA-034 does not name
    (row("patterns-v1", "pattern_review"), "rest.learning"),
    (row("mystery-v9", "other"), None),                                                     # rest.other is not a capability
])
def test_each_row_belongs_to_one_capability_or_to_none(r: Row, expected: str | None) -> None:
    assert capability_of(r) == expected


def test_a_capability_of_the_register_is_found_only_in_its_own_envelope() -> None:
    assert capability_of(row("battery-v4", scope="production")) == "rest.lab", "battery-v4 is paid by the LAB: in production it is IA-034's"


def test_the_month_adds_up_to_the_ledgers_and_is_complete_when_every_row_has_a_capability() -> None:
    rows = [row("review-v2", "pick_review", usd="39.54", calls=900, batch_calls=300, input_tokens=1000, cached_tokens=400),
            row(None, "web_search", scope="exa", tier="search", usd="12.92", calls=860),
            row("user-narrative-v3", "user_narrative", ledger="readers", tier="bulk", usd="3.65", calls=432)]
    out = report(rows, Totals(1760, D("52.46"), 432, D("3.65")))
    assert out["complete"] is True and out["unattributed"] == {"calls": 0, "usd": "0.00", "rows": []}
    assert out["total"]["reconciles"] is True and out["total"]["difference_usd"] == "0.000000"
    assert out["total"]["attributed_share"] == 1.0 and out["decides"] is False
    first = out["capabilities"][0]
    assert (first["key"], first["spent_usd"], first["batch_share"], first["cache_read_share"]) == ("production.review", "39.54", 0.3333, 0.4)
    assert first["registered"] is False and first["monthly_usd"] is None


def test_a_row_without_a_capability_is_named_and_the_month_is_not_complete() -> None:
    out = report([row("review-v2", "pick_review", usd="9"), row("mystery-v9", usd="1", calls=3)], Totals(4, D(10), 0, D(0)))
    assert out["complete"] is False and out["total"]["attributed_share"] == 0.9
    assert out["unattributed"]["rows"] == [{"ledger": "usage", "scope": "production", "prompt": "mystery-v9", "purpose": "other",
                                            "tier": "analysis", "agent": None, "calls": 3, "usd": "1.00"}]


def test_a_difference_with_the_ledgers_own_sum_is_said_and_breaks_completeness() -> None:
    out = report([row("review-v2", "pick_review", usd="9")], Totals(1, D("9.02"), 0, D(0)))
    assert out["total"]["reconciles"] is False and out["total"]["difference_usd"] == "-0.020000" and out["complete"] is False


def test_an_input_paid_twice_is_counted_with_what_it_cost() -> None:
    out = report([row("extract-v4", "evidence_extraction", tier="bulk", usd="3", calls=10, repeat_calls=2, repeat_usd=D("0.6"))],
                 Totals(10, D(3), 0, D(0)))
    cap = out["capabilities"][0]
    assert (cap["key"], cap["repeat_calls"], cap["repeat_usd"], out["repeat_usd"]) == ("research.extraction", 2, "0.60", "0.60")


def test_a_registered_capability_carries_its_cap_and_its_warning() -> None:
    out = report([row("chronicle-v4", "match_brief", tier="bulk", usd="11.20")], Totals(1, D("11.20"), 0, D(0)))
    cap = out["capabilities"][0]
    assert (cap["registered"], cap["piece"], cap["monthly_usd"], cap["alert"]) == (True, "AD-F02", "14.00", 80)


def test_the_same_page_has_one_key_whatever_address_or_match_asks() -> None:
    """Pay once per page (AD-K05 over AD-C03): tracking, fragment, case of the host, port and trailing slash do not make another page."""
    a = cache.url_key("https://Example.com:443/news/a/?utm_source=x&b=2&a=1#top")
    b = cache.url_key("https://example.com/news/a?a=1&b=2&fbclid=zz")
    assert a == b and a.startswith(cache.KEY_VERSION + ":url:")
    assert cache.url_key("https://example.com/news/b") != a


# ── the cut of a new piece at 95 % ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("spent", "nxt", "allowed", "reason"), [
    (D("13.29"), D(0), True, "dentro_del_tope"),
    (D("13.30"), D(0), False, "tope_95"),          # 95 % of 14
    (D("13.20"), D("0.10"), False, "tope_95"),     # the next call counted
    (None, D(0), False, "gasto_no_leido"),         # fails closed
])
def test_a_new_piece_stops_at_95_percent_of_its_cap_and_when_its_month_was_not_read(spent: Decimal | None, nxt: Decimal, allowed: bool,
                                                                                    reason: str) -> None:
    a = piece_allows("chronicle_v4", spent, nxt)
    assert (a.allowed, a.reason, a.cap) == (allowed, reason, D("14.00"))


def test_an_unknown_capability_never_spends() -> None:
    assert piece_allows("not_in_the_register", D(0)).reason == "capacidad_desconocida"
    assert capability_budget.CUT_AT == 95 and capability_budget.CUT_VERSION == "piece-cut-v1"
    assert capability_budget.VERSION == "capability-budget-v1", "the register, its caps and its warnings are what they were"


def test_the_pieces_that_call_on_their_own_ask_their_own_capability() -> None:
    news, chron = capability_budget.get(pipeline.CAPABILITY), capability_budget.get(v4_job.CAPABILITY)
    assert news is not None and news.monthly_usd == writer.PIECE_MONTHLY_USD and news.envelope == "lab"
    assert chron is not None and chron.envelope == "production" and "chronicle-v4" in chron.prompts
    assert not piece_allows(pipeline.CAPABILITY, D("1.90")).allowed and piece_allows(pipeline.CAPABILITY, D("1.89")).allowed


# ── the warnings at 80 and 95 %, in each envelope ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("envelope", ["production", "exa", "lab"])
@pytest.mark.parametrize(("share", "expected"), [("0.7999", set()), ("0.80", {80}), ("0.9499", {80}), ("0.95", {80, 95}), ("1.10", {80, 95})])
def test_each_envelope_warns_at_80_and_95_percent_on_its_own(envelope: str, share: str, expected: set[int]) -> None:
    budget = {"production": D(185), "exa": D(35), "lab": D(55)}[envelope]
    spent = (budget * D(share)).quantize(D("0.0001"))
    kw = {"intelligence": D(0), "readers": D(0), "lab": D(0), "exa": D(0)}
    kw[{"production": "intelligence", "exa": "exa", "lab": "lab"}[envelope]] = spent
    figures = budget_v3.figures_of(settings=settings(), **kw)
    found = budget_v3.warnings_of(date(2032, 8, 1), figures, [])
    assert {w.threshold for w in found if w.name == envelope} == expected
    assert not [w for w in found if w.name != envelope], "an envelope never warns for another one"


def test_the_version_is_its_own() -> None:
    assert capability_costs.VERSION == "capability-costs-v1" and capability_costs.UNATTRIBUTED == "sin_capacidad"
