"""The periodic checker of the registry of sources (IA-062, plan piece AD-C01): DESIGN and pure rules; ``scripts/ia_sources_check.py`` runs
it by hand. It is NOT scheduled: the owner decides when, and on how many sources.

What it does, per source:

1. It reads ``robots.txt`` of the source's domain with ONE plain request of its own (``httpx``, an honest User-Agent, ten seconds, no
   retry, a pause between domains). Never Exa, never a model, never another route: a source the directory found ``bloqueada`` is not
   asked again at all (``skip_reason``), and neither is one the exclusion list blocks or one already reserved from AI - the checker only
   looks for what would make a source stricter.
2. From what it read (``observe``): the lines for the AI crawlers (ClaudeBot, anthropic-ai, GPTBot, CCBot, Google-Extended...) that
   disallow everything mean a reservation from AI; ``User-agent: *`` disallowing everything means automated reading is restricted; a
   refused or failed request means the reader could not open it.
3. ``propose``: the state it would have NOW, never higher than the one it has (``STRICTNESS``): a check can move a source to «solo
   referencia» or «bloqueada», never to «autorizada» - that is the owner's signature. A source whose last review is older than
   ``STALE_AFTER`` (90 days) goes back to pending.

The output is a list of proposals (JSON). Nothing is written to the database: the proposals become a new version of the directory, which
the loader loads like any other."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from fbi.ai.source_policy import STRICTNESS
from fbi.ai.source_registry import Source

AI_AGENTS: Final = ("claudebot", "claude-web", "anthropic-ai", "gptbot", "chatgpt-user", "ccbot", "google-extended", "perplexitybot",
                    "bytespider", "applebot-extended", "meta-externalagent")
STALE_AFTER: Final = timedelta(days=90)
USER_AGENT: Final = "PrediGolSourceCheck/1.0 (robots.txt review of a news directory; one request per domain)"
PAUSE_SECONDS: Final = 2.0
TIMEOUT_SECONDS: Final = 10.0
SKIP_STATES: Final = frozenset({"bloqueada", "solo_referencia"})


def skip_reason(source: Source, *, excluded: bool) -> str | None:
    """Why a source is not asked: a blocked one is never retried by another route, a reserved one cannot get stricter, an excluded domain
    is not a source."""
    if source.state == "bloqueada":
        return "blocked_not_retried"
    if source.state == "solo_referencia" or source.ai_reserved:
        return "already_reserved"
    if excluded:
        return "excluded"
    return None


def parse_robots(text: str) -> dict[str, list[str]]:
    """``User-agent`` groups -> their ``Disallow`` paths (lower-case agents; consecutive agent lines share a group)."""
    groups: dict[str, list[str]] = {}
    agents: list[str] = []
    in_rules = False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if in_rules:
                agents, in_rules = [], False
            agents.append(value.lower())
            groups.setdefault(value.lower(), [])
        elif key in ("disallow", "allow"):
            in_rules = True
            if key == "disallow" and value:
                for a in agents:
                    groups.setdefault(a, []).append(value)
    return groups


@dataclass(frozen=True, slots=True)
class Observation:
    status: int | None
    """HTTP status of robots.txt; None when the request failed (timeout, refused)."""
    ai_reserved: bool = False
    all_disallowed: bool = False
    agents: tuple[str, ...] = ()


def observe(status: int | None, text: str = "") -> Observation:
    if status != 200:
        return Observation(status)
    groups = parse_robots(text)
    reserved = tuple(sorted(a for a in groups if any(a.startswith(x) for x in AI_AGENTS) and "/" in groups[a]))
    return Observation(status, bool(reserved), "/" in groups.get("*", []), reserved)


@dataclass(frozen=True, slots=True)
class Proposal:
    source_id: str
    domain: str
    current: str
    proposed: str
    reason: str


def propose(source: Source, obs: Observation | None, *, today: date) -> Proposal:
    """The state the check supports, never higher than the current one."""
    observed, reason = source.state, "unchanged"
    if obs is not None:
        if obs.status is None or obs.status in (401, 403, 429) or obs.status >= 500:
            observed, reason = "bloqueada", f"robots.txt not readable ({obs.status})"
        elif obs.ai_reserved:
            observed, reason = "solo_referencia", "robots.txt reserves it from AI: " + ",".join(obs.agents)
        elif obs.all_disallowed:
            observed, reason = "solo_referencia", "robots.txt disallows every automated reader"
    if observed == source.state and source.state == "verificada_autorizada" and (
            source.last_reviewed is None or today - source.last_reviewed > STALE_AFTER):
        observed, reason = "verificada_pendiente_derechos", "last review older than 90 days"
    proposed = observed if STRICTNESS[observed] <= STRICTNESS[source.state] else source.state  # never up
    return Proposal(source.source_id, source.domain, source.state, proposed, reason if proposed != source.state else "unchanged")


__all__ = ["PAUSE_SECONDS", "STALE_AFTER", "TIMEOUT_SECONDS", "USER_AGENT", "Observation", "Proposal", "observe", "parse_robots", "propose",
           "skip_reason"]
