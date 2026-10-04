"""Field coverage classes: a field followed from the payload to the column, the page and the model."""

from __future__ import annotations

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
                     "/players/squads", "/odds", "/odds/live"):
        assert fl.REGISTRY[endpoint], endpoint
    assert set(fl.RAW_ONLY) == {"/teams/statistics", "/players", "/coachs", "/venues", "/players/teams",
                                "/odds/bookmakers"}
