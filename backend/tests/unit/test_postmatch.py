"""Postpartido (plan UX, B4), the pure part: a post-mortem's facts as a reader may get them, and when a published pick is explained at all."""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, get_args

from fbi.api.contracts.postmatch import CauseCode, PostmatchCause, PostmatchPick
from fbi.api.services import postmatch
from fbi.api.services.postmatch import cause, causes_of, published_pick

AT = datetime(2034, 5, 3, 12, tzinfo=UTC)


def row(result: str | None = "win", market: str = "1X2", selection: str = "Home", line: str = "0") -> dict[str, Any]:
    return {"pick_id": 7, "market_key": market, "selection": selection, "line": Decimal(line), "pick_status": "qualified",
            "result_status": result, "p_model": Decimal("0.5500")}


def pm(settled: str = "win", causes: list[dict[str, Any]] | None = None, p_close: str | None = "0.5200") -> dict[str, Any]:
    return {"market_key": "1X2", "selection": "Home", "line": Decimal("0.00"), "settled": settled,
            "p_close": None if p_close is None else Decimal(p_close), "causes": causes or [], "created_at": AT}


def test_the_codes_are_the_post_mortems_own() -> None:
    """Every code the post-mortem writes (``fbi.intel.postmortem.causes_of``) has a field and a template; nothing else is let through."""
    from fbi.intel import postmortem as writer

    written = set(re.findall(r'"code": "([a-z_]+)"', inspect.getsource(writer.causes_of)))
    written |= {"xg_supported", "xg_against"}  # written through a conditional expression
    assert written == set(get_args(CauseCode))


def test_a_cause_keeps_its_figures_and_never_its_sentence() -> None:
    c = cause({"code": "red_card", "minute": 60, "side": "away", "effect": "for", "text": "Roja al visitante (a favor de la selección)"})
    assert c == PostmatchCause(code="red_card", effect="for", minute=60, side="away")
    assert "text" not in c.model_dump()
    assert cause({"code": "made_up", "effect": "for"}) is None
    odd = cause({"code": "early_goal", "minute": "12", "side": "north", "effect": "maybe", "score": "a very long text"})
    assert odd == PostmatchCause(code="early_goal", effect="neutral"), "what a cause cannot carry is dropped, never guessed"
    xg = cause({"code": "xg_against", "xg_home": 0.7, "xg_away": 2, "score": "1-0", "effect": "against"})
    assert (xg.xg_home, xg.xg_away, xg.score) == (0.7, 2.0, "1-0") if xg else False
    assert cause({"code": "early_substitution", "n": True, "effect": "neutral"}) == PostmatchCause(code="early_substitution",
                                                                                                   effect="neutral")


def test_the_most_telling_fact_comes_first() -> None:
    raw = [{"code": "cards_above_referee", "cards": 9, "referee_avg": 4.1, "effect": "neutral"},
           {"code": "xg_supported", "effect": "for"},
           {"code": "early_goal", "minute": 8, "side": "home", "effect": "for"},
           {"code": "red_card", "minute": 70, "side": "home", "effect": "for"},
           {"code": "red_card", "minute": 30, "side": "away", "effect": "against"},
           "not a cause", {"code": "nope", "effect": "for"}]
    assert [(c.code, c.minute) for c in causes_of(raw)] == [
        ("red_card", 30), ("red_card", 70), ("early_goal", 8), ("xg_supported", None), ("cards_above_referee", None)]
    assert causes_of(None) == [] and causes_of({"code": "red_card"}) == []


def test_a_pick_is_explained_only_by_a_post_mortem_of_its_own_settlement() -> None:
    explained = published_pick(row("win"), pm("win", [{"code": "early_goal", "minute": 9, "side": "home", "effect": "for"}]))
    assert (explained.analysed, explained.p_close, [c.code for c in explained.causes]) == (True, Decimal("0.52"), ["early_goal"])
    assert explained.analysed_at == AT
    for result, settled in (("win", "loss"), (None, "win"), ("pending", "win")):
        p = published_pick(row(result), pm(settled, [{"code": "red_card", "effect": "for"}]))
        assert (p.analysed, p.p_close, p.causes, p.analysed_at) == (False, None, [], None), (result, settled)
    alone = published_pick(row("loss"), None)
    assert (alone.result, alone.analysed) == ("loss", False)
    odd = published_pick(row("lost"), pm("lost"))
    assert odd.result is None and not odd.analysed, "a result the settlement does not use is no result"


def test_the_answer_has_no_field_for_what_a_post_mortem_judges() -> None:
    judged = {"verdict", "loss_class", "decision_quality", "quality", "review_verdict", "review_decision", "clv", "price_move", "answers",
              "evidence", "odds", "close_odds", "text", "roles"}
    for model in (PostmatchPick, PostmatchCause):
        assert not judged & set(model.model_fields), model.__name__


def test_the_lines_of_a_pick_and_its_post_mortem_meet_whatever_their_scale() -> None:
    assert postmatch._key("OU", "Over", Decimal("2.50")) == postmatch._key("OU", "Over", Decimal("2.5"))
    assert postmatch._key("1X2", "Home", Decimal("0.00")) == postmatch._key("1X2", "Home", 0)
    assert postmatch._key("AH", "Home", Decimal("-0.50")) == postmatch._key("AH", "Home", Decimal("-0.5"))
