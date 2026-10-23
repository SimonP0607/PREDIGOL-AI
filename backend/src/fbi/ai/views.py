"""What each reader of a packet reads of it (plan F6).

A packet says everything PrediGol can say about a match as of a moment. Two readers take it to a language model, and they do not need
the same part of it:

* **The brief** (``fbi.ai.brief``: the economical model, one call per match, a fraction of a cent) reads the packet whole. It DESCRIBES the
  match for the owner, and the server refuses a reason for a selection that rests on a context block nobody has validated.
* **The pick reviewer** (``fbi.ai.review``: Sonnet, Opus on the last look - the dearest call PrediGol makes and the one whose answer
  weighs on whether a pick is shown) reads the packet as it was before plan F6, until a person validates what packet-v8 added. The
  weighted head-to-head, the scenarios, the tactics and the registry of the factors describe a match and no experiment has shown that
  they predict anything: a block that must not weigh on a pick is a block the reviewer is not given. It is also what keeps a review at the
  price it has - those blocks are about half as many tokens again as the packet had, and every review reads all of the packet it is given.

A factor a person has VALIDATED (``intel.context_factors``: who, which experiment, what it showed) is given back to the reviewer whole,
with its entry in the registry, from the next packet on. ``review_view`` reads only what the packet itself says about that
(``factors``, written from the registry when the packet was built): the safe side of every doubt is DESCRIPTIVE, which stays out.

The same view is what the reviewer's claims are checked against and what its answer is remembered by: a number that only a block it was
not given contains does not support a claim, and a change that only a block it was not given shows does not buy a second review.

Everything here is a pure function of a packet's content: nothing is read from the database and nothing is written.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any, Final

from fbi.ai.packet import Packet, content_hash
from fbi.intel import factors

PLAIN: Final[dict[str, tuple[str, ...] | None]] = {
    factors.H2H: ("n", "home_view"),
    factors.SCENARIOS: None,
    factors.TACTICS: None,
}
"""The context factors whose block the reviewer is not given while they are DESCRIPTIVE, each with the keys of its block that the packet
carried before plan F6 and that the reviewer keeps (``None``: the block did not exist and is left out whole). A factor of the catalogue
that is in neither this table nor ``OLDER`` is left out whole: not knowing is DESCRIPTIVE."""

OLDER: Final = frozenset({factors.CALENDAR})
"""The context factors whose block is older than the registry: ``schedule`` came with packet-v7 and says nothing of its own status, and the
reviewer has always read it. What happens to it is not a question of plan F6."""

HIDDEN_MISSING: Final = frozenset({"factors"})
"""The names in a packet's ``missing`` that speak of a block the reviewer is not given (the registry could not be read)."""


def validated_factors(content: dict[str, Any]) -> frozenset[str]:
    """The factors the packet states as VALIDATED (``content["factors"]``, written by the server from the registry). Anything else -
    no block, an entry that is not one, a status that is not that word - is DESCRIPTIVE, which is the safe side of every doubt."""
    block = content.get("factors")
    if not isinstance(block, dict):
        return frozenset()
    return frozenset(k for k, v in block.items() if k in factors.BY_KEY and isinstance(v, dict) and v.get("status") == factors.VALIDATED)


def _holder(view: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any] | None:
    """The mapping that holds the last step of ``path``, or None when the packet has not the steps before it."""
    node: Any = view
    for step in path[:-1]:
        node = node.get(step) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else None


def review_view(content: dict[str, Any]) -> dict[str, Any]:
    """The packet as the pick reviewer reads it: a copy of ``content`` without the blocks of plan F6 that are still DESCRIPTIVE - the
    scenarios, the tactics, the registry, and the head-to-head but for the two keys it always carried - and with the ones a person has
    VALIDATED (and their entries in the registry) whole. The packet itself is not touched."""
    view = copy.deepcopy(content)
    validated = validated_factors(content)
    for f in factors.CATALOGUE:
        if f.key in validated or f.key in OLDER:
            continue
        holder, key = _holder(view, f.block), f.block[-1]
        if holder is None or key not in holder:
            continue
        keep, block = PLAIN.get(f.key), holder[key]
        if keep is None:
            del holder[key]
        elif isinstance(block, dict):
            holder[key] = {k: v for k, v in block.items() if k in keep}
    registry = view.get("factors")
    if validated and isinstance(registry, dict):
        view["factors"] = {k: v for k, v in registry.items() if k in factors.RESERVED or k in validated}
    else:
        view.pop("factors", None)
    return view


def review_missing(missing: Sequence[str]) -> list[str]:
    """What the packet could not say, as far as the reviewer is concerned: a block it is not given is not missing from what it reads."""
    return [m for m in missing if m not in HIDDEN_MISSING]


def review_hash(packet: Packet, view: dict[str, Any]) -> str:
    """The hash of what the reviewer reads, made the way ``Packet.hash`` is: two packets that differ only in what the reviewer is not given
    have the same one, and a review already paid for is reused (``fbi.ai.review``)."""
    return content_hash({"v": packet.version, "content": view, "missing": sorted(review_missing(packet.missing))})
