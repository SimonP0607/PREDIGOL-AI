"""What research v2 knows about a team, for the readers that choose evidence BY MATCH (plan IA, phase 2, finding H4 of the independent review).

A claim of research v2 about a team or one of its players that says nothing of a particular match (``applies_to`` ``UNSPECIFIED``: what is known of them
whatever match asks) is stored with ``fixture_id`` NULL and the team's ``team_id`` (``fbi.ai.extract_v2.to_evidence``). The packet of a match reads it
(``fbi.ai.packet.EVIDENCE_SQL``), so with research v2 ``on`` the model reads «X is out». The readers that choose evidence by ``fixture_id`` - the
decision layer (``fbi.intel.decision``), the set of the day (``fbi.picks.daily``), the post-match review (``fbi.intel.match_review``) and the report of
the day (``fbi.intel.report``) - did not: the model would have read the claim and the context, the day's set, the review and the report would not know
it exists.

This module is the one definition of the team's claims a match sees, and the four use it. It is what the packet shows, with one exception on purpose (the
third point):

* only while research v2 is ``on`` (the caller's ``%(typed)s``: ``fbi.ai.gates.typed_visible``); with ``off``, ``shadow`` or ``on`` without the evidence
  of its gate the term is false and the statement answers exactly what it always answered;
* only claims of research v2 (``subject_type`` not NULL) that belong to no match (``fixture_id`` NULL) and are about one of the two teams;
* only while the claim has not been set aside by the server (``status`` not ``OUTDATED``), as the packet does not show it - for the readers that look
  forward, the decision layer and the set of the day. The two that look back (the post-match review and the report of the day) take the claims whatever
  the server did with them afterwards (``set_aside``), as they take the claims of a match: a report that the line-up proved wrong is set aside by the
  server BECAUSE it proved wrong, and a review that judged only the claims that survived would judge the sources by their hits alone;
* only while it is not older than ``fbi.ai.evidence.STALE_AFTER`` - by its own date, the page's, or the day it was read - at the moment the reader asks
  (``at``: the instant of the decision, or the kick-off of the match for the readers that look back) and not read after that moment.

Nothing here reads or writes by itself: it is a piece of SQL and the two words it needs, and a test holds that the packet and the four readers agree on
the claims they see."""

from __future__ import annotations

from typing import Any


def team_claims(*, home: str, away: str, at: str, set_aside: bool = False) -> str:
    """The SQL term that lets a reader of ``ai.evidence e`` see the claims about a team that belong to no match: put it in an ``OR`` beside the match's
    own (``e.fixture_id = <the match>``). ``home`` and ``away`` are the SQL expressions of the two teams of the match, ``at`` the SQL expression of the
    moment the reader is looking from (a bound parameter, or the kick-off of the match). ``set_aside`` is for the readers that look back: it keeps the
    claims the server has set aside (``OUTDATED``), which the packet - and the readers that look forward - never show. The statement that uses it takes
    the words of ``words``."""
    standing = "" if set_aside else " AND e.status <> 'OUTDATED'"
    return (f"(%(typed)s AND e.fixture_id IS NULL AND e.subject_type IS NOT NULL AND e.team_id IN ({home}, {away}){standing} "
            f"AND e.retrieved_at <= {at} AND COALESCE(e.published_at, e.retrieved_at) > {at} - %(stale)s)")


def words(typed: bool) -> dict[str, Any]:
    """The two bound parameters ``team_claims`` needs: whether the claims of research v2 are part of what is read (``typed``, from
    ``fbi.ai.gates.typed_visible``) and how old a claim may be (``fbi.ai.evidence.STALE_AFTER``, the packet's)."""
    from fbi.ai.evidence import STALE_AFTER

    return {"typed": typed, "stale": STALE_AFTER}
