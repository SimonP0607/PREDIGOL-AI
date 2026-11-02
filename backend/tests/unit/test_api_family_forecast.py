"""What the families forecast for a match, as the Admin Console's preview lays it out (plan F10.17b, ``fbi.api.services.forecast``).

The families (the goals of each half, the corners, the cards, the yellow cards) write their forecasts under a version of their own,
``family-v1``: research, uncalibrated, with no interval. The page of the forecast of a match never mixes them into the forecast of the product -
that reads ``forecast-v1`` and nothing else - and a user never gets them: the preview alone gets a section of its own, ``families``, and it is
null in every other answer.

Here the layout is checked without a database: the service reads through two functions, and the tests answer them. The same page over real rows,
and the route with each role, are in ``tests/integration/test_families_forecast.py`` and ``tests/integration/test_forecast_api.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.api.contracts.forecast import FamilyMarket
from fbi.api.envelope import DataStatus
from fbi.api.services import families as families_service
from fbi.api.services import family_rules
from fbi.api.services import forecast as service
from fbi.families import forecast as families
from fbi.market.rules import RULES_BY_MEASURE

FIXTURE = 4242
AT = datetime(2035, 3, 3, 12, 0, tzinfo=UTC)
KICKOFF = AT + timedelta(days=1)
KNOWN = AT - timedelta(hours=2)
CUTOFF = AT - timedelta(hours=3)


def row(family: str, key: str, line: str, selection: str, p: str, *, known: datetime = KNOWN, cutoff: datetime = CUTOFF,
        model: str | None = None) -> dict[str, Any]:
    """A row of ``models.match_forecasts`` as the query returns it: what a family stores is the model's own number, with no interval."""
    return {"market_key": key, "line": Decimal(line), "family": family, "selection": selection, "model_name": model or f"family-{family.lower()}",
            "calibration": "UNCALIBRATED", "basis": "no_champion", "known_at": known, "data_cutoff_ts": cutoff,
            "p": Decimal(p), "p_lo": None, "p_hi": None, "p_model": Decimal(p)}


def two_way(family: str, key: str, line: str, over: str, **kw: Any) -> list[dict[str, Any]]:
    return [row(family, key, line, "Over", over, **kw), row(family, key, line, "Under", str(Decimal(1) - Decimal(over)), **kw)]


class Database:
    """The database as the service sees it: the fixture, and each query answered by what it asks for. Every question is kept."""

    def __init__(self, *, families: list[dict[str, Any]] | None = None, forecast: list[dict[str, Any]] | None = None) -> None:
        self.families = families or []
        self.forecast = forecast or []
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def fetch_all(self, conn: Any, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        asked = dict(params or {})
        self.asked.append((sql, asked))
        if sql == service.FORECAST_SQL:
            return list(self.families if asked["version"] == service.FAMILY_VERSION else self.forecast)
        return []

    def fetch_one(self, conn: Any, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return {"id": FIXTURE, "kickoff_at": KICKOFF, "status_group": "scheduled", "data_class": "MODEL_READY", "quarantined": False}

    def versions_read(self) -> list[str]:
        return [p["version"] for sql, p in self.asked if sql == service.FORECAST_SQL]


@pytest.fixture()
def database(monkeypatch: pytest.MonkeyPatch) -> Database:
    db = Database()
    monkeypatch.setattr(service, "fetch_all", db.fetch_all)
    monkeypatch.setattr(service, "fetch_one", db.fetch_one)
    monkeypatch.setattr(service, "environment", lambda: {})
    return db


def laid_out(db: Database, rows: list[dict[str, Any]]) -> list[FamilyMarket]:
    db.families = rows
    answer = service.match_forecast(object(), FIXTURE, preview=True, at=AT)  # type: ignore[arg-type]
    assert answer.data is not None and answer.data.families is not None
    assert answer.data.families.status == DataStatus.OK and answer.data.families.code is None
    return answer.data.families.data


# ── the layout ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_families_come_in_the_order_of_the_console_each_market_by_its_key_and_each_line_from_the_lowest(database: Database) -> None:
    rows = [
        *two_way("YELLOW", "YELLOW_OU", "2.5", "0.40"),
        *two_way("CARDS", "CARDS_OU", "3.5", "0.52"),
        *two_way("CORNERS", "CORNERS_OU", "10.5", "0.30"), *two_way("CORNERS", "CORNERS_OU", "8.5", "0.70"),
        *two_way("CORNERS", "CORNERS_OU", "9.5", "0.55"),
        *two_way("GOALS_HALF", "OU_1H", "0.5", "0.66"),
        *[row("GOALS_HALF", "HTFT", "0", s, p) for s, p in (("Home/Home", "0.30"), ("Draw/Draw", "0.20"), ("Away/Away", "0.50"))],
    ]
    markets = laid_out(database, rows)
    assert [(m.family, m.market) for m in markets] == [
        ("GOALS_HALF", "HTFT"), ("GOALS_HALF", "OU_1H"), ("CORNERS", "CORNERS_OU"), ("CARDS", "CARDS_OU"), ("YELLOW", "YELLOW_OU")], (
        "the order of the console (goals of the halves, corners, cards, yellow cards), then the key of the market")
    assert list(dict.fromkeys(m.family for m in markets)) == list(family_rules.FAMILIES)
    corners = next(m for m in markets if m.market == "CORNERS_OU")
    assert [ln.line for ln in corners.lines] == [Decimal("8.5"), Decimal("9.5"), Decimal("10.5")], "by the number, not by the text: 10.5 comes after 9.5"
    assert [o.selection for o in corners.lines[0].outcomes] == ["Over", "Under"], "the outcomes keep the order they were stored in"
    assert [ln.line for ln in next(m for m in markets if m.market == "HTFT").lines] == [Decimal("0")], "a market with no line has the line 0"


def test_the_most_probable_outcome_of_each_line_is_marked_and_the_first_wins_a_tie(database: Database) -> None:
    rows = [*two_way("CORNERS", "CORNERS_OU", "9.5", "0.55"), *two_way("CORNERS", "CORNERS_OU", "10.5", "0.50"),
            *two_way("CORNERS", "CORNERS_OU", "11.5", "0.25")]
    (market,) = laid_out(database, rows)
    likely = [[o.selection for o in ln.outcomes if o.likely] for ln in market.lines]
    assert likely == [["Over"], ["Over"], ["Under"]], "one outcome per line, the one with the most probability; a tie leaves the first"


def test_the_fair_odds_are_one_over_the_probability_and_nothing_is_added_to_what_the_family_stored(database: Database) -> None:
    (market,) = laid_out(database, [*two_way("CORNERS", "CORNERS_OU", "9.5", "0.55"), row("CORNERS", "CORNERS_OU", "9.5", "Void", "0")])
    over, under, void = market.lines[0].outcomes
    assert (over.probability, under.probability) == (Decimal("0.55"), Decimal("0.45"))
    assert (over.fair_odds, under.fair_odds) == (Decimal("1.82"), Decimal("2.22")), "1 / probability, to the cent"
    assert void.fair_odds is None, "no odds from a probability of zero"
    assert all(o.low is None and o.high is None for o in market.lines[0].outcomes), "a family measures no interval, and the page invents none"
    assert all(o.model_probability is None for o in market.lines[0].outcomes), "the model's number is the probability: it has no calibrated one beside it"
    assert (market.calibration, market.model) == ("UNCALIBRATED", "family-corners")


def test_each_market_names_the_rule_that_grades_a_bet_on_it_and_none_when_no_rule_can(database: Database) -> None:
    keys = {"OU_1H": ("GOALS_HALF", "goals_1h@v1"), "OU_2H": ("GOALS_HALF", "goals_2h@v1"), "HTFT": ("GOALS_HALF", "goals_halves@v1"),
            "CORNERS_OU": ("CORNERS", "corners_ft@v1"), "CARDS_OU": ("CARDS", "cards_lines_ft@v1"), "YELLOW_OU": ("YELLOW", "yellow_ft@v1"),
            "SOMETHING_ELSE": ("CORNERS", None)}
    markets = laid_out(database, [r for key, (family, _) in keys.items() for r in two_way(family, key, "1.5", "0.5")])
    assert {m.market: m.rule for m in markets} == {key: rule for key, (_, rule) in keys.items()}
    assert {rule for _, rule in keys.values() if rule} <= {r.key for r in RULES_BY_MEASURE.values()}, "a rule the registry has"


def test_a_market_is_dated_by_its_newest_line_and_cut_off_where_that_line_was(database: Database) -> None:
    older, newer = KNOWN - timedelta(hours=5), KNOWN
    rows = [*two_way("CORNERS", "CORNERS_OU", "9.5", "0.55", known=older, cutoff=CUTOFF - timedelta(days=1)),
            *two_way("CORNERS", "CORNERS_OU", "10.5", "0.35", known=newer, cutoff=CUTOFF)]
    (market,) = laid_out(database, rows)
    assert [ln.known_at for ln in market.lines] == [older, newer], "each line says when it was said: a newer set replaces a line only when it moved"
    assert market.known_at == newer and market.data_cutoff_at == CUTOFF


# ── what is said when there is nothing ───────────────────────────────────────────────────────────────────────────────────────

def test_a_match_the_families_forecast_nothing_for_says_so_and_does_not_look_like_a_gap(database: Database) -> None:
    answer = service.match_forecast(object(), FIXTURE, preview=True, at=AT)  # type: ignore[arg-type]
    assert answer.data is not None and answer.data.families is not None
    families_section = answer.data.families
    assert (families_section.status, families_section.code, families_section.data) == (DataStatus.EMPTY, "no_family_forecast", [])
    assert families_section.reason, "an empty section says why"
    assert answer.data.forecast.code == "no_forecast_yet", "and the forecast of the product is its own business"


# ── who reads what ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_preview_alone_reads_the_families_and_the_forecast_never_reads_them(database: Database) -> None:
    database.families = two_way("CORNERS", "CORNERS_OU", "9.5", "0.55")
    answer = service.match_forecast(object(), FIXTURE, preview=True, at=AT)  # type: ignore[arg-type]
    assert answer.data is not None
    assert sorted(database.versions_read()) == ["family-v1", "forecast-v1"]
    assert not answer.data.forecast.data and answer.data.forecast.code == "no_forecast_yet", "what the families forecast is not the forecast of the product"
    assert answer.data.families is not None and [m.market for m in answer.data.families.data] == ["CORNERS_OU"]


def test_the_forecast_of_the_product_shows_what_forecast_v1_holds_and_none_of_what_the_families_hold(database: Database) -> None:
    database.families = two_way("CORNERS", "CORNERS_OU", "9.5", "0.55")
    database.forecast = [
        {**row("TOTAL_GOALS", "OU", "2.5", "Over", "0.62", model="dixon_coles"), "p_lo": Decimal("0.55"), "p_hi": Decimal("0.68")},
        {**row("TOTAL_GOALS", "OU", "2.5", "Under", "0.38", model="dixon_coles"), "p_lo": Decimal("0.32"), "p_hi": Decimal("0.45")}]
    answer = service.match_forecast(object(), FIXTURE, preview=True, at=AT)  # type: ignore[arg-type]
    assert answer.data is not None and answer.data.families is not None
    assert [m.market for m in answer.data.forecast.data] == ["OU"], "the corners are not in the forecast of the match"
    assert [m.market for m in answer.data.families.data] == ["CORNERS_OU"], "nor the total of goals in the families"


@pytest.mark.parametrize("users", [False, True])
def test_a_user_never_gets_the_section_and_its_query_is_never_made(database: Database, monkeypatch: pytest.MonkeyPatch, users: bool) -> None:
    monkeypatch.setattr(service, "environment", lambda: {service.USERS_SWITCH: "1" if users else "0"})
    database.families = two_way("CORNERS", "CORNERS_OU", "9.5", "0.55")
    answer = service.match_forecast(object(), FIXTURE, preview=False, at=AT)  # type: ignore[arg-type]
    assert answer.data is None or answer.data.families is None
    assert "family-v1" not in database.versions_read(), "the query of the families is not made for a user, whatever the switch says"
    if users:
        assert database.versions_read() == ["forecast-v1"]
        assert answer.data is not None and answer.data.value is None and answer.data.picks is None
        assert "families" in answer.data.model_dump(), "the field is in the contract, and null"
        assert answer.data.model_dump()["families"] is None
    else:
        assert database.versions_read() == [], "while users do not see the forecast, nothing is read for them"


def test_both_questions_are_asked_as_of_the_same_moment_the_page_was_asked_for(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    service.match_forecast(object(), FIXTURE, preview=True, at=AT)  # type: ignore[arg-type]
    assert [p["at"] for sql, p in database.asked if sql == service.FORECAST_SQL] == [AT, AT]
    database.asked.clear()
    monkeypatch.setattr(service, "now", lambda: AT + timedelta(minutes=5))
    service.match_forecast(object(), FIXTURE, preview=True)  # type: ignore[arg-type]
    assert [p["at"] for sql, p in database.asked if sql == service.FORECAST_SQL] == [AT + timedelta(minutes=5)] * 2, "no moment given: now, for both"


# ── what the page holds about the families, held equal to the families ───────────────────────────────────────────────────────

def test_the_version_the_page_reads_is_the_one_the_families_write() -> None:
    assert service.FAMILY_VERSION == families.VERSION == families_service.FORECAST_VERSION
    assert len({service.FAMILY_VERSION, service.VERSION}) == 2, "two versions: the forecast of the product reads one, the preview of the families the other"
    assert "version = %(version)s" in service.FORECAST_SQL, "the same query, asked with another version"


def test_the_families_the_page_knows_are_the_ones_that_forecast() -> None:
    assert set(family_rules.FAMILIES) == {spec.family for spec in families.SPECS}
