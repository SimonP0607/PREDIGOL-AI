"""``council-weights-v1`` without a database: the shrinkage, the bounds, and zero for a version the owner did not promote."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.council import weights as w
from fbi.governance import promotions as registry

AT = datetime(2026, 11, 6, 18, 0, tzinfo=UTC)
D = Decimal


def record(hits: int, misses: int, voids: int = 0, *, agent: str = "match", version: str = "match-v2", family: str = "1X2") -> w.TrackRecord | None:
    rows = ([{"agent": agent, "agent_version": version, "market_key": family, "outcome": "HIT"}] * hits
            + [{"agent": agent, "agent_version": version, "market_key": family, "outcome": "MISS"}] * misses
            + [{"agent": agent, "agent_version": version, "market_key": family, "outcome": "VOID"}] * voids)
    return w.records_from(rows).get((agent, version, family))


def promotion(model_name: str, *, family: str = "1X2", to_role: str = "CHAMPION", decided_by: str = "owner", at: datetime = AT - timedelta(days=2),
              pid: int = 1) -> registry.Promotion:
    row: dict[str, Any] = {"id": pid, "at": at, "entity": "agent", "market_key": family, "model_name": model_name, "entity_id": None,
                           "from_role": None, "to_role": to_role, "gate_version": "ma-gate-v1", "criteria": {"report_hash": "0" * 64},
                           "reason": "passed the gate of the family with enough selections", "decided_by": decided_by}
    return registry.from_intel_promotion(row)


def champion(model_name: str = "match@match-v2") -> w.Champion:
    c = w.champion_of([promotion(model_name)], "1X2", at=AT)
    assert c is not None
    return c


def test_the_prior_is_a_coin_flip_and_a_small_sample_cannot_buy_a_weight() -> None:
    assert w.shrunk_precision(0, 0) == D("0.5")
    assert w.shrunk_precision(7, 3) == D("0.5667"), "(7 + 10) / (10 + 20)"
    assert w.shrunk_precision(70, 30) == D("0.6667"), "the same precision with ten times the sample is pulled less"
    assert w.shrunk_precision(3, 7) == D("0.4333")
    with pytest.raises(ValueError):
        w.shrunk_precision(-1, 0)


def test_a_promoted_version_without_a_record_weighs_the_neutral_one() -> None:
    got = w.weight_of("match", "match-v2", "1X2", record=None, champion=champion())
    assert got.promoted and got.weight == D("1.0000") and (got.hits, got.misses) == (0, 0)


def test_the_weight_is_bounded_both_ways_however_long_the_streak() -> None:
    top = w.weight_of("match", "match-v2", "1X2", record=record(1000, 0), champion=champion())
    bottom = w.weight_of("match", "match-v2", "1X2", record=record(0, 1000), champion=champion())
    assert top.weight == w.MAX_WEIGHT and bottom.weight == w.MIN_WEIGHT
    middle = w.weight_of("match", "match-v2", "1X2", record=record(7, 3), champion=champion())
    assert middle.weight == D("1.1334") and w.MIN_WEIGHT < middle.weight < w.MAX_WEIGHT


def test_the_weight_grows_with_the_record_and_voids_change_nothing() -> None:
    weights = [w.weight_of("match", "match-v2", "1X2", record=record(h, 10 - h), champion=champion()).weight for h in range(11)]
    assert weights == sorted(weights) and len(set(weights)) == 11
    assert w.weight_of("match", "match-v2", "1X2", record=record(7, 3, voids=50), champion=champion()).weight == D("1.1334")


@pytest.mark.parametrize("hits", [0, 10, 1000])
def test_a_version_that_is_not_promoted_weighs_zero_whatever_its_record(hits: int) -> None:
    assert w.weight_of("match", "match-v2", "1X2", record=record(hits, 0), champion=None).weight == 0
    other = w.weight_of("match", "match-v1", "1X2", record=record(hits, 0, version="match-v1"), champion=champion("match@match-v2"))
    assert not other.promoted and other.weight == 0, "the family's champion is another version"
    stats = w.weight_of("stats", "stats-v2", "1X2", record=None, champion=champion("match@match-v2"))
    assert stats.weight == 0, "a version the owner's row does not name weighs zero"


def test_the_champion_is_read_by_the_rule_of_the_database_function() -> None:
    assert w.champion_of([], "1X2", at=AT) is None
    head = w.champion_of([promotion("council@council-v1+match-v2+stats-v2")], "1X2", at=AT)
    assert head is not None and head.promotes("council", "council-v1")
    assert head.promotes("match", "match-v2") and head.promotes("stats", "stats-v2"), "an upstream of the champion is promoted with it"
    assert not head.promotes("match", "match-v1")
    assert w.champion_of([promotion("match@match-v2")], "OU", at=AT) is None, "a family's champion is that family's"
    assert w.champion_of([promotion("match@match-v2", at=AT + timedelta(minutes=1))], "1X2", at=AT) is None, "not yet signed at AT"
    ended = [promotion("match@match-v2"), promotion("match@match-v2", to_role="RETIRED", at=AT - timedelta(days=1), pid=2)]
    assert w.champion_of(ended, "1X2", at=AT) is None
    assert w.champion_of(ended, "1X2", at=AT - timedelta(days=1, minutes=1)) is not None, "as of before the retirement"
    report = [promotion("match@match-v2"), promotion("match@match-v2", to_role="VALIDATED", at=AT - timedelta(days=1), pid=2)]
    assert w.champion_of(report, "1X2", at=AT) is not None, "a VALIDATED row is a report: it ends nothing"
    newer = [promotion("match@match-v1", pid=1), promotion("match@match-v2", at=AT - timedelta(days=1), pid=2)]
    c = w.champion_of(newer, "1X2", at=AT)
    assert c is not None and c.head == ("match", "match-v2") and not c.promotes("match", "match-v1"), "the newest CHAMPION row is the champion"


def test_only_an_owner_signed_champion_promotes() -> None:
    assert w.champion_of([promotion("match@match-v2", decided_by="system")], "1X2", at=AT) is None


def test_the_records_are_grouped_by_family_and_a_market_of_no_family_is_not_counted() -> None:
    rows = [{"agent": "match", "agent_version": "match-v2", "market_key": "1X2", "outcome": "HIT"},
            {"agent": "match", "agent_version": "match-v2", "market_key": "OU", "outcome": "MISS"},
            {"agent": "match", "agent_version": "match-v2", "market_key": "OU", "outcome": "HIT"},
            {"agent": "stats", "agent_version": "stats-v2", "market_key": "CORNERS_OU", "outcome": "HIT"},
            {"agent": "match", "agent_version": "match-v2", "market_key": "HT_FT", "outcome": "HIT"}]
    got = w.records_from(rows)
    assert sorted(got) == [("match", "match-v2", "1X2"), ("match", "match-v2", "OU"), ("stats", "stats-v2", "CORNERS")]
    assert (got[("match", "match-v2", "OU")].hits, got[("match", "match-v2", "OU")].misses) == (1, 1)


def test_the_book_weighs_by_family() -> None:
    book = w.book_from(at=AT, track_rows=[{"agent": "match", "agent_version": "match-v2", "market_key": "1X2", "outcome": "HIT"}] * 10,
                       promotions=[promotion("match@match-v2")], families=["1X2", "OU"])
    assert book.weight("match", "match-v2", "1X2").weight == D("1.3334"), "(10 + 10) / 30 / 0.5"
    assert book.weight("match", "match-v2", "OU").weight == 0, "no champion in OU"


def test_the_track_record_sql_reads_as_of_the_moment_and_counts_a_selection_once() -> None:
    sql = " ".join(w.TRACK_SQL.split())
    assert "a.computed_at <= %(at)s" in sql and "f.kickoff_at < %(at)s" in sql
    assert "DISTINCT ON (a.agent, a.agent_version, a.fixture_id, a.market_key, a.selection, a.line)" in sql
    assert "a.signal = 'VERDICT'" in sql and "a.classified_by = 'code'" in sql
