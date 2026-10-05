"""The golden validation dataset: a few competitions, whole seasons, checked three ways.

For each golden competition-season (the five big leagues, the Champions League and Colombia's
Primera A; three complete seasons):

1. **provider** - ``/fixtures?league&season`` against every fixture and score we hold;
2. **table** - the provider's final ``/standings`` against the table our finished fixtures imply;
3. **external** - Football-Data.co.uk's results file (an independent compilation; free, no login),
   every row matched to our fixture by date, teams and score (``fbi.ingestion.historical_odds``):
   a row whose score disagrees with ours is a result mismatch. The CSVs already in the raw store
   are re-read; a missing season is downloaded once and kept as a NEW raw payload.

A result decided off the pitch is counted at its official score by checks 2 and 3 and listed
(``GoldenSeason.official``): the provider's AWD/WO score, or an official decision read on the
competition's or the sports court's site (``--decisions``). Our fixtures keep the played result.

The season's score is the share of checks that agree; a season is GOLDEN_VALIDATED when every
part is at least 99.5 % and nothing critical is unexplained. Nothing in core or market is written.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Json

from fbi.ingestion.historical_odds import (
    SOURCE,
    OurFixture,
    load_aliases,
    load_our_fixtures,
    match_rows,
)
from fbi.ingestion.payload_store import PayloadStore
from fbi.providers.football_data.parse import DIVISIONS, csv_url, decode, parse_csv, season_code
from fbi.truth import compare
from fbi.truth.audit import db_season_fixtures
from fbi.truth.findings import Tally
from fbi.truth.v2 import standings as st
from fbi.truth.v2.ledger import Evidence
from fbi.truth.v2.runner import V2Run

GOLDEN = (39, 140, 135, 78, 61, 2, 239)
SEASONS = (2023, 2024, 2025)
PASS = 0.995
USER_AGENT = "football-intelligence-v2 (private research; contact: repository owner)"


@dataclass
class GoldenSeason:
    league: int
    season: int
    name: str = ""
    fixtures_api: int = 0
    fixtures_db: int = 0
    fixtures_checked: int = 0
    fixtures_matched: int = 0
    results_checked: int = 0
    results_matched: int = 0
    table_rows: int = 0
    table_ok: int = 0
    table_verdict: str = "-"
    external_rows: int | None = None
    external_matched: int | None = None
    external_score_disagree: int | None = None
    external_other: int | None = None
    official: list[str] = field(default_factory=list)
    """Results decided off the pitch, counted at their official score (table and Football-Data)."""
    notes: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def parts(self) -> dict[str, float | None]:
        def share(a: int | None, b: int | None) -> float | None:
            return None if not b else (a or 0) / b
        return {"fixtures": share(self.fixtures_matched, self.fixtures_checked),
                "results": share(self.results_matched, self.results_checked),
                "table": share(self.table_ok, self.table_rows),
                "external": share(self.external_matched, (self.external_matched or 0)
                                  + (self.external_score_disagree or 0)) if self.external_rows else None}

    @property
    def score(self) -> float | None:
        vals = [v for v in self.parts().values() if v is not None]
        return sum(vals) / len(vals) if vals else None

    @property
    def verdict(self) -> str:
        parts = [v for v in self.parts().values() if v is not None]
        if not parts:
            return "NOT_CHECKED"
        return "GOLDEN_VALIDATED" if all(v >= PASS for v in parts) else "NEEDS_REVIEW"


def _competition(conn: psycopg.Connection[Any], league: int) -> tuple[int, str] | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, name FROM core.competitions WHERE provider_league_id = %s", (league,))
        row = cur.fetchone()
    return (int(row[0]), str(row[1])) if row else None


def _cs_id(conn: psycopg.Connection[Any], competition_id: int, season: int) -> int | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id FROM core.competition_seasons WHERE competition_id = %s AND season = %s",
                    (competition_id, season))
        row = cur.fetchone()
    return int(row[0]) if row else None


PROVIDER_AWARD = "AWD/WO at the provider: its /fixtures answer carries the official score"


def _kickoff(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def provider_awards(items: Sequence[Mapping[str, Any]]) -> list[st.Official]:
    """Matches the provider lists as decided off the pitch (AWD, WO) with the score it awards: we keep
    no result for them (they were not played out), the competition's table counts them."""
    out = []
    for item in items:
        fx, teams, goals = item.get("fixture") or {}, item.get("teams") or {}, item.get("goals") or {}
        status = str((fx.get("status") or {}).get("short") or "").upper()
        gh, ga = goals.get("home"), goals.get("away")
        home, away = (teams.get("home") or {}).get("id"), (teams.get("away") or {}).get("id")
        ko, fid = _kickoff(fx.get("date")), fx.get("id")
        if (status not in ("AWD", "WO") or not isinstance(gh, int) or not isinstance(ga, int)
                or not isinstance(home, int) or not isinstance(away, int) or not isinstance(fid, int) or ko is None):
            continue
        out.append(st.Official(st.Played(fid, ko, str((item.get("league") or {}).get("round") or ""),
                                         home, away, gh, ga), PROVIDER_AWARD))
    return out


OFFICIAL_FIXTURES_SQL = """
SELECT f.provider_fixture_id, f.id, (f.kickoff_at AT TIME ZONE 'UTC')::date, th.id, th.name, ta.id, ta.name
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.provider_fixture_id = ANY(%s)
"""


def official_variants(conn: psycopg.Connection[Any], official: Sequence[st.Official]) -> list[OurFixture]:
    """Our fixtures again at their official score, for a source that records the official result."""
    by_id = {o.match.fixture: o.match for o in official}
    if not by_id:
        return []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(OFFICIAL_FIXTURES_SQL, (list(by_id),))
        rows = cur.fetchall()
    return [OurFixture(int(fid), day, int(hid), str(hn), int(aid), str(an), by_id[int(pid)].gh, by_id[int(pid)].ga)
            for pid, fid, day, hid, hn, aid, an in rows]


def external_csv(conn: psycopg.Connection[Any], run: V2Run, http: httpx.Client | None, store: PayloadStore,
                 division: str, season: int) -> str | None:
    """The Football-Data CSV for a league-season: from the raw store, else downloaded and stored new."""
    endpoint = f"/mmz4281/{season_code(season)}/{division}.csv"
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT file_path FROM raw.ingestion_payloads WHERE provider = 'football_data' AND endpoint = %s "
                    "ORDER BY fetched_at DESC LIMIT 1", (endpoint,))
        got = cur.fetchone()
    if got is not None:
        return str(store.load(str(got[0]))["body"]["text"])
    local = os.environ.get("FBI_FD_CSV_DIR")
    path = Path(local) / season_code(season) / f"{division}.csv" if local else None
    text: str | None = None
    if path is not None and path.is_file():
        # A copy fetched elsewhere (the machine's network resets football-data.co.uk): stored as a NEW raw
        # payload like a download, its origin in the parameters.
        text = decode(path.read_bytes())
        return _store_csv(conn, run, store, endpoint, division, season, text, origin=f"file:{path.name}")
    if http is None:
        return None
    res = None
    for _attempt in range(3):
        try:
            res = http.get(csv_url(division, season))
            break
        except httpx.HTTPError as exc:  # a reset or a timeout: noted, the season keeps its other checks
            run.failures.append(f"{csv_url(division, season)}: {type(exc).__name__}: {exc}"[:200])
    if res is None:
        return None
    if res.status_code != 200:
        run.failures.append(f"{csv_url(division, season)}: HTTP {res.status_code}")
        return None
    return _store_csv(conn, run, store, endpoint, division, season, decode(res.content), origin="download")


def _store_csv(conn: psycopg.Connection[Any], run: V2Run, store: PayloadStore, endpoint: str, division: str,
               season: int, text: str, *, origin: str) -> str:
    at = datetime.now(UTC)
    params = {"division": division, "season": str(season), "origin": origin}
    stored = store.store(endpoint=endpoint, params=params, fetched_at=at, http_status=200,
                         body={"format": "csv", "text": text})
    with conn.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, "
                    "http_status, results_count, file_path, bytes) VALUES (%s,%s,'football_data',%s,%s,%s,200,%s,%s,%s) "
                    "ON CONFLICT (hash) DO NOTHING",
                    (stored.hash, run.ingestion_run_id, endpoint, Json(params), at, text.count("\n"),
                     stored.file_path, stored.bytes_written))
    conn.commit()
    return text


async def validate(run: V2Run, conn: psycopg.Connection[Any], league: int, season: int, *,
                   http: httpx.Client | None, store: PayloadStore,
                   decisions: Mapping[int, st.Decision] | None = None) -> GoldenSeason:
    """``decisions`` - official results not in the provider's fixtures (a sports court's award), read on
    the competition's or the court's site; with the provider's own AWD/WO scores they are counted at
    their official score by the table check and the Football-Data check, and listed."""
    g = GoldenSeason(league, season)
    comp = _competition(conn, league)
    if comp is None:
        g.notes.append("not in the catalogue")
        return g
    g.name = comp[1]
    # 1. provider fixtures and scores
    fixtures, results = Tally("fixtures"), Tally("results")
    answer = await run.get("/fixtures", {"league": league, "season": season})
    ours = db_season_fixtures(conn, league, season)
    g.fixtures_db = len(ours)
    if answer is not None:
        g.fixtures_api = len(answer.items)
        seen = set()
        for item in answer.items:
            pid = compare._id(item.get("fixture"))
            if pid is None:
                continue
            seen.add(pid)
            compare.compare_fixture(item, ours.get(pid), now=run.at, tally=fixtures, results=results)
        extra = [pid for pid in ours if pid not in seen]
        if extra:
            g.notes.append(f"{len(extra)} fixture(s) we hold are not in the provider's list")
    g.fixtures_checked, g.fixtures_matched = fixtures.checked, fixtures.matched
    g.results_checked, g.results_matched = results.checked, results.matched
    g.findings = [f.as_dict() for f in (fixtures.findings + results.findings)[:20]]
    # results decided off the pitch: the provider's AWD/WO scores, then the official decisions (which win)
    official = {o.match.fixture: o for o in provider_awards(answer.items if answer is not None else [])}
    cs = _cs_id(conn, comp[0], season)
    if cs is not None:
        mine = {f: d for f, d in (decisions or {}).items() if (d.league, d.season) == (league, season)}
        official |= {o.match.fixture: o for o in st.decided(conn, cs, mine)}
    g.official = [f"fixture {o.match.fixture}: official {o.match.gh}-{o.match.ga} ({o.basis})"
                  for o in official.values()]
    # 2. the final table against the fixtures
    if cs is not None:
        table = await run.get("/standings", {"league": league, "season": season})
        facts = {"provider_league_id": league, "name": comp[1], "season": season, "type": "league", "cs_id": cs}
        audit = st.audit_season(facts, table.body if table else None, st.db_rows(conn, cs), st.finished(conn, cs),
                                at=run.at, awarded_pairs=st.awarded(conn, cs), official=list(official.values()))
        g.table_rows = len(audit.rows)
        g.table_ok = sum(1 for r in audit.rows if r.verdict in ("ok", "adjusted", "awarded"))
        g.table_verdict = audit.verdict
        for r in [r for r in audit.rows if r.verdict not in ("ok", "adjusted", "awarded")][:5]:
            g.notes.append(f"table {r.name} ({r.group}): {r.verdict}" + (f" - {'; '.join(r.notes)}" if r.notes else ""))
    # 3. Football-Data's results
    division = DIVISIONS.get(league)
    if division is not None:
        text = external_csv(conn, run, http, store, division, season)
        if text is not None:
            rows, _skipped = parse_csv(text)
            variants = official_variants(conn, list(official.values()))
            report = match_rows(rows, load_our_fixtures(conn, comp[0], season) + variants, load_aliases(conn))
            decided_keys = {(v.fixture_id, v.goals_home, v.goals_away) for v in variants}
            for row, f in report.matched:
                if (f.fixture_id, f.goals_home, f.goals_away) in decided_keys:
                    g.notes.append(f"football-data {row.match_date} {row.home} v {row.away} "
                                   f"{row.goals_home}-{row.goals_away}: the official result (decided off the pitch)")
            g.external_rows = len(rows)
            g.external_matched = len(report.matched)
            g.external_score_disagree = sum(1 for _, why in report.unmatched if why.startswith("score disagreement"))
            g.external_other = len(report.unmatched) - g.external_score_disagree
            for row, why in report.unmatched[:5]:
                g.notes.append(f"football-data {row.match_date} {row.home} v {row.away} "
                               f"{row.goals_home}-{row.goals_away}: {why}")
    return g


def severity_of(g: GoldenSeason, issue: str, fault: str) -> str:
    """HIGH, unless only the PROVIDER's final table is behind while our fixtures and results agree with the provider's
    own fixture list and with the independent source (every other part at ``PASS`` or more): then what PrediGol holds
    is confirmed twice, the wrong table is the provider's, and the competition page already shows the table's
    agreement with our matches - MEDIUM, the same as the standings audit rates that same gap (Ligue 1 2025 on
    5 Oct 2026: the provider's table leaves out Toulouse-Nantes, abandoned, 0-0 homologated by the LFP)."""
    others = [v for k, v in g.parts().items() if k != "table"]
    confirmed = all(v is not None and v >= PASS for v in others)
    return "medium" if issue == "STANDINGS_MISMATCH" and fault == "provider" and confirmed else "high"


def evidence(seasons: Sequence[GoldenSeason]) -> list[Evidence]:
    out = []
    for g in seasons:
        if g.verdict != "NEEDS_REVIEW":
            continue
        parts = {k: (None if v is None else round(v, 4)) for k, v in g.parts().items()}
        if g.external_score_disagree or g.results_checked != g.results_matched:
            issue, fault = "RESULT_MISMATCH", "undetermined"
        elif (parts["fixtures"] or 1.0) < PASS:
            issue, fault = "FIXTURE_MISMATCH", "undetermined"
        else:  # the final table alone
            issue = "STANDINGS_MISMATCH"
            fault = {"provider_stale": "provider", "predigol_behind": "predigol", "mismatch": "predigol",
                     "fixtures_missing": "predigol"}.get(g.table_verdict, "undetermined")
        out.append(Evidence(
            key=f"golden:{g.league}:{g.season}", area="golden", issue_type=issue, severity=severity_of(g, issue, fault),
            at_fault=fault,
            entity=f"{g.name} {g.season} ({g.league})",
            claim=f"{g.name} {g.season}: golden checks below {PASS:.1%}: {parts}",
            api={"fixtures": [g.fixtures_api, g.fixtures_db], "table": g.table_verdict, "findings": g.findings[:8]},
            external={"source": SOURCE, "rows": g.external_rows, "matched": g.external_matched,
                      "score_disagree": g.external_score_disagree, "other": g.external_other, "notes": g.notes[:8]}))
    return out


def summary_rows(seasons: Sequence[GoldenSeason]) -> list[Mapping[str, Any]]:
    return [{"league": g.league, "name": g.name, "season": g.season, "verdict": g.verdict,
             "score": None if g.score is None else round(g.score, 4), "parts": g.parts(),
             "fixtures": [g.fixtures_api, g.fixtures_db, g.fixtures_matched, g.fixtures_checked],
             "results": [g.results_matched, g.results_checked], "table": [g.table_ok, g.table_rows, g.table_verdict],
             "external": [g.external_matched, g.external_rows, g.external_score_disagree, g.external_other],
             "official": g.official, "notes": g.notes[:8]} for g in seasons]
