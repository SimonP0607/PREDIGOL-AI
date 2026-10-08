"""What a model or search call costs - list prices read from the providers' official pages.

Verified 8 October 2026 (``docs/owner/AI_LAYER_REPORT_2026-10-08.md`` lists every source):
Anthropic platform.claude.com/docs/en/about-claude/pricing, OpenAI developers.openai.com/api/docs/pricing,
Google ai.google.dev/gemini-api/docs/pricing, Mistral mistral.ai/pricing, DeepSeek
api-docs.deepseek.com/quick_start/pricing, Groq / Together / DeepInfra model pages, and the search APIs'
own pricing pages.

Rules that keep the budget honest:

* A model not in the table is priced at the most expensive model known, so an unknown model can only
  make the cap bite earlier, never later.
* Long prompts pay the long-context tier where the provider has one (Claude Haiku 5.5 above 100k
  tokens, GPT-6 above 272k, Gemini 3.1 Pro above 200k).
* Gemini 3.8 Flash's promotional price ends on 31 December 2026: from 1 January 2027 the table
  charges the announced price.
* Cached input is charged at the provider's cache-read price; nothing else is discounted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

VERIFIED_ON = date(2026, 10, 8)
M = Decimal(1_000_000)


@dataclass(frozen=True, slots=True)
class Price:
    """USD per 1M tokens."""

    input: Decimal
    output: Decimal
    cached: Decimal
    long_after: int | None = None
    """Prompts above this many tokens pay the ``long`` price instead."""
    long: tuple[Decimal, Decimal, Decimal] | None = None
    valid_until: date | None = None
    """The last day this price applies (a promotion); ``then`` applies afterwards."""
    then: tuple[Decimal, Decimal, Decimal] | None = None
    note: str = ""


def _p(i: str, o: str, c: str, **kw: object) -> Price:
    return Price(Decimal(i), Decimal(o), Decimal(c), **kw)  # type: ignore[arg-type]


def _t(i: str, o: str, c: str) -> tuple[Decimal, Decimal, Decimal]:
    return Decimal(i), Decimal(o), Decimal(c)


PRICES: dict[tuple[str, str], Price] = {
    # Anthropic (Claude 4.7 and later count about 30 % more tokens for the same text: see ``TOKEN_FACTOR``)
    ("anthropic", "claude-fable-5-1"): _p("10", "50", "0.25"),
    ("anthropic", "claude-opus-5-5"): _p("4", "20", "0.20"),
    ("anthropic", "claude-sonnet-5-5"): _p("2", "10", "0.10"),
    ("anthropic", "claude-haiku-5-5"): _p("0.10", "0.50", "0.01", long_after=100_000, long=_t("0.50", "2.50", "0.05")),
    ("anthropic", "claude-haiku-4-5"): _p("1", "5", "0.10", note="previous generation"),
    ("anthropic", "claude-sonnet-4-5"): _p("3", "15", "0.30", note="previous generation"),
    # OpenAI (developer docs; the marketing page still shows the GPT-5.6 family)
    ("openai", "gpt-6-astra"): _p("10", "50", "1.00", long_after=272_000, long=_t("20", "75", "2.00")),
    ("openai", "gpt-6.1-sol"): _p("2", "10", "0.10", long_after=272_000, long=_t("4", "15", "0.20")),
    ("openai", "gpt-6-luna"): _p("0.10", "0.50", "0.01", long_after=272_000, long=_t("0.20", "0.75", "0.02")),
    # Google Gemini (paid tier)
    ("gemini", "gemini-3.1-pro-preview"): _p("2", "12", "0.20", long_after=200_000, long=_t("4", "18", "0.40")),
    ("gemini", "gemini-3.8-flash"): _p("0.75", "3.75", "0.075", valid_until=date(2026, 12, 31),
                                       then=_t("1.50", "7.50", "0.15"), note="promotional until 31 Dec 2026"),
    ("gemini", "gemini-3.5-flash-lite"): _p("0.30", "2.50", "0.03"),
    ("gemini", "gemini-3.1-flash-lite"): _p("0.25", "1.50", "0.025"),
    # Mistral (Large 4 is on a 50 % "sale" with no end date: budgets use the list price)
    ("mistral", "mistral-large-4"): _p("1.36", "4.18", "0.14", note="list price; sale price 0.68 / 2.09"),
    ("mistral", "mistral-medium"): _p("1.5", "7.5", "1.5"),
    ("mistral", "mistral-small"): _p("0.15", "0.6", "0.15"),
    # DeepSeek (peak price; off-peak is half) - data processed in China: not recommended
    ("deepseek", "deepseek-flash"): _p("0.30", "1.20", "0.006"),
    ("deepseek", "deepseek-v4-pro"): _p("1.32", "3.96", "0.044"),
    # open-weight models on inference providers
    ("groq", "openai/gpt-oss-120b"): _p("0.15", "0.60", "0.15"),
    ("groq", "openai/gpt-oss-20b"): _p("0.075", "0.30", "0.075"),
    ("together", "openai/gpt-oss-120b"): _p("0.15", "0.60", "0.15"),
    ("deepinfra", "openai/gpt-oss-120b"): _p("0.037", "0.17", "0.037"),
}

SEARCH_PRICES: dict[str, Decimal] = {
    # USD per 1,000 searches (search content tokens are billed as model tokens on top, where noted)
    "anthropic": Decimal("10"),  # + results billed as input tokens
    "openai": Decimal("10"),     # + search content billed at model rates
    "gemini": Decimal("14"),     # after 5,000 free a month (shared by Gemini 3.x)
    "mistral": Decimal("30"),
    "exa": Decimal("15"),        # 7 a search + 1 per 1,000 pages of text, and each search asks the text of up
                                 # to 8 results (fbi.analyst.search.MAX_RESULTS): budgeted at the full 8
    "brave": Decimal("5"),
    "tavily": Decimal("8"),
}

TOKEN_FACTOR: dict[str, Decimal] = {"anthropic": Decimal("1.30")}
"""Tokens per 4 characters relative to the usual 1.0: Claude 4.7 and later tokenize ~30 % more."""


def _most_expensive() -> Price:
    return max(PRICES.values(), key=lambda p: (p.output, p.input))


def price_of(provider: str, model: str) -> tuple[Price, bool]:
    """The price, and whether the model is known (unknown = the most expensive known price)."""
    exact = PRICES.get((provider, model))
    if exact is not None:
        return exact, True
    matches = [(k, v) for k, v in PRICES.items() if k[0] == provider and model.startswith(k[1])]
    if matches:
        return max(matches, key=lambda kv: len(kv[0][1]))[1], True
    return _most_expensive(), False


def token_cost(provider: str, model: str, *, input_tokens: int, output_tokens: int, cached_tokens: int = 0,
               at: datetime | date | None = None) -> Decimal:
    """USD for one call. ``input_tokens`` includes ``cached_tokens`` (as every provider reports them)."""
    price, _known = price_of(provider, model)
    day = at.date() if isinstance(at, datetime) else at
    pin, pout, pcache = price.input, price.output, price.cached
    if price.valid_until is not None and price.then is not None and day is not None and day > price.valid_until:
        pin, pout, pcache = price.then
    if price.long_after is not None and price.long is not None and input_tokens > price.long_after:
        pin, pout, pcache = price.long
    cached = max(0, min(cached_tokens, input_tokens))
    fresh = input_tokens - cached
    cost = (pin * fresh + pcache * cached + pout * output_tokens) / M
    return cost.quantize(Decimal("0.000001"))


def search_cost(backend: str, searches: int) -> Decimal:
    per_k = SEARCH_PRICES.get(backend, max(SEARCH_PRICES.values()))
    return (per_k * searches / Decimal(1000)).quantize(Decimal("0.000001"))


def approx_tokens(text: str, provider: str | None = None) -> int:
    """A planning estimate (about four characters a token), never a bill: the bill uses the
    provider's own token counts."""
    factor = TOKEN_FACTOR.get(provider or "", Decimal(1))
    return int((Decimal(len(text)) / 4 * factor).to_integral_value())
