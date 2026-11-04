"""Postpartido (plan UX, B4): what a finished match did to what the reader saved and to PrediGol's published picks, read for the product.
Reading only: nothing here settles, builds a post-mortem, re-prices a pick or calls anything.

* what the reader saved on the match, with its result and units once settled - the same records Mis picks shows (``picks.user_picks``);
* each pick PrediGol published for the match (the owner's preview adds the shadow ones): how it ended (``picks.pick_results``, the
  settlement) and why - the facts of the match its post-mortem found (``intel.selection_postmortems``, pm-v6: a man sent off, a penalty,
  an early goal, the chances each side made), as codes and figures, and the market's fair probability at its close.

What the post-mortem JUDGES never leaves it: its verdict, the class of a loss, the quality of the decision, the price against the close,
what the AI's review decided and its sentences are not even selected (``PM_SQL``), and a cause keeps only the figures of its code (``cause``).
A post-mortem whose outcome is not the settlement's (a result corrected after it was written) is not used: the pick waits for a new one.

Readers see it while they see the knowledge of a finished match (``FBI_KNOWLEDGE_USERS``, the same line: ``=0`` hides both); the Admin
Console's preview (``preview=shadow``) shows it either way.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, get_args

from fbi.api.cache import shared
from fbi.api.contracts.postmatch import (
    CauseCode,
    PickResult,
    PostMatch,
    PostmatchCause,
    PostmatchPick,
)
from fbi.api.envelope import Envelope, ok, unavailable
from fbi.api.errors import ApiError
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.api.repositories import product as repo
from fbi.api.services.knowledge import users_may_see
from fbi.api.services.records import user_picks_of_fixture
from fbi.core.clock import now

VERSION: Final = "postmatch-v1"
CODES: Final[tuple[str, ...]] = get_args(CauseCode)
RESULTS: Final[tuple[str, ...]] = get_args(PickResult)
ORDER: Final[dict[str, int]] = {code: n for n, code in enumerate(
    ("red_card", "penalty_scored", "penalty_missed", "early_goal", "xg_against", "xg_supported", "early_substitution",
     "cards_above_referee", "cards_below_referee"))}
"""The most telling fact first: a man sent off and a penalty change a match more than the run of the chances or the cards."""
EFFECT_RANK: Final[dict[str, int]] = {"against": 0, "for": 1, "neutral": 2}

FIXTURE_SQL = "SELECT f.id, f.kickoff_at, f.status_group FROM core.fixtures f WHERE f.id = %(f)s"

PM_SQL = """
SELECT pm.market_key, pm.selection, pm.line, pm.settled, pm.p_close, pm.causes, pm.created_at
  FROM intel.selection_postmortems pm
 WHERE pm.fixture_id = %(f)s
"""
"""The newest post-mortem of each selection of the match - only what a reader may be told: the outcome it saw (to check it is the
settlement's), the market's close and the facts it found. Its verdicts, classes, prices and sentences are not selected."""


def _int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def cause(raw: Mapping[str, Any]) -> PostmatchCause | None:
    """One fact of a post-mortem as a reader may get it: its code and its figures - never its sentence (``text`` is the post-mortem's own
    Spanish, written for the owner). A code this version does not know is left out. Pure."""
    code = raw.get("code")
    if code not in CODES:
        return None
    effect, side, score = raw.get("effect"), raw.get("side"), raw.get("score")
    return PostmatchCause.model_validate({
        "code": code, "effect": effect if effect in ("for", "against", "neutral") else "neutral",
        "side": side if side in ("home", "away") else None,
        "score": score if isinstance(score, str) and len(score) <= 7 else None,
        "minute": _int(raw.get("minute")), "n": _int(raw.get("n")), "cards": _int(raw.get("cards")),
        "referee_avg": _float(raw.get("referee_avg")), "xg_home": _float(raw.get("xg_home")),
        "xg_away": _float(raw.get("xg_away"))})


def causes_of(raw: Any) -> list[PostmatchCause]:
    """The facts of a post-mortem, the most telling first (``ORDER``; against the selection before for it, then by minute). Pure."""
    found = [c for c in (cause(x) for x in raw if isinstance(x, Mapping)) if c is not None] if isinstance(raw, list) else []
    return sorted(found, key=lambda c: (ORDER[c.code], EFFECT_RANK[c.effect], c.minute if c.minute is not None else 999))


def _key(market: Any, selection: Any, line: Any) -> tuple[str, str, Decimal]:
    return str(market), str(selection), Decimal(str(line)).normalize()


def published_pick(r: Row, pm: Mapping[str, Any] | None) -> PostmatchPick:
    """A started pick of the match with how it ended and, when its post-mortem saw the same outcome as the settlement, why. Pure."""
    result = r["result_status"] if r["result_status"] in RESULTS else None
    analysed = pm is not None and result not in (None, "pending") and pm["settled"] == result
    return PostmatchPick(
        pick_id=int(r["pick_id"]), market_key=str(r["market_key"]), selection=str(r["selection"]), line=Decimal(r["line"]),
        status=r["pick_status"], result=result, p_model=Decimal(r["p_model"]),
        p_close=Decimal(pm["p_close"]) if analysed and pm is not None and pm["p_close"] is not None else None,
        analysed=analysed, analysed_at=pm["created_at"] if analysed and pm is not None else None,
        causes=causes_of(pm["causes"]) if analysed and pm is not None else [])


@shared(60)
def published(conn: Conn, fixture_id: int, *, preview: bool, at: datetime) -> list[PostmatchPick]:
    """The picks published for the match (the owner's preview adds the shadow ones), as they were taken, with result and why. The same
    for every reader: kept a minute."""
    rows = repo.started_picks(conn, now=at, since=at, include_shadow=preview, fixture_id=fixture_id)
    pms = {_key(p["market_key"], p["selection"], p["line"]): p for p in fetch_all(conn, PM_SQL, {"f": fixture_id})}
    return [published_pick(r, pms.get(_key(r["market_key"], r["selection"], r["line"]))) for r in rows]


def postmatch(conn: Conn, fixture_id: int, *, user_id: int, preview: bool, at: datetime | None = None) -> Envelope[PostMatch | None]:
    """The Postpartido of a match for one reader: what they saved and how each of PrediGol's published picks ended, and why."""
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not preview and not users_may_see():
        return unavailable(None, "The after-match summary is not shown to users yet.")
    moment = (at or now()).replace(second=0, microsecond=0)  # to the minute: the published part is kept a minute (``published``)
    finished = fixture["status_group"] == "finished"
    body = PostMatch(version=VERSION, fixture_id=int(fixture["id"]), kickoff_at=fixture["kickoff_at"], finished=finished,
                     saved=user_picks_of_fixture(conn, user_id=user_id, fixture_id=fixture_id),
                     published=published(conn, fixture_id, preview=preview, at=moment)
                     if fixture["kickoff_at"] <= moment else [])
    newest = max((p.analysed_at for p in body.published if p.analysed_at is not None), default=None)
    return ok(body, data_as_of=newest)
