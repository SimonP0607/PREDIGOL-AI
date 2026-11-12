"""What the cache and the Message Batches saved (Plan Maestro IA, section 28 and 29): the arithmetic of ``fbi.ai.costs_v3.savings``, with
figures that can be checked by hand. Sonnet 5.5 costs US$2 in, US$10 out and US$0.10 for a token read from the cache, per million; Haiku 5.5
costs US$0.10 in, US$0.50 out and US$0.01 read - and five times as much (0.50 / 2.50 / 0.05) for a prompt above 100,000 input tokens.

IA-051: every call is priced ALONE. Until 11 Nov 2026 the panel added up a day's calls of a model and priced the sum as if it were one call:
a day of Haiku's briefs is millions of tokens, so the sum landed on the long price that no brief paid, and the panel showed US$51.73 of
"saving" in two weeks where the calls saved US$1.59."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pytest

from fbi.ai.calendar import DAY_TZ
from fbi.ai.costs_v3 import Call, savings, share
from fbi.ai.pricing import BATCH_FACTOR, CACHE_WRITE_FACTOR, PRICES, Price, token_cost

D = Decimal
M = D(1_000_000)
AT = datetime(2032, 8, 15, 15, 0, tzinfo=UTC)
SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"


def call(*, batch: bool = False, tin: int = 10_000, tout: int = 0, cached: int = 0, w5: int = 0, w1: int = 0, model: str = SONNET,
         provider: str = "anthropic", at: datetime = AT) -> Call:
    """One call of the ledger, billed the way the ledger bills it: the verified price of exactly these tokens, at its own date."""
    cost = token_cost(provider, model, input_tokens=tin, output_tokens=tout, cached_tokens=cached, cache_write_5m_tokens=w5,
                      cache_write_1h_tokens=w1, batch=batch, at=at)
    return Call(at, provider, model, batch, tin, tout, cached, w5, w1, cost)


def money(x: Decimal) -> Decimal:
    return x.quantize(D("0.0001"), rounding=ROUND_HALF_UP)


def test_the_cache_saves_what_a_read_token_costs_less_than_a_fresh_one() -> None:
    # 10,000 input of which 6,000 are read: billed (4,000 x 2 + 6,000 x 0.10) / 1e6 = 0.0086; all fresh would be 0.0200
    s = savings([call(cached=6_000)])
    assert (s.cache_usd, s.batch_usd, s.total_usd) == (D("0.0114"), D("0"), D("0.0114"))
    assert (s.calls, s.batch_calls, s.input_tokens, s.cached_tokens, s.write_tokens) == (1, 0, 10_000, 6_000, 0)
    assert s.read_share == 0.6 and s.batch_share == 0.0


def test_a_batch_halves_the_call_and_the_two_savings_add_up_without_counting_a_call_twice() -> None:
    # the same call at half price: billed 0.0043; all fresh at half price 0.0100; all fresh in real time 0.0200
    s = savings([call(batch=True, cached=6_000)])
    assert s.batch_usd == D("0.0100") and s.cache_usd == D("0.0057")
    assert s.total_usd == D("0.0157") == D("0.0200") - D("0.0043")
    assert s.batch_calls == 1 and s.batch_share == 1.0


def test_a_cache_write_that_nobody_reads_costs_a_quarter_more_and_the_saving_says_so() -> None:
    # 10,000 written for five minutes: 12,500 token-prices instead of 10,000, i.e. US$0.0050 over the fresh price
    s = savings([call(w5=10_000)])
    assert s.cache_usd == D("-0.0050") and s.total_usd == D("-0.0050") and s.write_tokens == 10_000
    one_hour = savings([call(w1=10_000)])
    assert one_hour.cache_usd == D("-0.0200"), "an hour's entry is billed twice the input price"


def test_the_calls_add_up_and_the_output_is_priced_the_same_with_or_without_the_cache() -> None:
    calls = [call(cached=6_000, tout=800), call(cached=6_000, tout=800), call(batch=True, cached=8_000, tout=500), call(tout=100)]
    s = savings(calls)
    assert s.calls == 4 and s.batch_calls == 1
    parts = [savings([c]) for c in calls]
    assert s.cache_usd == sum((p.cache_usd for p in parts), D(0)) and s.batch_usd == sum((p.batch_usd for p in parts), D(0))
    # output tokens cost the same in the billed price and in the fresh one: they cancel out of the cache's saving
    assert savings([call(cached=6_000, tout=800)]).cache_usd == savings([call(cached=6_000, tout=0)]).cache_usd


def test_haiku_is_priced_call_by_call_and_a_days_sum_priced_as_one_call_would_invent_a_saving_ia051() -> None:
    # 30 briefs of 20,000 input (5,000 read from the cache) and 1,000 output, each far below Haiku's 100k:
    # billed (15,000 x 0.10 + 5,000 x 0.01 + 1,000 x 0.50) / 1e6 = 0.00205; fresh (20,000 x 0.10 + 1,000 x 0.50) / 1e6 = 0.0025
    briefs = [call(model=HAIKU, tin=20_000, cached=5_000, tout=1_000) for _ in range(30)]
    s = savings(briefs)
    assert s.cache_usd == D("0.0135") == 30 * 5_000 * (D("0.10") - D("0.01")) / M  # each read token saves 0.09 per million
    assert (s.calls, s.input_tokens, s.cached_tokens, s.batch_usd) == (30, 600_000, 150_000, D("0"))
    # what the panel did before: the day's 600,000 tokens priced as ONE prompt land on the long price (five times the normal one)
    billed = sum((c.cost for c in briefs), D(0))
    as_one_call = token_cost("anthropic", HAIKU, input_tokens=600_000, output_tokens=30_000, at=AT) - billed
    assert (billed, as_one_call) == (D("0.0615"), D("0.3135"))
    assert as_one_call == 4 * billed + 5 * s.cache_usd, "the long price is 5x every rate: 5 x (billed + true saving) - billed"


def test_a_haiku_call_above_100k_pays_the_long_price_and_so_does_its_saving() -> None:
    # 150,000 input of which 100,000 are read: the long price, 0.50 fresh and 0.05 read: (0.50 - 0.05) x 100,000 / 1e6 = 0.0450
    big = call(model=HAIKU, tin=150_000, cached=100_000)
    assert big.cost == D("0.030000")  # (50,000 x 0.50 + 100,000 x 0.05) / 1e6
    assert savings([big]).cache_usd == D("0.0450")
    # beside a small call, each keeps its own price: 0.0450 + 5,000 x 0.09 / 1e6
    assert savings([big, call(model=HAIKU, tin=20_000, cached=5_000)]).cache_usd == D("0.0455")


def test_a_haiku_batch_saves_half_the_fresh_price_and_its_cache_saving_is_halved_too() -> None:
    # 10 calls in a batch of 20,000 input (5,000 read) and 1,000 output: fresh in real time 0.0025 each, at half price 0.00125
    calls = [call(model=HAIKU, tin=20_000, cached=5_000, tout=1_000, batch=True) for _ in range(10)]
    s = savings(calls)
    # billed 0.5 x (15,000 x 0.10 + 5,000 x 0.01 + 1,000 x 0.50) / 1e6 = 0.001025 each: the cache saved 0.00125 - 0.001025 = 0.000225 a call
    assert calls[0].cost == D("0.001025")
    assert (s.batch_usd, s.cache_usd, s.total_usd) == (D("0.0125"), D("0.0023"), D("0.0148"))  # 10 x 0.00125; 0.00225 to four places


def expected(price: Price, provider: str, c: Call, day: date) -> tuple[Decimal, Decimal]:
    """The saving of ONE call, from the price table and nothing else: each read token saves (input - read price), each written token costs
    (factor - 1) x the input price more, a batch halves all of it and saves half the fresh call. The tier is the call's own."""
    pin, pout, pread = price.input, price.output, price.cached
    if price.valid_until is not None and price.then is not None and day > price.valid_until:
        pin, pout, pread = price.then
    if price.long_after is not None and price.long is not None and c.input_tokens > price.long_after:
        pin, pout, pread = price.long
    f5, f1 = CACHE_WRITE_FACTOR.get(provider, (D(1), D(1)))
    half = BATCH_FACTOR if c.batch else D(1)
    cache = half * ((pin - pread) * c.cached_tokens - (f5 - 1) * pin * c.write_5m - (f1 - 1) * pin * c.write_1h) / M
    batch = (1 - BATCH_FACTOR) * (pin * c.input_tokens + pout * c.output_tokens) / M if c.batch else D(0)
    return cache, batch


@pytest.mark.parametrize(("provider", "model"), sorted(PRICES))
def test_every_priced_model_is_priced_call_by_call_at_its_own_tier(provider: str, model: str) -> None:
    price = PRICES[(provider, model)]
    # each call below the model's long-prompt limit (if it has one) and the three together above it: a sum priced as one call would pay the
    # long price no call paid. Multiples of 8,000 tokens keep every call's price exact to the millionth, at full price and at half.
    size = (price.long_after // 8_000 - 1) * 8_000 if price.long_after else 96_000
    calls = [call(provider=provider, model=model, tin=size, cached=size // 2 // 8_000 * 8_000, w5=8_000, w1=8_000, tout=8_000,
                  batch=batch) for batch in (False, True, False)]
    assert price.long_after is None or sum(c.input_tokens for c in calls) > price.long_after
    s = savings(calls)
    parts = [expected(price, provider, c, AT.date()) for c in calls]
    assert s.cache_usd == money(sum((p[0] for p in parts), D(0)))
    assert s.batch_usd == money(sum((p[1] for p in parts), D(0)))
    assert (s.calls, s.batch_calls) == (3, 1)


def test_a_promotion_is_read_at_each_calls_own_utc_date() -> None:
    # Gemini 3.8 Flash: 0.75 in / 0.075 read until 31 Dec 2026, then 1.50 / 0.15. The ledger bills a call at its UTC date: 01:00 UTC on 1 Jan
    # (still 31 Dec in Bogotá) pays the new price, and its saving is the new price's, (1.50 - 0.15) x 8,000 / 1e6 = 0.0108 - whatever time
    # zone the row comes back in. Until IA-051 the panel read the price at the Bogotá day of a group.
    def flash(at: datetime) -> Call:
        return call(provider="gemini", model="gemini-3.8-flash", tin=16_000, cached=8_000, at=at)

    before, after = flash(datetime(2026, 12, 31, 12, 0, tzinfo=UTC)), flash(datetime(2027, 1, 1, 1, 0, tzinfo=UTC))
    in_bogota = replace(after, at=after.at.astimezone(DAY_TZ))
    assert in_bogota.at.date() == date(2026, 12, 31) and in_bogota.cost == after.cost
    assert savings([before]).cache_usd == D("0.0054")  # (0.75 - 0.075) x 8,000 / 1e6
    assert savings([after]).cache_usd == savings([in_bogota]).cache_usd == D("0.0108")


def test_a_model_whose_price_is_a_guess_is_left_out_and_nothing_is_divided_by_zero() -> None:
    s = savings([call(model="some-model-nobody-priced", cached=5_000)])
    assert (s.calls, s.cache_usd, s.batch_usd, s.read_share, s.batch_share) == (0, D("0"), D("0"), None, None)
    assert savings([]).total_usd == D("0")


def test_a_share_is_none_without_an_envelope_and_a_fraction_with_one() -> None:
    assert share(D("50"), D("0")) is None and share(D("50"), D("200")) == 0.25 and share(D("0"), D("185")) == 0.0
