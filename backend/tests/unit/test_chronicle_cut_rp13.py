"""RP-1.3: the single chronicle was cut at its cap of output tokens because the model's thinking counts in that cap.

Measured on 26 Nov 2026 over 14 days of model-written chronicles: 1,108 of 1,589 stopped at exactly 4,000 tokens with ~3,300 spent thinking and
~690 visible; the 481 that fitted had ~2,000 thinking and ~1,500 visible. The fix gives the answer room, tells a cut answer from an invalid one
and asks again what a smaller cap had cut."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.ai.providers.anthropic import read_message
from fbi.ai.providers.base import CUT_PREFIX, JsonRequest, ProviderError
from fbi.chronicle import v4_job, writer

REQ = JsonRequest(system="s", user="u", schema={}, schema_name="submit_chronicle", max_tokens=writer.MAX_TOKENS)


def _message(text: str, stop: str, *, thinking: int = 3300, out: int = 4000) -> dict[str, Any]:
    return {"id": "msg_1", "model": "m", "stop_reason": stop, "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 10, "output_tokens": out, "output_tokens_details": {"thinking_tokens": thinking}}}


def test_the_cap_leaves_room_for_the_thinking_and_the_visible_text() -> None:
    # ~3,300 thinking at the median of the cut ones and ~1,500 visible: twice that and more must fit
    assert writer.MAX_TOKENS >= 8000
    assert writer.request(_input()).max_tokens == writer.MAX_TOKENS
    assert writer.request(_input()).timeout_s >= 120
    assert v4_job.TYPICAL_OUTPUT >= 3500  # what a call is reserved at: thinking included


def test_a_different_cap_is_a_different_input_so_what_a_small_cap_cut_is_asked_again(monkeypatch: pytest.MonkeyPatch) -> None:
    inp = _input()
    before = inp.hash
    monkeypatch.setattr(writer, "MAX_TOKENS", 4000)
    assert inp.hash != before


def test_an_answer_stopped_at_the_cap_says_so() -> None:
    with pytest.raises(ProviderError) as e:
        read_message(_message('{"es": {"que_se_juega": [', "max_tokens"), REQ, "m", native=True, latency_ms=0, request_id=None,
                     long_ttl_asked=True)
    assert e.value.code == "invalid_output" and str(e.value).startswith(CUT_PREFIX)
    assert e.value.usage is not None and e.value.usage.thinking_tokens == 3300  # what was billed is kept


def test_an_unreadable_answer_that_was_not_cut_does_not_say_so() -> None:
    with pytest.raises(ProviderError) as e:
        read_message(_message("not json at all", "end_turn"), REQ, "m", native=True, latency_ms=0, request_id=None, long_ttl_asked=True)
    assert CUT_PREFIX not in str(e.value)


def test_a_tool_answer_that_never_came_because_of_the_cap_says_so_too() -> None:
    out = {"id": "m", "stop_reason": "max_tokens", "content": [{"type": "thinking", "thinking": "..."}],
           "usage": {"input_tokens": 1, "output_tokens": 4000}}
    with pytest.raises(ProviderError) as e:
        read_message(out, REQ, "m", native=False, latency_ms=0, request_id=None, long_ttl_asked=True)
    assert str(e.value).startswith(CUT_PREFIX)


def test_the_job_tells_a_cut_answer_from_its_error() -> None:
    assert v4_job.was_cut(f"invalid_output: {CUT_PREFIX}the model did not submit the answer")
    assert not v4_job.was_cut("invalid_output: the model did not submit the answer")
    assert not v4_job.was_cut(None)


def _input() -> writer.WriterInput:
    from fbi.chronicle import plan as cp
    from tests.unit.test_chronicle_plan import inp

    return writer.WriterInput(cp.build(inp()))


class _Cur:
    def __init__(self, seen: list[dict[str, Any]]) -> None:
        self.seen = seen

    def __enter__(self) -> _Cur:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.seen.append(params)

    def fetchone(self) -> tuple[int]:
        return (7,)


class _Conn:
    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    def cursor(self, **kw: Any) -> _Cur:
        return _Cur(self.seen)


def test_a_cut_answer_is_kept_with_its_mark_and_an_invalid_one_without_it() -> None:
    from datetime import UTC, datetime

    from fbi.chronicle import plan as cp
    from tests.unit.test_chronicle_plan import inp

    plan = cp.build(inp())
    at = datetime(2026, 11, 26, tzinfo=UTC)
    conn = _Conn()
    v4_job.store(conn, plan, at=at, status="invalid_output", route="batch",  # type: ignore[arg-type]
                 error=f"invalid_output: {CUT_PREFIX}the model did not submit the answer")
    v4_job.store(conn, plan, at=at, status="invalid_output", route="batch", error="invalid_output: es.que_se_juega: field required")  # type: ignore[arg-type]
    cut, plain = (c["metrics"].obj for c in conn.seen)
    assert cut["cut"] is True and "cut" not in plain
