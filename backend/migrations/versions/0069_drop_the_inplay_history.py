"""drop the in-play history - only empty, or archived and verified with the same row counts

Second half of the owner's decision of 6 Oct 2026 (revision 0068 made in-play odds a bounded current book). The
history tables receive no row since 0068: market.live_odds_snapshots (the change-only series, ~2.4 M rows and
~0.7 GB after six days) and market.live_fixture_states (one row per fixture per tick), with the two views over them.
Nothing else depends on them: no foreign key points INTO them, no function names them, and no model, feature, pick,
parlay, backtest, settlement, consensus or validation reads them (tests/unit/test_prematch_independence.py,
tests/integration/test_prematch_without_inplay.py).

A table that still holds rows is dropped ONLY if audit.storage_cleanups records a verified archive of it with
exactly that many rows (``python -m scripts.inplay_cleanup archive``: exported outside PostgreSQL, read back and
compared with the database). Otherwise this revision refuses and nothing is dropped. What is dropped with rows in it is
recorded in audit.storage_cleanups (kind 'inplay_drop': rows and bytes, before the drop).

Downgrade recreates the tables and views EMPTY, exactly as revisions 0032, 0037 and 0038 defined them. The rows come
back only from the archive or the backup taken before - a schema can be reversed, deleted data cannot.

Revision ID: 0069
Revises: 0068
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

TABLES = ("market.live_odds_snapshots", "market.live_fixture_states")
VIEWS = ("market.live_market_movement", "market.live_odds_at_instant")


class InplayHistoryNotArchivedError(RuntimeError):
    """The in-play history holds rows that no verified archive accounts for."""


def _exists(conn: sa.engine.Connection, relation: str) -> bool:
    return bool(conn.execute(sa.text("SELECT to_regclass(:r) IS NOT NULL"), {"r": relation}).scalar())


def _bytes(conn: sa.engine.Connection, relation: str) -> int:
    # pg_partition_tree() lists nothing for a table that is not partitioned: its size is then its own.
    return int(conn.execute(sa.text(
        "SELECT coalesce((SELECT sum(pg_total_relation_size(relid)) FROM pg_partition_tree(CAST(:r AS regclass))), "
        "pg_total_relation_size(CAST(:r AS regclass)))"), {"r": relation}).scalar() or 0)


def upgrade() -> None:
    conn = op.get_bind()
    present = [t for t in TABLES if _exists(conn, t)]
    counts = {t: int(conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar() or 0) for t in present}
    for table, rows in counts.items():
        if rows == 0:
            continue
        archived = conn.execute(sa.text(
            "SELECT id FROM audit.storage_cleanups WHERE kind = 'inplay_archive' AND subject = :t AND verified "
            "AND rows = :n ORDER BY id DESC LIMIT 1"), {"t": table, "n": rows}).scalar()
        if archived is None:
            raise InplayHistoryNotArchivedError(
                f"{table} holds {rows} rows and no verified archive of exactly that many is recorded in "
                "audit.storage_cleanups. Run `python -m scripts.inplay_cleanup archive --out DIR --backup-label L` "
                "after a verified backup, then upgrade again. Nothing was dropped.")
    for table, rows in counts.items():
        if rows == 0:
            continue  # an empty table is dropped without ceremony (a fresh database): nothing was retired
        conn.execute(sa.text(
            "INSERT INTO audit.storage_cleanups (kind, subject, rows, bytes, verified, details, code_version) "
            "VALUES ('inplay_drop', :t, :n, :b, true, CAST(:d AS jsonb), :v)"),
            {"t": table, "n": rows, "b": _bytes(conn, table),
             "d": json.dumps({"revision": revision, "views_dropped": list(VIEWS)}), "v": f"alembic {revision}"})
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")


def _module(filename: str) -> ModuleType:
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"_inplay_history_{filename[:4]}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def downgrade() -> None:
    # The schema exactly as it stood at 0068, built by the revisions that defined it; empty.
    op.execute(_module("0032_live_odds_are_a_different_observation.py").UPGRADE)
    op.execute(_module("0037_the_live_series_records_changes.py").UPGRADE)
    op.execute(_module("0038_a_withdrawal_is_not_a_price_change.py").UPGRADE)
