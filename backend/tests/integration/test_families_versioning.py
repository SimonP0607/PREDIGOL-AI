"""Registering a model of counts (plan F10): the registry row (family ``counts``), one immutable version per spec and code."""

from __future__ import annotations

from datetime import date
from typing import Any

import psycopg
import pytest

from fbi.families import versioning

SPEC = "corners_ft:xi=0.0019,penalty=2"
HYPER: dict[str, Any] = {"measure": "corners_ft", "xi": 0.0019, "penalty": 2.0}
WINDOW: dict[str, Any] = {"train_from": date(2022, 10, 1), "train_to": date(2026, 10, 20), "n_train": 82_954}


def _register(db: psycopg.Connection[Any], **over: Any) -> int:
    args: dict[str, Any] = {"model": "family-corners-test", "description": "corners, negative binomial", "spec": SPEC, "hyper": HYPER,
                            "feature_names": ["team attack", "team defence"], "repo_commit": "abc123456789", **WINDOW}
    args.update(over)
    return versioning.ensure_version(db, **args)


def test_the_first_call_registers_the_model_and_its_version(db: psycopg.Connection[Any]) -> None:
    version_id = _register(db)
    row = db.execute("SELECT r.name, r.family, v.version, v.status, v.n_train, v.code_version, v.hyperparameters, v.train_to > v.train_from "
                     "FROM models.model_versions v JOIN models.model_registry r ON r.id = v.model_id WHERE v.id = %s", (version_id,)).fetchone()
    assert row is not None
    name, family, version, status, n_train, commit, hyper, window_ok = row
    assert (name, family, status, n_train, commit, window_ok) == ("family-corners-test", "counts", "experimental", 82_954, "abc123456789", True)
    assert version == versioning.version_string(SPEC)
    assert hyper["measure"] == "corners_ft" and hyper["code_version"] == versioning.code_version(), "the code that made it is recorded"


def test_the_same_version_is_the_same_row_and_another_spec_is_another_one(db: psycopg.Connection[Any]) -> None:
    first = _register(db)
    assert _register(db, description="a new description") == first, "calling again does not open a version"
    row = db.execute("SELECT description FROM models.model_registry WHERE name = 'family-corners-test'").fetchone()
    assert row == ("a new description",), "the registry keeps the latest description"
    other = _register(db, spec="corners_ft:xi=0.0030,penalty=2", hyper={**HYPER, "xi": 0.003})
    assert other != first, "another spec is another version"


def test_a_version_is_immutable(db: psycopg.Connection[Any]) -> None:
    _register(db)
    with pytest.raises(versioning.VersionConflictError):
        _register(db, hyper={**HYPER, "penalty": 5.0})


def test_a_window_of_a_single_day_still_makes_a_valid_version(db: psycopg.Connection[Any]) -> None:
    version_id = _register(db, model="family-one-day", train_from=date(2026, 10, 1), train_to=date(2026, 10, 1), n_train=0)
    row = db.execute("SELECT n_train, train_to - train_from FROM models.model_versions WHERE id = %s", (version_id,)).fetchone()
    assert row == (1, 1), "the table wants train_to after train_from and at least one training match"
