"""The read-only measurement of the player markets (IA-130, AD-E04): the sample registered for AD-K02.

Over the finished matches that kicked off in a window, for each one: the newest ``/odds`` answer stored before ``kick-off - LEAD``
(``market.odds_extractions`` with status ``ok``, all its pages; the body read back from RAW and re-hashed, ``fbi.odds.quote_extract
.load_body``), its player-shot prices (``fbi.playermarkets.quotes``), each name matched to the side's sheet, the settlement of every
price on the match's statistics (``fbi.playermarkets.settle``) and the state it would have in the private evaluation
(``fbi.playermarkets.admission``) - with the families on, so the report shows what the gate holds back. The counts:

* matches read, matches with any player-shot price, by family and side, and the bets the taxonomy hides (with their reason);
* selections (player x line), houses per selection (its distribution) and the share of «una sola casa»;
* names resolved to one man of the sheet, and not;
* settlement: win, loss, void (did not play), and None by reason;
* states (``admission.STATES``), and how many could have been judged (``evaluable``) - 0 while one house is the norm.

Read-only: it asks the provider nothing, writes nothing and reads no model. ``measure`` is the database part; ``tally`` is pure.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.playermarkets import admission, quotes, settle
from fbi.storage.payload_store import PayloadStore

LEAD: Final = timedelta(minutes=10)
"""The price is the one in force 10 minutes before kick-off (decision-v1's floor)."""
MAX_FIXTURES: Final = 400

FIXTURES_SQL: Final = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.status_short, cs.competition_id
  FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
 WHERE f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND f.status_group = 'finished'
   AND (cardinality(%(competitions)s::int[]) = 0 OR cs.competition_id = ANY(%(competitions)s::int[]))
   AND EXISTS (SELECT 1 FROM market.odds_extractions x WHERE x.fixture_id = f.id AND x.status = 'ok')
 ORDER BY f.kickoff_at, f.id
 LIMIT %(limit)s
"""
ANSWER_SQL: Final = """
SELECT x.payload_hash, x.captured_at, coalesce(x.page, 1) AS page, p.file_path, p.params, p.hash
  FROM market.odds_extractions x JOIN raw.ingestion_payloads p ON p.hash = x.payload_hash
 WHERE x.fixture_id = %(f)s AND x.status = 'ok' AND x.captured_at = (
       SELECT max(y.captured_at) FROM market.odds_extractions y
        WHERE y.fixture_id = %(f)s AND y.status = 'ok' AND y.captured_at < %(before)s)
 ORDER BY coalesce(x.page, 1)
"""
SHEET_SQL: Final = """
SELECT lp.team_side, lp.provider_player_id, lp.player_name, pl.name AS profile_name,
       nullif(concat_ws(' ', pl.firstname, pl.lastname), '') AS full_name, lp.is_starter
  FROM core.fixture_lineup_players lp LEFT JOIN core.players pl ON pl.provider_player_id = lp.provider_player_id
 WHERE lp.fixture_id = %(f)s AND lp.source = 'api-football' AND lp.provider_player_id > 0
"""
STATS_SQL: Final = """
SELECT s.team_side, s.provider_player_id, s.minutes, s.shots_total, s.shots_on
  FROM core.fixture_player_stats s
 WHERE s.fixture_id = %(f)s AND s.source = 'api-football' AND s.provider_player_id > 0
"""


@dataclass
class Tally:
    fixtures: int = 0
    unreadable: int = 0
    with_prices: int = 0
    by_family_side: Counter[str] = field(default_factory=Counter)
    hidden: Counter[str] = field(default_factory=Counter)
    selections: int = 0
    books: Counter[int] = field(default_factory=Counter)
    single_house: int = 0
    resolved: int = 0
    unresolved: int = 0
    settled: Counter[str] = field(default_factory=Counter)
    states: Counter[str] = field(default_factory=Counter)
    problems: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        n = self.selections
        return {"fixtures": self.fixtures, "unreadable": self.unreadable, "fixtures_with_player_shot_prices": self.with_prices,
                "by_family_side": dict(sorted(self.by_family_side.items())), "hidden_by_taxonomy": dict(sorted(self.hidden.items())),
                "selections": n, "books_per_selection": {str(k): v for k, v in sorted(self.books.items())},
                "single_house": self.single_house, "single_house_share": None if not n else round(self.single_house / n, 4),
                "names_resolved": self.resolved, "names_unresolved": self.unresolved,
                "settlement": dict(sorted(self.settled.items())), "states_if_on": dict(sorted(self.states.items())),
                "evaluable": self.states.get(admission.EVALUABLE, 0), "rule": settle.RULE, "gate": {
                    "e3_reliable": admission.E3_RELIABLE, "mode": admission.mode()}, "problems": self.problems[:20]}


Sheet = Mapping[str, Sequence[tuple[int, str | None, bool]]]
"""side -> (provider player id, a name, starter) of the official sheet; a man may appear once per spelling of his name."""
Stats = Mapping[int, tuple[str, int | None, int | None, int | None]]
"""provider player id -> (side, minutes, shots, shots on target)."""


def tally(t: Tally, entry: Mapping[str, Any], *, sheet: Sheet, stats: Stats, status: str, kickoff_at: datetime, at: datetime) -> None:
    """Add one match: its answer's ``response`` entry, its official sheet and its statistics. Pure."""
    t.fixtures += 1
    got = quotes.read(entry)
    for bet_id, why in got.hidden.items():
        t.hidden[f"{bet_id}: {why}"[:120]] += 1
    if not got.quotes:
        return
    t.with_prices += 1
    names = {side: [(pid, name) for pid, name, _ in men] for side, men in sheet.items()}
    starters = {pid for men in sheet.values() for pid, _, s in men if s}
    for fam_side in {f"{q.family}.{q.side}" for q in got.quotes}:
        t.by_family_side[fam_side] += 1
    for q, pid in quotes.resolved(got.quotes, names):
        t.selections += 1
        t.books[q.books] += 1
        t.single_house += int(q.single_house)
        if pid is None:
            t.unresolved += 1
        else:
            t.resolved += 1
            row = stats.get(pid)
            on_sheet = row is not None or any(p == pid for men in sheet.values() for p, _, _ in men)
            minutes = None if row is None else row[1]
            count = None if row is None else (row[2] if settle.STATS[q.family] == "shots" else row[3])
            out = settle.settle(at_least=q.at_least, match_status=status, kickoff_at=kickoff_at, at=at, has_stats=bool(stats),
                                line=settle.PlayerLine(on_sheet, minutes, count))
            t.settled[out.status.value if out.status is not None else f"none:{out.basis}"] += 1
        f = admission.Facts(q.family, pid is not None, q.books, official_lineup=q.side in sheet,
                            starts=None if q.side not in sheet else pid in starters, kicked_off=True)
        t.states[admission.state(f, mode_now="shadow")] += 1


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def measure(conn: psycopg.Connection[Any], store: PayloadStore, *, start: datetime, end: datetime, at: datetime,
            competitions: Sequence[int] = (), limit: int = MAX_FIXTURES) -> dict[str, Any]:
    """The tally over the window. Read-only: the caller's connection should refuse writes."""
    from fbi.odds.quote_extract import load_body

    t = Tally()
    fixtures = _fetch(conn, FIXTURES_SQL, {"start": start, "end": end, "competitions": list(competitions), "limit": limit})
    for fx in fixtures:
        fid, pfid, ko = int(fx["id"]), int(fx["provider_fixture_id"]), fx["kickoff_at"]
        pages = _fetch(conn, ANSWER_SQL, {"f": fid, "before": ko - LEAD})
        if not pages:
            continue
        books: list[Any] = []
        bad = False
        for row in pages:
            body, problem, _missing = load_body(store, row, verify=True)
            if body is None:
                t.problems.append(f"{fid}: {problem}")
                bad = True
                break
            for item in body.get("response") or []:
                fixture = item.get("fixture") if isinstance(item, dict) else None
                if isinstance(fixture, dict) and fixture.get("id") not in (None, pfid):
                    continue
                if isinstance(item, dict) and isinstance(item.get("bookmakers"), list):
                    books.extend(item["bookmakers"])
        if bad:
            t.unreadable += 1
            continue
        sheet: dict[str, list[tuple[int, str | None, bool]]] = {}
        for r in _fetch(conn, SHEET_SQL, {"f": fid}):
            for name in dict.fromkeys(n for n in (r["player_name"], r["profile_name"], r["full_name"]) if n):
                sheet.setdefault(str(r["team_side"]), []).append((int(r["provider_player_id"]), name, bool(r["is_starter"])))
        stats = {int(r["provider_player_id"]): (str(r["team_side"]), r["minutes"], r["shots_total"], r["shots_on"])
                 for r in _fetch(conn, STATS_SQL, {"f": fid})}
        tally(t, {"bookmakers": books}, sheet=sheet, stats=stats, status=str(fx["status_short"]), kickoff_at=ko, at=at)
    return {"window": [start.isoformat(), end.isoformat()], "lead_minutes": LEAD.total_seconds() / 60, "limit": limit,
            "competitions": list(competitions), "measured_at": at.isoformat()} | t.as_json()
