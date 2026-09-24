"""LLM -> tools -> product API. The analyst answers from tool results, and says which.

The loop is the standard tool-use one: the model asks for tools, the tools
run read-only against the database, their results go back, until the model
answers. The answer is then checked: every number in it must appear in some
tool result, or it is listed as unverified next to the answer.

Configuration comes from the environment and never reaches a client:
FBI_ANALYST_API_KEY, FBI_ANALYST_MODEL and optionally FBI_ANALYST_BASE_URL.
Without a key the analyst reports that it is not configured; the tools still
work on their own.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from fbi.analyst.tools import TOOLS, ToolError, run_tool
from fbi.api.repositories import Conn

MAX_ROUNDS = 6
MAX_QUESTION = 1000
ANTHROPIC_VERSION = "2023-06-01"

SYSTEM_PROMPT = """You are the research analyst of a private football-data platform.
Rules you never break:
- Every number you state must come from a tool result in this conversation. Cite it as [T<n>], the id of the tool
  call it came from. If a tool says a value is missing, insufficient or not available, say so; never estimate it.
- Model probabilities are probabilities, not confidence. Say how the model compares with the de-vigged market
  (get_model_evaluation) before drawing any conclusion from a model number.
- Picks are shadow research output. Publishing is disabled. You never recommend placing a bet, a stake, or a
  bookmaker. You may describe what a pick is and why the rule selected or rejected it.
- 'closing' in the historical market is the second source's label; the platform's own near-close capture is not a
  closing line.
Answer briefly, in the language of the question."""


@dataclass(frozen=True, slots=True)
class AnalystConfig:
    api_key: str | None
    model: str | None
    base_url: str

    @classmethod
    def from_env(cls) -> AnalystConfig:
        key = os.environ.get("FBI_ANALYST_API_KEY") or None
        model = os.environ.get("FBI_ANALYST_MODEL") or None
        return cls(key, model, os.environ.get("FBI_ANALYST_BASE_URL", "https://api.anthropic.com").rstrip("/"))

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    @property
    def missing(self) -> list[str]:
        return [name for name, v in (("FBI_ANALYST_API_KEY", self.api_key), ("FBI_ANALYST_MODEL", self.model))
                if not v]


@dataclass
class ToolCall:
    id: str
    tool: str
    arguments: dict[str, Any]
    ok: bool
    result: dict[str, Any] | None
    error: str | None = None


@dataclass
class AnalystAnswer:
    text: str
    calls: list[ToolCall] = field(default_factory=list)
    unverified_figures: list[str] = field(default_factory=list)
    rounds: int = 0
    stopped: str | None = None


MINUS = "\u2212"  # the typographic minus the web app renders
_NUMBER = re.compile(r"(?<![\w.])[-+\u2212]?\d+(?:[.,]\d+)?%?")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        n = raw.replace(MINUS, "-").replace(",", ".").rstrip("%").lstrip("+")
        out.add(n)
    return out


def unverified_figures(answer: str, calls: list[ToolCall]) -> list[str]:
    """Numbers in the answer that no tool result contains - by value, allowing a
    percentage shown for a stored fraction (54.2% for 0.542) and rounding to
    the displayed precision. Citation ids ([T3]) and small counting words are ignored."""
    corpus = " ".join(json.dumps(c.result, default=str) for c in calls if c.result is not None)
    stored = {float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", corpus)}
    cited = set(re.findall(r"\[T(\d+)\]", answer))
    flagged = []
    for n in sorted(_numbers(re.sub(r"\[T\d+\]", " ", answer))):
        try:
            v = float(n)
        except ValueError:
            continue
        if n in cited or (v.is_integer() and 0 <= v <= 10):
            continue
        decimals = len(n.split(".", 1)[1]) if "." in n else 0
        tol = 0.5 * 10 ** (-decimals)
        if any(abs(s - v) <= tol or abs(s * 100 - v) <= tol for s in stored):
            continue
        flagged.append(n)
    return flagged


class AnalystAgent:
    def __init__(self, conn: Conn, config: AnalystConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self._conn = conn
        self._config = config
        self._http = httpx.Client(base_url=config.base_url, timeout=60.0, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _call_model(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        assert self._config.api_key and self._config.model
        r = self._http.post("/v1/messages", headers={
            "x-api-key": self._config.api_key, "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json"}, json={
            "model": self._config.model, "max_tokens": 1200, "system": SYSTEM_PROMPT,
            "tools": [t.spec() for t in TOOLS.values()], "messages": messages})
        if r.status_code != 200:
            # Status only: the body can echo the request, and the request carries the key's owner.
            raise RuntimeError(f"LLM call failed with HTTP {r.status_code}")
        body: dict[str, Any] = r.json()
        return body

    def ask(self, question: str) -> AnalystAnswer:
        question = question.strip()
        if not question or len(question) > MAX_QUESTION:
            raise ValueError(f"a question is 1 to {MAX_QUESTION} characters")
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        answer = AnalystAnswer(text="")
        for rnd in range(1, MAX_ROUNDS + 1):
            answer.rounds = rnd
            reply = self._call_model(messages)
            content = reply.get("content") or []
            uses = [c for c in content if c.get("type") == "tool_use"]
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            if not uses:
                answer.text = text
                break
            messages.append({"role": "assistant", "content": content})
            results = []
            for use in uses:
                cid = f"T{len(answer.calls) + 1}"
                args = use.get("input") or {}
                try:
                    res = run_tool(self._conn, str(use.get("name")), dict(args))
                    res["citation"] = cid
                    answer.calls.append(ToolCall(cid, str(use.get("name")), dict(args), True, res))
                    body = json.dumps(res, default=str)[:60_000]
                    results.append({"type": "tool_result", "tool_use_id": use.get("id"), "content": body})
                except ToolError as exc:
                    answer.calls.append(ToolCall(cid, str(use.get("name")), dict(args), False, None, str(exc)))
                    results.append({"type": "tool_result", "tool_use_id": use.get("id"), "is_error": True,
                                    "content": f"{cid}: {exc}"})
            messages.append({"role": "user", "content": results})
        else:
            answer.stopped = f"no answer after {MAX_ROUNDS} tool rounds"
        answer.unverified_figures = unverified_figures(answer.text, answer.calls)
        return answer
