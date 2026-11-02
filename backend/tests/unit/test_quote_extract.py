"""The pure part of the price clock: reading a ``/odds`` body, stamping it, judging it (plan F1)."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fbi.odds.quote_extract import (
    ExtractionReport,
    ParsedEntry,
    Registry,
    judge,
    minutes_to_ko,
    parse_body,
    registry_from_taxonomy,
    stamp_for,
)
from fbi.providers.api_football.normalize import iter_odds

CONTRACTS = Path(__file__).parents[1] / "fixtures" / "contracts"
KICKOFF = datetime(2026, 10, 17, 11, 30, tzinfo=UTC)
D = Decimal


def real_body() -> dict[str, Any]:
    body: dict[str, Any] = json.loads((CONTRACTS / "odds_prematch.json").read_text())["body"]
    return body


def registry() -> Registry:
    return registry_from_taxonomy()


def tiny_body(bets: list[dict[str, Any]], *, fixture: int = 77, update: str | None = "2026-10-16T10:00:00+00:00",
              kickoff: str = "2026-10-17T11:30:00+00:00") -> dict[str, Any]:
    entry: dict[str, Any] = {
        "fixture": {"id": fixture, "date": kickoff, "timestamp": int(datetime.fromisoformat(kickoff).timestamp())},
        "bookmakers": [{"id": 8, "name": "Bet365", "bets": bets}],
    }
    if update is not None:
        entry["update"] = update
    return {"get": "odds", "results": 1, "response": [entry]}


def bet(bet_id: int, name: str, *values: tuple[Any, Any]) -> dict[str, Any]:
    return {"id": bet_id, "name": name, "values": [{"value": v, "odd": o} for v, o in values]}


# ── the pipeline and the price clock must read a payload the same way ───────────────────────────────────────────


def test_the_five_bets_come_out_exactly_as_the_pipelines_own_reader_has_them() -> None:
    """Price for price: the same real payload through ``iter_odds`` (what ``odds_snapshots`` is made of) and through the
    price clock. If this ever fails the two series disagree about what a row means."""
    body = real_body()
    theirs = {(q.provider_bookmaker_id, q.market_key, q.selection, q.line, q.odds_decimal)
              for q in iter_odds(body, kickoff_at=KICKOFF, captured_at=KICKOFF - timedelta(hours=3),
                                 payload_hash="x", source="prematch")}
    assert theirs

    reg = registry()
    (entry,) = parse_body(body, reg.specs, reg.known)
    key_of = {bet_id: spec.market_key for bet_id, (_, spec) in reg.extract.items() if spec.market_key}
    ours = {(q.provider_bookmaker_id, key_of[q.provider_bet_id], q.selection, q.line, q.odds)
            for q in entry.quotes if q.provider_bet_id in key_of}
    assert ours == theirs


def test_a_real_payload_yields_the_structured_families() -> None:
    reg = registry()
    (entry,) = parse_body(real_body(), reg.specs, reg.known)
    assert entry.provider_fixture_id == 1557430
    assert entry.kickoff_at == datetime.fromtimestamp(1792236600, UTC)
    assert entry.provider_update_at == datetime(2026, 9, 20, 9, 29, 18, tzinfo=UTC)
    assert entry.bookmakers == 5
    assert entry.bets_extracted > 10 and entry.bets_seen > entry.bets_extracted
    bets = {q.provider_bet_id for q in entry.quotes}
    assert {1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 16, 17, 19, 20, 26, 33, 34, 35, 104, 105, 106, 107, 108} <= bets
    assert all(q.odds > 1 for q in entry.quotes)
    assert not entry.renamed, "the catalogue names are the payload's names"
    assert not entry.unknown_bets, "every bet of a real payload is classified"


def test_a_real_payload_refuses_only_prices_that_are_not_prices() -> None:
    """The vocabularies of the extracted bets are the provider's, so the only values of a real payload that are refused are
    the 1.00 'prices' of an extreme line (nobody can bet at 1.00: the live pipeline refuses them too)."""
    reg = registry()
    (entry,) = parse_body(real_body(), reg.specs, reg.known)
    assert entry.refused == 12 and entry.refused_by_bet == {5: 6, 16: 1, 17: 1, 19: 2, 104: 2}
    assert all(sample.endswith("'1.00')") for samples in entry.refused_samples.values() for sample in samples)


def test_the_two_rows_of_every_handicap_pair_of_a_real_payload_are_complementary() -> None:
    """The measurement behind the negation of the away row, on real prices (bets 4, 19 and 104): with the away line negated,
    'home at L' and 'away at -L' are the two sides of one bet, so their inverse prices add up to the bookmaker's margin. Stored
    as printed they would pair a home line with an away line that is not its complement."""
    reg = registry()
    (entry,) = parse_body(real_body(), reg.specs, reg.known)
    prices = {(q.provider_bookmaker_id, q.provider_bet_id, q.selection, q.line): q.odds for q in entry.quotes}
    totals = [1 / odds + 1 / prices[(book, bet, "Away", -line)]
              for (book, bet, side, line), odds in prices.items()
              if bet in (4, 19, 104) and side == "Home" and (book, bet, "Away", -line) in prices]
    assert len(totals) > 60 and {b for (_, b, _, _) in prices if b in (4, 19, 104)} == {4, 19, 104}
    ordered = sorted(totals)
    assert Decimal("1.0") < ordered[0] and ordered[-1] < Decimal("1.25"), (ordered[0], ordered[-1])
    assert Decimal("1.03") < ordered[len(ordered) // 2] < Decimal("1.12"), ordered[len(ordered) // 2]


def test_the_selection_words_of_the_halves_are_those_of_the_full_time_markets() -> None:
    reg = registry()
    (entry,) = parse_body(real_body(), reg.specs, reg.known)
    words = {(q.provider_bet_id, q.selection) for q in entry.quotes}
    assert (13, "Draw") in words and (20, "1X") in words and (34, "Yes") in words and (22, "Odd") in words
    assert (7, "Home/Draw") in words and (11, "1st Half") in words
    totals = {(q.provider_bet_id, q.selection, q.line) for q in entry.quotes if q.provider_bet_id == 105}
    assert (105, "Over", D("1.5")) in totals and (105, "Under", D("0.5")) in totals


# ── what the reader refuses and reports ─────────────────────────────────────────────────────────────────────────


def test_a_renamed_bet_is_refused_not_relabelled() -> None:
    reg = registry()
    body = tiny_body([bet(45, "Corners Over Under", ("Over 9.5", "1.90"), ("Under 9.5", "1.90")),
                      bet(80, "Booking Points", ("Over 3.5", "1.80"), ("Under 3.5", "2.00"))])
    (entry,) = parse_body(body, reg.specs, reg.known)
    assert {q.provider_bet_id for q in entry.quotes} == {45}
    assert entry.renamed == [(80, "Cards Over/Under", "Booking Points")]
    assert entry.refused == 2 and entry.refused_by_bet == {80: 2}


def test_a_bet_nobody_has_classified_is_reported_not_ignored() -> None:
    reg = registry()
    body = tiny_body([bet(999, "A New Market", ("Yes", "2.0")), bet(92, "Anytime Goal Scorer", ("Someone", "3.0"))])
    (entry,) = parse_body(body, reg.specs, reg.known)
    assert entry.unknown_bets == {999: "A New Market"}, "92 is parked (known): not news; 999 is"
    assert not entry.quotes


def test_values_nobody_can_read_are_counted_with_samples() -> None:
    reg = registry()
    body = tiny_body([bet(45, "Corners Over Under", ("Over 9.5", "1.90"), ("Over 9.3", "1.90"), ("Under 9.5", "0.80"),
                          ("Under 10.5", "abc"), ("Over 10.5", None))])
    (entry,) = parse_body(body, reg.specs, reg.known)
    assert [(q.selection, q.line) for q in entry.quotes] == [("Over", D("9.5"))]
    assert entry.refused == 4
    assert entry.refused_by_bet == {45: 4}
    assert 0 < len(entry.refused_samples[45]) <= 5
    report = ExtractionReport()
    report.note(entry)
    assert report.quotes_refused == 4 and report.quotes_offered == 1 and report.refused_by_bet == {45: 4}


def test_malformed_bodies_do_not_raise() -> None:
    reg = registry()
    bodies: list[Any] = [{}, {"response": None}, {"response": "x"}, {"response": [None, 3, "a", {}]},
                         {"response": [{"fixture": {"id": "7"}, "bookmakers": "x"}]},
                         {"response": [{"fixture": 5, "bookmakers": [{"id": "a", "name": 3, "bets": 4}, None]}]},
                         {"response": [{"bookmakers": [{"id": 1, "name": "B",
                                                        "bets": [None, {"id": "x"}, {"id": 1, "values": 3}]}]}]}]
    for body in bodies:
        entries = parse_body(body, reg.specs, reg.known)
        assert all(not e.quotes for e in entries)


def test_a_payload_that_names_no_fixture_is_still_an_entry_to_judge() -> None:
    reg = registry()
    (entry,) = parse_body({"response": [{"bookmakers": []}]}, reg.specs, reg.known)
    assert entry.provider_fixture_id is None and entry.kickoff_at is None and entry.provider_update_at is None


def test_the_input_body_is_not_modified() -> None:
    body = real_body()
    before = copy.deepcopy(body)
    reg = registry()
    parse_body(body, reg.specs, reg.known)
    assert body == before


def test_the_reader_is_deterministic() -> None:
    reg = registry()
    first = parse_body(real_body(), reg.specs, reg.known)
    second = parse_body(real_body(), reg.specs, reg.known)
    assert first == second


# ── the instant a payload's prices are filed under ──────────────────────────────────────────────────────────────


def test_a_payload_fetched_before_kickoff_is_stamped_with_the_fetch() -> None:
    stamp = stamp_for(KICKOFF - timedelta(hours=2), KICKOFF, KICKOFF - timedelta(hours=5))
    assert stamp.captured_at == KICKOFF - timedelta(hours=2) and stamp.stamped_by == "fetch"


def test_a_payload_fetched_after_kickoff_is_stamped_with_the_providers_update_if_that_is_before_kickoff() -> None:
    update = KICKOFF - timedelta(minutes=3)
    stamp = stamp_for(KICKOFF + timedelta(hours=1), KICKOFF, update)
    assert stamp.captured_at == update and stamp.stamped_by == "provider_update"


def test_a_payload_fetched_after_kickoff_with_no_usable_update_is_not_filed() -> None:
    """It could be an in-play price filed as a pre-match one: the failure the live pipeline was built to avoid."""
    for update in (None, KICKOFF, KICKOFF + timedelta(minutes=1)):
        stamp = stamp_for(KICKOFF + timedelta(minutes=30), KICKOFF, update)
        assert stamp.captured_at is None and stamp.stamped_by == "none", update


def test_a_fetch_at_the_very_instant_of_kickoff_is_not_before_it() -> None:
    assert stamp_for(KICKOFF, KICKOFF, None).captured_at is None
    assert stamp_for(KICKOFF - timedelta(microseconds=1), KICKOFF, None).captured_at is not None


def test_minutes_to_kickoff_are_whole_minutes_floored_at_zero() -> None:
    assert minutes_to_ko(KICKOFF, KICKOFF - timedelta(hours=3, seconds=59)) == 180
    assert minutes_to_ko(KICKOFF, KICKOFF - timedelta(seconds=59)) == 0
    assert minutes_to_ko(KICKOFF, KICKOFF) == 0
    assert minutes_to_ko(KICKOFF, KICKOFF + timedelta(minutes=5)) == 0, "never negative for a pre-match price"


# ── judging an entry ────────────────────────────────────────────────────────────────────────────────────────────


FETCHED = KICKOFF - timedelta(hours=2)


def entry_for(**kw: Any) -> ParsedEntry:
    base: dict[str, Any] = {"provider_fixture_id": 77, "kickoff_at": KICKOFF,
                            "provider_update_at": KICKOFF - timedelta(hours=9)}
    base.update(kw)
    return ParsedEntry(**base)


def test_judging_an_entry_whose_fixture_we_know() -> None:
    verdict = judge(entry_for(), None, FETCHED, {77: (5, KICKOFF + timedelta(days=1))})
    assert verdict.status == "ok" and verdict.fixture_id == 5
    assert verdict.kickoff_at == KICKOFF, "the kick-off the payload carried, not the one the fixture has now"
    assert verdict.stamp.captured_at == FETCHED


def test_judging_an_entry_whose_fixture_we_do_not_know_yet() -> None:
    verdict = judge(entry_for(), None, FETCHED, {})
    assert verdict.status == "no_fixture" and verdict.provider_fixture_id == 77


def test_the_fixture_may_come_from_the_request_when_the_answer_does_not_name_it() -> None:
    assert judge(entry_for(provider_fixture_id=None), 77, FETCHED, {77: (5, None)}).status == "ok"
    assert judge(entry_for(provider_fixture_id=None), None, FETCHED, {77: (5, None)}).status == "error"


def test_the_kickoff_falls_back_to_the_fixture_when_the_payload_has_none() -> None:
    verdict = judge(entry_for(kickoff_at=None), None, FETCHED, {77: (5, KICKOFF)})
    assert verdict.status == "ok" and verdict.kickoff_at == KICKOFF
    assert judge(entry_for(kickoff_at=None), None, FETCHED, {77: (5, None)}).status == "error"


def test_judging_a_payload_fetched_after_kickoff() -> None:
    late = KICKOFF + timedelta(hours=3)
    assert judge(entry_for(provider_update_at=KICKOFF - timedelta(minutes=2)), None, late,
                 {77: (5, KICKOFF)}).stamp.stamped_by == "provider_update"
    assert judge(entry_for(provider_update_at=None), None, late, {77: (5, KICKOFF)}).status == "after_kickoff"


def test_the_extraction_taxonomy_registry_is_consistent() -> None:
    reg = registry()
    assert set(reg.extract) <= reg.known
    assert len(reg.extract) == 55 and len(reg.known) == 338
