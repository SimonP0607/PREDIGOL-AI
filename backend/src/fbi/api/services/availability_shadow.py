"""The shadow comparison of PM-02-06 (``fbi.coverage.shadow``): what each module shows today against what the matrix would say, both
read at the same instant. Run by ``scripts.availability_refresh`` in its own process after the nightly batch, never in the worker or on
a reader's request. Writes only ``analytics.availability_discrepancies``.

Four modules, each read with its own function:

* ``mercados_parlay`` - C-14's ``parlay.allowed`` of every selection priced now (``market_probs.build``) against Mi parlay's verdict
  of the same selection by the resolver (``fbi.coverage.resolve``);
* ``cuotas`` - a market C-14 lists (a price in force, whatever its houses) against the matrix's ``price_in_force`` (3 houses or more);
* ``probabilidad`` - a market where C-14 gives a reader PrediGol's figure against the matrix's ``prob_authorised``;
* ``estadisticas`` - a figure the statistics documents publish for the season (C-13, ``analytics.stat_documents``, 80 % of the
  team-matches) against the matrix's cell of its datum (B or more), once per competition season of the sample.
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services.availability import parlay_rules
from fbi.api.services.forecast import users_may_see
from fbi.api.services.market_probs import build as market_probs
from fbi.api.services.market_probs import parlay_policy
from fbi.api.services.market_status import load_catalogue
from fbi.coverage import resolve as resolver
from fbi.coverage import shadow
from fbi.coverage.job import PHASE_ALL, SHADOW_SECONDS

MAX_SECONDS: Final = SHADOW_SECONDS
BATCH: Final = 50

LEAGUE_DOC_SQL: Final = """
SELECT d.doc -> 'coverage' AS coverage FROM analytics.stat_documents d
 WHERE d.kind = 'league' AND d.entity_id = %(cs)s AND d.competition_season_id = %(cs)s AND d.scope = 'season' AND d.context = 'all'
"""
CELLS_SQL: Final = ("SELECT datum, level FROM analytics.coverage_cells WHERE competition_season_id = %(cs)s AND phase_key = %(phase)s")
SEASON_SQL: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %(f)s"


def _line(value: float | Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def compare_match(conn: Conn, fixture_id: int, *, at: datetime, catalogue: Any, rules: resolver.ParlayRules,
                  parlay_on: bool, state_of: Any, users: bool) -> list[shadow.Finding]:
    """The discrepancies of one match in C-14's three readings (Mi parlay's flag, the market listed, the model shown)."""
    probs = market_probs(conn, fixture_id, at=at, catalogue=catalogue, shadow=True)
    found = resolver.availability(conn, fixture_id, at=at, rules=rules, parlay_on=parlay_on, state_of=state_of, forecast_users=users)
    if found is None:
        return []
    by_key = {m.key: m for m in found.markets}
    shown_parlay: dict[str, bool] = {}
    matrix_parlay: dict[str, bool] = {}
    reasons: dict[str, str] = {}
    shown_listed: dict[str, bool] = {}
    matrix_listed: dict[str, bool] = {}
    shown_model: dict[str, bool] = {}
    matrix_model: dict[str, bool] = {}
    for m in probs.markets.items:
        state = by_key.get(m.key)
        verdicts = {(s.selection, _line(s.line)): s.mi_parlay for s in state.selections} if state else {}
        for s in m.selections:
            subject = f"{m.key}:{s.selection}:{_line(s.line)}"
            mine = verdicts.get((s.selection, _line(s.line)))
            shown_parlay[subject] = s.parlay.allowed
            matrix_parlay[subject] = mine is not None and not mine
            reasons[subject] = f"{s.parlay.reason}/{(mine[0] if mine else 'ok') if mine is not None else 'sin_estado'}"
        shown_listed[m.key] = True
        matrix_listed[m.key] = bool(state and state.price_in_force)
        shown_model[m.key] = any(not isinstance(s.model, Missing) for s in m.selections)
        matrix_model[m.key] = bool(state and state.prob_authorised)
    listed_reasons = {k: ("menos_de_3_casas" if not v else "solo_matriz") for k, v in matrix_listed.items()}
    out = shadow.compare(fixture_id, "mercados_parlay", shown_parlay, matrix_parlay, reasons=reasons)
    out += shadow.compare(fixture_id, "cuotas", shown_listed, matrix_listed, reasons=listed_reasons)
    out += shadow.compare(fixture_id, "probabilidad", shown_model, matrix_model,
                          reasons=dict.fromkeys(set(shown_model) | set(matrix_model), "modelo_vs_autorizada"))
    return out


def compare_season(conn: Conn, fixture_id: int, competition_season_id: int) -> list[shadow.Finding]:
    """C-13's publishable figures of the season against the matrix's cells of the data they rest on."""
    docs = fetch_all(conn, LEAGUE_DOC_SQL, {"cs": competition_season_id})
    cells = {r["datum"]: r["level"] for r in fetch_all(conn, CELLS_SQL, {"cs": competition_season_id, "phase": PHASE_ALL})}
    if not docs or not cells:
        return []
    published = {c.get("key"): bool(c.get("publishable")) for c in (docs[0]["coverage"] or []) if isinstance(c, dict)}
    shown = {datum: published[fig] for fig, datum in shadow.C13_DATA.items() if fig in published}
    matrix = {datum: cells.get(datum) in ("A", "B") for datum in shown}
    reasons = {datum: f"c13_vs_nivel_{cells.get(datum) or 'sin_medir'}" for datum in shown}
    return shadow.compare(fixture_id, "estadisticas", shown, matrix, reasons=reasons)


def run(conn: Conn, *, at: datetime, code_version: str | None = None, limit: int = shadow.SAMPLE,
        max_seconds: float = MAX_SECONDS) -> shadow.ShadowReport:
    """One day's comparison over the sample. A match that fails is recorded in the errors and skipped."""
    report = shadow.ShadowReport()
    started = time.monotonic()
    ids = shadow.sample(conn, at=at, limit=limit)
    conn.commit()
    catalogue = load_catalogue()
    rules = parlay_rules()
    policy = parlay_policy()
    users = users_may_see()
    seasons_done: set[int] = set()
    pending: list[shadow.Finding] = []
    for n, fid in enumerate(ids, start=1):
        if time.monotonic() - started > max_seconds:
            report.stopped = "tiempo_agotado"
            break
        try:
            found = compare_match(conn, fid, at=at, catalogue=catalogue, rules=rules, parlay_on=policy.enabled,
                                  state_of=policy.state_of, users=users)
            row = fetch_all(conn, SEASON_SQL, {"f": fid})
            cs = row[0]["competition_season_id"] if row else None
            if cs is not None and cs not in seasons_done:
                seasons_done.add(cs)
                found += compare_season(conn, fid, int(cs))
            conn.rollback()  # reads only: nothing to keep from the readings' transaction
        except Exception as exc:
            conn.rollback()
            report.errors.append(f"{fid}: {type(exc).__name__}: {exc}"[:200])
            continue
        report.matches += 1
        report.add(found)
        pending += found
        if n % BATCH == 0:
            report.written += shadow.write(conn, pending, at=at, day=at.date(), code_version=code_version)
            pending = []
    report.written += shadow.write(conn, pending, at=at, day=at.date(), code_version=code_version)
    return report
