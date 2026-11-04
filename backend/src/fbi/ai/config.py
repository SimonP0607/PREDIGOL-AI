"""The AI layer's settings - from the environment (the process, over the ``.env`` file: ``fbi.core.env``), never
from a request, never sent to a client.

    FBI_AI_MODE                 off | shadow (default) | enforce
                                shadow: every decision is recorded and shown to the owner, users see nothing
                                new. enforce: decisions filter what users see - and only once the AI's own
                                shadow gate has passed (``fbi.ai.shadow``); until then enforce behaves as shadow.
    FBI_AI_MODEL_BULK           provider:model for extraction and classification (cheap)
    FBI_AI_MODEL_ANALYSIS       provider:model for candidate reviews
    FBI_AI_MODEL_FINAL          provider:model for the best opportunities only (strong)
    FBI_AI_KEY_<PROVIDER>       the provider's API key (ANTHROPIC, OPENAI, GEMINI, MISTRAL, DEEPSEEK, TOGETHER,
                                GROQ, DEEPINFRA); FBI_ANALYST_API_KEY still counts for Anthropic
    FBI_AI_BASE_URL_<PROVIDER>  another endpoint for that provider (a proxy, a regional endpoint)
    FBI_AI_MONTHLY_BUDGET_USD   default FBI_ANALYST_MONTHLY_BUDGET_USD or 20 - the month's HARD cap for the whole
                                AI layer (the owner's machine: 150). With budget v3 on (Plan Maestro IA, section 26) it
                                is PRODUCTION's own envelope - Claude only, US$185 - and Exa and the LAB have theirs
    FBI_AI_LAB_MONTHLY_BUDGET_USD   default 0 (no LAB call is made) - the LAB workspace's internal envelope:
                                15 in phases 0-2, 55 in phases 3-8, 15 from phase 9
    FBI_AI_EXA_MONTHLY_BUDGET_USD   default 35 - Exa's own envelope, outside Claude's
    FBI_AI_JOINT_CEILING_USD    default 190 - production + LAB never plan to spend more than this together
    FBI_AI_RESERVE_USD          default 10 - kept for production only; released in the last 5 days of the month
    FBI_AI_KEY_ANTHROPIC_LAB    the LAB workspace's key (``worker-lab``); the production key stays FBI_AI_KEY_ANTHROPIC
    FBI_AI_WORKSPACE / FBI_AI_WORKSPACE_LAB / FBI_AI_KEY_LABEL / FBI_AI_KEY_LABEL_LAB
                                the NAMES the ledger records for each call (PREDIGOL, PREDIGOL-LAB, worker-prod,
                                worker-lab): labels only, never a key
    FBI_AI_DAILY_TARGET_USD     the day's SOFT target (FBI_AI_DAILY_BUDGET_USD is the older name); default the
                                monthly budget / 30. The day's real budget adapts to it (``fbi.ai.usage``): the pace
                                left in the month times the day's load, at most FBI_AI_DAILY_MAX_FACTOR times it
    FBI_AI_DAILY_MAX_FACTOR     default 2 - how much an important day may spend over the target
    FBI_AI_MAX_LLM_REVIEWS_PER_DAY  default 60 (a safety cap: the budget decides first)
    FBI_AI_MAX_DEEP_PER_DAY     default 10 (final-tier reviews)
    FBI_AI_MAX_WEB_FIRST        default 20 - matches searched on the web in the first pass of the day
    FBI_AI_MAX_WEB_PRE          default 12 - matches searched again before kick-off (only escalated ones)
    FBI_AI_MAX_WATCH_PER_DAY    default 8 - intermediate reviews of escalated matches without a candidate
    FBI_AI_MULTIMODAL           off (default) | on - images only for selected matches, each one logged
    FBI_AI_HORIZON_HOURS        default 96 - how far ahead the free part (packets, rules, analyses) looks
    FBI_AI_SEARCH               exa | brave | tavily | none (default exa when EXA_API_KEY is set, else none)

Phase 0 of the Plan Maestro IA (each switch: ``off`` = rolled back, ``on`` = forced, ``auto`` (default) = on once its
own evidence allows it - ``fbi.ai.gates``). To go back: set the switch to 0 and restart the worker (about a minute):

    FBI_AI_CACHE                prompt caching: the system block is cached (1 h); the match block too once the
                                ``cache_layout`` gate has passed
    FBI_AI_BATCH                the Message Batches API (half price) for what can wait: needs the ``batch`` gate
    FBI_AI_NATIVE_SCHEMA        structured outputs (``output_config.format``) instead of a forced tool call: needs the
                                ``native_schema`` gate (a stability test on stored packets)
    FBI_AI_BRIEF_MATERIAL       the brief is paid again only for a MATERIAL change (section 19 of the plan)
    FBI_AI_BUDGET_V3            the adaptive budget v3 of section 26 (projection, scopes, AJUSTE, API limit errors)
    FBI_AI_BATCH_MIN_LEAD_MINUTES   default 240 - a task goes to Batch only with this many minutes before kick-off

Phase 2 of the plan - the research of an entity (``fbi.ai.entity_research``):

    FBI_AI_RESEARCH_V2          off (default) | shadow | on. off: the cycle does not know it. shadow: it runs after v1's research in the same
                                pass and writes typed evidence that no packet shows (the week of comparison; v1 goes on deciding). on: it
                                REPLACES v1's research and the packet shows what it wrote - and only once the ``research_v2`` gate has passed
                                (``fbi.ai.gates.research_mode``); until then ``on`` behaves as ``shadow``. Any other word is ``off``. To go
                                back: set it to ``off`` (or ``shadow``) and restart the worker (about a minute).

Phase 3 of the plan - the multi-agent engines in SHADOW (``fbi.ai.arms``): they run in the LAB workspace only, write rows no user and no decision
reads, and are rolled back by the same three words. Nothing runs until ALL THREE say so (``AiSettings.orchestrate``):

    FBI_AI_ENGINES              default ``rules,llm`` - the engines that review, separated by commas, in any case. ``rules`` and ``llm`` are always
                                there (the production baseline: ``FBI_AI_MODE`` governs them); the list can only ADD shadow engines: ``ma-v1`` (the
                                multi-agent), ``ma-v1-h`` (the same with the Haiku judge) and ``cs-v1`` (COUNCIL SOLO: Sonnet reading the compact
                                view, no specialists). A name that is none of those - a typo - is dropped: it switches nothing on. The plan's
                                activation is ``rules,llm,ma-v1,ma-v1-h``; its rollback is ``rules,llm``.
    FBI_AI_SHADOW_SAMPLE        default 0 - the share of the matches with candidates the shadow runs on, from 0 to 1 (0.3 = 30 %; above 1 counts
                                as 1, below 0 as 0, and a word that is not a number as 0). Each match is assigned once, before its first shadow
                                pass, and never changes group (``ai.shadow_assignments``). The plan's activation is ``0.3``; its rollback is ``0``.
    FBI_AI_AGENTS               default empty - the agents that may run: ``match``, ``council`` and (phase 4) ``stats`` (a name that is none of those is
                                dropped). The plan's activation is ``match,council``, and ``match,council,stats`` adds the Statistics Agent; its
                                rollback is to take ``stats`` out. ``stats`` alone switches nothing on: the orchestrator needs ``match`` and ``council``.

Phase 5 of the plan - after the result (the Post-Match Reviewer ``pmr-v1`` and the Learning Analyst ``la-v1``). Both are OFF by default, both write only
into tables no pick, filter, decision or user reads, and both go back with a single word:

    FBI_AI_PM_REVIEWER          default off - ``1``/``on``/``true``/``yes`` switches on, in the daily step ``ai_learn`` (07:35 Bogota), the MECHANICAL
                                attribution of the shadow (``intel.agent_attributions``, no model) and the Post-Match Reviewer's classification of the
                                rows the code left ``UNKNOWN`` (Batch, LAB). Any other word - a typo - is off. Rollback: ``0``.
    FBI_AI_LEARNING_ANALYST     default off - the same words switch on, in the weekly step ``intel_weekly`` (Monday), the Learning Analyst: at most five
                                hypotheses a week, each for one agent version and citing attributions (Batch, LAB); it only proposes. Rollback: ``0``.

A model or a search is used only for TODAY's matches (America/Bogota) that have a market (``fbi.ai.day``).

No tier configured = the layer runs its deterministic reviewer only and says so (``status()``). A tier is
switched on only by its own FBI_AI_MODEL_* variable: the earlier analyst's FBI_ANALYST_MODEL never turns the
decision layer's model calls on by itself (its key still counts once a tier names Anthropic).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal

from fbi.core.env import environment

Mode = Literal["off", "shadow", "enforce"]
Tier = Literal["bulk", "analysis", "final"]
TIERS: tuple[Tier, ...] = ("bulk", "analysis", "final")
Switch = Literal["off", "on", "auto"]
ResearchMode = Literal["off", "shadow", "on"]
SWITCH_ENV: dict[str, str] = {"cache": "FBI_AI_CACHE", "batch": "FBI_AI_BATCH", "native_schema": "FBI_AI_NATIVE_SCHEMA",
                              "brief_material": "FBI_AI_BRIEF_MATERIAL", "budget_v3": "FBI_AI_BUDGET_V3"}
"""The five optimisations of Phase 0 and the variable that rolls each one back."""
PROVIDERS = ("anthropic", "openai", "gemini", "mistral", "deepseek", "together", "groq", "deepinfra")

KNOWN_ENGINES: Final[tuple[str, ...]] = ("rules", "llm", "ma-v1", "ma-v1-h", "cs-v1")
"""The engines the owner can name in ``FBI_AI_ENGINES``, in the one canonical order (phase 3). ``combined`` is not a choice: it is what the production
engines add up to (``fbi.ai.review.combine``). ``cs-v1`` is the COUNCIL SOLO arm (Sonnet reading the compact view, no specialists)."""
BASELINE_ENGINES: Final[tuple[str, ...]] = ("rules", "llm")
"""The production baseline: always on whatever ``FBI_AI_ENGINES`` says (``FBI_AI_MODE`` governs them)."""
SHADOW_ENGINES: Final[tuple[str, ...]] = tuple(e for e in KNOWN_ENGINES if e not in BASELINE_ENGINES)
"""The engines that only ever run in shadow (``ma-v1``, ``ma-v1-h``, ``cs-v1``): rows nobody reads for a decision (filter 6 never sees them)."""
PRODUCTION_ENGINES: Final[tuple[str, ...]] = (*BASELINE_ENGINES, "combined")
"""The engines whose rows every figure of production counts: the two of the baseline and what they add up to. Every reader of ``ai.pick_reviews`` that
does not name its engine filters on exactly this list (``engine IN ('rules', 'llm', 'combined')``): a shadow row added to the table moves no figure of
production (``tests/unit/test_engine_filter_guard.py`` keeps every reader in line with it)."""
AGENTS: Final[tuple[str, ...]] = ("match", "council", "stats")
"""The agents ``FBI_AI_AGENTS`` can name, in canonical order (phase 4 added ``stats``: the one place the list is kept)."""
ORCHESTRATOR_AGENTS: Final[tuple[str, ...]] = ("match", "council")
"""The agents the orchestrator needs to run at all (a multi-agent without its Match Agent or its Council is not one)."""

BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "mistral": "https://api.mistral.ai/v1",
    "deepseek": "https://api.deepseek.com",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepinfra": "https://api.deepinfra.com/v1/openai",
}


@dataclass(frozen=True, slots=True)
class TierModel:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def _tier_model(raw: str | None) -> TierModel | None:
    if not raw or ":" not in raw:
        return None
    provider, model = raw.split(":", 1)
    provider, model = provider.strip().lower(), model.strip()
    if provider not in PROVIDERS or not model:
        return None
    return TierModel(provider, model)


def _decimal(name: str, default: str, env: Mapping[str, str]) -> Decimal:
    try:
        value = Decimal(env.get(name) or default)
    except InvalidOperation:
        value = Decimal(default)
    return max(Decimal(0), value)


def _int(name: str, default: int, env: Mapping[str, str]) -> int:
    try:
        return max(0, int(env.get(name) or default))
    except ValueError:
        return default


def _share(raw: str | None) -> Decimal:
    """``FBI_AI_SHADOW_SAMPLE``: a share from 0 to 1. Clamped; a word that is not a number - or not a finite one - is 0, so a typo costs nothing."""
    try:
        value = Decimal((raw or "").strip() or "0")
    except InvalidOperation:
        return Decimal(0)
    if not value.is_finite():
        return Decimal(0)
    return min(Decimal(1), max(Decimal(0), value))


def _names(raw: str | None, known: tuple[str, ...]) -> frozenset[str]:
    """The known names a comma-separated word lists, whatever the case or the spaces; anything else is dropped."""
    return frozenset(part.strip().lower() for part in (raw or "").split(",")) & frozenset(known)


def _engines(raw: str | None) -> tuple[str, ...]:
    """``FBI_AI_ENGINES``: the baseline (``rules``, ``llm``) always, plus the shadow engines the list names, in the canonical order."""
    asked = _names(raw, SHADOW_ENGINES)
    return tuple(e for e in KNOWN_ENGINES if e in BASELINE_ENGINES or e in asked)


def _agents(raw: str | None) -> tuple[str, ...]:
    """``FBI_AI_AGENTS``: the known agents the list names, in the canonical order; none by default."""
    asked = _names(raw, AGENTS)
    return tuple(a for a in AGENTS if a in asked)


def _on(raw: str | None) -> bool:
    """A word that is on only when it says so (``1``, ``on``, ``true``, ``yes``): a typo or an empty word is off, so nothing starts by accident."""
    return (raw or "").strip().lower() in ("1", "on", "true", "yes")


def _switch(raw: str | None) -> Switch:
    value = (raw or "").strip().lower()
    if value in ("0", "off", "false", "no"):
        return "off"
    if value in ("1", "on", "true", "yes"):
        return "on"
    return "auto"


def _research_mode(raw: str | None) -> ResearchMode:
    """``FBI_AI_RESEARCH_V2``: only the words ``shadow`` and ``on`` switch research v2 on - ``1``, ``true`` or a typo are ``off``, so nothing
    reaches the packet by accident."""
    value = (raw or "").strip().lower()
    return "shadow" if value == "shadow" else "on" if value == "on" else "off"


def _all_auto() -> dict[str, Switch]:
    return dict.fromkeys(SWITCH_ENV, "auto")


@dataclass(frozen=True)
class AiSettings:
    mode: Mode = "shadow"
    tiers: dict[str, TierModel | None] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict, repr=False)
    base_urls: dict[str, str] = field(default_factory=dict)
    daily_budget: Decimal = Decimal("1.00")
    """The day's soft target (the adaptive budget is built around it, ``fbi.ai.usage.budget``)."""
    monthly_budget: Decimal = Decimal("20")
    max_llm_reviews_per_day: int = 60
    max_deep_per_day: int = 10
    daily_max_factor: Decimal = Decimal("2")
    max_web_first: int = 20
    max_web_pre: int = 12
    max_watch_per_day: int = 8
    multimodal: bool = False
    horizon_hours: int = 96
    search: str | None = None
    legacy_postmortems: bool = False
    """The two first post-mortems (``fbi.ai.postmortem`` by match, ``fbi.ai.pick_postmortem`` by selection) write again, beside the
    one post-mortem of ``fbi.intel.postmortem`` (plan F8). Off: they are frozen - their tables keep what they wrote, nothing reads them
    for what is new. It exists to go back, not to be used (``FBI_AI_LEGACY_POSTMORTEMS=1``)."""
    switches: dict[str, Switch] = field(default_factory=_all_auto)
    """Phase 0's five optimisations (``SWITCH_ENV``): off = rolled back, on = forced, auto = once its evidence allows."""
    lab_keys: dict[str, str] = field(default_factory=dict, repr=False)
    """The LAB workspace's key per provider (``FBI_AI_KEY_ANTHROPIC_LAB``): experiments never spend production's key."""
    workspace: str = "PREDIGOL"
    workspace_lab: str = "PREDIGOL-LAB"
    key_label: str = "worker-prod"
    key_label_lab: str = "worker-lab"
    lab_monthly_budget: Decimal = Decimal(0)
    """The LAB's internal envelope (15 / 55 / 15 by phase). Zero: no LAB call is made."""
    exa_monthly_budget: Decimal = Decimal("35")
    joint_ceiling: Decimal = Decimal("190")
    """Production + LAB, never planned above it."""
    reserve: Decimal = Decimal("10")
    """Kept for production only (released in the last five days of the month)."""
    batch_min_lead_minutes: int = 240
    package: bool = True
    """Plan IA, phase 1: the state of each match is written from the passes already run (``fbi.ai.match_runs``; no model, no cost, and nothing reads it
    yet). ``FBI_AI_PACKAGE=0`` stops the job - it is the phase's rollback."""
    research_v2: ResearchMode = "off"
    """Plan IA, phase 2: what the owner asked of the research of an entity (``FBI_AI_RESEARCH_V2``). What the cycle does is ``gates.research_mode``:
    ``on`` is ``shadow`` until the ``research_v2`` gate has passed."""
    engines: tuple[str, ...] = BASELINE_ENGINES
    """Plan IA, phase 3: the engines that review (``FBI_AI_ENGINES``), in the canonical order of ``KNOWN_ENGINES``: ``rules`` and ``llm`` always, and the
    shadow engines the owner named. The list only adds: it cannot take the baseline away."""
    shadow_sample: Decimal = Decimal(0)
    """Plan IA, phase 3: the share (0 to 1) of the matches with candidates the shadow runs on (``FBI_AI_SHADOW_SAMPLE``). Zero: no match is assigned."""
    agents: tuple[str, ...] = ()
    """Plan IA, phase 3: the agents that may run (``FBI_AI_AGENTS``), in the canonical order of ``AGENTS``."""
    pm_reviewer: bool = False
    """Plan IA, phase 5: the attribution of the shadow and the Post-Match Reviewer (``FBI_AI_PM_REVIEWER``). Off unless the word says ``on``."""
    learning_analyst: bool = False
    """Plan IA, phase 5: the Learning Analyst (``FBI_AI_LEARNING_ANALYST``). Off unless the word says ``on``."""

    @classmethod
    def from_env(cls) -> AiSettings:
        env = environment()
        raw_mode = (env.get("FBI_AI_MODE") or "shadow").strip().lower()
        mode: Mode = raw_mode if raw_mode in ("off", "shadow", "enforce") else "shadow"  # type: ignore[assignment]
        keys = {p: v for p in PROVIDERS if (v := env.get(f"FBI_AI_KEY_{p.upper()}") or "")}
        if "anthropic" not in keys and env.get("FBI_ANALYST_API_KEY"):
            keys["anthropic"] = env["FBI_ANALYST_API_KEY"]
        tiers: dict[str, TierModel | None] = {t: _tier_model(env.get(f"FBI_AI_MODEL_{t.upper()}"))
                                             for t in TIERS}
        base_urls = {p: (env.get(f"FBI_AI_BASE_URL_{p.upper()}") or BASE_URLS[p]).rstrip("/")
                     for p in PROVIDERS}
        if env.get("FBI_ANALYST_BASE_URL") and not env.get("FBI_AI_BASE_URL_ANTHROPIC"):
            base_urls["anthropic"] = env["FBI_ANALYST_BASE_URL"].rstrip("/")
        search_raw = (env.get("FBI_AI_SEARCH") or "").strip().lower()
        if not search_raw:
            search_raw = "exa" if env.get("EXA_API_KEY") else "none"
        monthly_default = env.get("FBI_ANALYST_MONTHLY_BUDGET_USD") or "20"
        monthly = _decimal("FBI_AI_MONTHLY_BUDGET_USD", monthly_default, env)
        target_name = "FBI_AI_DAILY_TARGET_USD" if env.get("FBI_AI_DAILY_TARGET_USD") else "FBI_AI_DAILY_BUDGET_USD"
        target_default = str((monthly / 30).quantize(Decimal("0.01")))
        return cls(
            mode=mode, tiers=tiers, keys=keys, base_urls=base_urls,
            daily_budget=_decimal(target_name, target_default, env),
            monthly_budget=monthly,
            max_llm_reviews_per_day=_int("FBI_AI_MAX_LLM_REVIEWS_PER_DAY", 60, env),
            max_deep_per_day=_int("FBI_AI_MAX_DEEP_PER_DAY", 10, env),
            daily_max_factor=max(Decimal(1), _decimal("FBI_AI_DAILY_MAX_FACTOR", "2", env)),
            max_web_first=_int("FBI_AI_MAX_WEB_FIRST", 20, env),
            max_web_pre=_int("FBI_AI_MAX_WEB_PRE", 12, env),
            max_watch_per_day=_int("FBI_AI_MAX_WATCH_PER_DAY", 8, env),
            multimodal=(env.get("FBI_AI_MULTIMODAL") or "").strip().lower() in ("1", "on", "true", "yes"),
            horizon_hours=max(1, _int("FBI_AI_HORIZON_HOURS", 96, env)),
            search=None if search_raw in ("", "none", "off") else search_raw,
            legacy_postmortems=(env.get("FBI_AI_LEGACY_POSTMORTEMS") or "").strip().lower() in ("1", "on", "true", "yes"),
            switches={name: _switch(env.get(var)) for name, var in SWITCH_ENV.items()},
            lab_keys={p: v for p in PROVIDERS if (v := env.get(f"FBI_AI_KEY_{p.upper()}_LAB") or "")},
            workspace=(env.get("FBI_AI_WORKSPACE") or "PREDIGOL").strip()[:60],
            workspace_lab=(env.get("FBI_AI_WORKSPACE_LAB") or "PREDIGOL-LAB").strip()[:60],
            key_label=(env.get("FBI_AI_KEY_LABEL") or "worker-prod").strip()[:60],
            key_label_lab=(env.get("FBI_AI_KEY_LABEL_LAB") or "worker-lab").strip()[:60],
            lab_monthly_budget=_decimal("FBI_AI_LAB_MONTHLY_BUDGET_USD", "0", env),
            exa_monthly_budget=_decimal("FBI_AI_EXA_MONTHLY_BUDGET_USD", "35", env),
            joint_ceiling=_decimal("FBI_AI_JOINT_CEILING_USD", "190", env),
            reserve=_decimal("FBI_AI_RESERVE_USD", "10", env),
            batch_min_lead_minutes=max(30, _int("FBI_AI_BATCH_MIN_LEAD_MINUTES", 240, env)),
            package=(env.get("FBI_AI_PACKAGE") or "1").strip().lower() not in ("0", "off", "false", "no"),
            research_v2=_research_mode(env.get("FBI_AI_RESEARCH_V2")),
            engines=_engines(env.get("FBI_AI_ENGINES")),
            shadow_sample=_share(env.get("FBI_AI_SHADOW_SAMPLE")),
            agents=_agents(env.get("FBI_AI_AGENTS")),
            pm_reviewer=_on(env.get("FBI_AI_PM_REVIEWER")),
            learning_analyst=_on(env.get("FBI_AI_LEARNING_ANALYST")),
        )

    def switch(self, name: str) -> Switch:
        """The owner's setting of one Phase 0 optimisation: what the environment says, ``auto`` for a known switch it does not
        mention, and ``off`` for a name that is not one (so a typo never switches anything on)."""
        return self.switches.get(name, "auto" if name in SWITCH_ENV else "off")

    def labelled(self, *, lab: bool) -> tuple[str, str]:
        """The workspace and key NAMES the ledger records for a call (never the key)."""
        return (self.workspace_lab, self.key_label_lab) if lab else (self.workspace, self.key_label)

    def tier(self, tier: Tier, *, lab: bool = False) -> TierModel | None:
        """The model of a tier, only when its provider's key is present (the LAB workspace's own key for a LAB call)."""
        tm = self.tiers.get(tier)
        return tm if tm is not None and tm.provider in (self.lab_keys if lab else self.keys) else None

    @property
    def shadow_engines(self) -> tuple[str, ...]:
        """The engines of ``engines`` that are not the production baseline: the ones that run in shadow."""
        return tuple(e for e in self.engines if e in SHADOW_ENGINES)

    @property
    def orchestrate(self) -> bool:
        """Whether the orchestrator may run (plan IA, phase 3): the layer is not off, at least one shadow engine is named, the sample is above zero
        and the agents it needs - ``match`` and ``council`` - are both allowed. Any one of the three words missing leaves the shadow switched off."""
        return (self.mode != "off" and bool(self.shadow_engines) and self.shadow_sample > 0
                and all(agent in self.agents for agent in ORCHESTRATOR_AGENTS))

    @property
    def llm_configured(self) -> bool:
        return any(self.tier(t) for t in TIERS)

    def missing(self) -> list[str]:
        """What the owner would set to switch the language model on - names only."""
        out: list[str] = []
        for t in TIERS:
            tm = self.tiers.get(t)
            if tm is None:
                out.append(f"FBI_AI_MODEL_{t.upper()}")
            elif tm.provider not in self.keys:
                out.append(f"FBI_AI_KEY_{tm.provider.upper()}")
        return sorted(set(out))

    def public(self) -> dict[str, Any]:
        """The settings an admin may see: models and limits, never a key."""
        return {
            "mode": self.mode,
            "llm_configured": self.llm_configured,
            "tiers": {t: (None if (tm := self.tiers.get(t)) is None else
                          {"provider": tm.provider, "model": tm.model, "key_present": tm.provider in self.keys})
                      for t in TIERS},
            "missing": self.missing(),
            "daily_budget_usd": str(self.daily_budget),
            "daily_target_usd": str(self.daily_budget),
            "daily_max_factor": str(self.daily_max_factor),
            "monthly_budget_usd": str(self.monthly_budget),
            "max_llm_reviews_per_day": self.max_llm_reviews_per_day,
            "max_deep_per_day": self.max_deep_per_day,
            "max_web_first": self.max_web_first,
            "max_web_pre": self.max_web_pre,
            "max_watch_per_day": self.max_watch_per_day,
            "multimodal": self.multimodal,
            "horizon_hours": self.horizon_hours,
            "search": self.search,
            "search_configured": self.search_configured,
            "legacy_postmortems": self.legacy_postmortems,
            "switches": dict(self.switches),
            "workspaces": {"production": self.workspace, "lab": self.workspace_lab},
            "key_labels": {"production": self.key_label, "lab": self.key_label_lab},
            "lab_key_present": "anthropic" in self.lab_keys,
            "lab_monthly_budget_usd": str(self.lab_monthly_budget),
            "exa_monthly_budget_usd": str(self.exa_monthly_budget),
            "joint_ceiling_usd": str(self.joint_ceiling),
            "reserve_usd": str(self.reserve),
            "batch_min_lead_minutes": self.batch_min_lead_minutes,
            "package": self.package,
            "research_v2": self.research_v2,
            "engines": list(self.engines),
            "shadow_engines": list(self.shadow_engines),
            "shadow_sample": format(self.shadow_sample.normalize(), "f"),
            "agents": list(self.agents),
            "orchestrate": self.orchestrate,
            "pm_reviewer": self.pm_reviewer,
            "learning_analyst": self.learning_analyst,
        }

    @property
    def search_configured(self) -> bool:
        env = environment()
        if self.search == "exa":
            return bool(env.get("EXA_API_KEY"))
        if self.search in ("brave", "tavily"):
            return bool(env.get(f"FBI_AI_KEY_{self.search.upper()}"))
        return False
