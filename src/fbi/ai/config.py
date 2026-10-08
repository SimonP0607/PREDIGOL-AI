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
    FBI_AI_DAILY_BUDGET_USD     default 1.00 - the day's spend cap
    FBI_AI_MONTHLY_BUDGET_USD   default FBI_ANALYST_MONTHLY_BUDGET_USD or 20 - one cap for the whole AI layer
    FBI_AI_MAX_LLM_REVIEWS_PER_DAY  default 60
    FBI_AI_MAX_DEEP_PER_DAY     default 10 (final-tier reviews)
    FBI_AI_MULTIMODAL           off (default) | on - images only for selected matches, each one logged
    FBI_AI_HORIZON_HOURS        default 96 - how far ahead matches are analysed
    FBI_AI_SEARCH               exa | brave | tavily | none (default exa when EXA_API_KEY is set, else none)

No tier configured = the layer runs its deterministic reviewer only and says so (``status()``). A tier is
switched on only by its own FBI_AI_MODEL_* variable: the earlier analyst's FBI_ANALYST_MODEL never turns the
decision layer's model calls on by itself (its key still counts once a tier names Anthropic).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fbi.core.env import environment

Mode = Literal["off", "shadow", "enforce"]
Tier = Literal["bulk", "analysis", "final"]
TIERS: tuple[Tier, ...] = ("bulk", "analysis", "final")
PROVIDERS = ("anthropic", "openai", "gemini", "mistral", "deepseek", "together", "groq", "deepinfra")

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


@dataclass(frozen=True)
class AiSettings:
    mode: Mode = "shadow"
    tiers: dict[str, TierModel | None] = field(default_factory=dict)
    keys: dict[str, str] = field(default_factory=dict, repr=False)
    base_urls: dict[str, str] = field(default_factory=dict)
    daily_budget: Decimal = Decimal("1.00")
    monthly_budget: Decimal = Decimal("20")
    max_llm_reviews_per_day: int = 60
    max_deep_per_day: int = 10
    multimodal: bool = False
    horizon_hours: int = 96
    search: str | None = None

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
        return cls(
            mode=mode, tiers=tiers, keys=keys, base_urls=base_urls,
            daily_budget=_decimal("FBI_AI_DAILY_BUDGET_USD", "1.00", env),
            monthly_budget=_decimal("FBI_AI_MONTHLY_BUDGET_USD", monthly_default, env),
            max_llm_reviews_per_day=_int("FBI_AI_MAX_LLM_REVIEWS_PER_DAY", 60, env),
            max_deep_per_day=_int("FBI_AI_MAX_DEEP_PER_DAY", 10, env),
            multimodal=(env.get("FBI_AI_MULTIMODAL") or "").strip().lower() in ("1", "on", "true", "yes"),
            horizon_hours=max(1, _int("FBI_AI_HORIZON_HOURS", 96, env)),
            search=None if search_raw in ("", "none", "off") else search_raw,
        )

    def tier(self, tier: Tier) -> TierModel | None:
        """The model of a tier, only when its provider's key is present."""
        tm = self.tiers.get(tier)
        return tm if tm is not None and tm.provider in self.keys else None

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
            "monthly_budget_usd": str(self.monthly_budget),
            "max_llm_reviews_per_day": self.max_llm_reviews_per_day,
            "max_deep_per_day": self.max_deep_per_day,
            "multimodal": self.multimodal,
            "horizon_hours": self.horizon_hours,
            "search": self.search,
            "search_configured": self.search_configured,
        }

    @property
    def search_configured(self) -> bool:
        env = environment()
        if self.search == "exa":
            return bool(env.get("EXA_API_KEY"))
        if self.search in ("brave", "tavily"):
            return bool(env.get(f"FBI_AI_KEY_{self.search.upper()}"))
        return False
