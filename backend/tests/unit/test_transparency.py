"""«Cómo le va a PrediGol» (plan UX, A12), the parts without a database: the tally and its sample rules, the margin, the
reasons and stops of a day without picks, the calibration's ranges, the window - and the source code's own guards: it
only reads, it never names the evaluation set or a client's table, and every published pick it counts is of the qualified
set."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.api.services import transparency as service
from fbi.api.switches import TRANSPARENCY, transparency_open

SOURCE = Path(service.__file__).read_text(encoding="utf-8")
SCRIPT = (Path(__file__).resolve().parents[2] / "scripts" / "transparency_check.py").read_text(encoding="utf-8")


def rows(*pairs: tuple[str, str | None]) -> list[dict[str, object]]:
    return [{"status": s, "profit": None if p is None else Decimal(p)} for s, p in pairs]


def test_a_tally_counts_like_mis_picks() -> None:
    c = service.count(rows(("WIN", "1.10"), ("LOSS", "-1"), ("HALF_WIN", "0.45"), ("HALF_LOSS", "-0.5"), ("PUSH", "0"),
                           ("VOID", "0"), ("PENDING", None)))
    assert (c.published, c.pending, c.won, c.lost, c.half_won, c.half_lost, c.push, c.void) == (7, 1, 1, 1, 1, 1, 1, 1)
    assert c.staked == 5, "a void is not a stake; a push is (it wins nothing)"
    assert c.profit == Decimal("0.05") and c.roi == Decimal("0.01")


def test_units_roi_and_margin_only_from_25_settled() -> None:
    small = service.tally_fields(service.count(rows(*[("WIN", "1")] * 24)))
    assert (small["settled"], small["units"], small["roi"], small["margin"], small["conclusive"]) == (
        24, None, None, None, False)
    enough = service.tally_fields(service.count(rows(*[("WIN", "1")] * 13, *[("LOSS", "-1")] * 12)))
    assert (enough["settled"], enough["units"], enough["roi"], enough["margin"]) == (
        25, Decimal("1.00"), Decimal("0.0400"), Decimal("0.2000"))
    assert not enough["conclusive"]
    assert service.tally_fields(service.count(rows(*[("LOSS", "-1")] * 100)))["conclusive"]


@pytest.mark.parametrize(("n", "points"), [(25, "0.2000"), (50, "0.1414"), (100, "0.1000"), (400, "0.0500")])
def test_the_margin_is_the_plans(n: int, points: str) -> None:
    assert service.margin(n) == Decimal(points), "plan section 31: ±20 with 25, ±14 with 50, ±10 with 100, ±5 with 400"


def test_the_small_kinds_of_bet_go_together_last() -> None:
    data = ([{"status": "WIN", "profit": Decimal("1"), "market_key": "OU"}] * 30
            + [{"status": "LOSS", "profit": Decimal("-1"), "market_key": "AH"}] * 26
            + [{"status": "WIN", "profit": Decimal("1"), "market_key": "BTTS"}] * 3
            + [{"status": "VOID", "profit": Decimal("0"), "market_key": "1X2"}] * 40)
    out = service.markets(data)
    assert [m.market for m in out] == ["OU", "AH", "other"], "most settled first; 40 voids are not 25 settled"
    assert (out[2].published, out[2].settled, out[2].void) == (43, 3, 40)


def test_the_commonest_stop_and_its_tie() -> None:
    assert service.commonest({"market": 3, "calibration": 3, "ev": 1}) == "market", "a tie goes to the earlier filter"
    assert service.commonest({"risk": 2, "calibration": 1}) == "risk"
    assert service.commonest({}) is None and service.commonest({"nonsense": 9}) is None


def test_the_window_never_starts_before_the_daily_rule() -> None:
    assert service.window(datetime(2026, 10, 26, 12, tzinfo=UTC)) == (date(2026, 10, 4), date(2026, 10, 25))
    assert service.window(datetime(2027, 1, 15, 12, tzinfo=UTC)) == (date(2026, 12, 16), date(2027, 1, 14))
    first, last = service.window(datetime(2026, 10, 4, 12, tzinfo=UTC))
    assert first > last, "on the rule's first day nothing is counted yet"


@pytest.mark.parametrize(("market", "selection", "home", "away", "expected"), [
    ("1X2", "Home", 2, 1, True), ("1X2", "Draw", 1, 1, True), ("1X2", "Away", 1, 1, False), ("1X2", "Away", 0, 3, True),
    ("OU", "Over", 2, 1, True), ("OU", "Under", 2, 1, False), ("OU", "Under", 1, 1, True),
    ("BTTS", "Yes", 1, 1, True), ("BTTS", "No", 1, 0, True), ("BTTS", "Yes", 3, 0, False)])
def test_what_happened(market: str, selection: str, home: int, away: int, expected: bool) -> None:
    assert service.happened(market, selection, home, away) is expected


def test_the_calibration_ranges_leave_the_small_ones_out() -> None:
    points = ([(Decimal("0.35"), True)] * 7 + [(Decimal("0.35"), False)] * 23 + [(Decimal("0.62"), True)] * 40
              + [(Decimal("1"), True)] * 5 + [(Decimal("0.0"), False)] * 29)
    bins, omitted = service.bins_of(points)
    assert [(b.low, b.high, b.n, b.observed, b.predicted) for b in bins] == [
        (Decimal("0.3"), Decimal("0.4"), 30, Decimal("0.233"), Decimal("0.350")),
        (Decimal("0.6"), Decimal("0.7"), 40, Decimal("1.000"), Decimal("0.620"))]
    assert omitted == 34, "a certainty goes to the last range; ranges under 30 cases are left out and counted"


@pytest.mark.parametrize(("value", "expected"), [(None, False), ("", False), ("1", True), ("on", True), ("0", False),
                                                 ("maybe", False)])
def test_the_switch_is_off_until_the_owner_opens_it(value: str | None, expected: bool,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    if value is None:
        monkeypatch.delenv(TRANSPARENCY, raising=False)
    else:
        monkeypatch.setenv(TRANSPARENCY, value)
    assert transparency_open() is expected and service.shown() is expected


WRITES = re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+[a-z_]+\.|DELETE\s+FROM|TRUNCATE|ALTER\s+TABLE|CREATE\s+|DROP\s+)",
                    re.IGNORECASE)
CLIENT_TABLES = re.compile(r"(?<![\w.])(?:auth\.[a-z_]+|customer\.[a-z_]+|picks\.user_[a-z_]+)\b")


@pytest.mark.parametrize("name", ["service", "script"])
def test_the_page_and_its_contrast_only_read(name: str) -> None:
    text = SOURCE if name == "service" else SCRIPT
    assert not WRITES.search(text), "the page and its contrast never write"
    assert not CLIENT_TABLES.search(text), "no client's data: no auth, customer or a client's own picks"


@pytest.mark.parametrize("name", ["service", "script"])
def test_the_evaluation_set_is_never_named(name: str) -> None:
    text = SOURCE if name == "service" else SCRIPT
    assert "'evaluation'" not in text, "no query reads the evaluation set"
    for sql in re.findall(r'"""(.*?)"""', text, re.DOTALL):
        if "daily_sets" in sql:
            assert "source = 'qualified'" in sql, f"a query of the sets without the qualified filter:\n{sql}"
