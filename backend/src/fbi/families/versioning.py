"""Which code made a family's numbers, and the registration of a model of counts (plan F10).

A version of a model is keyed by the code that decides what it predicts, not by the repository commit: keyed by the commit, every deploy -
a page, a doc, an audit - would open a new version of every model and none could ever gather the prospective record that qualifying it
needs (``fbi.core.version.model_code_version`` says it for the goal models, 5 Oct 2026). The goal models fingerprint the packages
``models``, ``features``, ``predictions``, ``backtesting`` and ``domain``. The families live OUTSIDE those packages on purpose - a file added
there renews the version of every goal model, and F10 must not touch what runs today - so they have a fingerprint of their own: the
sources of ``fbi.families`` and the one file of the goal model they reuse (``fbi.models.goals``: the fit of the strengths). A change in
either is a new family version; a change anywhere else is not.

The fingerprint is read as git stores the files (LF endings), so the same commit has the same fingerprint on every machine.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import tuple_row

FAMILY_SEMVER: Final = "1.0.0"
"""Bump it when a version must be new although no source changed (a hyper-parameter that is not in the sources)."""

REGISTRY_FAMILY: Final = "counts"
"""The value of ``models.model_registry.family`` for these models (migration 0093)."""

REUSED: Final = ("models/goals.py",)
"""Files outside ``fbi.families`` whose code decides what a family predicts (relative to the ``fbi`` package)."""


class VersionConflictError(RuntimeError):
    """The version string exists with other hyper-parameters: a version is immutable."""


def _base() -> Path:
    return Path(__file__).resolve().parents[1]


def fingerprint(root: Path | None = None) -> str:
    """sha256 of the sources of ``families/`` and of the reused files, path and bytes, in path order (LF endings): 10 hex characters."""
    base = root or _base()
    paths = sorted(base.joinpath("families").rglob("*.py")) + [base / name for name in REUSED]
    digest = hashlib.sha256()
    for path in sorted(p for p in paths if "__pycache__" not in p.parts):
        digest.update(str(path.relative_to(base)).replace(os.sep, "/").encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()[:10]


@lru_cache(maxsize=1)
def code_version() -> str:
    """What a family version is keyed by: ``fc`` and the fingerprint (``FBI_FAMILY_CODE_VERSION`` overrides it, for a test)."""
    return os.environ.get("FBI_FAMILY_CODE_VERSION") or f"fc{fingerprint()}"


def version_string(spec: str, code: str | None = None) -> str:
    """``1.0.0/<spec>@fc<fingerprint>``: the spec says what was fixed besides the code (the measure and the hyper-parameters)."""
    return f"{FAMILY_SEMVER}/{spec}@{code or code_version()}"


def ensure_version(conn: psycopg.Connection[Any], *, model: str, description: str, spec: str, hyper: dict[str, Any],
                   feature_names: Sequence[str], train_from: date, train_to: date, n_train: int, repo_commit: str) -> int:
    """The id of (model, version), created on first use: the model in the registry (family ``counts``) and its version, ``experimental``.

    A version is immutable: the same version string with other hyper-parameters is a conflict. The training window and the number of
    matches are those of the first fit of the version (what ``models.model_versions`` has always recorded)."""
    hyper = {**hyper, "code_version": code_version()}
    version = version_string(spec)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("INSERT INTO models.model_registry (name, family, description) VALUES (%s, %s, %s) "
                    "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description RETURNING id",
                    (model, REGISTRY_FAMILY, description))
        row = cur.fetchone()
        assert row is not None
        model_id = int(row[0])
        cur.execute("SELECT id, hyperparameters FROM models.model_versions WHERE model_id = %s AND version = %s", (model_id, version))
        existing = cur.fetchone()
        if existing is not None:
            if dict(existing[1]) != json.loads(json.dumps(hyper)):
                raise VersionConflictError(f"{model} {version} exists with other hyper-parameters; bump FAMILY_SEMVER")
            return int(existing[0])
        cur.execute("INSERT INTO models.model_versions (model_id, version, hyperparameters, feature_names, train_from, train_to, "
                    "n_train, code_version, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'experimental') RETURNING id",
                    (model_id, version, json.dumps(hyper), list(feature_names), train_from, max(train_to, train_from + timedelta(days=1)),
                     max(n_train, 1), repo_commit))
        row = cur.fetchone()
        assert row is not None
        return int(row[0])
