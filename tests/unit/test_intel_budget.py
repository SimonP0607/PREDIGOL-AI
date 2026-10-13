"""The AI budget fixes of PrediGol Intelligence (13 Oct 2026), each a regression test:

* an answer that came back but did not validate is billed: its tokens are counted (before, US$0);
* near the budget, depth on MARGINAL matches stops first, never on the candidates;
* the analyst's cap is the layer's one cap (before, US$20 against the whole layer's spend);
* the month alerts at 50 / 70 / 85 / 95 / 100 %;
* the tiered web search: the competition's language first, then the official words, then an English preview.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest

from fbi.ai.collectors import language_of, queries_for, query_for
from fbi.ai.providers import AnthropicProvider, ProviderError
from fbi.ai.providers.base import JsonRequest
from fbi.ai.usage import ALERT_THRESHOLDS, Budget

REQ = JsonRequest(system="s", user="u", schema={"type": "object"}, schema_name="submit", max_tokens=100, timeout_s=5)


def test_an_invalid_answer_carries_what_it_was_billed() -> None:
    reply = httpx.Response(200, json={"content": [{"type": "text", "text": "thinking only"}],
                                      "usage": {"input_tokens": 1000, "output_tokens": 2000,
                                                "cache_read_input_tokens": 500}})
    p = AnthropicProvider("k", "https://api.example", transport=httpx.MockTransport(lambda _r: reply))
    with pytest.raises(ProviderError) as e:
        p.complete_json("claude-haiku-5-5", REQ)
    assert e.value.code == "invalid_output"
    assert e.value.usage is not None
    assert (e.value.usage.input_tokens, e.value.usage.output_tokens, e.value.usage.cached_tokens) == (1500, 2000, 500)


def _budget(state: str, spent_today: str, daily: str, spent_month: str, monthly: str = "180") -> Budget:
    return Budget(state, Decimal(spent_today), Decimal(spent_month), Decimal(daily), Decimal(monthly),  # type: ignore[arg-type]
                  Decimal(daily) * Decimal("1.5"), Decimal(daily), 1.0, 10, Decimal("6"), date(2032, 9, 20))


def test_marginal_depth_stops_first() -> None:
    assert _budget("NORMAL", "3.00", "6.00", "90").marginal_allowed()
    assert not _budget("NORMAL", "4.80", "6.00", "90").marginal_allowed(), "80 % of the day"
    assert not _budget("NORMAL", "1.00", "6.00", "153").marginal_allowed(), "85 % of the month"
    assert not _budget("REDUCED", "1.00", "6.00", "90").marginal_allowed()
    assert _budget("NORMAL", "4.80", "6.00", "90").pass_allows("final"), "the candidates keep their depth"


def test_one_cap_for_the_whole_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.analyst import budget

    monkeypatch.setattr(budget, "environment", lambda: {"FBI_AI_MONTHLY_BUDGET_USD": "180"})
    assert budget.monthly_budget() == Decimal("180")
    monkeypatch.setattr(budget, "environment", lambda: {"FBI_AI_MONTHLY_BUDGET_USD": "180",
                                                        "FBI_ANALYST_MONTHLY_BUDGET_USD": "25"})
    assert budget.monthly_budget() == Decimal("25"), "an explicit analyst cap still wins"
    monkeypatch.setattr(budget, "environment", lambda: {})
    assert budget.monthly_budget() == Decimal("20")


def test_the_month_alerts_at_fifty_too() -> None:
    assert ALERT_THRESHOLDS == (50, 70, 85, 95, 100)


KO = datetime(2032, 9, 20, 18, tzinfo=UTC)


def test_the_tiered_search() -> None:
    assert language_of("Italy") == "it" and language_of("Germany") == "de" and language_of("Japan") == "en"
    assert query_for("Inter", "Milan", KO, "Italy") == "Inter Milan probabili formazioni infortunati squalificati 2032-09-20"
    one = queries_for("Millonarios", "Santa Fe", KO, "Colombia", "Primera A", levels=1)
    assert one == [query_for("Millonarios", "Santa Fe", KO, "Colombia")], "level 1 keeps its query (and its cache)"
    three = queries_for("Millonarios", "Santa Fe", KO, "Colombia", "Primera A", levels=3)
    assert len(three) == 3 and "comunicado oficial" in three[1] and "preview" in three[2]
    assert queries_for("A", "B", KO, None, None, levels=9)[2] == "A vs B preview predicted lineups 2032-09-20"


def test_call_json_records_the_cost_of_an_invalid_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import usage
    from fbi.ai.config import AiSettings
    from fbi.ai.providers.base import LlmUsage

    class Broken:
        name = "anthropic"

        def complete_json(self, model: str, request: JsonRequest) -> object:
            raise ProviderError("invalid_output", "no tool call", usage=LlmUsage(input_tokens=10_000,
                                                                                 output_tokens=4_000))

    recorded: list[dict[str, object]] = []

    class Ledger:
        def record(self, **kw: object) -> int:
            recorded.append(kw)
            return 7

    monkeypatch.setattr(usage, "budget", lambda conn, at, settings: _budget("NORMAL", "1", "6", "10"))
    out = usage.call_json(None, AiSettings(), tier="bulk", purpose="match_brief", request=REQ,  # type: ignore[arg-type]
                          at=KO, prompt_version="v", input_hash="h", ledger=Ledger(),  # type: ignore[arg-type]
                          provider=(Broken(), "claude-haiku-5-5"))  # type: ignore[arg-type]
    assert out.error == "invalid_output" and out.cost > 0, "the billed tokens are counted"
    assert recorded[0]["status"] == "invalid_output" and recorded[0]["cost"] == out.cost
