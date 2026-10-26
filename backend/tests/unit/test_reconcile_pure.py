"""Reading a Console cost export and judging a month against the ledger (``fbi.ai.reconcile``): no database, no network.

The rules that matter: a figure that does not parse stops the run (it is never skipped), the workspace is mapped the way the
ledger maps its own, the month is chosen and never guessed, 5 % of the Console's figure is the limit, and under US$0.50 is
rounding."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from fbi.ai.reconcile import (
    ABSOLUTE_FLOOR,
    INVESTIGATE,
    NO_DATA,
    OK,
    TOLERANCE,
    ConsoleCosts,
    CsvError,
    judge,
    merge_all,
    month_bounds,
    parse_console_csv,
    parse_day,
    parse_money,
    scope_of_workspace,
)

D = Decimal

CSV = """date,workspace,model,cost_usd
2026-10-01,PREDIGOL,claude-haiku-5-5,10.50
2026-10-01,PREDIGOL-LAB,claude-sonnet-5-5,1.25
2026-10-02,PREDIGOL,claude-sonnet-5-5,20.00
2026-10-02,PREDIGOL-LAB,claude-haiku-5-5,0.75
"""


def test_the_money_of_a_cell_is_read_or_the_run_stops() -> None:
    assert parse_money("$1,234.56", row=2) == D("1234.56")
    assert parse_money("US$ 12.30", row=2) == D("12.30")
    assert parse_money("(3.10)", row=2) == D("-3.10"), "a credit"
    assert parse_money("-3.1", row=2) == D("-3.1")
    assert parse_money("", row=2) == 0
    with pytest.raises(CsvError, match="row 7"):
        parse_money("n/a", row=7)


def test_a_day_is_a_utc_day() -> None:
    assert parse_day("2026-10-03", row=2) == date(2026, 10, 3)
    assert parse_day("2026-10-03T00:00:00Z", row=2) == date(2026, 10, 3)
    assert parse_day("2026-10-03T22:00:00-05:00", row=2) == date(2026, 10, 4), "22:00 in Bogotá is already the next UTC day"
    assert parse_day("10/3/2026", row=2) == date(2026, 10, 3), "the US spelling"
    with pytest.raises(CsvError, match="not a date"):
        parse_day("yesterday", row=4)
    assert parse_day("03/10/2026", row=2, formats=("%d/%m/%Y",)) == date(2026, 10, 3), "an unusual spelling, named by the caller"


def test_a_workspace_is_the_labs_when_its_name_ends_in_lab_as_the_ledger_reads_it() -> None:
    assert scope_of_workspace("PREDIGOL-LAB") == "lab"
    assert scope_of_workspace(" predigol-lab ") == "lab"
    assert scope_of_workspace("PREDIGOL") == "production"
    assert scope_of_workspace("Default") == "production", "the workspace every account starts with"
    assert scope_of_workspace("LABORATORY") == "production", "only a name that ENDS in LAB (ai.scope_of's LIKE '%LAB')"


def test_a_console_export_is_read_by_workspace_and_day() -> None:
    c = parse_console_csv(CSV)
    assert c.month == date(2026, 10, 1)
    assert c.by_scope == {"production": D("30.50"), "lab": D("2.00")}
    assert c.by_day[("production", date(2026, 10, 2))] == D("20.00")
    assert c.by_day[("lab", date(2026, 10, 1))] == D("1.25")
    assert c.rows == 4 and c.ignored_rows == 0
    assert c.columns == {"cost": "cost_usd", "date": "date", "workspace": "workspace"}
    assert c.workspaces == {"PREDIGOL": "production", "PREDIGOL-LAB": "lab"}
    assert len(c.sha256) == 64


def test_the_spelling_of_the_export_does_not_matter() -> None:
    odd = "\ufeffDay;Workspace Name;Total Cost\n2026-10-01;PREDIGOL;$1000.00\n2026-10-01;PREDIGOL-LAB;3.50\n"
    c = parse_console_csv(odd.encode("utf-8"))
    assert c.by_scope == {"production": D("1000.00"), "lab": D("3.50")}, "a BOM, semicolons and other names are read"
    assert c.columns == {"cost": "Total Cost", "date": "Day", "workspace": "Workspace Name"}


def test_cents_are_turned_into_dollars() -> None:
    c = parse_console_csv("date,workspace,amount\n2026-10-01,PREDIGOL,1250\n", divisor=D(100))
    assert c.by_scope == {"production": D("12.5")}


def test_a_file_made_for_one_workspace_takes_the_scope_it_is_given() -> None:
    c = parse_console_csv("date,cost\n2026-10-01,4.00\n2026-10-02,6.00\n", scope="lab")
    assert c.by_scope == {"lab": D("10.00")} and c.workspaces == {"(whole file)": "lab"}
    with pytest.raises(CsvError, match="no workspace column"):
        parse_console_csv("date,cost\n2026-10-01,4.00\n")
    with pytest.raises(CsvError, match="scope must be"):
        parse_console_csv("date,cost\n2026-10-01,4.00\n", scope="exa")


def test_the_month_is_chosen_never_guessed() -> None:
    two_months = CSV + "2026-09-30,PREDIGOL,claude-haiku-5-5,99.00\n"
    with pytest.raises(CsvError, match="2026-09, 2026-10 - choose one with --month"):
        parse_console_csv(two_months)
    c = parse_console_csv(two_months, month=date(2026, 10, 15))
    assert c.month == date(2026, 10, 1) and c.ignored_rows == 1
    assert c.by_scope["production"] == D("30.50"), "September's 99.00 is not counted"
    undated = parse_console_csv("workspace,cost\nPREDIGOL,5.00\n", month=date(2026, 10, 1))
    assert undated.by_scope == {"production": D("5.00")} and undated.by_day == {}
    with pytest.raises(CsvError, match="no date column"):
        parse_console_csv("workspace,cost\nPREDIGOL,5.00\n")


def test_an_unreadable_export_says_what_to_pass() -> None:
    with pytest.raises(CsvError, match=r"no cost column found among: date, workspace, model.*--cost-column"):
        parse_console_csv("date,workspace,model\n2026-10-01,PREDIGOL,x\n")
    with pytest.raises(CsvError, match="'spend_total' is not in the CSV"):
        parse_console_csv(CSV, cost_column="spend_total")
    assert parse_console_csv("date,workspace,gasto\n2026-10-01,PREDIGOL,3\n", cost_column="Gasto").by_scope == {"production": D(3)}
    with pytest.raises(CsvError, match="empty"):
        parse_console_csv("")
    with pytest.raises(CsvError, match="no rows"):
        parse_console_csv("date,workspace,cost\n")
    with pytest.raises(CsvError, match=r"row 3.*not an amount"):
        parse_console_csv("date,workspace,cost\n2026-10-01,PREDIGOL,1\n2026-10-02,PREDIGOL,oops\n")


def test_two_exports_of_one_month_read_as_one_and_two_months_do_not() -> None:
    prod = parse_console_csv("date,cost\n2026-10-01,10\n2026-10-02,5\n", scope="production")
    lab = parse_console_csv("date,cost\n2026-10-01,1\n", scope="lab")
    both = merge_all([prod, lab])
    assert both.by_scope == {"production": D(15), "lab": D(1)} and both.rows == 3
    assert isinstance(both, ConsoleCosts) and len(both.sha256) == 64
    other = parse_console_csv("date,cost\n2026-09-01,1\n", scope="lab")
    with pytest.raises(CsvError, match="different months"):
        merge_all([prod, other])
    with pytest.raises(CsvError, match="no CSV"):
        merge_all([])


def test_five_percent_of_the_consoles_figure_is_the_limit_and_under_fifty_cents_is_rounding() -> None:
    assert (str(TOLERANCE), str(ABSOLUTE_FLOOR)) == ("0.05", "0.50")
    assert judge(D("105.00"), D("100.00")) == OK, "exactly 5 %"
    assert judge(D("95.00"), D("100.00")) == OK
    assert judge(D("105.01"), D("100.00")) == INVESTIGATE
    assert judge(D("94.99"), D("100.00")) == INVESTIGATE
    assert judge(D("0.80"), D("0.40")) == OK, "100 % apart but 40 cents: rounding"
    assert judge(D("0.95"), D("0.40")) == INVESTIGATE, "55 cents is not"
    assert judge(D("3.00"), D(0)) == INVESTIGATE, "we paid for what the Console never charged"
    assert judge(D(0), D("3.00")) == INVESTIGATE, "the Console charged what we never recorded"
    assert judge(D(0), D(0)) == NO_DATA


def test_a_months_bounds_are_utc() -> None:
    first, following = month_bounds(date(2026, 12, 15))
    assert (first.isoformat(), following.isoformat()) == ("2026-12-01T00:00:00+00:00", "2027-01-01T00:00:00+00:00")
    assert month_bounds(date(2026, 2, 1))[1].isoformat() == "2026-03-01T00:00:00+00:00"
