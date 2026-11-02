"""The month against the Console (``fbi.ai.reconcile``, ``scripts/ia_reconcile.py``) on a built ledger: October 2026, a production
and a LAB workspace, Exa's searches (not Claude's), the analyst's runs (production's) and a call of the night of the 31st that is
already November in UTC. Written by hand, one transaction, rolled back."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from scripts import ia_reconcile

from fbi.ai import reconcile
from fbi.ai.usage import UsageLedger, shared

D = Decimal
MONTH = date(2026, 10, 1)


def spend(db: psycopg.Connection[Any], at: datetime, usd: str, *, workspace: str | None = "PREDIGOL", search: bool = False) -> None:
    UsageLedger(shared(db)).record(
        at=at, purpose="web_search" if search else "pick_review", tier="search" if search else "analysis",
        provider="exa" if search else "anthropic", model="exa" if search else "claude-sonnet-5-5", usage=None, cost=D(usd),
        status="ok", workspace=None if search else workspace)


def october(db: psycopg.Connection[Any]) -> None:
    spend(db, datetime(2026, 10, 1, 12, tzinfo=UTC), "10.50")
    spend(db, datetime(2026, 10, 2, 12, tzinfo=UTC), "20.00")
    spend(db, datetime(2026, 10, 1, 13, tzinfo=UTC), "1.25", workspace="PREDIGOL-LAB")
    spend(db, datetime(2026, 10, 2, 13, tzinfo=UTC), "0.75", workspace="PREDIGOL-LAB")
    spend(db, datetime(2026, 10, 2, 14, tzinfo=UTC), "5.00", search=True)  # Exa: not in the Console
    db.execute("INSERT INTO analytics.ai_runs (kind, model, started_at, finished_at, status, cost_usd) "
               "VALUES ('daily_report', 'claude-sonnet-5-5', %s, %s, 'ok', 1.00)",
               (datetime(2026, 10, 3, 12, tzinfo=UTC), datetime(2026, 10, 3, 12, 1, tzinfo=UTC)))
    # 21:00 on the 31st in Bogotá is 02:00 on 1 November in UTC: the Console counts it in November
    spend(db, datetime(2026, 11, 1, 2, tzinfo=UTC), "7.00")


CONSOLE = """date,workspace,model,cost_usd
2026-10-01,PREDIGOL,claude-haiku-5-5,10.50
2026-10-01,PREDIGOL-LAB,claude-sonnet-5-5,1.25
2026-10-02,PREDIGOL,claude-sonnet-5-5,20.00
2026-10-02,PREDIGOL-LAB,claude-haiku-5-5,0.75
2026-10-03,PREDIGOL,claude-sonnet-5-5,1.00
"""


def test_a_month_that_agrees_is_ok_whatever_exa_and_the_next_months_first_night_did(db: psycopg.Connection[Any]) -> None:
    october(db)
    out = reconcile.reconcile(db, reconcile.parse_console_csv(CONSOLE))
    assert out.verdict == reconcile.OK
    by = {s.scope: s for s in out.scopes}
    assert (by["production"].ours, by["production"].console) == (D("31.50"), D("31.50")), \
        "the analyst's run is production's; Exa's search and the night of the 31st are not"
    assert (by["lab"].ours, by["lab"].console) == (D("2.00"), D("2.00"))
    assert by["production"].days == () and by["production"].diff_pct == D("0.00")
    doc = out.as_json()
    assert doc["month"] == "2026-10" and doc["verdict"] == "OK" and doc["csv"]["rows"] == 5
    assert json.dumps(doc), "the report is JSON"


def test_a_month_that_differs_names_the_day_to_look_at(db: psycopg.Connection[Any]) -> None:
    october(db)
    console = CONSOLE.replace("2026-10-02,PREDIGOL,claude-sonnet-5-5,20.00", "2026-10-02,PREDIGOL,claude-sonnet-5-5,25.00")
    out = reconcile.reconcile(db, reconcile.parse_console_csv(console))
    assert out.verdict == reconcile.INVESTIGATE
    production = next(s for s in out.scopes if s.scope == "production")
    assert production.verdict == reconcile.INVESTIGATE and production.diff == D("-5.00")
    assert production.diff_pct == D("-13.70"), "5.00 under a Console figure of 36.50"
    assert [d.day for d in production.days] == [date(2026, 10, 2)]
    assert next(s for s in out.scopes if s.scope == "lab").verdict == reconcile.OK, "the LAB agrees: it is judged on its own"


def test_the_lab_is_never_hidden_inside_production(db: psycopg.Connection[Any]) -> None:
    """The Console says the LAB spent 5 more and production 5 less: the two together agree to the cent, each workspace does not."""
    october(db)
    console = CONSOLE.replace("2026-10-02,PREDIGOL-LAB,claude-haiku-5-5,0.75", "2026-10-02,PREDIGOL-LAB,claude-haiku-5-5,5.75")
    console = console.replace("2026-10-02,PREDIGOL,claude-sonnet-5-5,20.00", "2026-10-02,PREDIGOL,claude-sonnet-5-5,15.00")
    out = reconcile.reconcile(db, reconcile.parse_console_csv(console))
    assert sum(s.ours for s in out.scopes) == sum(s.console for s in out.scopes), "the premise: the total is exact"
    assert {s.scope: s.verdict for s in out.scopes} == {"production": reconcile.INVESTIGATE, "lab": reconcile.INVESTIGATE}
    assert out.verdict == reconcile.INVESTIGATE


def test_nothing_spent_on_either_side_is_no_data(db: psycopg.Connection[Any]) -> None:
    out = reconcile.reconcile(db, reconcile.parse_console_csv("date,workspace,cost_usd\n2031-03-01,PREDIGOL,0\n"))
    assert out.verdict == reconcile.NO_DATA


def test_the_command_reads_files_and_answers_with_an_exit_status(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    october(db)
    (tmp_path / "prod.csv").write_text("date,cost\n2026-10-01,10.50\n2026-10-02,20.00\n2026-10-03,1.00\n")
    (tmp_path / "lab.csv").write_text("date,cost\n2026-10-01,1.25\n2026-10-02,0.75\n")
    args = ia_reconcile.build_parser().parse_args(["--csv", f"{tmp_path / 'prod.csv'}=production",
                                                   "--csv", f"{tmp_path / 'lab.csv'}=lab"])
    report, code = ia_reconcile.run(ia_reconcile.read(args), db)
    assert code == ia_reconcile.OK and report["verdict"] == "OK"
    (tmp_path / "lab.csv").write_text("date,cost\n2026-10-01,1.25\n2026-10-02,9.75\n")
    report, code = ia_reconcile.run(ia_reconcile.read(args), db)
    assert code == ia_reconcile.DIFFERS and report["verdict"] == "INVESTIGAR"
    empty = ia_reconcile.build_parser().parse_args(["--csv", f"{tmp_path / 'none.csv'}=lab", "--month", "2031-03"])
    (tmp_path / "none.csv").write_text("date,cost\n2031-03-01,0\n")
    assert ia_reconcile.run(ia_reconcile.read(empty), db)[1] == ia_reconcile.EMPTY


def test_the_command_refuses_what_it_cannot_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ia_reconcile.main(["--csv", str(tmp_path / "missing.csv")]) == ia_reconcile.CANNOT
    assert "cannot read" in capsys.readouterr().err
    (tmp_path / "x.csv").write_text("a,b\n1,2\n")
    assert ia_reconcile.main(["--csv", str(tmp_path / "x.csv")]) == ia_reconcile.CANNOT
    assert "no cost column found" in capsys.readouterr().err
    assert ia_reconcile.main(["--csv", str(tmp_path / "x.csv"), "--cost-divisor", "zero"]) == ia_reconcile.CANNOT
    assert ia_reconcile.main(["--csv", str(tmp_path / "x.csv"), "--month", "October"]) == ia_reconcile.CANNOT
