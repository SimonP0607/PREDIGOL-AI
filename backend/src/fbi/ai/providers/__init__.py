"""Language-model providers behind one interface (``base.LlmProvider``)."""

from __future__ import annotations

import httpx

from fbi.ai.config import BASE_URLS, AiSettings, Tier
from fbi.ai.providers.anthropic import AnthropicBatches, AnthropicProvider, BatchResult
from fbi.ai.providers.base import JsonRequest, LlmProvider, LlmResult, LlmUsage, ProviderError
from fbi.ai.providers.fake import FakeBatches, FakeProvider
from fbi.ai.providers.openai_compat import OpenAICompatibleProvider


def provider_for(settings: AiSettings, tier: Tier, *, transport: httpx.BaseTransport | None = None,
                 lab: bool = False) -> tuple[LlmProvider, str] | None:
    """The provider and model of a tier, or None when the tier has no model or no key. ``lab``: the LAB workspace's own key
    (experiments never spend production's)."""
    tm = settings.tier(tier, lab=lab)
    if tm is None:
        return None
    key = (settings.lab_keys if lab else settings.keys)[tm.provider]
    base = settings.base_urls[tm.provider]
    if tm.provider == "anthropic":
        return AnthropicProvider(key, base, transport=transport), tm.model
    return OpenAICompatibleProvider(tm.provider, key, base, transport=transport), tm.model


def batches_for(settings: AiSettings, *, lab: bool = False,
                transport: httpx.BaseTransport | None = None) -> AnthropicBatches | None:
    """The Message Batches client of a workspace, or None when that workspace has no Anthropic key (the LAB workspace's own key
    for the LAB: an experiment never spends production's). Only Anthropic has the API."""
    key = (settings.lab_keys if lab else settings.keys).get("anthropic")
    if not key:
        return None
    return AnthropicBatches(key, settings.base_urls.get("anthropic") or BASE_URLS["anthropic"], transport=transport)


__all__ = ["AnthropicBatches", "AnthropicProvider", "BatchResult", "FakeBatches", "FakeProvider", "JsonRequest",
           "LlmProvider", "LlmResult", "LlmUsage", "OpenAICompatibleProvider", "ProviderError", "batches_for",
           "provider_for"]
