"""Where the candidates of ``autopromo-v1`` come from - read-only: every statement is a SELECT and the connection is the caller's.

Only one class has a ledger of candidates today: ``calibrator_refit``. A candidate is the newest fit of each method of a (market, model) whose
calibrator in force (the registry's ``current`` of ``calibrator``) is older; it is compared with the champion the same way the nightly
calibration compares them (``fbi.intel.calibration``): the walk-forward log loss and sample stored with each fit. A (market, model) with no
champion is listed too - and refused (``no_champion``): its first champion is a new model in force.

The Council weights, the credibility of sources and the cache windows have no ledger of proposed values yet; they show zero candidates
(``NO_SOURCE``) until one exists.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.governance import promotions as registry
from fbi.governance.autopromo.evaluate import Candidate
from fbi.governance.autopromo.policy import ChangeClass

NO_SOURCE: Final = frozenset({ChangeClass.COUNCIL_WEIGHTS, ChangeClass.SOURCE_CREDIBILITY, ChangeClass.CACHE_WINDOWS})

FITS_SQL: Final = """
SELECT DISTINCT ON (c.market_key, c.model_name, c.method) c.id, c.market_key, c.model_name, c.method, c.known_at, c.wf
  FROM intel.calibrators c
 WHERE c.method <> 'identity' AND (%(at)s::timestamptz IS NULL OR c.known_at <= %(at)s::timestamptz)
 ORDER BY c.market_key, c.model_name, c.method, c.known_at DESC, c.id DESC
"""
"""The newest fit of each method of each (market, model) - the identity is the reference, never a candidate."""

BY_ID_SQL: Final = "SELECT id, method, known_at, wf FROM intel.calibrators WHERE id = ANY(%(ids)s)"


def _float(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _int(x: Any) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def calibrator_candidates(fits: Iterable[Mapping[str, Any]], champions: Mapping[str, Mapping[str, Any]]) -> list[Candidate]:
    """Pure: the candidates from the newest fits and the champion fit of each key in force."""
    out: list[Candidate] = []
    for f in fits:
        key = f"{f['market_key']}/{f['model_name']}"
        champ = champions.get(key)
        if champ is not None and (int(f["id"]) == int(champ["id"]) or f["known_at"] <= champ["known_at"]):
            continue  # nothing newer than what is in force
        wf, cwf = f.get("wf") or {}, (champ.get("wf") or {}) if champ is not None else {}
        out.append(Candidate(ChangeClass.CALIBRATOR_REFIT.value, key, str(f["id"]), f["known_at"],
                             None if champ is None else str(champ["id"]), _float(wf.get("logloss_cal")),
                             _float(cwf.get("logloss_cal")) if champ is not None else None, _int(wf.get("n")), "wf_logloss_cal",
                             str(f["method"]), None if champ is None else str(champ["method"])))
    return sorted(out, key=lambda c: (c.key, c.method or "", c.version))


def read_calibrator_candidates(conn: psycopg.Connection[Any], records: Sequence[registry.Promotion], *,
                               at: datetime | None = None) -> list[Candidate]:
    champion_ids: dict[str, int] = {}
    for etype, key in registry.keys_of(records):
        if etype != "calibrator":
            continue
        now = registry.current_of(records, etype, key, at=at)
        if now is not None and now.in_force and now.version is not None and now.version.isdigit():
            champion_ids[key] = int(now.version)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FITS_SQL, {"at": at})
        fits = cur.fetchall()
        champions: dict[str, Mapping[str, Any]] = {}
        if champion_ids:
            cur.execute(BY_ID_SQL, {"ids": sorted(champion_ids.values())})
            by_id = {int(r["id"]): r for r in cur.fetchall()}
            champions = {k: by_id[i] for k, i in champion_ids.items() if i in by_id}
    return calibrator_candidates(fits, champions)
