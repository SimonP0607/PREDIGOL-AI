"""What may ever promote itself, and the owner's signature that authorises it (``autopromo-v1``).

THE CLASSES. ``ChangeClass`` is closed: four routine changes and nothing else. A word in ``NEVER_AUTOMATIC`` is refused by name (``forbidden_class``)
and any other word because it is not in the enum (``unknown_class``) - a signature cannot open a class the code does not list.

THE SIGNATURE. A policy is a row of ``intel.promotions`` with ``entity = 'autopromo_policy'``, written by the owner (``decided_by = 'owner'``):

    market_key   the class (a value of ``ChangeClass``)
    to_role      VALIDATED authorises it; RETIRED, REJECTED or NOT_VALIDATED revoke it
    criteria     the terms: {"version": "autopromo-v1", "margin": 0.002, "min_sample": 1500, "max_changes": 1, "period_days": 7,
                             "band": 0.1, "notify": "email"}
    at           when it was signed (a policy covers candidates from then on)

The newest owner row of a class decides. A row signed by ``system`` is not a signature and is ignored (listed as refused). Nothing in this
package writes such a row: the table's entity check does not even admit ``autopromo_policy`` today, so until the owner adds that entity in a
migration of his own no policy exists and nothing can be eligible - off twice over.

THE TERMS a signature can tighten but never loosen (``CEILINGS``): the margin is never negative (a candidate must not be worse than the champion),
the sample never under the class's floor, at most ``MAX_CHANGES`` changes per class in a period of at least ``MIN_PERIOD_DAYS`` days, the band
never wider than the class's own, and the notification channel one the platform has.

THE SWITCH. ``FBI_AUTOPROMO``: ``on`` (or 1, true, yes) is the only word that turns it on; absent, empty or anything else is off.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "autopromo-v1"
SWITCH_ENV: Final = "FBI_AUTOPROMO"
POLICY_ENTITY: Final = "autopromo_policy"


class ChangeClass(StrEnum):
    CALIBRATOR_REFIT = "calibrator_refit"
    """Periodic refit of a calibrator that is ALREADY the champion of its (market, model), with the same method."""
    COUNCIL_WEIGHTS = "council_weights"
    """The weight of an agent that already counts in the Council, moved within a band."""
    SOURCE_CREDIBILITY = "source_credibility"
    """The credibility of a source of evidence, moved within a band."""
    CACHE_WINDOWS = "cache_windows"
    """How long a cached item stays valid, moved within a relative band."""


NEVER_AUTOMATIC: Final = frozenset({"new_model", "new_market", "agent_starts_counting", "decision_rules", "stake_policy", "budget"})
"""Changes that are the owner's, always, whatever a policy says (architecture section 6)."""

SAMPLE_FLOOR: Final[Mapping[ChangeClass, int]] = {
    ChangeClass.CALIBRATOR_REFIT: 1500,  # calib-gate-v1's out-of-sample minimum (fbi.intel.calibration.MIN_OOS_N; a test ties them)
    ChangeClass.COUNCIL_WEIGHTS: 300,
    ChangeClass.SOURCE_CREDIBILITY: 300,
    ChangeClass.CACHE_WINDOWS: 300,
}
BAND_CEILING: Final[Mapping[ChangeClass, float | None]] = {
    ChangeClass.CALIBRATOR_REFIT: None,  # a refit has no band: its bound is the same method and the margin
    ChangeClass.COUNCIL_WEIGHTS: 0.25,  # absolute, in weight units (council-weights-v1 keeps every weight in [0.5, 1.5])
    ChangeClass.SOURCE_CREDIBILITY: 0.10,  # absolute, on a credibility in [0, 1]
    ChangeClass.CACHE_WINDOWS: 0.50,  # relative to the window in force
}
MAX_CHANGES: Final = 4
MIN_PERIOD_DAYS: Final = 7
MAX_MARGIN: Final = 1.0
NOTIFY_CHANNELS: Final = frozenset({"email", "telegram"})
AUTHORISE: Final = "VALIDATED"
REVOKE: Final = frozenset({"RETIRED", "REJECTED", "NOT_VALIDATED"})

Status = Literal["AUTHORISED", "REVOKED", "INVALID"]


def refusal_of(raw: str) -> str | None:
    """None for a class that may promote itself; otherwise why not: ``forbidden_class`` or ``unknown_class``."""
    if raw in NEVER_AUTOMATIC:
        return "forbidden_class"
    if raw not in {c.value for c in ChangeClass}:
        return "unknown_class"
    return None


def class_of(raw: str) -> ChangeClass | None:
    return ChangeClass(raw) if refusal_of(raw) is None else None


@dataclass(frozen=True, slots=True)
class Terms:
    margin: float
    """How much lower (a loss: lower is better) the candidate's out-of-sample metric must be than the champion's."""
    min_sample: int
    max_changes: int
    period_days: int
    band: float | None
    notify: str

    def as_json(self) -> dict[str, Any]:
        return {"margin": self.margin, "min_sample": self.min_sample, "max_changes": self.max_changes, "period_days": self.period_days,
                "band": self.band, "notify": self.notify}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    out = float(value)
    return out if math.isfinite(out) else None


def _whole(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_terms(change_class: ChangeClass, criteria: Any) -> tuple[Terms | None, tuple[str, ...]]:
    """The terms of a signature, or the problems that make it invalid (an invalid policy authorises nothing)."""
    if not isinstance(criteria, Mapping):
        return None, ("terms_not_an_object",)
    problems: list[str] = []
    if criteria.get("version") != VERSION:
        problems.append("terms_version")
    margin = _number(criteria.get("margin"))
    if margin is None or margin < 0 or margin > MAX_MARGIN:
        problems.append("terms_margin")
    min_sample = _whole(criteria.get("min_sample"))
    if min_sample is None or min_sample < SAMPLE_FLOOR[change_class]:
        problems.append("terms_min_sample")
    max_changes = _whole(criteria.get("max_changes"))
    if max_changes is None or not 1 <= max_changes <= MAX_CHANGES:
        problems.append("terms_max_changes")
    period = _whole(criteria.get("period_days"))
    if period is None or period < MIN_PERIOD_DAYS:
        problems.append("terms_period_days")
    ceiling = BAND_CEILING[change_class]
    band = _number(criteria.get("band"))
    if ceiling is None:
        if criteria.get("band") is not None:
            problems.append("terms_band")
    elif band is None or band <= 0 or band > ceiling:
        problems.append("terms_band")
    notify = criteria.get("notify")
    if not isinstance(notify, str) or notify not in NOTIFY_CHANNELS:
        problems.append("terms_notify")
    if problems:
        return None, tuple(problems)
    assert margin is not None and min_sample is not None and max_changes is not None and period is not None and isinstance(notify, str)
    return Terms(margin, min_sample, max_changes, period, band if ceiling is not None else None, notify), ()


@dataclass(frozen=True, slots=True)
class Policy:
    change_class: ChangeClass
    status: Status
    terms: Terms | None
    signed_at: datetime
    source_id: str
    problems: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {"change_class": self.change_class.value, "status": self.status, "terms": None if self.terms is None else self.terms.as_json(),
                "signed_at": self.signed_at.isoformat(), "source": f"intel.promotions#{self.source_id}", "problems": list(self.problems)}


@dataclass(frozen=True, slots=True)
class Refused:
    """A row that looked like a policy and is not one."""

    source_id: str
    raw_class: str
    reason: str

    def as_json(self) -> dict[str, Any]:
        return {"source": f"intel.promotions#{self.source_id}", "class": self.raw_class, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class PolicyBook:
    by_class: Mapping[ChangeClass, Policy]
    refused: tuple[Refused, ...] = ()

    def of(self, change_class: ChangeClass) -> Policy | None:
        return self.by_class.get(change_class)


def book_from_rows(rows: Iterable[Mapping[str, Any]], *, at: datetime | None = None) -> PolicyBook:
    """The policies in force at ``at`` from rows of ``intel.promotions`` (any entity: only ``autopromo_policy`` rows are read)."""
    def order(r: Mapping[str, Any]) -> tuple[datetime, int]:
        return (r["at"], int(r["id"]))

    by_class: dict[ChangeClass, Policy] = {}
    refused: list[Refused] = []
    for r in sorted((r for r in rows if r.get("entity") == POLICY_ENTITY and (at is None or r["at"] <= at)), key=order):
        sid, raw = str(r["id"]), str(r.get("market_key") or "")
        why = refusal_of(raw)
        if why is not None:
            refused.append(Refused(sid, raw, why))
            continue
        if r.get("decided_by") != "owner":
            refused.append(Refused(sid, raw, "not_signed_by_owner"))
            continue
        change_class = ChangeClass(raw)
        role = str(r.get("to_role") or "")
        if role in REVOKE:
            by_class[change_class] = Policy(change_class, "REVOKED", None, r["at"], sid)
        elif role == AUTHORISE:
            terms, problems = parse_terms(change_class, r.get("criteria"))
            by_class[change_class] = Policy(change_class, "AUTHORISED" if terms else "INVALID", terms, r["at"], sid, problems)
        else:
            by_class[change_class] = Policy(change_class, "INVALID", None, r["at"], sid, (f"role_{role or 'missing'}",))
    return PolicyBook(by_class, tuple(refused))


POLICY_SQL: Final = """
SELECT id, at, entity, market_key, to_role, criteria, reason, decided_by
  FROM intel.promotions WHERE entity = %(entity)s ORDER BY at, id
"""


def read_policies(conn: psycopg.Connection[Any], *, at: datetime | None = None) -> PolicyBook:
    """A SELECT and nothing else."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(POLICY_SQL, {"entity": POLICY_ENTITY})
        rows = cur.fetchall()
    return book_from_rows(rows, at=at)


def switch_on(env: Mapping[str, str] | None = None) -> bool:
    raw = (os.environ if env is None else env).get(SWITCH_ENV, "")
    return raw.strip().lower() in ("on", "1", "true", "yes")
