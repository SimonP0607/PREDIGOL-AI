"""THE STATISTICS OF THE CHRONICLE'S SHEET, READ FROM C-13 (Plan Maestro PM, PM-11-07; IA-158): ``chronicle-stat-sheet-v1``.

WHY. Until now the single chronicle (``chronicle-v4``) told a team's expected goals and its goals and points per match from the packet's
``dossier`` (``fbi.intel.dossier``: the last ten matches in ANY competition, averaged to two decimals) and from its ``form`` block (the last
six results), while the team's statistics page and the match's «Estadísticas» read C-13 (``analytics.stat_documents``, ``fbi.stats.team``:
the matches of ONE competition season, by scope and context, three decimals and the coverage rule of EA-008). The same match could then
show «1,62 xG por partido» in its chronicle and «1,40» on the profile one tap away. PM-11-07: ONE source for each figure.

WHAT IT DOES, only while ``FBI_CHRONICLE_STAT_SHEET`` is ``on`` (``off`` by default; any other word is off; the worker reads it at start):

* the plan's ``xg`` fact of each side is the C-13 document's ``xg_for`` and ``xg_against`` - the same values the profile serves - in the
  match's competition season, scope ``u10`` and context ``all`` (the team page's default, ``TeamStatsHub``), or ``season`` when the team has
  no ``u10`` document there; ``n`` is the fewer of the two figures' ``matches_with_data``. A figure C-13 does not publish (``sin_datos``,
  ``sin_cobertura``) is not told: the chronicle never fills what the profile leaves empty;
* the packet's own ``xg`` fact is left out (``fuente_c13``), and the packet's ``form`` keeps its results (sequence, wins, draws, losses)
  but loses its averages (``ppg``, ``goals_for``, ``goals_against``): a per-match average is told from C-13 or not at all;
* the fact's ``source`` cites the C-13 metric keys, the document (competition season, scope, context, ``calc_version``) and its date; its
  ``known_at`` is the document's ``computed_at`` - a document computed after the plan's moment never enters (``posterior_al_plan``), and the
  plan uses the document in force at its moment, never a recomputation: the chronicle does not wait for the 07:20 UTC pass.

Off, nothing is read and the plan is exactly what it was (same facts, same hash). The prompt (``fbi.chronicle.writer.GLOSSARY``) does not
change: the ``xg`` fact keeps its params. No model, no probability, no write: one indexed SELECT per side (``stat_documents_pkey``).
``differences`` is the watch: a plan's ``xg`` facts against the documents as the API reads them (``scripts.chronicle_stat_check``).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "chronicle-stat-sheet-v1"
SWITCH: Final = "FBI_CHRONICLE_STAT_SHEET"
SCOPES: Final[tuple[str, ...]] = ("u10", "season")
"""In order of preference: the team page's default first, the whole season when there is no ``u10`` document."""
CONTEXT: Final = "all"
XG_KEYS: Final[tuple[str, str]] = ("xg_for", "xg_against")
FORM_AVERAGES: Final = frozenset({"ppg", "goals_for", "goals_against"})
"""The form's per-match averages: with the sheet on they are C-13's to tell (``xg``) or nobody's."""
SOURCE_PREFIX: Final = "C-13"

Mode = Literal["off", "on"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "on" if raw.strip().lower() in ("1", "on", "true", "yes") else "off"


@dataclass(frozen=True, slots=True)
class SheetFigure:
    key: str
    value: float
    matches_with_data: int


@dataclass(frozen=True, slots=True)
class SideSheet:
    """One team's C-13 document as the chronicle's sheet reads it: the published figures only (``Missing`` is not a value)."""

    team_id: int
    competition_season_id: int
    scope: str
    context: str
    calc_version: str
    computed_at: datetime
    matches: int
    figures: Mapping[str, SheetFigure]

    def source(self, keys: Iterable[str]) -> str:
        """What the fact cites: the metric keys and the document they come from, with its date."""
        return (f"{SOURCE_PREFIX}:team/{self.competition_season_id}/{self.scope}/{self.context}/{','.join(keys)}"
                f"@{self.calc_version}@{self.computed_at.isoformat()}")

    def xg(self) -> tuple[float, float, int] | None:
        """``xg_for``, ``xg_against`` and their sample, or None when C-13 does not publish both."""
        a, b = (self.figures.get(k) for k in XG_KEYS)
        if a is None or b is None:
            return None
        return a.value, b.value, min(a.matches_with_data, b.matches_with_data)


def _number(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def side_sheet(row: Mapping[str, Any]) -> SideSheet | None:
    """A ``analytics.stat_documents`` row (``doc``, ``computed_at``, ``calc_version``, ``scope``, ``context``, ``entity_id``,
    ``competition_season_id``) as a sheet; None when its body is not a team's. Pure."""
    doc = row.get("doc")
    if not isinstance(doc, Mapping) or not isinstance(doc.get("figures"), list):
        return None
    figures: dict[str, SheetFigure] = {}
    for f in doc["figures"]:
        if not isinstance(f, Mapping) or not isinstance(f.get("key"), str):
            continue
        value = _number(f.get("value"))  # a Missing is a dict: not a value
        if value is None:
            continue
        figures[str(f["key"])] = SheetFigure(str(f["key"]), value, int(f.get("matches_with_data") or 0))
    raw = doc.get("record")
    record: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    return SideSheet(int(row["entity_id"]), int(row["competition_season_id"]), str(row["scope"]), str(row["context"]),
                     str(row["calc_version"]), row["computed_at"], int(record.get("matches") or 0), figures)


SEASON_SQL: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %(f)s"
DOCS_SQL: Final = """
SELECT entity_id, competition_season_id, scope, context, calc_version, computed_at, doc
  FROM analytics.stat_documents
 WHERE kind = 'team' AND entity_id = %(team)s AND competition_season_id = %(cs)s AND context = %(context)s AND scope = ANY(%(scopes)s)
"""
"""The team's documents of the match's competition season in the sheet's context (``stat_documents_pkey``: kind, entity, season...)."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def choose(rows: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The document the sheet reads among a team's rows of one season and context: ``u10`` first, else ``season``."""
    by_scope = {str(r["scope"]): r for r in rows}
    return next((by_scope[s] for s in SCOPES if s in by_scope), None)


def read(conn: psycopg.Connection[Any], fixture_id: int, *, home_id: int, away_id: int) -> dict[str, SideSheet]:
    """Each side's sheet in the match's competition season (a side without a document there is absent). Read-only."""
    season = _rows(conn, SEASON_SQL, {"f": fixture_id})
    if not season or season[0]["competition_season_id"] is None:
        return {}
    cs = int(season[0]["competition_season_id"])
    out: dict[str, SideSheet] = {}
    for side, team in (("home", home_id), ("away", away_id)):
        row = choose(_rows(conn, DOCS_SQL, {"team": team, "cs": cs, "context": CONTEXT, "scopes": list(SCOPES)}))
        sheet = side_sheet(row) if row is not None else None
        if sheet is not None:
            out[side] = sheet
    return out


@dataclass(frozen=True, slots=True)
class Difference:
    fixture_id: int
    side: str
    key: str
    chronicle: float | None
    profile: float | None
    note: str

    def as_json(self) -> dict[str, Any]:
        return {"fixture_id": self.fixture_id, "side": self.side, "key": self.key, "chronicle": self.chronicle, "profile": self.profile,
                "note": self.note}


def differences(fixture_id: int, facts: Iterable[Any], profile: Mapping[str, Mapping[str, float]]) -> list[Difference]:
    """Every figure of a plan's ``xg`` facts that is not the profile's: ``facts`` are ``PlanFact``s (or anything with ``kind``, ``side``
    and ``params``); ``profile`` is, by side, the C-13 values the API serves (``xg_for``, ``xg_against``). A side the profile has and the
    plan does not tell is not a difference (the chronicle may stay silent); a figure the plan tells and the profile does not publish is.
    Pure."""
    out: list[Difference] = []
    for f in facts:
        if getattr(f, "kind", None) != "xg" or getattr(f, "side", None) not in ("home", "away"):
            continue
        side = str(f.side)
        mine = profile.get(side, {})
        for key in XG_KEYS:
            told = _number(f.params.get(key))
            if told is None:
                continue
            shown = mine.get(key)
            if shown is None:
                out.append(Difference(fixture_id, side, key, told, None, "el_perfil_no_la_publica"))
            elif abs(told - shown) > 1e-9:
                out.append(Difference(fixture_id, side, key, told, shown, "cifra_distinta"))
    return out


__all__ = ["CONTEXT", "FORM_AVERAGES", "SCOPES", "SOURCE_PREFIX", "SWITCH", "VERSION", "XG_KEYS", "Difference", "SheetFigure", "SideSheet",
           "choose", "differences", "mode", "read", "side_sheet"]
