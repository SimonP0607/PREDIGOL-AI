"""A provider that never leaves the machine: tests, and dry runs that measure how many tokens a real
model would read and write (``fbi.ai.costs.simulate``). It answers with a scripted function of the
request, and counts tokens the way the planning estimate does (about four characters a token).
``FakeBatches`` is the same for the Message Batches API: a batch that ends when the test says so."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from fbi.ai.pricing import approx_tokens
from fbi.ai.providers.anthropic import AnthropicBatches, BatchResult
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage, ProviderError

Script = Callable[[JsonRequest], dict[str, Any]]
UsageScript = Callable[[JsonRequest, LlmUsage], LlmUsage]
"""Given the request and the usage counted by the estimate, the usage the "provider" bills: to script cache writes and reads,
thinking tokens - what a real API reports and the estimate cannot know."""


class FakeProvider:
    def __init__(self, script: Script, *, name: str = "fake", fail: str | None = None,
                 output_tokens: int | None = None, usage: UsageScript | None = None,
                 limit: str | None = None) -> None:
        self.name = name
        self._script = script
        self._fail = fail
        self._output_tokens = output_tokens
        self._usage = usage
        self._limit = limit
        self.requests: list[JsonRequest] = []

    def complete_json(self, model: str, request: JsonRequest) -> LlmResult:
        self.requests.append(request)
        if self._limit is not None:  # a spent workspace limit ("workspace_limit") or tier cap ("tier_cap")
            raise ProviderError("limit_reached", "scripted spend limit", status=400 if self._limit == "workspace_limit" else 429,
                                limit_kind=self._limit, request_id="req_fake")
        if self._fail is not None:
            raise ProviderError(self._fail, f"scripted failure: {self._fail}")  # type: ignore[arg-type]
        data = self._script(request)
        text_in = request.system + request.user_text + json.dumps(request.schema)
        out_tokens = self._output_tokens if self._output_tokens is not None else approx_tokens(json.dumps(data))
        counted = LlmUsage(input_tokens=approx_tokens(text_in), output_tokens=out_tokens)
        return LlmResult(data, counted if self._usage is None else self._usage(request, counted),
                         self.name, model, latency_ms=0)


# ── a Message Batches API that never leaves the machine ──────────────────────────────────────────────────────

class FakeBatches:
    """The Message Batches API as ``fbi.ai.providers.anthropic.AnthropicBatches`` speaks it, simulated: a batch is created
    ``in_progress`` and stays so until the test ends it (``end``), when each of its requests is answered by the script (the same
    kind of function ``FakeProvider`` has) or by the outcome the test scripted for its ``custom_id`` (``outcomes``: ``errored``,
    ``canceled``, ``expired``, ``refused``: a message without the answer, ``cut``: an answer that is not valid JSON for the
    schema). It checks what the real API checks - the ``custom_id`` shape and its being unique in the batch - and it keeps what it
    was asked (``created``, ``polls``) so a test can say exactly what was sent."""

    CUSTOM_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

    def __init__(self, script: Script, *, name: str = "fake", output_tokens: int | None = None,
                 usage: UsageScript | None = None, outcomes: dict[str, str] | None = None,
                 fail_create: str | None = None, limit: str | None = None, fail_results: str | None = None) -> None:
        self.name = name
        self._script = script
        self._output_tokens = output_tokens
        self._usage = usage
        self.outcomes: dict[str, str] = dict(outcomes or {})
        self.fail_create = fail_create
        self.limit = limit
        self.fail_results = fail_results
        self.batches: dict[str, dict[str, Any]] = {}
        self.created: list[list[dict[str, Any]]] = []
        self.polls = 0
        self.fetched: list[str] = []
        self._results: dict[str, list[BatchResult]] = {}

    item = staticmethod(AnthropicBatches.item)

    # the API ------------------------------------------------------------------------------------------------
    def create(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if self.limit is not None:
            raise ProviderError("limit_reached", "scripted spend limit", status=400 if self.limit == "workspace_limit" else 429,
                                limit_kind=self.limit, request_id="req_fake")
        if self.fail_create is not None:
            raise ProviderError(self.fail_create, f"scripted failure: {self.fail_create}")  # type: ignore[arg-type]
        ids = [str(i.get("custom_id")) for i in items]
        if not items or len(set(ids)) != len(ids) or not all(self.CUSTOM_ID.match(i) for i in ids):
            raise ProviderError("refused", "the batch is not valid (empty, a custom_id repeated or not shaped as the API asks)",
                                status=400)
        self.created.append([dict(i) for i in items])
        ref = f"msgbatch_fake_{len(self.batches) + 1:04d}"
        self.batches[ref] = {"id": ref, "type": "message_batch", "processing_status": "in_progress",
                             "request_counts": {"processing": len(items), "succeeded": 0, "errored": 0, "canceled": 0,
                                                "expired": 0},
                             "created_at": "2032-08-01T12:00:00Z", "expires_at": "2032-08-02T12:00:00Z", "ended_at": None,
                             "_items": [dict(i) for i in items]}
        return self._public(ref)

    def get(self, batch_ref: str) -> dict[str, Any]:
        self.polls += 1
        if batch_ref not in self.batches:
            raise ProviderError("refused", "no such batch (HTTP 404)", status=404)
        return self._public(batch_ref)

    def cancel(self, batch_ref: str) -> dict[str, Any]:
        b = self.batches.get(batch_ref)
        if b is None:
            raise ProviderError("refused", "no such batch (HTTP 404)", status=404)
        if b["processing_status"] == "in_progress":
            b["processing_status"] = "canceling"
        return self._public(batch_ref)

    def results(self, batch_ref: str) -> list[BatchResult]:
        self.fetched.append(batch_ref)
        if self.fail_results is not None:
            raise ProviderError(self.fail_results, f"scripted failure: {self.fail_results}")  # type: ignore[arg-type]
        if batch_ref not in self._results:
            raise ProviderError("refused", "the batch has not ended (HTTP 409)", status=409)
        return list(self._results[batch_ref])

    # what a test does -----------------------------------------------------------------------------------------
    def end(self, batch_ref: str | None = None, *, outcomes: dict[str, str] | None = None) -> None:
        """The provider finishes a batch (or every open one): each request gets its result."""
        self.outcomes.update(outcomes or {})
        for ref in [batch_ref] if batch_ref is not None else [r for r, b in self.batches.items()
                                                              if b["processing_status"] != "ended"]:
            b = self.batches[ref]
            canceling = b["processing_status"] == "canceling"
            results = [self._answer(i, canceling) for i in b["_items"]]
            counts = {"processing": 0, "succeeded": 0, "errored": 0, "canceled": 0, "expired": 0}
            for r in results:
                counts[r.kind] += 1
            b["request_counts"], b["processing_status"], b["ended_at"] = counts, "ended", "2032-08-01T12:30:00Z"
            self._results[ref] = results

    def custom_ids(self, batch_ref: str | None = None) -> list[str]:
        refs = [batch_ref] if batch_ref is not None else list(self.batches)
        return [str(i["custom_id"]) for r in refs for i in self.batches[r]["_items"]]

    # internals -----------------------------------------------------------------------------------------------
    def _public(self, ref: str) -> dict[str, Any]:
        return {k: v for k, v in self.batches[ref].items() if not k.startswith("_")}

    def _request(self, params: dict[str, Any]) -> JsonRequest:
        """The ``JsonRequest`` a script reads, rebuilt from a request body (a tool call's name, or the schema of structured outputs)."""
        system = params.get("system")
        if isinstance(system, list):
            system = "".join(str(b.get("text") or "") for b in system)
        content = (params.get("messages") or [{}])[0].get("content")
        texts = [str(b.get("text") or "") for b in content] if isinstance(content, list) else [str(content or "")]
        tools = params.get("tools") or []
        native = ((params.get("output_config") or {}).get("format") or {}).get("schema")
        schema = tools[0]["input_schema"] if tools else native or {}
        return JsonRequest(system=str(system or ""), user=texts[-1], shared="".join(texts[:-1]), schema=schema,
                           schema_name=str(tools[0]["name"]) if tools else str(schema.get("title") or ""),
                           max_tokens=int(params.get("max_tokens") or 0), native_schema=bool(native and not tools))

    def _answer(self, item: dict[str, Any], canceling: bool) -> BatchResult:
        custom_id, params = str(item["custom_id"]), item["params"]
        outcome = self.outcomes.get(custom_id)
        if outcome in ("errored", "expired", "canceled"):
            return BatchResult(custom_id, outcome, error_type="overloaded_error" if outcome == "errored" else None)  # type: ignore[arg-type]
        if canceling and outcome is None:
            return BatchResult(custom_id, "canceled")
        request = self._request(params)
        data = self._script(request)
        text_in = request.system + request.user_text + json.dumps(request.schema)
        out_tokens = self._output_tokens if self._output_tokens is not None else approx_tokens(json.dumps(data))
        counted = LlmUsage(input_tokens=approx_tokens(text_in), output_tokens=out_tokens)
        u = counted if self._usage is None else self._usage(request, counted)
        usage = {"input_tokens": u.input_tokens - u.cached_tokens - u.cache_write_tokens, "output_tokens": u.output_tokens,
                 "cache_read_input_tokens": u.cached_tokens, "cache_creation_input_tokens": u.cache_write_tokens,
                 "cache_creation": {"ephemeral_5m_input_tokens": u.cache_write_5m_tokens,
                                    "ephemeral_1h_input_tokens": u.cache_write_1h_tokens}}
        if outcome == "refused":
            content: list[dict[str, Any]] = [{"type": "text", "text": "I cannot help with that."}]
        elif outcome == "cut":
            content = ([{"type": "text", "text": json.dumps(data)[: max(1, len(json.dumps(data)) // 2)]}]
                       if request.native_schema else [{"type": "tool_use", "name": request.schema_name, "input": "cut"}])
        elif request.native_schema:
            content = [{"type": "text", "text": json.dumps(data)}]
        else:
            content = [{"type": "tool_use", "id": "toolu_fake", "name": request.schema_name, "input": data}]
        message = {"id": f"msg_fake_{custom_id[:12]}", "type": "message", "role": "assistant", "model": params.get("model"),
                   "content": content, "stop_reason": "refusal" if outcome == "refused" else "end_turn", "usage": usage}
        return BatchResult(custom_id, "succeeded", message=message)
