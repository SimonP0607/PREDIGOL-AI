"""Field coverage classes: a field followed from the payload to the column, the page and the model."""

from __future__ import annotations

from typing import Any

from scripts.audit_field_coverage import Field, classify

from fbi.truth.v2 import fields as fl


def f(rule: str, *, present: int = 10, seen: int = 10, product: bool | None = None, model: bool | None = None,
      db: tuple[int, int] | None = None) -> Field:
    x = Field("/fixtures", "x", True, seen, present, rule, product, model)
    if db is not None:
        x.db_rows, x.db_filled = db
    classify(x)
    return x


def test_classes() -> None:
    assert f("core.fixtures.round", product=True, model=False).klass == "STORED_AND_USED"
    assert f("core.fixture_player_stats.saves", product=False, model=False).klass == "STORED_NOT_USED"
    assert f("ignore:presentation").klass == "INTENTIONALLY_IGNORED"
    assert f("useful:referee identity").klass == "BUG_DROPPED_FIELD"
    assert f("useful:referee identity", present=0).klass == "UNSUPPORTED", "nothing to drop when never sent"
    assert f("raw:audit only").klass == "UNSUPPORTED"
    assert f("unmapped").klass == "UNSUPPORTED"


def test_a_stored_column_far_emptier_than_its_payloads_is_a_dropped_field() -> None:
    dropped = f("core.fixture_events.comments", product=True, db=(100, 10))
    assert dropped.klass == "BUG_DROPPED_FIELD" and "10%" in dropped.why
    assert f("core.fixture_events.comments", product=True, db=(100, 90)).klass == "STORED_AND_USED"
    assert f("core.fixture_events.comments", present=2, product=True, db=(100, 0)).klass == "STORED_AND_USED", \
        "a field the payloads rarely carry is not judged by its column"


def test_registry_covers_every_normalized_endpoint() -> None:
    for endpoint in ("/fixtures", "/standings", "/injuries", "/leagues", "/teams", "/players/profiles",
                     "/players/squads", "/odds", "/odds/live", "/predictions", "/fixtures/rounds", "/players/topscorers",
                     "/players/topassists", "/players/topyellowcards", "/players/topredcards", "/coachs", "/transfers",
                     "/sidelined", "/trophies", "/countries", "/odds/mapping", "/odds/bets", "/odds/live/bets",
                     "/odds/bookmakers", "/players", "/teams/statistics"):
        assert fl.REGISTRY[endpoint], endpoint
    assert set(fl.RAW_ONLY) == {"/venues", "/players/teams", "/timezone", "/leagues/seasons", "/players/seasons",
                                "/teams/countries", "/teams/seasons"}
    assert all(rule.startswith("ignore:") for rule in fl.RAW_ONLY.values()), "every RAW-only list is a decision"


def test_an_empty_list_is_the_container_of_mapped_fields_not_a_field() -> None:
    rows = fl.inventory("/fixtures", [{"response": [{"fixture": {"id": 1}, "events": [], "lineups": [],
                                                      "players": []}]}], used_columns=set())
    assert {r.path: r.klass for r in rows if r.path.endswith("[]")} == {
        "events[]": "INTENTIONALLY_IGNORED", "lineups[]": "INTENTIONALLY_IGNORED", "players[]": "INTENTIONALLY_IGNORED"}


def test_every_field_of_the_contract_probe_answers_has_a_decision() -> None:
    """Shapes as the provider sent them on 4 Oct 2026 (contract probe), trimmed: no path is left unmapped."""
    bodies: dict[str, dict[str, Any]] = {
        "/predictions": {"response": [{"predictions": {"winner": {"id": 1, "name": "A", "comment": "Win or draw"},
                                                       "win_or_draw": True, "under_over": None,
                                                       "goals": {"home": "-2.5", "away": "-2.5"}, "advice": "x",
                                                       "percent": {"home": "45%", "draw": "45%", "away": "10%"}},
                                       "league": {"id": 239}, "teams": {"home": {"id": 1, "last_5": {"form": "47%"},
                                                                                "league": {"form": "WW"}}},
                                       "comparison": {"form": {"home": "70%"}}, "h2h": [{"fixture": {"id": 9}}]}]},
        "/sidelined": {"response": [{"id": 5179, "sidelined": [{"type": "Injury", "start": "2021-07-25",
                                                                "end": "2021-07-31"}]}]},
        "/trophies": {"response": [{"id": 3470, "trophies": [{"league": "Primera B", "country": "Colombia",
                                                              "season": "2022", "place": "Winner"}]}]},
        "/fixtures/rounds": {"response": [{"round": "Apertura - 1", "dates": ["2026-01-16"]}]},
        "/teams/statistics": {"response": {"league": {"id": 45}, "team": {"id": 50}, "form": "WW",
                                           "fixtures": {"played": {"home": 4, "away": 2, "total": 6}},
                                           "goals": {"for": {"minute": {"0-15": {"total": 1}}}},
                                           "penalty": {"scored": {"total": 1, "percentage": "100%"}},
                                           "lineups": [{"formation": "4-2-3-1", "played": 3}]}},
    }
    for endpoint, body in bodies.items():
        rows = fl.inventory(endpoint, [body], used_columns=set())
        assert [r.path for r in rows if r.klass == "UNSUPPORTED_FIELD"] == [], endpoint
