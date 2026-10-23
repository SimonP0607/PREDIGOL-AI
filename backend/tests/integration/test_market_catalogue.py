"""Plan F9 - the catalogue of markets in the database: the rules that are never edited, the keys that are derived and never switched on,
the view of how finished matches ended, and the matrix checked against numbers worked out by hand ("the manual audit")."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.market import catalogue, matrix, rules
from fbi.market.rules import RULES
from fbi.odds.quote_taxonomy import sync_definitions

from .conftest import Seed
from .knowledge_world import FETCHED, KICKOFF, World

pytestmark = pytest.mark.integration

LEGACY = ("1X2", "OU", "BTTS", "DC", "AH")
NAMES = {
    77: "Total Corners (1st Half)", 84: "Total Corners (3 way) (1st Half)", 125: "Corners Asian Handicap (1st Half)",
    126: "Corners Asian Handicap (2nd Half)", 127: "Total Corners (2nd Half)", 128: "Total Corners (3 way) (2nd Half)",
    130: "Corners 1x2 (1st Half)", 131: "Corners 1x2 (2nd Half)", 132: "Home Total Corners (1st Half)",
    133: "Home Total Corners (2nd Half)", 134: "Away Total Corners (1st Half)", 135: "Away Total Corners (2nd Half)",
}
AT = KICKOFF + timedelta(days=10)


def one(db: psycopg.Connection[Any], sql: str, *args: object) -> Any:
    with db.cursor() as cur:
        cur.execute(sql, args)  # type: ignore[arg-type]
        row = cur.fetchone()
    assert row is not None
    return row[0]


@pytest.fixture()
def catalogued(db: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    sync_definitions(db, names=NAMES)
    catalogue.sync(db)
    return db


# ── the rules and the keys ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_catalogue_is_written_once_and_a_second_run_changes_nothing(db: psycopg.Connection[Any]) -> None:
    sync_definitions(db, names=NAMES)
    keys_before = one(db, "SELECT count(*) FROM market.markets")
    assert one(db, "SELECT count(*) FROM market.settlement_rules") == 0, "the migration writes no rule: the code does, once"
    first = catalogue.sync(db)
    assert first.rules_written == len(RULES) and first.keys_written > 40 and first.keys_total == first.keys_written
    assert first.markets_linked > 40 and first.rules_linked >= 55
    assert first.drift == []
    assert one(db, "SELECT count(*) FROM market.markets") == keys_before + first.keys_written
    again = catalogue.sync(db)
    assert (again.rules_written, again.keys_written, again.markets_linked, again.rules_linked, again.drift) == (0, 0, 0, 0, [])
    assert again.keys_total == first.keys_total, "the keys it would ask for are the same, and all of them are there"


def test_a_key_in_the_catalogue_is_not_a_market_that_is_followed_or_modelled(catalogued: psycopg.Connection[Any]) -> None:
    """The five-market pipeline, the quality counters and the tests that count the catalogue see what they always saw."""
    assert one(catalogued, "SELECT count(*) FROM market.markets WHERE key <> ALL(%s) AND (is_tracked OR is_model_enabled)",
               list(LEGACY)) == 0
    assert one(catalogued, "SELECT count(*) FROM market.markets WHERE key = ANY(%s) AND is_tracked AND is_model_enabled",
               list(LEGACY)) == 5, "and the five that are followed and modelled still are"


def test_every_extracted_definition_is_linked_to_a_key_and_a_rule(catalogued: psycopg.Connection[Any]) -> None:
    assert one(catalogued, "SELECT count(*) FROM market.market_definitions WHERE extract AND (market_key IS NULL OR settle_rule IS NULL)") == 0
    assert one(catalogued, "SELECT settle_rule FROM market.market_definitions WHERE provider_bet_id = 6") == "goals_1h@v1"
    assert one(catalogued, "SELECT market_key FROM market.market_definitions WHERE provider_bet_id = 6") == "OU_1H"
    assert one(catalogued, "SELECT count(*) FROM market.market_definitions WHERE settle_rule IS NOT NULL AND NOT extract") == 0
    for bet_id in NAMES:
        assert one(catalogued, "SELECT settle_rule FROM market.market_definitions WHERE provider_bet_id = %s", bet_id) is None, (
            "no rule can grade the corners of a half")


def test_what_the_database_holds_is_never_overwritten_it_is_reported(catalogued: psycopg.Connection[Any]) -> None:
    catalogued.execute("UPDATE market.market_definitions SET market_key = 'OU_2H' WHERE provider_bet_id = 6")
    catalogued.execute("UPDATE market.market_definitions SET settle_rule = NULL WHERE provider_bet_id = 5")
    report = catalogue.sync(catalogued)
    assert report.markets_linked == 0 and report.rules_linked == 1, "only what was empty is filled"
    assert any("bet 6" in line and "OU_2H" in line for line in report.drift)
    assert one(catalogued, "SELECT market_key FROM market.market_definitions WHERE provider_bet_id = 6") == "OU_2H"


def test_a_rule_is_never_edited_or_deleted(catalogued: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    for sql in ("UPDATE market.settlement_rules SET note = 'x' WHERE rule_key = 'goals_ft@v1'",
                "DELETE FROM market.settlement_rules WHERE rule_key = 'goals_ft@v1'"):
        with pytest.raises(psycopg.errors.CheckViolation):
            catalogued.execute(sql)
        catalogued.rollback()
        sync_definitions(catalogued, names=NAMES)
        catalogue.sync(catalogued)
    changed = tuple(r if r.key != "yellow_ft@v1" else rules.Rule("yellow_ft", 1, "cards", "FT", "another convention", r.columns)
                    for r in RULES)
    monkeypatch.setattr(catalogue, "RULES", changed)
    with pytest.raises(catalogue.RuleChangedError, match="yellow_ft@v1"):
        catalogue.sync(catalogued)


def test_a_rule_that_cannot_grade_has_no_columns_and_a_rule_that_can_has_them(db: psycopg.Connection[Any]) -> None:
    catalogue.sync(db)
    assert one(db, "SELECT count(*) FROM market.settlement_rules WHERE liquidable") == sum(1 for r in RULES if r.liquidable)
    assert one(db, "SELECT reason FROM market.settlement_rules WHERE rule_key = 'corners_1h@v1'") == rules.NO_PERIOD_DATA
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("INSERT INTO market.settlement_rules (rule_key, measure, version, family, period, convention, columns, liquidable, "
                   "reason) VALUES ('x_ft@v1', 'x_ft', 1, 'goals', 'FT', 'c', '{}', true, 'ok')")


# ── how finished matches ended ──────────────────────────────────────────────────────────────────────────────────────────

def _stats(w: World, fid: int, home: dict[str, Any], away: dict[str, Any]) -> None:
    w.team_stats(fid, "home", **home)
    w.team_stats(fid, "away", **away)


def _kind(w: World, fid: int, seq: int, kind: str, period: str, side: str, player_side: str | None = None) -> None:
    w.cur.execute("INSERT INTO core.fixture_event_kinds (fixture_id, source, seq, rules_version, kind, period, side, player_side, "
                  "event_fetched_at) VALUES (%s, 'api-football', %s, 'test', %s, %s, %s, %s, %s)",
                  (fid, seq, kind, period, side, player_side, FETCHED))


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture()
def world(w: World) -> dict[str, int]:
    """Seven matches, each one chosen for what the view must get right. Returns their ids by name."""
    h = timedelta(hours=1)
    ids: dict[str, int] = {}
    # a plain match: 2-1 (1-0 at the break), full statistics, cards from events that agree with the statistics
    ids["plain"] = fid = w.match(KICKOFF, 0, 1, (2, 1), ht=(1, 0))
    _stats(w, fid, {"corners": 7, "shots": 12, "shots_on_target": 5, "fouls": 11, "offsides": 2, "saves": 2, "yellow_cards": 2, "red_cards": 0},
           {"corners": 4, "shots": 9, "shots_on_target": 3, "fouls": 14, "offsides": 1, "saves": 3, "yellow_cards": 1, "red_cards": 0})
    _kind(w, fid, 1, "yellow", "1H", "home")
    _kind(w, fid, 2, "yellow", "2H", "home")
    _kind(w, fid, 3, "yellow", "2H", "away")
    # extra time: 1-1 after 90 minutes (0-1 at the break), 2-1 after 120; the provider's totals may include the extra half hour
    ids["extra_time"] = fid = w.match(KICKOFF + h, 0, 2, (2, 1), ht=(0, 1), ft=(1, 1), et=(2, 1), status="AET")
    _stats(w, fid, {"corners": 9, "yellow_cards": 3, "red_cards": 0}, {"corners": 3, "yellow_cards": 2, "red_cards": 0})
    # no score at the break was kept
    ids["no_break"] = w.match(KICKOFF + 2 * h, 1, 2, (1, 1), ht=None)
    # a half-time score that cannot be (3-0 at the break, 1-0 at the end): the halves are not believed
    ids["bad_break"] = w.match(KICKOFF + 3 * h, 2, 3, (1, 0), ht=(3, 0))
    # a dismissal after a second yellow (home) and a straight red (away), from events that agree with the statistics
    ids["dismissals"] = fid = w.match(KICKOFF + 4 * h, 3, 0, (0, 0), ht=(0, 0))
    _stats(w, fid, {"corners": 5, "yellow_cards": 1, "red_cards": 1}, {"corners": 6, "yellow_cards": 0, "red_cards": 1})
    _kind(w, fid, 1, "yellow", "1H", "home")
    _kind(w, fid, 2, "second_yellow", "2H", "home")
    _kind(w, fid, 3, "red", "2H", "away")
    # cards from the statistics only (no classified events), and no corners
    ids["stats_only"] = fid = w.match(KICKOFF + 5 * h, 1, 3, (3, 0), ht=(2, 0))
    _stats(w, fid, {"yellow_cards": 3, "red_cards": 0}, {"yellow_cards": 2, "red_cards": 1})
    # a match that has not been played: not an outcome
    ids["scheduled"] = w.match(KICKOFF + 6 * h, 0, 3, None, status="NS", group="scheduled")
    return ids


def _outcome(db: psycopg.Connection[Any], fid: int) -> dict[str, Any]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM market.fixture_outcomes WHERE fixture_id = %s", (fid,))
        row = cur.fetchone()
    assert row is not None
    return row


def test_the_view_has_one_row_for_each_finished_match_and_none_for_the_others(db: psycopg.Connection[Any], world: dict[str, int]) -> None:
    ids = tuple(world.values())
    got = {r[0] for r in db.execute("SELECT fixture_id FROM market.fixture_outcomes WHERE fixture_id = ANY(%s)", (list(ids),)).fetchall()}
    assert got == set(ids) - {world["scheduled"]}


def test_the_goals_by_half(db: psycopg.Connection[Any], world: dict[str, int]) -> None:
    plain = _outcome(db, world["plain"])
    assert (plain["goals_ft_home"], plain["goals_ft_away"]) == (2, 1)
    assert (plain["goals_1h_home"], plain["goals_1h_away"], plain["goals_2h_home"], plain["goals_2h_away"]) == (1, 0, 1, 1)
    extra = _outcome(db, world["extra_time"])
    assert extra["extra_time"] is True
    assert (extra["goals_ft_home"], extra["goals_ft_away"]) == (1, 1), "extra time and penalties never count"
    assert (extra["goals_1h_home"], extra["goals_1h_away"], extra["goals_2h_home"], extra["goals_2h_away"]) == (0, 1, 1, 0)
    for name in ("no_break", "bad_break"):
        row = _outcome(db, world[name])
        assert row["goals_ft_home"] is not None, "the score of the match is there"
        assert all(row[c] is None for c in ("goals_1h_home", "goals_1h_away", "goals_2h_home", "goals_2h_away")), (
            f"{name}: no half is invented from a break score that is missing or impossible")


def test_a_statistic_of_the_match_is_unknown_after_extra_time_and_never_zero(db: psycopg.Connection[Any], world: dict[str, int]) -> None:
    plain = _outcome(db, world["plain"])
    assert (plain["corners_ft_home"], plain["corners_ft_away"], plain["shots_ft_home"], plain["shots_on_target_ft_away"]) == (7, 4, 12, 3)
    assert (plain["fouls_ft_home"], plain["offsides_ft_away"], plain["saves_ft_away"]) == (11, 1, 3)
    extra = _outcome(db, world["extra_time"])
    assert extra["corners_ft_home"] is None and extra["corners_ft_away"] is None, "the provider does not say whether 9 includes the extra half hour"
    assert _outcome(db, world["stats_only"])["corners_ft_home"] is None, "a statistic nobody gave is unknown, not zero"
    assert _outcome(db, world["no_break"])["corners_ft_home"] is None


def test_the_cards_by_period_and_by_convention(db: psycopg.Connection[Any], world: dict[str, int]) -> None:
    plain = _outcome(db, world["plain"])
    assert plain["cards_source"] == "events" and plain["cards_consistent"] is True
    assert (plain["yellow_ft_home"], plain["yellow_ft_away"], plain["yellow_1h_home"], plain["yellow_1h_away"],
            plain["yellow_2h_home"], plain["yellow_2h_away"]) == (2, 1, 1, 0, 1, 1)
    assert (plain["cards_lines_ft_home"], plain["cards_lines_ft_away"], plain["red_ft_home"], plain["red_ft_away"]) == (2, 1, 0, 0)
    assert (plain["cards_points_ft_home"], plain["cards_points_ft_away"]) == (20, 10)
    d = _outcome(db, world["dismissals"])
    assert d["cards_source"] == "events" and d["cards_consistent"] is True
    assert (d["yellow_ft_home"], d["yellow_ft_away"]) == (1, 0), "the yellow of a pair counts, the red that follows is a dismissal"
    assert (d["red_ft_home"], d["red_ft_away"]) == (1, 1), "a second yellow and a straight red are both dismissals"
    assert (d["cards_lines_ft_home"], d["cards_lines_ft_away"]) == (2, 1), "every card shown counts one, the red after a second yellow as the red it is"
    assert (d["cards_lines_1h_home"], d["cards_lines_2h_home"], d["cards_lines_2h_away"]) == (1, 1, 1)
    assert (d["cards_points_ft_home"], d["cards_points_ft_away"]) == (25, 25), "10 a yellow, 25 a straight red, 15 more for the red after a second yellow"
    only = _outcome(db, world["stats_only"])
    assert only["cards_source"] == "stats"
    assert (only["yellow_ft_home"], only["red_ft_away"], only["cards_lines_ft_away"]) == (3, 1, 3)
    assert only["cards_lines_1h_home"] is None and only["yellow_2h_away"] is None, "the period of a card is not in the statistics"
    extra = _outcome(db, world["extra_time"])
    assert extra["cards_lines_ft_home"] is None, "cards after extra time without events cannot be told from the 90 minutes"


# ── the matrix, checked against numbers worked out by hand ───────────────────────────────────────────────────────────────

def _quote(db: psycopg.Connection[Any], w: World, extraction: int, fid: int, bet_id: int, books: int, selection: str, line: str,
           odds: str) -> None:
    definition = one(db, "SELECT id FROM market.market_definitions WHERE provider_bet_id = %s", bet_id)
    for book in w.books(books):
        db.execute("INSERT INTO market.odds_quotes (fixture_id, bookmaker_id, definition_id, selection, line, odds_decimal, captured_at, "
                   "minutes_to_ko, extraction_id) VALUES (%s, %s, %s, %s, %s, %s, %s, 60, %s)",
                   (fid, book, definition, selection, line, odds, AT - timedelta(days=1), extraction))


@pytest.fixture()
def priced(catalogued: psycopg.Connection[Any], db: psycopg.Connection[Any], w: World, world: dict[str, int]) -> matrix.Facts:
    extraction = one(db, "INSERT INTO market.odds_extractions (payload_hash, extractor_version, provider_fixture_id, fetched_at, "
                         "stamped_by, status) VALUES (%s, 'qx-test', 1, %s, 'fetch', 'ok') RETURNING id", w.hash, AT - timedelta(days=1))
    for key in ("plain", "dismissals"):  # corners, three houses, on two matches
        _quote(db, w, extraction, world[key], 45, 3, "Over", "9.5", "1.90")
    _quote(db, w, extraction, world["plain"], 6, 2, "Over", "0.5", "1.30")  # goals of the first half, two houses, on one match
    return matrix.collect(db, at=AT)


def test_the_matrix_counts_what_a_hand_count_counts(priced: matrix.Facts) -> None:
    """Six finished matches in the window; what each measure can be graded on, counted by hand from the seven matches above."""
    f = priced
    assert f.finished_window == 6
    by = {m: s.window for m, s in f.measures.items()}
    assert by["goals_ft"] == 6
    assert by["goals_1h"] == by["goals_2h"] == 4, "plain, extra time, dismissals, stats only - not the two without a believable break"
    assert by["corners_ft"] == 2, "plain and dismissals: extra time is unknown, the others have no corners"
    assert by["cards_lines_ft"] == 3 and by["cards_lines_1h"] == 2, "plain and dismissals from events, stats only from the statistics"
    assert by["yellow_1h"] == 2
    assert f.cards["with_events"] == 2 and f.cards["with_dismissal"] == 1 and f.cards["compared"] == 2 and f.cards["consistent"] == 2


def test_the_price_the_matrix_reports_is_the_price_the_quotes_hold(priced: matrix.Facts) -> None:
    rows = {r["key"]: r for r in matrix.build_rows(priced)}
    corners = rows["corners.total"]
    assert corners["price"]["fixtures"] == 2 and corners["price"]["houses_median"] == 3.0 and corners["price"]["base_fixtures"] == 2
    assert corners["price"]["coverage"] == 1.0
    assert corners["results"]["n_window"] == 2 and corners["results"]["pct"] == round(2 / 6, 4)
    assert (corners["verdict"], corners["priority"], corners["reason"]) == (matrix.INVESTIGAR, matrix.LOW, "priced"), (
        "all the matches with a price have corners, but two matches are nothing to train a model on")
    half = rows["goals_half.over_under"]
    assert half["price"]["fixtures"] == 1 and half["price"]["houses_median"] == 2.0 and half["price"]["coverage"] == 0.5
    assert half["results"]["n_window"] == 4
    assert rows["corners.half"]["reason"] == rules.NO_PERIOD_DATA and rows["corners.half"]["verdict"] == matrix.NO_VIABLE
    assert rows["cards.total"]["reason"] == "no_prices_in_window"
    assert rows["result.1x2"]["verdict"] == matrix.NO_VIABLE or rows["result.1x2"]["reason"] in ("no_prices_in_window", "edge_not_validated")


def test_a_matrix_is_stored_and_read_back_whole(catalogued: psycopg.Connection[Any], world: dict[str, int]) -> None:
    assert matrix.latest(catalogued) is None
    generated = matrix.generate(catalogued, at=AT)
    run = matrix.store(catalogued, generated)
    last = matrix.latest(catalogued)
    assert last is not None and last["id"] == run
    assert last["matrix_version"] == matrix.MATRIX_VERSION and len(last["rows"]) == len(matrix.ROWS)
    assert [r["key"] for r in last["rows"]] == [r.key for r in matrix.ROWS]
    assert last["summary"]["definitions"] == generated["summary"]["definitions"]
