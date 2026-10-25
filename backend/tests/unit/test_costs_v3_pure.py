"""What the cache and the Message Batches saved (Plan Maestro IA, section 28 and 29): the arithmetic of ``fbi.ai.costs_v3.savings``, with
figures that can be checked by hand. Sonnet 5.5 costs US$2 in, US$10 out and US$0.10 for a token read from the cache, per million."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fbi.ai.costs_v3 import Group, savings, share
from fbi.ai.pricing import token_cost

D = Decimal
DAY = date(2032, 8, 15)
SONNET = "claude-sonnet-5-5"


def group(*, batch: bool = False, calls: int = 1, tin: int = 10_000, tout: int = 0, cached: int = 0, w5: int = 0, w1: int = 0,
          model: str = SONNET, provider: str = "anthropic") -> Group:
    cost = token_cost(provider, model, input_tokens=tin, output_tokens=tout, cached_tokens=cached, cache_write_5m_tokens=w5,
                      cache_write_1h_tokens=w1, batch=batch, at=DAY)
    return Group(DAY, provider, model, batch, calls, tin, tout, cached, w5, w1, cost)


def test_the_cache_saves_what_a_read_token_costs_less_than_a_fresh_one() -> None:
    # 10,000 input of which 6,000 are read: billed (4,000 x 2 + 6,000 x 0.10) / 1e6 = 0.0086; all fresh would be 0.0200
    s = savings([group(cached=6_000)])
    assert (s.cache_usd, s.batch_usd, s.total_usd) == (D("0.0114"), D("0"), D("0.0114"))
    assert (s.calls, s.batch_calls, s.input_tokens, s.cached_tokens, s.write_tokens) == (1, 0, 10_000, 6_000, 0)
    assert s.read_share == 0.6 and s.batch_share == 0.0


def test_a_batch_halves_the_call_and_the_two_savings_add_up_without_counting_a_call_twice() -> None:
    # the same call at half price: billed 0.0043; all fresh at half price 0.0100; all fresh in real time 0.0200
    s = savings([group(batch=True, cached=6_000)])
    assert s.batch_usd == D("0.0100") and s.cache_usd == D("0.0057")
    assert s.total_usd == D("0.0157") == D("0.0200") - D("0.0043")
    assert s.batch_calls == 1 and s.batch_share == 1.0


def test_a_cache_write_that_nobody_reads_costs_a_quarter_more_and_the_saving_says_so() -> None:
    # 10,000 written for five minutes: 12,500 token-prices instead of 10,000, i.e. US$0.0050 over the fresh price
    s = savings([group(w5=10_000)])
    assert s.cache_usd == D("-0.0050") and s.total_usd == D("-0.0050") and s.write_tokens == 10_000
    one_hour = savings([group(w1=10_000)])
    assert one_hour.cache_usd == D("-0.0200"), "an hour's entry is billed twice the input price"


def test_the_groups_add_up_and_the_output_is_priced_the_same_with_or_without_the_cache() -> None:
    groups = [group(cached=6_000, tout=800, calls=3), group(batch=True, cached=8_000, tout=500, calls=2), group(tout=100)]
    s = savings(groups)
    assert s.calls == 6 and s.batch_calls == 2
    parts = [savings([g]) for g in groups]
    assert s.cache_usd == sum((p.cache_usd for p in parts), D(0)) and s.batch_usd == sum((p.batch_usd for p in parts), D(0))
    # output tokens cost the same in the billed price and in the fresh one: they cancel out of the cache's saving
    assert savings([group(cached=6_000, tout=800)]).cache_usd == savings([group(cached=6_000, tout=0)]).cache_usd


def test_a_model_whose_price_is_a_guess_is_left_out_and_nothing_is_divided_by_zero() -> None:
    s = savings([group(model="some-model-nobody-priced", cached=5_000)])
    assert (s.calls, s.cache_usd, s.batch_usd, s.read_share, s.batch_share) == (0, D("0"), D("0"), None, None)
    assert savings([]).total_usd == D("0")


def test_a_share_is_none_without_an_envelope_and_a_fraction_with_one() -> None:
    assert share(D("50"), D("0")) is None and share(D("50"), D("200")) == 0.25 and share(D("0"), D("185")) == 0.0
