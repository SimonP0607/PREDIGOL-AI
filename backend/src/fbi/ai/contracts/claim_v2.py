"""``claim-v2``: what the QUARANTINED extractor (``fbi.ai.quarantine``, prompt ``extract-v4``, IA-060) returns about ONE page.

It is ``claim-v1`` made smaller, for a reader the server does not trust at all (plan piece AD-A01): whatever the model was told by the page, the
only things it can hand back are references the server gave it and a passage of the page it was shown.

* ``call``: the code word of the call, copied from the message - a random word the server writes for each call and never shows twice. An
  answer that does not carry it exactly (an answer written for someone else: «reply DONE», a JSON the page dictated) stands for nothing.
* ``claims``: at most ``CLAIMS_MAX``. Each says WHO (``subject``: a reference of the list the server wrote for THIS call, ``S1``...; never a
  name, never an id of the provider), WHAT (``claim_type``: a closed list), WHICH MATCH (``applies_to``) and the ``quote`` - a passage of the
  page, copied, that the server finds again, character for character, in the window it sent.

There is no page id (a call reads one page), no date (the date is the search API's, never the model's), no link, no name, no number: the wire
schema has an enum for every field but ``quote`` and ``call``, and both are checked against what the server itself wrote or sent
(``fbi.ai.quarantine.read``). What does not stand is dropped with a closed reason and counted; an answer that is not this contract at all is
discarded whole (fail closed).
"""

from __future__ import annotations

from typing import Final, Literal, get_args

from pydantic import Field

from fbi.ai.contracts.base import Contract

QUOTE_MAX: Final = 300
CLAIMS_MAX: Final = 8
"""Claims of one answer - one page. A page of team news rarely says more than a handful of things about who can play."""
CALL_MAX: Final = 40

SubjectRef = Literal["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17",
                     "S18", "S19", "S20"]
"""The references of the list a call is given. The server maps each to a subject of its catalogue (a team or a player of the match) for that
call only: the same reference means someone else in another call."""
SUBJECT_REFS: Final = get_args(SubjectRef)

ClaimType = Literal["OUT", "DOUBT", "AVAILABLE", "STARTER", "SUSPENSION", "COACH", "SCHEDULE", "VENUE", "OTHER"]
"""The words of ``claim-v1``, the same meaning: out, doubtful, back or fit, in the eleven, banned, the coach, the time, the ground, anything
else. Which of them can be said of a team or of a player is the server's rule (``fbi.ai.quarantine.ALLOWED``)."""
CLAIM_TYPES: Final = get_args(ClaimType)
AppliesTo = Literal["THIS_MATCH", "NEXT_MATCH", "OTHER_MATCH", "UNSPECIFIED"]


class QuarantineClaim(Contract):
    subject: SubjectRef
    claim_type: ClaimType
    applies_to: AppliesTo
    quote: str = Field(max_length=QUOTE_MAX)


class QuarantineOut(Contract):
    contract: Literal["claim-v2"]
    call: str = Field(max_length=CALL_MAX)
    claims: list[QuarantineClaim] = Field(max_length=CLAIMS_MAX)
