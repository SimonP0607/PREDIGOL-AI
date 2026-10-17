"""Import the legacy knowledge that survived the audit, with a report.

Two sources, one importer, one report:

* ``competition_context`` (DuckDB backup, 81 rows) - hand-curated domain
  knowledge: entity scope, competition kind, Elo weight.
* ``tracked_competitions`` (Supabase backup, 77 rows) - the provider's own
  catalogue: real names, country, league/cup format, current season.
* ``ref_bookmakers`` (Supabase backup, 32 rows) - the bookmaker catalogue.

Nothing is copied blindly. Every row is accepted, transformed (with the change
named) or rejected (with the reason), and the counts go in the report. The
importer is idempotent: running it twice yields the same database and the same
report.

What is NOT imported, by decision of the audit: calibration_registry (128/152
without validation), backtest_runs (accuracy stored as ROI), MatchContextScorer
heuristics, OddsPredictor. None of them is knowledge; all of them are the
defect.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import polars as pl
import psycopg
import structlog
from psycopg.rows import tuple_row

from fbi.domain.market import MarketType

log = structlog.get_logger(__name__)

# The legacy's own documented rule (competition_context comment):
#   liga 1.0, continental 0.5-0.8, copa 0.4, amistoso 0.3
CUP_ELO_WEIGHT = 0.40

PROVIDER_BET_IDS: dict[MarketType, int] = {
    MarketType.MATCH_WINNER: 1,
    MarketType.TOTAL_GOALS: 5,
    MarketType.BOTH_TEAMS_TO_SCORE: 8,
    MarketType.DOUBLE_CHANCE: 12,
    MarketType.ASIAN_HANDICAP: 4,
}
MARKET_NAMES: dict[MarketType, str] = {
    MarketType.MATCH_WINNER: "Match Winner",
    MarketType.TOTAL_GOALS: "Goals Over/Under",
    MarketType.BOTH_TEAMS_TO_SCORE: "Both Teams Score",
    MarketType.DOUBLE_CHANCE: "Double Chance",
    MarketType.ASIAN_HANDICAP: "Asian Handicap",
}


@dataclass
class RowOutcome:
    source: str
    key: str
    outcome: str  # accepted | transformed | rejected
    reason: str = ""
    changes: dict[str, Any] = field(default_factory=dict)


@dataclass
class MigrationReport:
    dry_run: bool
    source_rows: dict[str, int] = field(default_factory=dict)
    accepted: dict[str, int] = field(default_factory=dict)
    transformed: dict[str, int] = field(default_factory=dict)
    rejected: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    rows: list[RowOutcome] = field(default_factory=list)
    written: dict[str, int] = field(default_factory=dict)

    def record(self, row: RowOutcome) -> None:
        self.rows.append(row)
        bucket = {"accepted": self.accepted, "transformed": self.transformed, "rejected": self.rejected}[row.outcome]
        bucket[row.source] = bucket.get(row.source, 0) + 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False, default=str)

    def summary_table(self) -> str:
        lines = ["| Dataset | Source rows | Accepted | Transformed | Rejected |", "|---|---:|---:|---:|---:|"]
        for src, n in self.source_rows.items():
            lines.append(
                f"| {src} | {n} | {self.accepted.get(src, 0)} | {self.transformed.get(src, 0)} | {self.rejected.get(src, 0)} |"
            )
        return "\n".join(lines)


@dataclass(frozen=True)
class CompetitionRow:
    provider_league_id: int
    name: str
    country: str | None
    format: str  # league | cup
    entity_scope: str
    competition_type: str
    elo_weight: float
    tier: int | None
    season: int | None
    season_is_current: bool


def _normalise_format(provider_type: str) -> str:
    return {"League": "league", "Cup": "cup"}.get(provider_type, "league")


def merge_competitions(context: pl.DataFrame, tracked: pl.DataFrame, report: MigrationReport) -> list[CompetitionRow]:
    """Join the curated context with the provider catalogue and decide row by row."""
    report.source_rows["competition_context"] = context.height
    report.source_rows["tracked_competitions"] = tracked.height
    tracked_by_id = {int(r["provider_league_id"]): r for r in tracked.to_dicts()}
    out: list[CompetitionRow] = []
    seen: set[int] = set()

    for ctx in context.to_dicts():
        lid = int(ctx["provider_league_id"])
        seen.add(lid)
        key = f"league:{lid}"
        prov = tracked_by_id.get(lid)
        if prov is None:
            report.record(
                RowOutcome(
                    "competition_context", key, "rejected",
                    "not in the provider catalogue and the legacy name is a placeholder "
                    f"({ctx['league_name']!r}); re-create from /leagues when needed",
                )
            )
            continue

        changes: dict[str, Any] = {}
        fmt = _normalise_format(str(prov["type"]))
        kind = str(ctx["competition_type"])
        weight = float(ctx["elo_weight"])
        name = str(prov["name"])

        if str(ctx["league_name"]) != name:
            changes["name"] = {"from": ctx["league_name"], "to": name, "why": "provider catalogue is authoritative"}
        if fmt == "cup" and kind == "domestic_league":
            # The provider says cup; the legacy context left the default. Apply
            # the legacy's OWN documented rule for cups rather than keep a
            # contradiction, and say so.
            changes["competition_type"] = {"from": kind, "to": "domestic_cup", "why": "provider type is Cup"}
            kind = "domestic_cup"
            if weight == 1.0:
                changes["elo_weight"] = {"from": weight, "to": CUP_ELO_WEIGHT, "why": "legacy rule: cups weigh 0.4"}
                weight = CUP_ELO_WEIGHT
                report.warnings.append(
                    f"{key} ({name}): classified domestic_league in legacy context but Cup at the provider; "
                    f"imported as domestic_cup with elo_weight {CUP_ELO_WEIGHT} (legacy's own rule). Review."
                )

        row = CompetitionRow(
            provider_league_id=lid,
            name=name,
            country=(str(prov["country"]) if prov.get("country") else None),
            format=fmt,
            entity_scope=str(ctx["entity_scope"]),
            competition_type=kind,
            elo_weight=weight,
            tier=(int(prov["priority"]) if prov.get("priority") is not None else None),
            season=(int(prov["season"]) if prov.get("season") is not None else None),
            season_is_current=bool(prov.get("current", False)),
        )
        out.append(row)
        report.record(
            RowOutcome("competition_context", key, "transformed" if changes else "accepted", changes=changes)
        )
        report.record(RowOutcome("tracked_competitions", key, "accepted"))

    for lid in tracked_by_id:
        if lid not in seen:
            report.record(
                RowOutcome("tracked_competitions", f"league:{lid}", "rejected", "no curated context row")
            )
    return out


def load_bookmakers(bookmakers: pl.DataFrame, report: MigrationReport) -> list[tuple[int, str]]:
    report.source_rows["ref_bookmakers"] = bookmakers.height
    out: list[tuple[int, str]] = []
    for r in bookmakers.to_dicts():
        pid, name = int(r["provider_bookmaker_id"]), str(r["name"]).strip()
        if pid <= 0 or not name:
            report.record(RowOutcome("ref_bookmakers", f"book:{pid}", "rejected", "missing id or name"))
            continue
        out.append((pid, name))
        report.record(RowOutcome("ref_bookmakers", f"book:{pid}", "accepted"))
    return out


def write(conn: psycopg.Connection, competitions: Sequence[CompetitionRow], bookmakers: Sequence[tuple[int, str]], report: MigrationReport) -> None:
    """Upsert everything. is_tracked is NEVER set here: activation belongs to config."""
    with conn.cursor(row_factory=tuple_row) as cur:
        n_comp = n_season = 0
        for c in competitions:
            cur.execute(
                """
                INSERT INTO core.competitions
                  (provider_league_id, name, country, type, entity_scope, competition_type, elo_weight, tier, is_tracked)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,false)
                ON CONFLICT (provider_league_id) DO UPDATE SET
                  name = EXCLUDED.name, country = EXCLUDED.country, type = EXCLUDED.type,
                  entity_scope = EXCLUDED.entity_scope, competition_type = EXCLUDED.competition_type,
                  elo_weight = EXCLUDED.elo_weight, tier = EXCLUDED.tier, updated_at = now()
                RETURNING id
                """,
                (c.provider_league_id, c.name, c.country, c.format, c.entity_scope, c.competition_type, c.elo_weight, c.tier),
            )
            comp_id = cur.fetchone()[0]  # type: ignore[index]
            n_comp += 1
            if c.season is not None:
                cur.execute(
                    """
                    INSERT INTO core.competition_seasons (competition_id, season, is_current)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (competition_id, season) DO UPDATE SET is_current = EXCLUDED.is_current
                    """,
                    (comp_id, c.season, c.season_is_current),
                )
                n_season += 1
        cur.executemany(
            "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s,%s) "
            "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name",
            list(bookmakers),
        )
        # is_model_enabled is deliberately NOT written here: which markets our
        # models may use is an operational decision, not a catalogue fact, and
        # re-importing the catalogue must never quietly enable a market.
        cur.executemany(
            "INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive, provider_bet_id, "
            " line_is_signed) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (key) DO UPDATE SET "
            "name = EXCLUDED.name, n_outcomes = EXCLUDED.n_outcomes, has_line = EXCLUDED.has_line, "
            "is_exclusive = EXCLUDED.is_exclusive, provider_bet_id = EXCLUDED.provider_bet_id, "
            "line_is_signed = EXCLUDED.line_is_signed",
            [
                (m.value, MARKET_NAMES[m], m.n_outcomes, m.has_line, m.is_exclusive, PROVIDER_BET_IDS[m],
                 m.line_is_signed)
                for m in MarketType
            ],
        )
    report.written = {
        "core.competitions": n_comp,
        "core.competition_seasons": n_season,
        "market.bookmakers": len(bookmakers),
        "market.markets": len(MarketType),
    }


def run(conn: psycopg.Connection | None, legacy_dir: Path, *, dry_run: bool) -> MigrationReport:
    report = MigrationReport(dry_run=dry_run)
    context = pl.read_parquet(legacy_dir / "competition_context.parquet")
    tracked = pl.read_parquet(legacy_dir / "tracked_competitions.parquet")
    books = pl.read_parquet(legacy_dir / "ref_bookmakers.parquet")

    competitions = merge_competitions(context, tracked, report)
    bookmakers = load_bookmakers(books, report)

    if dry_run or conn is None:
        report.written = {"core.competitions": 0, "core.competition_seasons": 0, "market.bookmakers": 0, "market.markets": 0}
        log.info("legacy_import.dry_run", competitions=len(competitions), bookmakers=len(bookmakers))
        return report

    write(conn, competitions, bookmakers, report)
    conn.commit()
    log.info("legacy_import.written", **report.written)
    return report
