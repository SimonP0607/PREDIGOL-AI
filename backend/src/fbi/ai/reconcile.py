"""Monthly reconciliation of the AI ledger with the Console (Plan Maestro IA, section 32 and the acceptance list).

The usage and cost API is not available to this account, so once a month the sum of ``ai.usage`` for Anthropic is compared,
workspace by workspace, with the CSV that the Console's Cost page exports. More than 5 % apart is investigated. Exa has no
Console: it is reconciled with its invoice, by hand.

Nothing here guesses. The CSV is read by column NAME (the first that matches the known spellings, or the one the caller names),
a figure that does not parse stops the run with its row number, a workspace label is mapped the way the ledger maps its own
(``ai.scope_of``: a name ending in LAB is the LAB's, any other is production's) and every assumption is returned with the
report. The Console's days are UTC days, so the ledger is read by UTC day and UTC month here, not by Bogotá's.

A difference under ``ABSOLUTE_FLOOR`` dollars is rounding (the Console rounds each line to the cent), not a finding: it passes
whatever its percentage, and the report says so."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.rows import tuple_row

TOLERANCE = Decimal("0.05")
ABSOLUTE_FLOOR = Decimal("0.50")
SCOPES = ("production", "lab")
COST_COLUMNS = ("cost_usd", "total_cost_usd", "cost", "total_cost", "amount_usd", "amount", "usd", "spend", "total")
DATE_COLUMNS = ("date", "day", "usage_date", "cost_date", "starting_at", "period_start", "start_date", "time", "timestamp",
                "datetime", "created_at")
WORKSPACE_COLUMNS = ("workspace", "workspace_name", "workspace_label", "workspace_id", "project")
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d")
OK, INVESTIGATE, NO_DATA = "OK", "INVESTIGAR", "SIN DATOS"


class CsvError(ValueError):
    """The CSV cannot be read as a cost report: the message says what to pass to read it."""


def normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def scope_of_workspace(label: str) -> str:
    """The ledger's own rule (``ai.scope_of``): a workspace whose name ends in LAB is the LAB's, any other is production's."""
    return "lab" if label.strip().upper().endswith("LAB") else "production"


def parse_money(text: str, *, row: int) -> Decimal:
    """``$1,234.56``, ``US$ 12.30``, ``(3.10)`` (a credit) or ``-3.1``; an empty cell is zero."""
    raw = text.strip()
    if not raw:
        return Decimal(0)
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", raw)
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise CsvError(f"row {row}: {text!r} is not an amount") from exc
    return -abs(value) if negative else value


def parse_day(text: str, *, row: int, formats: Sequence[str] = DATE_FORMATS) -> date:
    """A date or a timestamp, read as UTC (the Console's days are UTC days)."""
    raw = text.strip()
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return (stamp.astimezone(UTC) if stamp.tzinfo else stamp).date()
    except ValueError:
        pass
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    raise CsvError(f"row {row}: {text!r} is not a date (pass --date-format, e.g. %d/%m/%Y)")


def pick(header: dict[str, str], wanted: str | None, known: Sequence[str], what: str, *, required: bool) -> str | None:
    """The column to use for ``what``: the one the caller named, else the first of the known spellings the header has."""
    if wanted:
        key = normalise(wanted)
        if key not in header:
            raise CsvError(f"the {what} column {wanted!r} is not in the CSV (its columns: {', '.join(header.values())})")
        return key
    for candidate in known:
        if candidate in header:
            return candidate
    if required:
        raise CsvError(f"no {what} column found among: {', '.join(header.values())} - name it with --{what}-column")
    return None


@dataclass(frozen=True)
class ConsoleCosts:
    """What the Console says it charged in a month: per scope, and per UTC day when the CSV has dates."""

    month: date
    by_scope: dict[str, Decimal]
    by_day: dict[tuple[str, date], Decimal]
    rows: int
    ignored_rows: int
    columns: dict[str, str | None]
    workspaces: dict[str, str]
    """Each workspace label found, and the scope it was read as."""
    sha256: str

    def merged(self, other: ConsoleCosts) -> ConsoleCosts:
        """Two exports of the same month (one per workspace, say) read as one."""
        if other.month != self.month:
            raise CsvError(f"the CSVs cover different months ({self.month:%Y-%m} and {other.month:%Y-%m})")
        by_scope = dict(self.by_scope)
        for scope, usd in other.by_scope.items():
            by_scope[scope] = by_scope.get(scope, Decimal(0)) + usd
        by_day = dict(self.by_day)
        for key, usd in other.by_day.items():
            by_day[key] = by_day.get(key, Decimal(0)) + usd
        return ConsoleCosts(self.month, by_scope, by_day, self.rows + other.rows, self.ignored_rows + other.ignored_rows,
                            self.columns, self.workspaces | other.workspaces,
                            hashlib.sha256((self.sha256 + other.sha256).encode()).hexdigest())


def parse_console_csv(raw: bytes | str, *, month: date | None = None, scope: str | None = None, cost_column: str | None = None,
                      date_column: str | None = None, workspace_column: str | None = None, divisor: Decimal = Decimal(1),
                      date_formats: Sequence[str] = DATE_FORMATS) -> ConsoleCosts:
    """Read an export of the Console's Cost page.

    ``scope`` fixes the whole file's scope (an export made for one workspace has no workspace column); without it the workspace
    column decides, row by row. ``month`` (the first of it) selects the month when the file holds several. ``divisor`` turns
    the figures into dollars (100 for cents)."""
    data = raw if isinstance(raw, bytes) else raw.encode()
    text = data.decode("utf-8-sig")
    digest = hashlib.sha256(data).hexdigest()
    if scope is not None and scope not in SCOPES:
        raise CsvError(f"scope must be one of {', '.join(SCOPES)}")
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        names = next(reader)
    except StopIteration as exc:
        raise CsvError("the CSV is empty") from exc
    header = {normalise(n): n.strip() for n in names if normalise(n)}
    cost_key = pick(header, cost_column, COST_COLUMNS, "cost", required=True)
    date_key = pick(header, date_column, DATE_COLUMNS, "date", required=False)
    ws_key = pick(header, workspace_column, WORKSPACE_COLUMNS, "workspace", required=False)
    if ws_key is None and scope is None:
        raise CsvError("the CSV has no workspace column: say whose it is with --csv FILE=production or FILE=lab")
    if date_key is None and month is None:
        raise CsvError("the CSV has no date column: say the month with --month YYYY-MM")
    index = {normalise(n): i for i, n in enumerate(names)}
    assert cost_key is not None

    lines: list[tuple[date | None, str, str, Decimal]] = []
    for number, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue

        def cell(key: str | None, cells: list[str] = cells) -> str:
            return "" if key is None or index[key] >= len(cells) else cells[index[key]]

        day = parse_day(cell(date_key), row=number, formats=date_formats) if date_key else None
        label = cell(ws_key).strip() if ws_key else ""
        row_scope = scope if scope is not None else scope_of_workspace(label)
        lines.append((day, label or "(whole file)", row_scope, parse_money(cell(cost_key), row=number) / divisor))
    if not lines:
        raise CsvError("the CSV has a header and no rows")

    if month is None:
        months = {d.replace(day=1) for d, *_ in lines if d is not None}
        if len(months) != 1:
            raise CsvError("the CSV spans " + ", ".join(sorted(f"{m:%Y-%m}" for m in months)) + " - choose one with --month")
        month = next(iter(months))
    month = month.replace(day=1)
    by_scope: dict[str, Decimal] = {}
    by_day: dict[tuple[str, date], Decimal] = {}
    workspaces: dict[str, str] = {}
    kept = 0
    for day, label, row_scope, usd in lines:
        if day is not None and day.replace(day=1) != month:
            continue
        kept += 1
        workspaces[label] = row_scope
        by_scope[row_scope] = by_scope.get(row_scope, Decimal(0)) + usd
        if day is not None:
            by_day[(row_scope, day)] = by_day.get((row_scope, day), Decimal(0)) + usd
    return ConsoleCosts(month, by_scope, by_day, kept, len(lines) - kept,
                        {"cost": header[cost_key], "date": header.get(date_key) if date_key else None,
                         "workspace": header.get(ws_key) if ws_key else None}, workspaces, digest)


OURS_SQL = """
SELECT scope, day, sum(cost) FROM (
    SELECT scope, (at AT TIME ZONE 'UTC')::date AS day, cost_usd AS cost
      FROM ai.usage_scoped WHERE provider = 'anthropic' AND at >= %(since)s AND at < %(until)s
    UNION ALL
    SELECT 'production', (started_at AT TIME ZONE 'UTC')::date, cost_usd
      FROM analytics.ai_runs WHERE started_at >= %(since)s AND started_at < %(until)s
) x GROUP BY scope, day
"""
"""Claude's spend in the ledger, by scope and UTC day: the calls of ``ai.usage`` made to Anthropic (Exa has no Console) and the
analyst's runs (``analytics.ai_runs``, which the production workspace pays)."""


def month_bounds(month: date) -> tuple[datetime, datetime]:
    first = month.replace(day=1)
    following = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return (datetime(first.year, first.month, 1, tzinfo=UTC), datetime(following.year, following.month, 1, tzinfo=UTC))


def ledger_costs(conn: psycopg.Connection[Any], month: date) -> tuple[dict[str, Decimal], dict[tuple[str, date], Decimal]]:
    since, until = month_bounds(month)
    by_scope: dict[str, Decimal] = {}
    by_day: dict[tuple[str, date], Decimal] = {}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OURS_SQL, {"since": since, "until": until})
        for scope, day, usd in cur.fetchall():
            by_scope[scope] = by_scope.get(scope, Decimal(0)) + Decimal(usd or 0)
            by_day[(scope, day)] = Decimal(usd or 0)
    return by_scope, by_day


@dataclass(frozen=True)
class DayLine:
    day: date
    ours: Decimal
    console: Decimal

    @property
    def diff(self) -> Decimal:
        return self.ours - self.console

    def as_json(self) -> dict[str, Any]:
        return {"day": self.day.isoformat(), "ours_usd": str(self.ours.quantize(Decimal("0.0001"))),
                "console_usd": str(self.console.quantize(Decimal("0.0001"))), "diff_usd": str(self.diff.quantize(Decimal("0.0001")))}


def judge(ours: Decimal, console: Decimal, *, tolerance: Decimal = TOLERANCE, floor: Decimal = ABSOLUTE_FLOOR) -> str:
    """OK when the two agree within the tolerance of the Console's figure - or within the rounding floor; INVESTIGAR otherwise;
    SIN DATOS when neither side spent anything."""
    if ours == 0 and console == 0:
        return NO_DATA
    diff = abs(ours - console)
    if diff <= floor:
        return OK
    if console == 0:
        return INVESTIGATE
    return OK if diff / abs(console) <= tolerance else INVESTIGATE


@dataclass(frozen=True)
class ScopeLine:
    scope: str
    ours: Decimal
    console: Decimal
    verdict: str
    days: tuple[DayLine, ...] = ()
    """Days whose figures differ by more than the tolerance (and the floor): where to look first when the month does not agree."""

    @property
    def diff(self) -> Decimal:
        return self.ours - self.console

    @property
    def diff_pct(self) -> Decimal | None:
        return None if self.console == 0 else (self.diff / self.console * 100).quantize(Decimal("0.01"))

    def as_json(self) -> dict[str, Any]:
        return {"scope": self.scope, "ours_usd": str(self.ours.quantize(Decimal("0.0001"))),
                "console_usd": str(self.console.quantize(Decimal("0.0001"))),
                "diff_usd": str(self.diff.quantize(Decimal("0.0001"))),
                "diff_pct": None if self.diff_pct is None else str(self.diff_pct), "verdict": self.verdict,
                "days_off": [d.as_json() for d in self.days]}


@dataclass(frozen=True)
class Reconciliation:
    month: date
    scopes: tuple[ScopeLine, ...]
    console: ConsoleCosts
    assumptions: tuple[str, ...] = field(default=())

    @property
    def verdict(self) -> str:
        """OK when every scope that spent anything agrees; INVESTIGAR if one does not; SIN DATOS when nothing was spent."""
        judged = [s.verdict for s in self.scopes if s.verdict != NO_DATA]
        if not judged:
            return NO_DATA
        return OK if all(v == OK for v in judged) else INVESTIGATE

    def as_json(self) -> dict[str, Any]:
        return {"month": f"{self.month:%Y-%m}", "verdict": self.verdict, "tolerance_pct": str(TOLERANCE * 100),
                "rounding_floor_usd": str(ABSOLUTE_FLOOR), "scopes": [s.as_json() for s in self.scopes],
                "csv": {"sha256": self.console.sha256, "rows": self.console.rows, "ignored_rows": self.console.ignored_rows,
                        "columns": self.console.columns, "workspaces": self.console.workspaces},
                "assumptions": list(self.assumptions)}


def reconcile(conn: psycopg.Connection[Any], console: ConsoleCosts, *, tolerance: Decimal = TOLERANCE,
              floor: Decimal = ABSOLUTE_FLOOR) -> Reconciliation:
    """The ledger of the CSV's month against the CSV, scope by scope."""
    ours_scope, ours_day = ledger_costs(conn, console.month)
    lines: list[ScopeLine] = []
    for scope in SCOPES:
        ours, theirs = ours_scope.get(scope, Decimal(0)), console.by_scope.get(scope, Decimal(0))
        off: list[DayLine] = []
        for day in sorted({d for s, d in (*ours_day, *console.by_day) if s == scope}):
            line = DayLine(day, ours_day.get((scope, day), Decimal(0)), console.by_day.get((scope, day), Decimal(0)))
            if judge(line.ours, line.console, tolerance=tolerance, floor=floor) == INVESTIGATE:
                off.append(line)
        lines.append(ScopeLine(scope, ours, theirs, judge(ours, theirs, tolerance=tolerance, floor=floor), tuple(off)))
    notes = [f"days are UTC days, as the Console's (the ledger is read {console.month:%Y-%m-01} to the first of the next month, UTC)",
             f"a difference under US${floor} counts as rounding; above it the limit is {tolerance * 100:g} % of the Console's figure",
             "ours = ai.usage (provider anthropic) + the analyst's analytics.ai_runs, which the production workspace pays; "
             "Exa is not in the Console: reconcile it with its invoice"]
    notes += [f"workspace {label!r} was read as {scope}" for label, scope in sorted(console.workspaces.items())]
    if console.ignored_rows:
        notes.append(f"{console.ignored_rows} row(s) of other months were left out")
    return Reconciliation(console.month, tuple(lines), console, tuple(notes))


def merge_all(parts: Iterable[ConsoleCosts]) -> ConsoleCosts:
    items = list(parts)
    if not items:
        raise CsvError("no CSV given")
    out = items[0]
    for nxt in items[1:]:
        out = out.merged(nxt)
    return out
