"""The dataset register's classes: the provider's own gaps never count against us; anything stale, never read
or contradicted by an open finding does."""

from __future__ import annotations

from fbi.truth.freshness import DatasetFreshness, Freshness
from fbi.truth.register import classify


def ds(**counts: int) -> DatasetFreshness:
    d = DatasetFreshness("x", "sla", "fixture")
    for state, n in counts.items():
        d.add(Freshness[state.upper()], n)
    return d


def test_the_provider_gap_is_not_ours_and_a_stale_entity_is() -> None:
    assert classify(ds(fresh=60, unavailable=40), 0)[0] == "FRESH"
    klass, coverage, gap, _ = classify(ds(fresh=60, unavailable=40), 0)
    assert (coverage, gap) == (1.0, 0.4)
    stale = classify(ds(fresh=99, stale=1), 0)
    assert stale[0] == "STALE" and "stale" in stale[3][0]


def test_never_read_is_incomplete_and_an_open_finding_is_invalid() -> None:
    assert classify(ds(fresh=91, unknown=9), 0)[0] == "INCOMPLETE"
    assert classify(ds(fresh=99, unknown=1), 0)[0] == "FRESH", "under 5% never read"
    assert classify(ds(fresh=100), 2)[0] == "INVALID"
    assert classify(ds(), 0)[0] == "UNKNOWN"
