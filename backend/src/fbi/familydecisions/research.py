"""PEDIR INVESTIGACIÓN, FORMALLY, FOR A FAMILY (plan F11, ``research-fam-v1``): what a decision of a family would have to know before anyone
believed it, what finding out would cost, and which context factors could explain it - written on the decision, never served.

WHY. The AI can already ask the server to look into a match (``fbi.ai.research``, plan F6): it names a topic from a closed list and the server
decides whether and when. That door is for the picks the pipeline shortlists. A selection of a family has no pick and no AI review - it is a
measurement (``fbi.familydecisions.decide``) - so nobody is there to ask. This module makes the same request on the server's own account, in
the same words, at the moment the family decides, so that the owner can read on the decision itself what it did not know.

WHAT IS WRITTEN. One record in the decision's ``filters`` (key ``research``, version ``research-fam-v1``; the record is informational, ``ok`` is
null, like the layer's "no se aplica"):

* the NEEDS of the family, each KNOWN, PARTIAL or MISSING at the moment of the decision. Two come from the provider and cost no search: the
  referee the competition designated (the cards and the yellow cards: the model scales its means by his multiplier when he is assigned) and the
  line-ups (the goals of the halves and the corners). One is read from the outside world: the context (who can play, what the match is worth),
  which is the decision layer's own ``context_status`` and which only a search can improve. A need that a search serves names the topics of the
  AI's closed list (``fbi.ai.research.TOPICS``) and therefore the levels of the tiered search (one search a level), never a query;
* what the open ones would COST in searches: the levels of their topics together, because a search of a level serves every selection of the
  match, so three selections of one match do not cost three times;
* that nothing serves them: ``served`` is false and, when a search is what is missing, ``unserved`` says why (``family_shadow``; what only the
  provider brings is not something the server declines to serve, it arrives when the competition publishes it). A family decides in shadow, its
  decisions reach nobody, and the day's searches and the day's budget are the owner's (plan §22, decision 12). The day a family leaves research
  and the owner allows the spending, serving a request is a step of its own, added with its reason in the open, and this record is what it reads;
* the context FACTORS that could explain the family (``HYPOTHESES``), with the standing each had when the family decided
  (``fbi.intel.factors``). They are hypotheses for an experiment of plan F12, not findings: a factor is DESCRIPTIVE until a person validates
  an experiment of it, no model of a family reads one (``tests/unit/test_context_isolation.py``) and the decision does not move for them.

WHAT IT CANNOT DO. It changes nothing of the decision: the state, the reasons, the score and the stake are the ones the filters gave, with
or without the record (a test holds it). It reads no news, calls no provider and spends no money. Pure: it reads nothing and writes nothing;
the reading is ``fbi.familydecisions.decide.read_referees`` and ``read_standing``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.ai import research as ai_research

VERSION: Final = "research-fam-v1"
KEY: Final = "research"
"""The key of the record among the filters of a decision (the ten filters, ``family`` and ``correlation`` have theirs)."""

KNOWN: Final = "KNOWN"
PARTIAL: Final = "PARTIAL"
MISSING: Final = "MISSING"
STATES: Final = (KNOWN, PARTIAL, MISSING)

PROVIDER: Final = "provider"
SEARCH: Final = "search"
"""Who fills a need: the provider's own data (free, it arrives when the competition publishes it) or a search of the outside world (paid)."""

UNSERVED: Final = "family_shadow"
"""Why no request of a family is served: the families decide in shadow. Not one of the reasons the AI gives for the requests of a brief
(``fbi.ai.research.UNSERVED``): those count in the passes of the AI, and no pass of the AI reads this record."""

DESCRIPTIVE: Final = "DESCRIPTIVE"
"""The standing of a factor nobody has validated (``fbi.intel.factors.DESCRIPTIVE``; a test holds the two equal): also what a factor is when the registry could not be read."""


@dataclass(frozen=True, slots=True)
class Need:
    """Something a decision of a family would want to know: who fills it, which topics of the AI's list a search for it takes, and what it is called."""

    key: str
    source: str
    topics: tuple[str, ...]
    label: str

    @property
    def levels(self) -> tuple[int, ...]:
        """The levels of the tiered search that serve the topics (``fbi.ai.research.TOPICS``): one search each."""
        return tuple(sorted({level for topic in self.topics for level in ai_research.BY_KEY[topic].levels}))


NEEDS: Final[Mapping[str, Need]] = {n.key: n for n in (
    Need("referee", PROVIDER, (), "el árbitro designado"),
    Need("lineups", PROVIDER, (), "las alineaciones confirmadas"),
    Need("context", SEARCH, ("availability", "preview"), "el contexto de fuera (bajas y previa)"),
)}
"""What a decision can lack. The context is what the tiered search of a match with candidates reads (all three levels, ``fbi.ai.research.FULL``)."""

OF_FAMILY: Final[Mapping[str, tuple[str, ...]]] = {
    "GOALS_HALF": ("lineups", "context"),
    "CORNERS": ("lineups", "context"),
    "CARDS": ("referee", "context"),
    "YELLOW": ("referee", "context"),
}
"""What each family would want to know. Every family of ``fbi.familydecisions.decide.SPECS`` is here (a test holds it). The cards and the yellow cards
scale their means by the referee's multiplier when one is assigned (``fbi.families.referee``); the goals of the halves and the corners are
sensitive to who plays."""

HYPOTHESES: Final[Mapping[str, tuple[str, ...]]] = {
    "GOALS_HALF": ("tactics_profile", "scenarios", "rest_congestion"),
    "CORNERS": ("tactics_profile",),
    "CARDS": ("scenarios",),
    "YELLOW": ("scenarios",),
}
"""The context factors of the registry (``fbi.intel.factors.CATALOGUE``) that an experiment could test against each family: how a side behaves with
the lead or without it and whether it presses (``tactics_profile``) bears on the goals of each half and on the corners; what the match is worth to a table
or a tie (scenarios) bears on the intensity of the cards and on the goals of the second half; rest and congestion on the second half. A hypothesis
is a place to start an experiment, not a result: every factor is DESCRIPTIVE until a person validates one."""

CONTEXT_STATE: Final[Mapping[str, str]] = {"FULL": KNOWN, "PARTIAL": PARTIAL, "LIMITED": MISSING, "PENDING": MISSING, "AI_OFF": MISSING}
"""The decision layer's word for how much of the outside world was read (``fbi.intel.decision.context_status``) as the state of the context need.
FULL: web evidence from a known source, or the confirmed line-ups after a search. PARTIAL: the provider's reports only. LIMITED: read and nothing
found beyond the numbers. PENDING: not read yet. AI_OFF: the layer is switched off. Anything else is missing."""


@dataclass(frozen=True, slots=True)
class Facts:
    """What was known of a match when a family decided it: every field is read AS OF that moment (a sighting after it does not count)."""

    referee_seen_at: datetime | None
    """When the referee the competition designated was seen (None: none designated by then)."""
    lineups_at: datetime | None
    """When the line-ups were read (None: not read by then)."""
    context: str
    """The decision layer's context status for the selection (``fbi.intel.decision.context_status``)."""


def state_of(need: str, facts: Facts) -> tuple[str, datetime | None]:
    """The state of a need and, when it is known, since when."""
    if need == "referee":
        return (MISSING, None) if facts.referee_seen_at is None else (KNOWN, facts.referee_seen_at)
    if need == "lineups":
        return (MISSING, None) if facts.lineups_at is None else (KNOWN, facts.lineups_at)
    if need == "context":
        return CONTEXT_STATE.get(facts.context, MISSING), None
    raise KeyError(need)


def _searches(n: int) -> str:
    return "1 búsqueda" if n == 1 else f"{n} búsquedas"


def request(family: str, facts: Facts, standing: Mapping[str, tuple[str, str]], *, registry_read: bool = True) -> tuple[str, dict[str, Any]]:
    """The record of a family's decision: the sentence the owner reads (Spanish, like every filter's) and the data.

    ``standing`` maps a factor key to its (version, status) at the moment of the decision (``decide.read_standing``); a factor it does not list is
    DESCRIPTIVE, the safe side of every doubt. ``registry_read`` is false when the registry could not be read, and the record says so."""
    needs: list[dict[str, Any]] = []
    for key in OF_FAMILY.get(family, ()):
        need = NEEDS[key]
        state, since = state_of(key, facts)
        needs.append({"key": key, "state": state, "source": need.source, "topics": list(need.topics), "levels": list(need.levels),
                      "since": None if since is None else since.isoformat()})
    open_needs = [n for n in needs if n["state"] != KNOWN]
    to_search = [n for n in open_needs if n["source"] == SEARCH]
    levels = sorted({level for n in to_search for level in n["levels"]})
    hypotheses: list[dict[str, Any]] = []
    for factor in HYPOTHESES.get(family, ()):
        version, status = standing.get(factor, (None, DESCRIPTIVE))
        hypotheses.append({"factor": factor, "version": version, "status": status})
    data: dict[str, Any] = {
        "version": VERSION, "family": family, "needs": needs, "open": [n["key"] for n in open_needs], "levels": levels,
        "searches": len(levels), "served": False, "unserved": UNSERVED if to_search else None, "factors": hypotheses,
        "registry": "read" if registry_read else "unread"}
    return _sentence(family, open_needs, len(levels)), data


def _sentence(family: str, open_needs: list[dict[str, Any]], searches: int) -> str:
    if family not in OF_FAMILY:
        return "pedir investigación: esta familia no tiene lista de lo que necesita saber"
    if not open_needs:
        return "pedir investigación: no le falta nada de lo que se puede saber antes del partido"
    labels = [NEEDS[n["key"]].label + (", leído solo en parte" if n["state"] == PARTIAL else "")
              + (" (lo trae el proveedor)" if n["source"] == PROVIDER else "") for n in open_needs]
    tail = f"; {_searches(searches)} si se sirviera; no se sirve: las familias están en sombra" if searches else ""
    return f"pedir investigación: le falta {' y '.join(labels)}{tail}"
