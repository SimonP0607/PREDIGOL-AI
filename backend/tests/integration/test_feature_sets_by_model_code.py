"""PM-13-02 (BE-064): a deploy that leaves the model code as it was does not write the feature sets again.

The forecast keeps a vector unless its newest stored one has the same input hash AND the same ``code_version``; the pipeline passed
the repository commit, so every deploy wrote every upcoming fixture's vector again (9.4 % of the sets of 6 to 20 nov 2026). With
``FBI_FEATURE_SETS_BY_MODEL_CODE=on`` the pipeline names the first commit that ran the model code in force
(``fbi.picks.feature_code``). Off, the behaviour before is kept - the last part of the test shows the defect it fixes."""

from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from fbi.core.version import model_code_version
from fbi.picks import feature_code
from fbi.predictions.forecast import forecast_upcoming
from tests.integration.helpers import scalar
from tests.integration.test_pick_pipeline import AT, _prices_do_not_age, league  # noqa: F401  (fixtures)


def _sets(db: psycopg.Connection, fixture: int) -> int:
    return int(scalar(db.execute("SELECT count(*) FROM features.feature_sets WHERE fixture_id = %s", (fixture,))))


def test_a_new_commit_with_the_same_model_code_writes_no_feature_set_and_the_lineage_holds(
    db: psycopg.Connection, league: dict[str, object], monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    target = int(league["target"])  # type: ignore[call-overload]
    monkeypatch.setenv(feature_code.SWITCH, "on")

    first = feature_code.forecast_code_version(db, "commit-aaaa")
    report = forecast_upcoming(db, at=AT, code_version=first)
    db.commit()
    assert report.feature_sets_written >= 1
    before = _sets(db, target)

    # the next deploy: another commit, the same model code
    second = feature_code.forecast_code_version(db, "commit-bbbb")
    assert second == first == feature_code.first_commit_of(db, model_code_version()), (
        "the commit named is the first one that ran the model code in force, whatever commit is deployed"
    )
    again = forecast_upcoming(db, at=AT + timedelta(hours=1), code_version=second)
    db.commit()
    assert again.feature_sets_written == 0 and again.feature_sets_unchanged >= 1
    assert _sets(db, target) == before, "same inputs, same model code: the same vector is not stored again"

    # no history was touched and every stored set of the fixture still has its values
    assert int(scalar(db.execute(
        "SELECT count(*) FROM features.feature_sets s WHERE s.fixture_id = %s AND NOT EXISTS "
        "(SELECT 1 FROM features.fixture_features ff WHERE ff.feature_set_id = s.id)", (target,)))) == 0
    # the lineage: every forecast that names a feature input hash finds a stored set of its fixture with it
    orphans = int(scalar(db.execute(
        "SELECT count(*) FROM models.predictions p JOIN models.model_versions v ON v.id = p.model_version_id "
        "JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = %s AND m.name = 'elo_ologit' "
        "AND NOT EXISTS (SELECT 1 FROM features.feature_sets s WHERE s.fixture_id = p.fixture_id "
        "AND s.input_hash = p.feature_set_hash)", (target,))))
    assert orphans == 0

    # off: the commit, as before - and a new commit writes the vector again (the defect)
    monkeypatch.setenv(feature_code.SWITCH, "off")
    assert feature_code.forecast_code_version(db, "commit-cccc") == "commit-cccc"
    old_way = forecast_upcoming(db, at=AT + timedelta(hours=2), code_version="commit-cccc")
    db.commit()
    assert old_way.feature_sets_written >= 1 and _sets(db, target) > before


def test_without_a_version_of_the_model_code_the_current_commit_is_named(
    db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(feature_code.SWITCH, "on")
    assert feature_code.first_commit_of(db, "mc_no_such_code") is None
    assert feature_code.forecast_code_version(db, "commit-dddd", model_code="mc_no_such_code") == "commit-dddd"
