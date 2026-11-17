"""Every dollar of the month given to ONE capability (IA-137, AD-K05 of the plan of the definitive architecture 2026): ``capability-costs-v1``.

WHY. ``fbi.ai.capability_budget`` (IA-058) gives each NEW piece of the plan its cap, but most of what is spent today is paid by the
components that were there before it (the review of production, the brief, the search, the extraction, the shadow's deliberation...), and
those had no capability of their own. AD-K05 asks that 100 % of the month's spend be attributed to a capability. This module does it,
row by row of both ledgers (``ai.usage`` with its scope, and the readers' own ledger, read by ``fbi.ai.envelopes_readers`` and paid from production's envelope):

    1. a capability of the register (``capability_budget.capability_of``: its own envelope, its prompt prefix or its purpose);
    2. else a prompt of a component with a known owner that the paths of IA-034 do not name (``EXTRA``);
    3. else the path and part of IA-034 (``fbi.ai.cost_paths.path_of``: ``production.review``, ``research.search``...), the same words
       the cost-by-path report uses, so the two reports never give one call two names;
    4. ``rest.other`` is NOT a capability: such a row is ``sin_capacidad`` and listed with its prompt, purpose, tier and agent, so it
       can be named. The criterion of AD-K05 is that the month has none (``complete``).

Beside each capability, from the same rows: how many of its calls went through a Message Batch (``batch_share``), how much of its input
was read from the prompt cache (``cache_read_share``) and how many of its PAID calls repeated an input already paid this month (the same
prompt and the same ``input_hash``: ``repeat_calls``, ``repeat_usd``). For the extraction of pages that is the "pay once per page"
of AD-K05 (unified research keys a page by its fingerprint and its canonical address: ``fbi.ai.deep_pages``, ``fbi.ai.cache.url_key``), and
it must be 0; for a search it can be a legitimate refresh after its freshness (``fbi.ai.cache.FRESHNESS``) and is shown, not judged.

THE TOTAL. The rows add up to the ledgers' own sums, read by statements of their own (``Totals``): the report says the difference to the
millionth of a dollar and whether it is under a cent (``reconciles``).

It INFORMS and decides nothing (``"decides": False``): no route, model, switch, cap, envelope or threshold reads it. Pure: no database
and no clock (the rows are read by ``fbi.ai.envelopes_readers``, which only the owner's cost panel imports)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from fbi.ai import capability_budget
from fbi.ai.cost_paths import Call, path_of

VERSION: Final = "capability-costs-v1"
UNATTRIBUTED: Final = "sin_capacidad"
LEDGERS: Final[tuple[str, ...]] = ("usage", "readers")
EXTRA: Final[tuple[tuple[str, str], ...]] = (
    ("pick-why-", "narrator.pick_why"),
    ("user-narrative-", "chronicles.chronicle"),
    ("match-v", "deliberation.match_agent"),
    ("stats-v", "deliberation.stats_agent"),
    ("player-v", "deliberation.player_agent"),
)
"""Prompts whose component is known but that IA-034's paths would leave in ``rest.other``: the pick's narrator (``pick-why-v1``, off
today) and the shadow's agents by their registry's prompt (``match-v5``, ``stats-v4``, ``player-v1``), which IA-034 finds only by the
ledger's ``agent`` column - a row written without it would otherwise be nobody's. ``user-narrative-`` is IA-034's own word for the readers' chronicle, repeated so a row of the readers' ledger never depends on the
order of the paths."""
CENT: Final = Decimal("0.01")
MICRO: Final = Decimal("0.000001")
_EPOCH: Final = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Row:
    """The month's calls of one (ledger, scope, prompt, purpose, tier, agent): how many, what they cost and how they were paid."""

    ledger: str
    scope: str
    prompt: str | None
    purpose: str | None
    tier: str | None
    agent: str | None
    calls: int
    usd: Decimal
    batch_calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    repeat_calls: int = 0
    repeat_usd: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class Totals:
    """The ledgers' own count and sum of the window, read apart from the rows."""

    usage_calls: int
    usage_usd: Decimal
    readers_calls: int
    readers_usd: Decimal

    @property
    def usd(self) -> Decimal:
        return self.usage_usd + self.readers_usd

    @property
    def calls(self) -> int:
        return self.usage_calls + self.readers_calls


def capability_of(r: Row) -> str | None:
    """The capability a row's calls belong to, or None (``sin_capacidad``)."""
    key = capability_budget.capability_of(r.scope, r.prompt, r.purpose)
    if key is not None:
        return key
    prompt = r.prompt or ""
    for prefix, name in EXTRA:
        if prompt.startswith(prefix):
            return name
    call = Call(0, _EPOCH, r.purpose or "", r.tier or "", "", "", r.prompt, "ok", Decimal(0), agent=r.agent)
    path, part = path_of(call)
    if (path, part) == ("rest", "other"):
        return None
    return f"{path}.{part}"


def _usd(x: Decimal) -> str:
    return str(x.quantize(CENT, rounding=ROUND_HALF_UP))


def _exact(x: Decimal) -> str:
    return str(x.quantize(MICRO, rounding=ROUND_HALF_UP))


def _share(part: Decimal | int, whole: Decimal | int) -> float | None:
    return None if not whole else round(float(Decimal(part) / Decimal(whole)), 4)


@dataclass
class _Tally:
    calls: int = 0
    usd: Decimal = Decimal(0)
    batch_calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    repeat_calls: int = 0
    repeat_usd: Decimal = Decimal(0)

    def add(self, r: Row) -> None:
        self.calls += r.calls
        self.usd += r.usd
        self.batch_calls += r.batch_calls
        self.input_tokens += r.input_tokens
        self.cached_tokens += r.cached_tokens
        self.repeat_calls += r.repeat_calls
        self.repeat_usd += r.repeat_usd


def report(rows: Iterable[Row], totals: Totals) -> dict[str, Any]:
    """The month by capability, the rows no capability claims, and the check against the ledgers' own sums."""
    by: dict[str, _Tally] = defaultdict(_Tally)
    envelopes: dict[str, set[str]] = defaultdict(set)
    loose: list[Row] = []
    every = _Tally()
    for r in rows:
        every.add(r)
        key = capability_of(r)
        if key is None:
            loose.append(r)
            continue
        by[key].add(r)
        envelopes[key].add(r.scope)
    whole = totals.usd
    caps = []
    for key, t in sorted(by.items(), key=lambda kv: (-kv[1].usd, kv[0])):
        reg = capability_budget.get(key)
        caps.append({
            "key": key, "registered": reg is not None, "piece": None if reg is None else reg.piece,
            "envelopes": sorted(envelopes[key]), "calls": t.calls, "spent_usd": _usd(t.usd), "share": _share(t.usd, whole),
            "monthly_usd": None if reg is None else _usd(reg.monthly_usd),
            "alert": None if reg is None else capability_budget.level(t.usd, reg.monthly_usd),
            "batch_calls": t.batch_calls, "batch_share": _share(t.batch_calls, t.calls),
            "cache_read_share": _share(t.cached_tokens, t.input_tokens),
            "repeat_calls": t.repeat_calls, "repeat_usd": _usd(t.repeat_usd)})
    loose_usd = sum((r.usd for r in loose), Decimal(0))
    loose_calls = sum(r.calls for r in loose)
    attributed = every.usd - loose_usd
    difference = every.usd - whole
    return {
        "version": VERSION, "capabilities": caps,
        "unattributed": {"calls": loose_calls, "usd": _usd(loose_usd),
                         "rows": [{"ledger": r.ledger, "scope": r.scope, "prompt": r.prompt, "purpose": r.purpose, "tier": r.tier,
                                   "agent": r.agent, "calls": r.calls, "usd": _usd(r.usd)}
                                  for r in sorted(loose, key=lambda x: (-x.usd, x.prompt or ""))[:20]]},
        "total": {"rows_usd": _exact(every.usd), "ledger_usd": _exact(whole), "difference_usd": _exact(difference),
                  "rows_calls": every.calls, "ledger_calls": totals.calls, "reconciles": abs(difference) < CENT,
                  "attributed_usd": _usd(attributed), "attributed_share": _share(attributed, whole) if whole else None,
                  "readers_usd": _usd(totals.readers_usd)},
        "complete": loose_calls == 0 and abs(difference) < CENT and every.calls == totals.calls,
        "batch_share": _share(every.batch_calls, every.calls), "cache_read_share": _share(every.cached_tokens, every.input_tokens),
        "repeat_usd": _usd(every.repeat_usd), "decides": False,
    }


__all__ = ["EXTRA", "LEDGERS", "UNATTRIBUTED", "VERSION", "Row", "Totals", "capability_of", "report"]
