"""PM-02-04: properties of the resolver of the seven states - a market with no settlement rule is never settleable, a market priced by
fewer than three houses never has a price in force, a reader never sees an unauthorised probability - and the blocks of a page. Pure: the
inputs are built by hand. The database and the 1,000 selections of Mi parlay are proved in ``tests/integration/test_coverage_resolve.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

import fbi.coverage.resolve as resolve
from fbi.coverage.resolve import Cell, MatchInputs
from fbi.market.eligibility import MIN_BOOKS, spec_for_key
from fbi.market.in_force import key_of
from fbi.market.rules import rule_for
from fbi.odds.quote_current import CurrentQuote
from fbi.odds.quote_taxonomy import EXTRACTED

AT = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def parlay_rules() -> resolve.ParlayRules:
    """Mi parlay's own checks, as the API hands them to the resolver (``fbi.api.services.availability.parlay_rules``)."""
    from fbi.picks.count_settlement import settle_numbers
    from fbi.userdata import records

    return resolve.ParlayRules(core_markets=records.CORE_MARKETS, lookback=records.SNAPSHOT_LOOKBACK,
                               valid_selection=records.valid_selection, quarter_line=records.quarter_line,
                               outlier_price=records.outlier_price, grade=settle_numbers)


RULES = parlay_rules()
SPECS = [s for s in EXTRACTED if s.has_line or s.kind in ("one_x_two", "both_teams_score", "double_chance")]


def quote(spec_index: int, book: int, selection: str, line: str) -> CurrentQuote:
    s = SPECS[spec_index]
    return CurrentQuote(bookmaker_id=book, bookmaker=f"Casa {book}", bet_id=s.bet_id, family=s.family, period=s.period,
                        subject=s.subject, kind=s.kind, has_line=s.has_line, market_key=s.market_key, provider_name=s.name,
                        selection=selection, line=Decimal(line), odds=Decimal("1.90"), captured_at=AT, since=AT)


def inputs(quotes: tuple[CurrentQuote, ...], *, covered: bool = True, state: str = "evaluable", forecasts: frozenset[str] = frozenset(),
           users: bool = True, cells: dict[str, Cell] | None = None, present: frozenset[str] | None = None) -> MatchInputs:
    return MatchInputs(fixture_id=1, kickoff_at=AT + timedelta(hours=6), status_group="scheduled", competition_season_id=7, at=AT,
                       cells=cells or {}, markets={}, present=present, quotes=quotes, consensus=(), forecasts=forecasts,
                       covered=lambda rule: covered, state_of=lambda bet: state, parlay_on=True, forecast_users=users,
                       rules=RULES)


quotes_st = st.lists(st.tuples(st.integers(0, len(SPECS) - 1), st.integers(1, 6), st.sampled_from(["Over", "Under", "Home", "Away"]),
                               st.sampled_from(["0", "2.5", "9.5", "4.5"])), max_size=40)


@settings(max_examples=150, deadline=None)
@given(quotes_st, st.booleans(), st.sampled_from(["evaluable", "en_calibracion", "no_ofrecer"]), st.booleans())
def test_properties_of_every_market(raw: list[tuple[int, int, str, str]], covered: bool, state: str, users: bool) -> None:
    qs = tuple(quote(*r) for r in raw)
    forecasts = frozenset(key_of(q) for q in qs[::2])
    got = resolve.resolve(inputs(qs, covered=covered, state=state, forecasts=forecasts, users=users))
    for m in got.markets:
        spec = spec_for_key(m.key)
        if spec is None or rule_for(spec) is None:
            assert not m.settleable                       # no rule: never settleable
        books = max((s.books for s in m.selections), default=0)
        if books < MIN_BOOKS:
            assert not m.price_in_force                   # fewer than 3 houses: never a price in force
            assert not m.modules["cuotas"].ok
        if m.prob_authorised:
            assert m.prob_computed and m.catalogue_state == "evaluable" and users
        if m.modules["mi_parlay"].ok:
            assert any(not s.mi_parlay for s in m.selections)
        for s in m.selections:
            assert s.mi_parlay == resolve.parlay_leg(inputs(qs, covered=covered, state=state), m.key, s.selection, s.line)


def test_a_started_match_takes_no_leg() -> None:
    i = inputs((quote(0, 1, "Over", "2.5"),))
    late = MatchInputs(**{**{f: getattr(i, f) for f in i.__dataclass_fields__}, "at": AT + timedelta(hours=7)})
    assert resolve.parlay_leg(late, "OU", "Over", Decimal("2.5")) == ("started",)
    assert resolve.parlay_leg(late, "OU", "Over", Decimal("2.25")) == ("quarter_line", "started")


def test_blocks_follow_the_cells_and_the_facts() -> None:
    cells = {d: Cell("A", 40, 40, False, None) for d in ("events", "lineups", "corners", "yellow_cards", "shots")}
    cells["shots"] = Cell("C", 40, 25, False, None)
    cells["xg"] = Cell("D", 40, 0, False, "no_entregado")
    got = resolve.resolve(inputs((), cells=cells)).blocks
    assert got["events"].level == "A" and got["events"].exists
    assert got["team_stats"].level == "C"                 # the worst of its data
    assert got["xg"].level == "D" and not got["xg"].exists and got["xg"].reason == "no_entregado"
    assert got["referee"].level is None and got["referee"].reason == "sin_medir"
    after = resolve.resolve(inputs((), cells=cells, present=frozenset({"events"}))).blocks
    assert after["events"].exists and not after["lineups"].exists


def test_the_body_names_the_rules_and_every_core_market() -> None:
    body = resolve.resolve(inputs(())).as_json()
    assert body["rules_version"] == "coverage-levels-v1"
    assert {m["key"] for m in body["markets"]} == {"1X2", "OU", "BTTS", "AH", "DC"}
    for m in body["markets"]:
        assert set(m["modules"]) == {"mi_parlay", "picks", "cuotas"}
        assert m["price_in_force"] is False
