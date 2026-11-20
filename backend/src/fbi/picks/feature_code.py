"""Which commit the pick pipeline's forecast names as the code of the feature sets it writes (PM-13-02, BE-064).

THE DEFECT. ``fbi.predictions.forecast`` stores a new feature set for a fixture unless its newest stored one has the same input hash
AND the same ``code_version`` - and ``code_version`` is the repository commit. Every deploy (a page, a document, a guide) is a new
commit, so the first pass after each deploy writes every upcoming fixture's vector again, with the same inputs and the same values:
on 20-nov-2026, 11,776 of the 125,054 feature sets of the 14 days before (9.4 %; 18.2 % in the last four days, with 4 to 14 deploys
a day) repeated their predecessor's input hash, each with its 43 rows of ``features.fixture_features`` (the largest table, 4.4 GB).

WHAT DECIDES A VECTOR. Its inputs (``input_hash``) and the code that computes it, which is the MODEL code: ``fbi.features`` is one of
``fbi.core.version.MODEL_PACKAGES`` and ``model_code_version`` fingerprints it. Two commits with the same model code compute the same
vector from the same inputs.

THE CHANGE. With ``FBI_FEATURE_SETS_BY_MODEL_CODE=on`` the forecast is told, as its ``code_version``, the first commit that ran the
model code in force (the ``code_version`` of the oldest ``models.model_versions`` row keyed by that fingerprint: the commit
``ensure_version`` records, "the first commit that ran this model code"), and the current commit while no version of that model
code exists yet. So a deploy that does not touch the model code no longer renews the feature sets, and one that does still does.
Nothing else changes: the forecast's own rows of ``models.predictions`` are keyed by the input hash, which is the same; the model
versions are keyed by the fingerprint, which is the same (a version created later under the same model code records that first
commit instead of the current one: both are commits of the same model code). No history is touched: every stored set stays as
it was, and the lineage of each forecast keeps pointing at a stored set with its input hash.

WHY HERE AND NOT IN ``fbi.predictions``. A change in a model package renews the version of every model (the guard in
``tests/unit/test_model_code_version.py``): 92,937 forecasts written again the last time it happened by accident (23-oct-2026).
The commit is chosen where the pipeline calls the forecast, outside the model packages, so the fingerprint does not move.

``off`` (the default, and anything not listed as on) is the behaviour before: the current commit. The worker needs a restart to read it.
"""

from __future__ import annotations

from typing import Final

import psycopg
from psycopg.rows import tuple_row

from fbi.core.env import environment
from fbi.core.version import model_code_version

SWITCH: Final = "FBI_FEATURE_SETS_BY_MODEL_CODE"
ON: Final = frozenset({"1", "on", "true", "yes"})

FIRST_COMMIT_SQL: Final = (
    "SELECT code_version FROM models.model_versions WHERE version LIKE %s AND code_version IS NOT NULL "
    "AND code_version <> '' AND code_version <> 'unknown' ORDER BY id LIMIT 1"
)
"""The commit the oldest model version of this model code was created with. ``version`` ends in ``@<model code>``
(``fbi.backtesting.persist.version_string``)."""


def enabled() -> bool:
    return environment().get(SWITCH, "off").strip().lower() in ON


def _like(model_code: str) -> str:
    """``LIKE`` pattern for the versions keyed by ``model_code``: ``%@mc9a7bec97ca``, its wildcards escaped."""
    escaped = model_code.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%@{escaped}"


def first_commit_of(conn: psycopg.Connection, model_code: str) -> str | None:
    """The first commit that ran ``model_code`` (None: no model version of it exists yet). Read-only."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(FIRST_COMMIT_SQL, (_like(model_code),))
        row = cur.fetchone()
    return None if row is None else str(row[0])


def forecast_code_version(conn: psycopg.Connection, commit: str, *, model_code: str | None = None) -> str:
    """The ``code_version`` the pipeline gives the forecast: ``commit`` when the switch is off or no version of the model code in force
    exists yet; otherwise the first commit that ran that model code. A read that fails is never a reason for the pass to fail:
    the current commit is used, as before."""
    if not enabled():
        return commit
    code = model_code or model_code_version()
    try:
        with conn.transaction():
            first = first_commit_of(conn, code)
    except psycopg.Error:
        return commit
    return first or commit
