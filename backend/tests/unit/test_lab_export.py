"""PM-12-02 (OPS-013): the LAB's read-only export - what may leave is a closed list, auth and customer never leave, the
snapshot is one read-only transaction, and the manifest describes every file exactly (``verify`` catches a changed one)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest
from scripts import lab_export as le

_REF = re.compile(r"\b([a-z_]+)\.([a-z_]+)\b")


def test_the_closed_list_holds_only_football_prices_models_and_the_lab() -> None:
    assert le.TABLES, "an empty list would export nothing"
    for name, spec in le.TABLES.items():
        assert name == spec.name and name.count(".") == 1
        assert spec.schema in le.ALLOWED_SCHEMAS, name
        assert spec.schema not in le.FORBIDDEN_SCHEMAS, name
    assert {"auth", "customer"} <= le.FORBIDDEN_SCHEMAS
    assert not le.ALLOWED_SCHEMAS & le.FORBIDDEN_SCHEMAS


@pytest.mark.parametrize("name", ["auth.users", "auth.sessions", "customer.subscriptions", "customer.payment_requests",
                                  "ai.usage", "picks.public_picks", "audit.login_attempts", "pg_catalog.pg_authid",
                                  "core.does_not_exist", "users"])
def test_anything_outside_the_list_is_refused_before_the_database_is_asked(name: str) -> None:
    with pytest.raises(le.ExportRefusedError):
        le.check_table(name)


def test_auth_and_customer_are_refused_by_name() -> None:
    for schema in ("auth", "customer"):
        with pytest.raises(le.ExportRefusedError, match="never leaves the server"):
            le.check_table(f"{schema}.anything")


@pytest.mark.parametrize("filters", [{}, {"session": 4}, {"since": datetime(2026, 1, 1, tzinfo=UTC)},
                                     {"session": 4, "since": datetime(2026, 1, 1, tzinfo=UTC)}])
def test_every_query_reads_only_allowed_schemas(filters: dict[str, Any]) -> None:
    for spec in le.select_tables(None, filters):
        sql, params = le.query_for(spec, filters)
        cols = ", ".join(spec.columns) if spec.columns else "*"
        assert sql.startswith(f"SELECT {cols} FROM {spec.name}")
        schemas = {m.group(1) for m in _REF.finditer(sql)} - {"s", "r", "f"}
        assert schemas <= le.ALLOWED_SCHEMAS, (spec.name, schemas)
        assert set(params) <= set(filters)


def test_big_tables_never_leave_whole() -> None:
    whole = {s.name for s in le.select_tables(None, {})}
    big = {n for n, s in le.TABLES.items() if s.needs_filter}
    assert big and not whole & big
    with pytest.raises(le.ExportRefusedError, match="too big"):
        le.select_tables(["models.predictions"], {})
    session = {s.name for s in le.select_tables(None, {"session": 4})}
    assert {"analytics.backtest_samples", "core.fixture_results", "models.predictions"} <= session


def test_v2_people_tables_leave_without_names_free_text_or_external_ids() -> None:
    """IA-154/IA-155: events, lineups, officials, referees' aliases and open identifiers leave as ids, kinds and counts only."""
    assert le.VERSION == "lab-export-v3"
    people = {"core.fixture_events", "core.fixture_lineups", "core.fixture_officials", "core.referee_aliases", "core.entity_ids"}
    assert "core.entity_aliases" not in le.TABLES, "v2 took the wrong alias table for the referees (IA-155)"
    assert people <= set(le.TABLES)
    banned = {"player_name", "assist_name", "comments", "coach_name", "alias", "alias_key", "external_id", "evidence",
              "row_key", "name", "firstname", "lastname", "birth_date", "promoted_by", "name_key", "display"}
    for name in people | {"analytics.promoted_forecast_spec"}:
        spec = le.TABLES[name]
        assert spec.columns, name
        assert not set(spec.columns) & banned, name
        sql, _ = le.query_for(spec, {"since": datetime(2019, 1, 1, tzinfo=UTC)})
        assert "*" not in sql.split(" FROM ", 1)[0], name
    for name in ("core.fixture_events", "core.fixture_lineups", "core.fixture_officials", "core.referee_aliases",
                 "core.standings"):
        assert le.TABLES[name].needs_filter and "since" in le.TABLES[name].filters, name
    since = {s.name for s in le.select_tables(None, {"since": datetime(2019, 1, 1, tzinfo=UTC)})}
    assert people | {"market.historical_odds", "core.standings", "core.fixture_team_stats"} <= since
    assert "models.predictions" not in since and "analytics.backtest_samples" not in since


@pytest.mark.parametrize(("hhmm", "inside"), [((3, 29), False), ((3, 30), True), ((4, 59), True), ((5, 0), False),
                                              ((12, 0), False)])
def test_no_export_during_the_nightly_copy(hhmm: tuple[int, int], inside: bool) -> None:
    assert le.in_copy_window(datetime(2026, 11, 20, *hhmm, tzinfo=UTC)) is inside


# ── a run against a fake database ──────────────────────────────────────────────────────────────────────────────────


@dataclass
class _Col:
    name: str
    type_code: int


ROWS: list[tuple[Any, ...]] = [
    (1, Decimal("0.412345"), {"a": [1, 2]}, datetime(2026, 11, 1, 20, tzinfo=UTC), "Home", True),
    (2, None, None, None, None, None),
    (3, Decimal("1"), {"b": None}, datetime(2026, 11, 2, 1, tzinfo=UTC), "Away", False),
]
DESC = [_Col("id", 20), _Col("p", 1700), _Col("details", 3802), _Col("at", 1184), _Col("selection", 25), _Col("ok", 16)]


class _Cur:
    def __init__(self, conn: _Conn, name: str | None) -> None:
        self.conn, self.name, self.itersize = conn, name, 0
        self.description: list[_Col] | None = None
        self._rows: Iterator[tuple[Any, ...]] = iter(())

    def __enter__(self) -> _Cur:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> None:
        self.conn.queries.append((sql, params))
        if sql.startswith("SELECT pg_current_snapshot()"):
            self._rows = iter([("100:100:", "fbi", datetime(2026, 11, 20, 8, tzinfo=UTC))])
            return
        self.description = DESC
        self._rows = iter(ROWS)

    def fetchone(self) -> tuple[Any, ...] | None:
        return next(self._rows, None)

    def fetchmany(self, n: int) -> list[tuple[Any, ...]]:
        out = []
        for _ in range(min(n, 2)):  # two per batch: the writer must stream several batches
            row = next(self._rows, None)
            if row is None:
                break
            out.append(row)
        return out


class _Conn:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict[str, Any] | None]] = []
        self.rolled_back = False

    def cursor(self, name: str | None = None) -> _Cur:
        return _Cur(self, name)

    def rollback(self) -> None:
        self.rolled_back = True


def _export(tmp_path: Path) -> tuple[Path, _Conn]:
    conn = _Conn()
    specs = le.select_tables(["analytics.backtest_runs", "analytics.backtest_samples"], {"session": 4})
    folder = le.run(conn, specs, {"session": 4}, out=tmp_path, max_bytes=le.MAX_BYTES,
                    at=datetime(2026, 11, 20, 8, tzinfo=UTC), code_version="abc1234")
    return folder, conn


def test_a_run_writes_one_parquet_per_table_and_a_manifest_that_describes_it(tmp_path: Path) -> None:
    folder, conn = _export(tmp_path)
    lines = [json.loads(x) for x in (folder / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["kind"] for x in lines] == ["run", "table", "table", "end"]
    run, end = lines[0], lines[-1]
    assert run["version"] == le.VERSION and run["code_version"] == "abc1234" and run["snapshot"] == "100:100:"
    assert run["filters"] == {"session": 4} and run["isolation"] == "repeatable read, read only"
    for t in lines[1:3]:
        assert t["rows"] == 3 and t["params"] == {"session": 4} and "WHERE" in t["query"]
        assert [c["as"] for c in t["columns"]] == ["int64", "float64", "json", "timestamptz", "string", "bool"]
        table = pq.read_table(folder / t["file"])
        assert table.num_rows == 3
        assert table.column("p").to_pylist() == [pytest.approx(0.412345), None, 1.0]
        assert json.loads(table.column("details").to_pylist()[0]) == {"a": [1, 2]}
    assert end["rows"] == 6 and end["stopped"] is None
    assert conn.rolled_back, "the read-only transaction is closed without committing anything"
    assert all(sql.startswith("SELECT") for sql, _ in conn.queries)
    assert le.verify(folder) == []


def test_verify_catches_a_changed_or_missing_file(tmp_path: Path) -> None:
    folder, _ = _export(tmp_path)
    first = folder / "analytics.backtest_runs.parquet"
    first.write_bytes(first.read_bytes() + b"x")
    (folder / "analytics.backtest_samples.parquet").unlink()
    problems = le.verify(folder)
    assert any("SHA-256 differs" in p for p in problems) and any("missing" in p for p in problems)


def test_a_run_stops_before_passing_the_byte_cap(tmp_path: Path) -> None:
    conn = _Conn()
    specs = le.select_tables(["analytics.backtest_runs", "analytics.backtest_samples"], {"session": 4})
    folder = le.run(conn, specs, {"session": 4}, out=tmp_path, max_bytes=1, at=datetime(2026, 11, 20, 8, tzinfo=UTC),
                    code_version="x")
    lines = [json.loads(x) for x in (folder / "manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["kind"] for x in lines] == ["run", "table", "end"] and lines[-1]["stopped"]


def test_the_command_refuses_a_forbidden_table_without_connecting(monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(le, "_connect", lambda: pytest.fail("must not connect"))
    assert le.main(["plan", "--table", "customer.subscriptions"]) == 2
    assert "never leaves the server" in capsys.readouterr().out


# ── the reproduction on the laptop (scripts.lab_reproduce) ─────────────────────────────────────────────────────────


def _session(folder: Path, *, logloss: float, brier: float, flip: bool = False) -> None:
    import math

    import pyarrow as pa

    folder.mkdir(parents=True, exist_ok=True)
    probs = {10: (0.5, 0.3, 0.2), 11: (0.2, 0.3, 0.5)}
    results = {10: (2, 1), 11: (0, 0)}  # home win, draw
    samples = []
    for fid, ps in probs.items():
        h, a = results[fid]
        happened = "Home" if h > a else "Draw" if h == a else "Away"
        for sel, p in zip(("Home", "Draw", "Away"), ps, strict=True):
            samples.append({"backtest_run_id": 7, "fixture_id": fid, "market_key": "1X2", "selection": sel,
                            "p_calibrated": p, "outcome_correct": (sel == happened) != (flip and fid == 10)})
        samples.append({"backtest_run_id": 7, "fixture_id": fid, "market_key": "OU", "selection": "Over",
                        "p_calibrated": 0.5, "outcome_correct": True})
    pq.write_table(pa.Table.from_pylist(samples), folder / "analytics.backtest_samples.parquet")
    pq.write_table(pa.Table.from_pylist([
        {"fixture_id": fid, "reg_goals_home": h, "reg_goals_away": a, "ft_goals_home": h, "ft_goals_away": a}
        for fid, (h, a) in results.items()]), folder / "core.fixture_results.parquet")
    pq.write_table(pa.Table.from_pylist([{"id": 7, "name": "s:poisson", "n_samples": 2, "logloss": logloss,
                                          "brier_score": brier}]), folder / "analytics.backtest_runs.parquet")
    assert math.isfinite(logloss)


def test_lab_reproduce_recomputes_log_loss_and_brier_like_fbi_models_metrics(tmp_path: Path) -> None:
    import math

    from scripts import lab_reproduce as lr

    want_ll = (-math.log(0.5) - math.log(0.3)) / 2
    want_br = ((0.5 - 1) ** 2 + 0.3**2 + 0.2**2 + 0.2**2 + (0.3 - 1) ** 2 + 0.5**2) / 2
    _session(tmp_path / "ok", logloss=round(want_ll, 6), brier=round(want_br, 6))
    [row] = lr.reproduce(tmp_path / "ok")
    assert row["matches"] == 2 and row["reproduced"] is True
    assert row["logloss"] == pytest.approx(want_ll, abs=1e-6) and row["brier"] == pytest.approx(want_br, abs=1e-6)
    _session(tmp_path / "other", logloss=round(want_ll + 0.001, 6), brier=round(want_br, 6))
    assert lr.reproduce(tmp_path / "other")[0]["reproduced"] is False
    _session(tmp_path / "flip", logloss=round(want_ll, 6), brier=round(want_br, 6), flip=True)
    flipped = lr.reproduce(tmp_path / "flip")[0]
    assert flipped["outcome_disagrees"] == 3 and flipped["reproduced"] is False
