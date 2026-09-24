"""Persisting feature sets and Elo history. Append-only."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.features.engine import FEATURES, EloRecord, FeatureVector


def ensure_registry(conn: psycopg.Connection) -> None:
    """The registry mirrors the engine's feature list: the code is the source."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO features.feature_registry "
            "(name, feature_group, entity_type, value_type, description, window_spec, refresh_policy) "
            "VALUES (%s, %s, 'fixture', 'numeric', %s, %s, 'on_demand') "
            "ON CONFLICT (name) DO UPDATE SET feature_group = EXCLUDED.feature_group, "
            "description = EXCLUDED.description, window_spec = EXCLUDED.window_spec",
            [(f.name, f.group, f.description, f.window) for f in FEATURES],
        )


def write_feature_sets(
    conn: psycopg.Connection,
    vectors: Sequence[FeatureVector],
    *,
    version: str,
    code_version: str,
    run_id: int | None,
    lineage: dict[str, Any],
) -> tuple[int, int]:
    """Returns (inserted, already_present). A vector with the same fixture,
    version, cut-off and input hash is the same vector: it is not written twice.
    A different input hash for the same cut-off (more history was backfilled)
    is a new feature set; the old one stays."""
    inserted = present = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        rows: list[tuple[int, str, float | None]] = []
        for v in vectors:
            cur.execute(
                "INSERT INTO features.feature_sets (fixture_id, feature_version, data_cutoff, code_version, run_id, "
                "input_hash, n_inputs, newest_input_at, lineage) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (fixture_id, feature_version, data_cutoff, input_hash) DO NOTHING RETURNING id",
                (v.fixture_id, version, v.data_cutoff, code_version, run_id, v.input_hash, v.n_inputs,
                 v.newest_input_at, Json(lineage)),
            )
            got = cur.fetchone()
            if got is None:
                present += 1
                continue
            inserted += 1
            rows.extend((int(got[0]), name, value) for name, value in v.values.items())
        if rows:
            with cur.copy("COPY features.fixture_features (feature_set_id, name, value) FROM STDIN") as cp:
                for r in rows:
                    cp.write_row(r)
    return inserted, present


def write_elo_history(conn: psycopg.Connection, history: Sequence[EloRecord], *, version: str, run_id: int) -> int:
    with conn.cursor() as cur, cur.copy(
        "COPY features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, rating_before, "
        "rating_after, expected_score, actual_score, k_factor, margin_multiplier) FROM STDIN"
    ) as cp:
        for h in history:
            cp.write_row((version, run_id, h.team_id, h.fixture_id, h.kickoff_at, h.rating_before,
                          h.rating_after, h.expected_score, h.actual_score, h.k_factor, h.margin_multiplier))
    return len(history)


def load_feature_matrix(
    conn: psycopg.Connection, *, version: str, fixture_ids: Sequence[int] | None = None
) -> dict[int, tuple[datetime, dict[str, float | None]]]:
    """fixture_id -> (data_cutoff, values) from the newest feature set per fixture
    (most inputs, then most recently generated)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            """
            WITH latest AS (
              SELECT DISTINCT ON (fixture_id) id, fixture_id, data_cutoff
              FROM features.feature_sets
              WHERE feature_version = %s AND (%s::bigint[] IS NULL OR fixture_id = ANY(%s::bigint[]))
              ORDER BY fixture_id, n_inputs DESC, generated_at DESC, id DESC
            )
            SELECT l.fixture_id, l.data_cutoff, ff.name, ff.value
            FROM latest l JOIN features.fixture_features ff ON ff.feature_set_id = l.id
            """,
            (version, list(fixture_ids) if fixture_ids is not None else None,
             list(fixture_ids) if fixture_ids is not None else None),
        )
        out: dict[int, tuple[datetime, dict[str, float | None]]] = {}
        for fid, cutoff, name, value in cur.fetchall():
            entry = out.setdefault(int(fid), (cutoff, {}))
            entry[1][str(name)] = None if value is None else float(value)
        return out
