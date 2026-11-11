"""What each path of decision costs, from the ledger, and whether every call to Opus has the rule that allows it (IA-034; INT-T01 of the
Plan Maestro de PrediGol Intelligence 2026).

THE PATHS. Every row of ``ai.usage`` in the window belongs to exactly ONE path and one part of it, read from its prompt (``path_of``):

    production    ``review``: the review of production, ``review-v2`` (``pick_review``: Sonnet at L2, Opus at L3, in real time or in a
                  Message Batch); ``brief``: its reading of the match, ``brief-v8`` (Haiku, ``match_brief``)
    deliberation  the shadow's deliberation, in the LAB workspace: ``match_agent`` (``match-context-*``, ``match-assess-*``), ``stats_agent``
                  (``stats-assess-*``), ``player_agent`` (``player-assess-*``), ``council`` (``council-v*``) and ``escalation``, its calls to
                  Opus (``council-opus-*``)
    research      the web: ``search`` (Exa, ``web_search``) and ``extraction`` of what the searches found (``extract-*``)
    chronicles    the readers' chronicle when one of its calls is in this ledger (``user-narrative-*``). It writes its calls to
                  its own ledger (plan UX, A11), which only the readers name (``USER_LEDGER_SQL``): that one is reported beside the
                  paths and never added to their total
    rest          everything else, by family: ``learning`` (``learning-*``, ``patterns-*``), ``postmortem`` (``pick-postmortem-*``,
                  ``postmortem-*``, ``pmr-*``, ``la-*``), ``lab`` (the battery, the probes, the equivalence test) and ``other``

A path gives its calls (and how many did not end ``ok``), its cost and share, the matches its calls were about (``fixture_id``) and the
CANDIDATES its paid calls judged - the selections of the rows of ``ai.pick_reviews`` of its engines that hold the call's usage id (``llm``
for production, the three engines of the shadow for the deliberation) - with the cost per match and per candidate and their n. A part
without candidates (the brief, a search) has no cost per candidate. Each part also gives its models.

OPUS BY RULE. Every call to Opus with the rule the code recorded for it, and where (``opus_rule``):

    production    ``ai.pick_reviews.output`` of the ``llm`` review that holds the call: ``tier = final`` and the cycle's ``role`` - ``pick`` (the
                  selection is a pick of the day or a leg of a parlay: ``L3_pick``), ``contradiction`` (the rules and the intermediate model
                  contradict each other outright, live or after a Batch: ``L3_contradiction``) or ``candidate`` (the brief saw a material change,
                  a contradiction or important news, and the selection is the match's best: ``L3_material``)
    deliberation  ``ai.agent_tasks.route`` of the task that asked it (``router-v1``): ``action = CALL`` and the escalation E1-E7 that fired
    rest          ``ai.batch_items.context`` of the LAB's item: the adversarial battery's base (``lab_battery``) - a test of the prompt, not a
                  decision

A call to Opus with none of those is ``unregistered`` and counted, with its cost and its ids: the gate of INT-T01 is that there is none.

BATCH AND CACHE, per path and part, as the ledger keeps them: the calls answered in a batch (``batch_id``), the input tokens read from the
cache (``cached_tokens``) and written to it, the calls that read it, and what the cache and the Batch saved: each call priced again with the verified
price table (``fbi.ai.pricing``) as if every input token had been fresh and the call made in real time. Call by call, never over a sum of calls: a
price that depends on the size of ONE prompt (Haiku's above 100k input tokens) applied to a sum would invent a saving. And, for the review of production,
the calls made in real time that the plan's table lets wait (``could_wait``: a candidate's or a pick's review with four hours or more to the
kick-off, ``fbi.ai.batch``) - half their cost is what the Batch would have saved if its gate is on for the model.

THE TOTAL. The paths add up to the ledger's own sum of the window, read by a statement of its own in the same snapshot (``ledger``): the report
says the difference, to the millionth of a dollar, and whether it is under a cent (``reconciles``).

It INFORMS and decides nothing (``"decides": False``): it changes no route, no model, no switch and no threshold. Pure: no database, no clock
(the readers are ``fbi.ai.cost_paths_readers``)."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Final

from fbi.ai.batch import BATCH_ROLES
from fbi.ai.pricing import price_of, token_cost
from fbi.ai.router import ESCALATIONS

VERSION: Final = "cost-paths-v1"
PATHS: Final[tuple[str, ...]] = ("production", "deliberation", "research", "chronicles", "rest")
PARTS: Final[dict[str, tuple[str, ...]]] = {
    "production": ("review", "brief"),
    "deliberation": ("match_agent", "stats_agent", "player_agent", "council", "escalation"),
    "research": ("search", "extraction"),
    "chronicles": ("chronicle",),
    "rest": ("learning", "postmortem", "lab", "other"),
}
PROMPTS: Final[tuple[tuple[str, str, str], ...]] = (
    ("review-", "production", "review"),
    ("brief-", "production", "brief"),
    ("match-context-", "deliberation", "match_agent"),
    ("match-assess-", "deliberation", "match_agent"),
    ("stats-assess-", "deliberation", "stats_agent"),
    ("player-assess-", "deliberation", "player_agent"),
    ("council-opus-", "deliberation", "escalation"),
    ("council-", "deliberation", "council"),
    ("extract-", "research", "extraction"),
    ("user-narrative-", "chronicles", "chronicle"),
    ("learning-", "rest", "learning"),
    ("patterns-", "rest", "learning"),
    ("pick-postmortem-", "rest", "postmortem"),
    ("postmortem-", "rest", "postmortem"),
    ("pmr-", "rest", "postmortem"),
    ("la-", "rest", "postmortem"),
    ("battery-", "rest", "lab"),
    ("probe-", "rest", "lab"),
    ("equiv-", "rest", "lab"),
)
"""The prompt's prefix, its path and its part, the first that matches. ``council-opus-`` comes before ``council-``. A row without a prompt is read
by its purpose (``path_of``)."""
PRODUCTION_ENGINES: Final[tuple[str, ...]] = ("llm",)
SHADOW_ENGINES: Final[tuple[str, ...]] = ("ma-v1", "ma-v1-h", "cs-v1")
"""Whose ``ai.pick_reviews`` rows name the candidates of each path (``fbi.ai.cost_paths_readers`` reads them in two statements)."""
L3_RULES: Final[dict[str, str]] = {"pick": "L3_pick", "contradiction": "L3_contradiction", "candidate": "L3_material"}
"""The cycle's three ways to the strong model of production (``fbi.ai.cycle``), by the ``role`` it records with ``tier = final``."""
BATCH_LEAD_MINUTES: Final = 240
"""The plan's table (``fbi.ai.batch``): a review can wait for a batch with four hours or more to the kick-off (``FBI_AI_BATCH_MIN_LEAD_MINUTES``)."""
CENT: Final = Decimal("0.01")
MICRO: Final = Decimal("0.000001")


def _usd(x: Decimal) -> str:
    return str(x.quantize(CENT, rounding=ROUND_HALF_UP))


def _exact(x: Decimal) -> str:
    return str(x.quantize(MICRO, rounding=ROUND_HALF_UP))


def _per(x: Decimal, n: int) -> str | None:
    return None if n <= 0 else str((x / n).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _pct(part: Decimal | int, whole: Decimal | int) -> str | None:
    if not whole:
        return None
    return str((Decimal(100) * Decimal(part) / Decimal(whole)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# -- the rows -----------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Call:
    """One row of ``ai.usage``: what was asked of whom, about which match, how it ended and what it cost."""

    id: int
    at: datetime
    purpose: str
    tier: str
    provider: str
    model: str
    prompt_version: str | None
    status: str
    cost: Decimal
    fixture_id: int | None = None
    kickoff_at: datetime | None = None
    batch: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    cache_write_1h_tokens: int = 0
    agent: str | None = None
    workspace: str | None = None

    @property
    def opus(self) -> bool:
        return "opus" in self.model

    @property
    def tokens(self) -> bool:
        return self.input_tokens > 0 or self.output_tokens > 0

    @property
    def lead_minutes(self) -> float | None:
        """How long before the kick-off the call was made (negative after it), or None without a match."""
        return None if self.kickoff_at is None else (self.kickoff_at - self.at).total_seconds() / 60


@dataclass(frozen=True, slots=True)
class Link:
    """A review row of ``ai.pick_reviews`` that holds a call's usage id: the selection the call judged and, for production, the role and the tier
    the cycle recorded with it."""

    usage_id: int
    engine: str
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    role: str | None = None
    tier: str | None = None

    @property
    def key(self) -> tuple[int, str, str, str]:
        return (self.fixture_id, self.market_key, self.selection, str(self.line.normalize()) if self.line != 0 else "0")


@dataclass(frozen=True, slots=True)
class Route:
    """The routing the orchestrator recorded for the shadow's task that made a call (``ai.agent_tasks.route``, ``router-v1``)."""

    usage_id: int
    task_kind: str | None
    action: str | None
    escalation: str | None
    fired: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LabItem:
    """What the LAB recorded of a batch item that made a call (``ai.batch_items.context``)."""

    usage_id: int
    lab: str | None
    target: str | None = None
    base: str | None = None
    experiment: str | None = None


@dataclass(frozen=True, slots=True)
class Ledger:
    """The ledger's own count and sum of the window, read apart from the rows (the check of the total)."""

    calls: int
    usd: Decimal


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    registered: bool
    where: str


# -- the classification -------------------------------------------------------------------------------------------------------------

def path_of(c: Call) -> tuple[str, str]:
    """The path and the part of a call: by its prompt's prefix (``PROMPTS``), else by its purpose, else ``rest.other``."""
    prompt = c.prompt_version or ""
    for prefix, path, part in PROMPTS:
        if prompt.startswith(prefix):
            return path, part
    if c.purpose == "web_search" or c.tier == "search":
        return "research", "search"
    if c.purpose == "evidence_extraction":
        return "research", "extraction"
    if c.purpose == "match_brief":
        return "production", "brief"
    if c.agent in ("match", "stats", "player", "council"):
        part = {"match": "match_agent", "stats": "stats_agent", "player": "player_agent", "council": "council"}[c.agent]
        return "deliberation", "escalation" if part == "council" and c.opus else part
    if c.purpose in ("learning", "pattern_review"):
        return "rest", "learning"
    if c.purpose == "postmortem":
        return "rest", "postmortem"
    return "rest", "other"


def opus_rule(c: Call, path: str, link: Link | None, route: Route | None, item: LabItem | None) -> Rule:
    """The rule the code recorded for a call to Opus, and where - or ``unregistered`` when there is none."""
    if path == "production":
        if link is not None and link.tier == "final" and link.role in L3_RULES:
            return Rule(L3_RULES[link.role], True, "ai.pick_reviews.output")
        return Rule("unregistered", False, "ai.pick_reviews.output" if link is not None else "-")
    if path == "deliberation":
        if route is not None and route.action == "CALL" and route.escalation in ESCALATIONS:
            return Rule(str(route.escalation), True, "ai.agent_tasks.route")
        return Rule("unregistered", False, "ai.agent_tasks.route" if route is not None else "-")
    if item is not None and item.lab == "battery":
        return Rule("lab_battery", True, "ai.batch_items.context")
    if item is not None and (item.lab or item.experiment):
        return Rule(f"lab_{item.lab or 'experiment'}", True, "ai.batch_items.context")
    return Rule("unregistered", False, "-")


def could_wait(c: Call, link: Link | None) -> bool:
    """A review of production made in real time that the plan's table lets wait for a batch: a candidate's or a pick's, four hours or more before
    the kick-off. Whether it would have gone depends also on the owner's switch and the ``batch`` gate of the model (``BatchQueue.routes``)."""
    lead = c.lead_minutes
    return (not c.batch and c.status == "ok" and link is not None and link.role in BATCH_ROLES and lead is not None
            and lead >= BATCH_LEAD_MINUTES)


# -- the sums -------------------------------------------------------------------------------------------------------------------------

@dataclass
class _Tally:
    calls: int = 0
    not_ok: int = 0
    usd: Decimal = Decimal(0)
    fixtures: set[int] = field(default_factory=set)
    without_fixture: int = 0
    candidates: set[tuple[int, str, str, str]] = field(default_factory=set)
    linked: int = 0
    batch_calls: int = 0
    batch_usd: Decimal = Decimal(0)
    model_calls: int = 0
    reading_cache: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    write_tokens: int = 0
    cache_saved: Decimal = Decimal(0)
    batch_saved: Decimal = Decimal(0)
    unpriced: int = 0
    models: Counter[str] = field(default_factory=Counter)
    models_usd: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    could_wait: Counter[str] = field(default_factory=Counter)
    could_wait_usd: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))

    def add(self, c: Call, links: Sequence[Link], *, waits: bool) -> None:
        self.calls += 1
        self.not_ok += c.status != "ok"
        self.usd += c.cost
        if c.fixture_id is None:
            self.without_fixture += 1
        else:
            self.fixtures.add(c.fixture_id)
        self.candidates.update(link.key for link in links)
        self.linked += bool(links)
        if c.batch:
            self.batch_calls += 1
            self.batch_usd += c.cost
        self.models[c.model] += 1
        self.models_usd[c.model] += c.cost
        if waits:
            self.could_wait[c.model] += 1
            self.could_wait_usd[c.model] += c.cost
        if not c.tokens or c.tier == "search":
            return
        self.model_calls += 1
        self.reading_cache += c.cached_tokens > 0
        self.input_tokens += c.input_tokens
        self.cached_tokens += c.cached_tokens
        self.write_tokens += c.cache_write_tokens
        if not price_of(c.provider, c.model)[1]:
            self.unpriced += 1  # an unknown model's price is a guess: no saving is claimed for it
            return
        # call by call: a price that changes with the size of ONE prompt (Haiku's above 100k tokens) is never applied to a sum of prompts
        fresh = token_cost(c.provider, c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, batch=c.batch, at=c.at)
        self.cache_saved += fresh - c.cost
        if c.batch:
            self.batch_saved += token_cost(c.provider, c.model, input_tokens=c.input_tokens, output_tokens=c.output_tokens, at=c.at) - fresh

    def as_json(self, total: Decimal) -> dict[str, Any]:
        n_fx, n_cand = len(self.fixtures), len(self.candidates)
        waited = sum(self.could_wait_usd.values(), Decimal(0))
        return {
            "calls": self.calls, "not_ok": self.not_ok, "usd": _usd(self.usd), "usd_exact": _exact(self.usd), "share_pct": _pct(self.usd, total),
            "fixtures": n_fx, "calls_without_fixture": self.without_fixture, "usd_per_fixture": _per(self.usd, n_fx),
            "candidates": n_cand, "usd_per_candidate": _per(self.usd, n_cand), "calls_linked_to_a_review": self.linked,
            "batch": {"calls": self.batch_calls, "usd": _usd(self.batch_usd), "share_of_calls_pct": _pct(self.batch_calls, self.calls)},
            "cache": {"model_calls": self.model_calls, "calls_reading_cache": self.reading_cache,
                      "calls_reading_cache_pct": _pct(self.reading_cache, self.model_calls), "input_tokens": self.input_tokens,
                      "cached_tokens": self.cached_tokens, "read_share_pct": _pct(self.cached_tokens, self.input_tokens),
                      "write_tokens": self.write_tokens},
            "saved": {"cache_usd": _usd(self.cache_saved), "batch_usd": _usd(self.batch_saved), "calls_unpriced": self.unpriced},
            "could_wait": {"calls": sum(self.could_wait.values()), "usd": _usd(waited), "half_usd": _usd(waited / 2),
                           "models": [{"model": m, "calls": n, "usd": _usd(self.could_wait_usd[m])} for m, n in sorted(self.could_wait.items())]},
            "models": [{"model": m, "calls": n, "usd": _usd(self.models_usd[m])} for m, n in
                       sorted(self.models.items(), key=lambda kv: (-self.models_usd[kv[0]], kv[0]))],
        }


def _index(links: Iterable[Link], engines: Sequence[str]) -> dict[int, list[Link]]:
    out: dict[int, list[Link]] = defaultdict(list)
    for link in links:
        if link.engine in engines:
            out[link.usage_id].append(link)
    return dict(out)


def report(calls: Iterable[Call], links: Iterable[Link] = (), routes: Iterable[Route] = (), lab_items: Iterable[LabItem] = (), *,
           ledger: Ledger | None = None, user_ledger: Iterable[Mapping[str, Any]] = (), since: datetime | None = None,
           until: datetime | None = None) -> dict[str, Any]:
    """The whole report, as JSON: the total and its check against the ledger, each path and its parts, Opus by rule, and the readers' chronicle
    from its own ledger (beside the total, never in it)."""
    rows = sorted(calls, key=lambda c: c.id)
    all_links = list(links)
    prod_links, shadow_links = _index(all_links, PRODUCTION_ENGINES), _index(all_links, SHADOW_ENGINES)
    by_route = {r.usage_id: r for r in routes}
    by_item = {i.usage_id: i for i in lab_items}
    total = sum((c.cost for c in rows), Decimal(0))
    paths: dict[str, _Tally] = {p: _Tally() for p in PATHS}
    parts: dict[str, dict[str, _Tally]] = {p: {q: _Tally() for q in PARTS[p]} for p in PATHS}
    opus_n: Counter[tuple[str, str, str, bool]] = Counter()
    opus_usd: dict[tuple[str, str, str, bool], Decimal] = defaultdict(Decimal)
    unregistered: list[int] = []
    for c in rows:
        path, part = path_of(c)
        mine = prod_links.get(c.id, []) if path == "production" else shadow_links.get(c.id, []) if path == "deliberation" else []
        first = mine[0] if mine else None
        waits = path == "production" and part == "review" and could_wait(c, first)
        paths[path].add(c, mine, waits=waits)
        parts[path][part].add(c, mine, waits=waits)
        if c.opus:
            rule = opus_rule(c, path, first if path == "production" else None, by_route.get(c.id), by_item.get(c.id))
            slot = (path, rule.code, rule.where, rule.registered)
            opus_n[slot] += 1
            opus_usd[slot] += c.cost
            if not rule.registered:
                unregistered.append(c.id)
    unreg = [k for k in opus_n if not k[3]]
    unreg_n = sum(opus_n[k] for k in unreg)
    user_rows = [dict(r) for r in user_ledger]
    user_usd = sum((Decimal(str(r.get("usd") or 0)) for r in user_rows), Decimal(0))
    diff = None if ledger is None else ledger.usd - total
    return {
        "version": VERSION, "decides": False, "since": None if since is None else since.isoformat(),
        "until": None if until is None else until.isoformat(),
        "total": {"calls": len(rows), "usd": _usd(total), "usd_exact": _exact(total),
                  "ledger_calls": None if ledger is None else ledger.calls,
                  "ledger_usd_exact": None if ledger is None else _exact(ledger.usd),
                  "difference_usd": None if diff is None else _exact(diff),
                  "reconciles": None if ledger is None or diff is None else (abs(diff) < CENT and ledger.calls == len(rows))},
        "paths": {p: paths[p].as_json(total) | {"parts": {q: parts[p][q].as_json(total) for q in PARTS[p]}} for p in PATHS},
        "opus": {"calls": sum(opus_n.values()), "usd": _usd(sum(opus_usd.values(), Decimal(0))),
                 "registered": sum(opus_n.values()) - unreg_n, "unregistered": unreg_n,
                 "unregistered_usd": _usd(sum((opus_usd[k] for k in unreg), Decimal(0))), "all_registered": unreg_n == 0,
                 "unregistered_ids": unregistered[:50],
                 "by_rule": [{"path": k[0], "rule": k[1], "where": k[2], "registered": k[3], "calls": opus_n[k], "usd": _usd(opus_usd[k])}
                             for k in sorted(opus_n, key=lambda k: (PATHS.index(k[0]), -opus_n[k], k[1]))]},
        "chronicles_user_ledger": {"calls": sum(int(r.get("calls") or 0) for r in user_rows), "usd": _usd(user_usd),
                                   "in_total": False,
                                   "lines": [{"prompt_version": r.get("prompt_version"), "model": r.get("model"), "calls": int(r.get("calls") or 0),
                                              "usd": _usd(Decimal(str(r.get("usd") or 0)))} for r in user_rows]},
    }


# -- for a person -------------------------------------------------------------------------------------------------------------------

LABELS: Final[dict[str, str]] = {"production": "producción (review-v2 + brief-v8)", "deliberation": "deliberación en sombra",
                                 "research": "Research / Exa", "chronicles": "crónicas (en ai.usage)", "rest": "resto"}


def lines(rep: Mapping[str, Any]) -> list[str]:
    """The report for a person, in Spanish: the total and its check, a line per path and per part with its n, Opus by rule."""
    t = rep["total"]
    out = [f"Coste por camino {rep['version']} (informa, no decide) desde {rep.get('since') or '-'} hasta {rep.get('until') or '-'}",
           f"  Total ai.usage: US$ {t['usd']} en {t['calls']} llamadas · libro US$ {t['ledger_usd_exact'] or '-'} en {t['ledger_calls'] or '-'} "
           f"· diferencia {t['difference_usd'] or '-'} · cuadra: {'sí' if t['reconciles'] else 'NO' if t['reconciles'] is False else '-'}"]
    for name, p in rep["paths"].items():
        out.append(f"  {LABELS.get(name, name)}: US$ {p['usd']} ({p['share_pct'] or '0'} %), {p['calls']} llamadas, "
                   f"{p['fixtures']} partidos (US$ {p['usd_per_fixture'] or '-'} c/u), {p['candidates']} candidatos "
                   f"(US$ {p['usd_per_candidate'] or '-'} c/u), Batch {p['batch']['calls']} llamadas, caché leída {p['cache']['read_share_pct'] or '-'} %")
        for part, q in p["parts"].items():
            if q["calls"]:
                models = ", ".join(f"{m['model']} {m['calls']} (US$ {m['usd']})" for m in q["models"][:3])
                out.append(f"      {part}: US$ {q['usd']} en {q['calls']} llamadas · {q['fixtures']} partidos · {q['candidates']} candidatos · "
                           f"Batch {q['batch']['calls']} · {models}")
    o = rep["opus"]
    out.append(f"  Opus: {o['calls']} llamadas, US$ {o['usd']}; con regla registrada {o['registered']}, sin regla {o['unregistered']} "
               f"(US$ {o['unregistered_usd']})")
    for r in o["by_rule"]:
        out.append(f"      {r['path']} · {r['rule']} ({r['where']}): {r['calls']} llamadas, US$ {r['usd']}")
    u = rep["chronicles_user_ledger"]
    out.append(f"  Crónicas de lectores (su propio libro de gasto, fuera del total): US$ {u['usd']} en {u['calls']} llamadas")
    return out


__all__ = ["PATHS", "VERSION", "Call", "LabItem", "Ledger", "Link", "Route", "Rule", "could_wait", "lines", "opus_rule", "path_of", "report"]
