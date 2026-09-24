"""Football-Data.co.uk rows are parsed literally and attached to a fixture only on full agreement."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fbi.ingestion.historical_odds import OurFixture, match_rows
from fbi.market.baseline import baseline_from_prices
from fbi.providers.football_data.names import normalise, similarity
from fbi.providers.football_data.parse import FDRow, csv_url, parse_csv, season_code

CSV = """Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA,PSCH,PSCD,PSCA,P>2.5,P<2.5,PC>2.5,PC<2.5,AvgH,AvgD,AvgA
E0,16/08/2024,20:00,Man United,Fulham,1,0,H,1.60,4.20,5.25,1.62,4.33,5.40,1.57,4.49,5.62,1.80,2.08,1.75,2.15,1.59,4.19,5.21
E0,17/08/2024,12:30,Ipswich,Liverpool,,,,4.00,3.60,1.85,,,,,,,,,,,,,
E0,17/08/2024,15:00,Arsenal,Wolves,2,0,H,1.22,6.50,12.00,1.23,6.90,13.25,,,,1.55,2.50,,,1.22,6.44,12.30
"""


def test_parse_keeps_literal_prices_and_skips_rows_without_a_score() -> None:
    rows, skipped = parse_csv(CSV)
    assert len(rows) == 2 and len(skipped) == 1 and "no full-time score" in skipped[0]
    first = rows[0]
    assert (first.match_date, first.home, first.away, first.goals_home, first.goals_away) == (
        date(2024, 8, 16), "Man United", "Fulham", 1, 0)
    by = {(p.bookmaker_code, p.price_kind, p.market_key, p.selection): p.odds for p in first.prices}
    assert by[("pinnacle", "closing", "1X2", "Home")] == Decimal("1.57")
    assert by[("pinnacle", "pre_closing", "1X2", "Away")] == Decimal("5.40")
    assert by[("pinnacle", "closing", "OU", "Over")] == Decimal("1.75")
    assert by[("AVG", "pre_closing", "1X2", "Draw")] == Decimal("4.19")
    second = {(p.bookmaker_code, p.price_kind) for p in rows[1].prices}
    assert ("pinnacle", "closing") not in second, "an empty closing column is absent, not zero"


def test_season_codes_follow_the_source() -> None:
    assert season_code(2023) == "2324" and season_code(1999) == "9900"
    assert csv_url("E0", 2024) == "https://www.football-data.co.uk/mmz4281/2425/E0.csv"


def test_names_are_compared_as_evidence() -> None:
    assert normalise("Man United") == "manchester united"
    assert similarity("Man United", "Manchester United") == 1.0
    assert similarity("Dortmund", "Borussia Dortmund") >= 0.9
    assert similarity("Real Madrid", "Real Mallorca") < similarity("Real Madrid", "Real Madrid CF")


def _ours(fid: int, d: date, home: tuple[int, str], away: tuple[int, str], gh: int, ga: int) -> OurFixture:
    return OurFixture(fid, d, home[0], home[1], away[0], away[1], gh, ga)


MU, FUL, ARS, WOL = (1, "Manchester United"), (2, "Fulham"), (3, "Arsenal"), (4, "Wolverhampton Wanderers")


def test_a_row_attaches_on_date_score_and_names_even_a_day_apart() -> None:
    rows, _ = parse_csv(CSV)
    ours = [_ours(10, date(2024, 8, 17), MU, FUL, 1, 0), _ours(11, date(2024, 8, 17), ARS, WOL, 2, 0)]
    report = match_rows(rows, ours)
    assert {f.fixture_id for _, f in report.matched} == {10, 11}
    assert report.aliases["Man United"] == (1, 1) and report.aliases["Wolves"][0] == 4


def test_a_score_disagreement_is_reported_not_forced() -> None:
    row = FDRow("D1", date(2024, 12, 14), "Union Berlin", "Bochum", 0, 2)
    ours = [_ours(20, date(2024, 12, 14), (5, "Union Berlin"), (6, "VfL Bochum"), 1, 1)]
    report = match_rows([row], ours)
    assert not report.matched
    assert report.unmatched[0][1].startswith("score disagreement")


def test_two_equally_good_candidates_make_a_row_ambiguous() -> None:
    row = FDRow("E0", date(2024, 9, 1), "United", "City", 1, 1)
    ours = [_ours(30, date(2024, 9, 1), (7, "Leeds United"), (8, "Hull City"), 1, 1),
            _ours(31, date(2024, 9, 1), (9, "Sheffield United"), (10, "Stoke City"), 1, 1)]
    report = match_rows([row], ours)
    assert not report.matched and "ambiguous" in report.unmatched[0][1]


def test_a_known_alias_is_a_hard_constraint() -> None:
    row = FDRow("E0", date(2024, 9, 1), "Man United", "Fulham", 1, 0)
    ours = [_ours(40, date(2024, 9, 1), MU, FUL, 1, 0)]
    assert match_rows([row], ours, known={"Man United": 99}).matched == []
    assert len(match_rows([row], ours, known={"Man United": 1}).matched) == 1


def test_a_name_that_maps_to_two_teams_is_rejected_everywhere() -> None:
    rows = [FDRow("E0", date(2024, 9, 1), "United", "Fulham", 1, 0),
            FDRow("E0", date(2024, 9, 8), "United", "Arsenal", 2, 2)]
    ours = [_ours(50, date(2024, 9, 1), (7, "Leeds United"), FUL, 1, 0),
            _ours(51, date(2024, 9, 8), (9, "Sheffield United"), ARS, 2, 2)]
    report = match_rows(rows, ours)
    assert not report.matched
    assert all("more than one stored team" in why for _, why in report.unmatched)


def test_every_devig_method_returns_a_distribution() -> None:
    rows = baseline_from_prices(1, "s", "pinnacle", "closing", Decimal("1.57"), Decimal("4.49"), Decimal("5.62"))
    assert {r.method for r in rows} == {"proportional", "shin", "power"}
    for r in rows:
        assert r.p_home + r.p_draw + r.p_away == pytest.approx(1.0, abs=1e-9)
        assert r.p_home > r.p_away > 0
        assert r.overround == pytest.approx(1 / 1.57 + 1 / 4.49 + 1 / 5.62, abs=1e-6)
    assert baseline_from_prices(1, "s", "MAX", "closing", Decimal("2.2"), Decimal("4.0"), Decimal("4.5")) == [], \
        "a book with no margin (a best-price composite) has nothing to remove"
