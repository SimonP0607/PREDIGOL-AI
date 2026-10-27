"""PEDIR INVESTIGACIÓN - the AI asks, the server decides (plan F6, first version; F11 makes it formal for each family of markets).

Until brief-v8 the AI could do one thing about what it did not know: set ``escalate``, and the server read that as «look closer» without
knowing at what. Now the brief can say WHAT is missing, from a list the server wrote, and for which side:

    availability   who can play: injuries, suspensions and doubts
    confirmation   a rumour, an old report or a contradiction to settle with the clubs' and the competition's own statements
    preview        what an international preview says about the stakes, the probable line-ups and the mood

and nothing else:

* The AI never writes a query, a URL, a name to look for or a number of searches. The server writes the queries (``fbi.ai.collectors``,
  in the competition's language), reads the results and decides what each one is worth (``fbi.ai.evidence``), as it always did.
* A request is a request. The server may serve it at the next pass that reads the web - the pre pass after a first pass that asked, or the
  owner's «run now» - and only inside what it already allows itself: the day's searches (``FBI_AI_MAX_WEB_PRE`` / ``FBI_AI_MAX_WEB_FIRST``:
  a request is ranked after the matches with a candidate, so it takes no search one of them would have had) and the day's budget (the
  rule that drops the paid depth of a match without candidates near the budget drops it too). A final pass does not read the web, so
  what a pre pass asks is left for the owner's «run now». A match served is read through the same cache as always: an answer still fresh
  is not paid for again.
* It is not a reason to escalate: no intermediate-model review comes of it. It never changes what a model, a rule or a pick decides.
* Each request carries its reason as a claim like any other - typed, cited, its numbers checked against the packet
  (``fbi.ai.brief.validate``) - and what the server did with it is counted (``ai.fixture_passes.counts``: ``research_asked`` and either
  ``research_searched`` or ``research_unserved`` with the reason, ``UNSERVED``).

Pure: the module reads nothing and writes nothing; the cycle (``fbi.ai.cycle``) reads the latest brief and calls the collector.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

VERSION: Final = "research-v1"

MAX_ASKS: Final = 3
"""Requests in one brief."""
SIDES: Final = ("home", "away", "both")

FULL: Final = 3
"""The levels of the tiered search of a match with candidates (``fbi.ai.collectors.queries_for``): 1 team news, 2 official statements,
3 an international preview."""


@dataclass(frozen=True, slots=True)
class Topic:
    """A thing the AI may ask the server to look into: the levels of the tiered search that serve it, what it is called for the
    owner (Spanish) and what it means for the model (the prompt)."""

    key: str
    levels: tuple[int, ...]
    label: str
    means: str


TOPICS: Final[tuple[Topic, ...]] = (
    Topic("availability", (1, 2), "quién puede jugar (bajas, dudas, sanciones)",
          "who can play: the injuries, suspensions and doubts of the match"),
    Topic("confirmation", (2,), "confirmar con fuentes oficiales",
          "a rumour, an old report or a contradiction to settle with the clubs' and the competition's own statements"),
    Topic("preview", (3,), "previa de medios internacionales",
          "what an international preview says about the stakes, the probable line-ups and the mood of the match"),
)
BY_KEY: Final[dict[str, Topic]] = {t.key: t for t in TOPICS}

LEVEL_TOPIC: Final[dict[int, str]] = {1: "availability", 2: "confirmation", 3: "preview"}
"""Research v2 keeps ONE answer per entity and topic (``fbi.ai.cache.entity_key``), and the topic of an answer is the kind of search that
found it: team news (level 1) is what is known about WHO CAN PLAY, the clubs' and the competition's own words (level 2) are the
CONFIRMATION, the international preview (level 3) is the PREVIEW. A level reached as the fallback of ``availability`` keeps the topic of its
query: the same search is the same answer whoever asked for it."""
TOPIC_ENTITY: Final = {"availability": "TEAM", "confirmation": "TEAM", "preview": "MATCH"}
"""What an answer is about: the teams of the match for the first two (each team's answer is kept apart, so the next match of either team reads
it), the match itself for a preview (nobody else shares it)."""


UNSERVED: Final = {
    "no_allowance": "the day's searches of this pass were spent on matches ranked before it, or no search is set up",
    "near_budget": "the day is near its budget: a match without a candidate loses its paid depth first",
    "pass_budget": "the budget left for this pass does not allow a search",
    "no_search_pass": "this pass does not read the web",
    "research_failed": "the research of an entity failed in this pass, and it was the one reading the web (``FBI_AI_RESEARCH_V2=on``)",
}
"""Why a request was not served, in the words of the cycle's counts (``research_unserved_<reason>``)."""


@dataclass(frozen=True, slots=True)
class Ask:
    """A request that passed the server's checks: a topic of the list, a side, and the reason as a claim (text, type, refs)."""

    topic: str
    side: str
    why: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"topic": self.topic, "side": self.side, "why": self.why}

    @property
    def levels(self) -> tuple[int, ...]:
        return BY_KEY[self.topic].levels


def asks_in(raw: Any) -> list[Ask]:
    """The requests stored in a brief (``content["research"]``), read defensively: anything that is not a well-formed request of the
    list is not one. A brief written before brief-v8 has none."""
    out: list[Ask] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:MAX_ASKS]:
        if not isinstance(item, dict):
            continue
        topic, side, why = item.get("topic"), item.get("side"), item.get("why")
        if isinstance(topic, str) and topic in BY_KEY and side in SIDES and isinstance(why, dict):
            out.append(Ask(topic, str(side), dict(why)))
    return out


def levels_for(asks: Sequence[Ask], *, candidates: bool) -> int | tuple[int, ...]:
    """The levels of the tiered search a match is read with in a pass that reads the web: all three for a match with a candidate
    (as ever); for the others the levels of the topics asked - the cheapest answer to what was asked - or the first level alone
    (as ever) when nothing was."""
    if candidates:
        return FULL
    wanted = sorted({level for a in asks for level in a.levels})
    return tuple(wanted) if wanted else 1
