"""The one validator every answer of a model meets before anything of it is kept (IA-064, plan piece AD-A02): ``output-guard-v1``.

WHY. Each agent and each generator of text already reads its answer its own way (``fbi.ai.contracts.parse``, a Pydantic model, a verifier of
sentences). Those readers differ: some are strict, some are lenient on purpose (``fbi.ai.brief.lenient`` fits a 512-character summary into 500),
and a lenient reader that drops an unknown key is a reader that ACCEPTS an answer outside its schema. This module is the common floor under all
of them, applied where every call comes back - ``fbi.ai.usage.call_json`` (real time) and ``fbi.ai.batch._resolve`` (the Message Batches API) -
so that no caller can forget it:

1. CLOSED SCHEMA (``check``). The answer is compared with the very schema the request sent: an object where the schema says object, every
   property present, no property the schema does not list (``additionalProperties: false`` is the rule, whatever the schema says), the JSON
   type of every value (a boolean is not a number, ``"3"`` is not an integer), every enum value one of its list, ``minItems``. Bounds of length
   and of count are NOT checked here: the caller's reader checks or fits them, as it always did (that is accepted behaviour, not invalid output).
2. NO FREE TEXT WITHOUT SUPPORT (``SURFACES``, ``text_problems``). Every string of an output schema that is not an enum is FREE TEXT, and each one
   of every surface is declared here with what supports it (``Coverage``): a literal quote the server finds again in what it sent (``quote``),
   references the server checks exist (``refs``), facts of the server's own list checked sentence by sentence (``facts``), numbers checked
   against the input (``numbers``), an identifier or a date the server resolves against its own list (``id``, ``date``) - or, for the prose
   kept only for the owner's analysis, the shape verifier ``text-guard-v1`` alone (``shape``: no link, no markup, no order to a machine, no
   control character). ``shape`` says the text is safe to keep, NOT that it is true; the list of such fields is in the owner's guide.
   ``text-guard-v1`` runs on every prose field (``shape``, ``refs``, ``facts``, ``numbers``); a quote is a page's own words and has its verifier.
3. FAIL CLOSED. An answer that fails 1 or 2 is not handed to its caller: ``call_json`` returns it as ``invalid_output`` (the code every caller
   already handles: the provider says it when the model did not submit its tool) and the batch hands its handler the same ``ProviderError``.
4. THE LOG OF REJECTIONS. The ledger row of the call (``ai.usage``, append-only) says ``status = 'invalid_output'`` and ``error =
   'output_guard: <reason>@<path>; ...'`` - the closed ``Reason`` and the path in the SCHEMA's names, never a value and never a key the model
   invented (an answer may be an attacker's). The surface's own table keeps what it always kept (the agents' runs, the readers' narratives...).
5. NO SECOND PAYMENT FOR AN INVALID INPUT (``Repeat``). Before a call, a surface marked ``ledger`` looks in ``ai.usage`` for an answer of the same
   prompt, the same input, the same model and the same workspace that came back ``invalid_output`` in the last ``REPEAT_DAYS`` days: the call is
   not made (nothing is paid, no row) and the caller gets ``invalid_output``.

MODES (``FBI_AI_OUTPUT_GUARD``, ``AiSettings.output_guard``). ``default``: every surface in its own mode - ``enforce`` for the surfaces whose
output reaches no view of a person (the agents of the shadow, the extractors of research v2 and of the quarantine, the LAB), ``shadow`` for those
that do (the brief, the pick review, the narratives, the post-mortems, ``extract-v1``): in ``shadow`` nothing is refused and the ledger row of
the call carries ``output_guard(shadow): ...``, so the owner sees what ``enforce`` would refuse before it does. ``shadow`` (the word): every
surface in shadow - the switch that takes the guard back. ``enforce``: every surface refuses. Any other word is ``default``. A PINNED request
(an experiment: the battery, the replay bank, the probes) is never touched: what it measures is the model's raw answer.

What this is not: a reader of meaning. It does not know whether a reference supports a sentence - the surface's own verifier does - and a
surface is only as safe as the coverage it declares; ``tests/unit/test_ai_outputs.py`` holds every model call of ``backend/src/fbi`` to this
list, every schema to the closed form and every free-text field to a declared coverage.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import cache
from typing import Any, Final, Literal, get_args

from fbi.ai import commands

VERSION: Final = "output-guard-v1"
TEXT_VERSION: Final = "text-guard-v1"

Reason = Literal[
    "not_an_object", "missing_field", "extra_field", "wrong_type", "not_in_enum", "too_few_items", "too_deep",
    "text_link", "text_markup", "text_order", "text_control", "repeat_after_invalid"]
"""Why an answer is refused - a closed list: the ledger never carries anything else."""
REASONS: Final[tuple[str, ...]] = get_args(Reason)

Coverage = Literal["quote", "refs", "facts", "numbers", "id", "date", "shape"]
COVERAGES: Final[tuple[str, ...]] = get_args(Coverage)
PROSE: Final = frozenset({"shape", "refs", "facts", "numbers"})
"""The coverages of text a model writes in its own words: ``text-guard-v1`` reads them."""

Mode = Literal["enforce", "shadow", "observe"]
Switch = Literal["default", "shadow", "enforce"]
SWITCHES: Final[tuple[str, ...]] = get_args(Switch)
Repeat = Literal["ledger", "retry_once", "experiment"]
"""How a surface avoids paying twice for an input that got an invalid answer: ``ledger`` (the check of rule 5), ``retry_once`` (the brief asks
once more, told what was wrong - accepted behaviour of ``brief-v8``, kept, and its own table then never asks that input again) or ``experiment``
(a measurement asks on purpose)."""

MAX_DEPTH: Final = 12
REPEAT_DAYS: Final = 14
SHADOW_PREFIX: Final = "output_guard(shadow): "
ENFORCE_PREFIX: Final = "output_guard: "


def switch_of(raw: str | None) -> Switch:
    """``FBI_AI_OUTPUT_GUARD``: only ``shadow`` and ``enforce`` move the guard off ``default``; a typo is ``default``."""
    value = (raw or "").strip().lower()
    return "shadow" if value == "shadow" else "enforce" if value == "enforce" else "default"


# ── 1. the closed schema ─────────────────────────────────────────────────────────────────────────────────────────

_JSON_TYPES: Final = {"object", "array", "string", "integer", "number", "boolean", "null"}


def _is(value: Any, kind: str) -> bool:
    if kind == "null":
        return value is None
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if kind == "array":
        return isinstance(value, list)
    if kind == "object":
        return isinstance(value, dict)
    return False


def _types(node: Mapping[str, Any]) -> tuple[str, ...]:
    t = node.get("type")
    if isinstance(t, str):
        return (t,)
    if isinstance(t, list):
        return tuple(str(x) for x in t)
    if "properties" in node:
        return ("object",)
    return ()


def _walk(node: Any, value: Any, path: str, depth: int, out: list[str],
          texts: list[tuple[str, str]]) -> None:
    """Check ``value`` against ``node``; the problems go to ``out`` (``reason@path``) and every free-text string to ``texts``."""
    if depth > MAX_DEPTH:
        out.append(f"too_deep@{path or 'answer'}")
        return
    if not isinstance(node, Mapping):
        return
    if "anyOf" in node and isinstance(node["anyOf"], list):
        trials: list[tuple[list[str], list[tuple[str, str]]]] = []
        for branch in node["anyOf"]:
            o: list[str] = []
            t: list[tuple[str, str]] = []
            _walk(branch, value, path, depth + 1, o, t)
            if not o:
                texts.extend(t)
                return
            trials.append((o, t))
        out.extend(trials[0][0] if trials else [f"wrong_type@{path or 'answer'}"])
        return
    kinds = _types(node)
    if kinds and not any(_is(value, k) for k in kinds):
        out.append(f"wrong_type@{path or 'answer'}")
        return
    if "enum" in node and isinstance(node["enum"], list):
        if not any(value == e and type(value) is type(e) for e in node["enum"]):
            out.append(f"not_in_enum@{path or 'answer'}")
        return
    if isinstance(value, dict):
        raw = node.get("properties")
        props: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        for name, child in props.items():
            where = f"{path}.{name}" if path else name
            if name not in value:
                out.append(f"missing_field@{where}")
            else:
                _walk(child, value[name], where, depth + 1, out, texts)
        if "properties" in node and any(k not in props for k in value):  # an object with no properties listed constrains nothing,
            out.append(f"extra_field@{path or 'answer'}")                  # like ``{}`` - and no output schema is one (closed_problems)
    elif isinstance(value, list):
        least = node.get("minItems")
        if isinstance(least, int) and len(value) < least:
            out.append(f"too_few_items@{path or 'answer'}")
        items = node.get("items")
        for v in value:
            _walk(items, v, f"{path}[]", depth + 1, out, texts)
    elif isinstance(value, str) and ("string" in kinds or not kinds):
        texts.append((path, value))


def check(schema: Mapping[str, Any], data: Any) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
    """The problems of ``data`` against ``schema`` (``reason@path``, deduplicated, in order) and its free-text strings ``(path, text)``.
    An empty schema (``{}``) constrains nothing. Never raises."""
    out: list[str] = []
    texts: list[tuple[str, str]] = []
    if schema and not isinstance(data, dict):
        return ("not_an_object@answer",), ()
    try:
        _walk(schema, data, "", 0, out, texts)
    except RecursionError:
        out.append("too_deep@answer")
    return tuple(dict.fromkeys(out)), tuple(texts)


def closed_problems(schema: Mapping[str, Any]) -> list[str]:
    """What keeps a schema from being CLOSED: an object without ``additionalProperties: false``, a property not required, an object without
    properties, a node without a type. Empty for every output schema of PrediGol (a test holds it)."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            found.append(f"not_a_schema@{path or 'answer'}")
            return
        if "anyOf" in node:
            for b in node["anyOf"]:
                walk(b, path)
            return
        kinds = _types(node)
        if not kinds and "enum" not in node:
            found.append(f"untyped@{path or 'answer'}")
        if any(k not in _JSON_TYPES for k in kinds):
            found.append(f"unknown_type@{path or 'answer'}")
        if "object" in kinds:
            props = node.get("properties")
            if not isinstance(props, Mapping) or not props:
                found.append(f"open_object@{path or 'answer'}")
                return
            if node.get("additionalProperties") is not False:
                found.append(f"open_object@{path or 'answer'}")
            if set(node.get("required") or ()) != set(props):
                found.append(f"optional_field@{path or 'answer'}")
            for name, child in props.items():
                walk(child, f"{path}.{name}" if path else name)
        if "array" in kinds:
            walk(node.get("items"), f"{path}[]")

    walk(schema, "")
    return found


def free_text_paths(schema: Mapping[str, Any]) -> list[str]:
    """Every path of a schema whose value is a string with no enum: what a model writes in its own words (or as a token of its own)."""
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            return
        if "anyOf" in node:
            for b in node["anyOf"]:
                walk(b, path)
            return
        kinds = _types(node)
        if "enum" in node:
            return
        if "string" in kinds:
            found.append(path)
        if "object" in kinds:
            for name, child in (node.get("properties") or {}).items():
                walk(child, f"{path}.{name}" if path else name)
        if "array" in kinds:
            walk(node.get("items"), f"{path}[]")

    walk(schema, "")
    return list(dict.fromkeys(found))


# ── 2. text-guard-v1 ─────────────────────────────────────────────────────────────────────────────────────────────

_LINK: Final = re.compile(r"(?i)\bhttps?://|\bmailto:|\]\(\s*[a-z/#.]|\bjavascript:|\bdata:[a-z]+/")
"""An address: a scheme or a markdown link. A source NAMED in prose («según Marca», «goal.com», «www.maxifoot.fr») is not one: on 16-nov-2026
the only finding of a bare ``www.`` in 437 stored narratives was a rumour attributed to its site, an honest sentence."""
_MARKUP: Final = re.compile(r"<\s*/?\s*[a-zA-Z][a-zA-Z0-9-]*(?:\s[^<>]*)?/?\s*>|!\[|```|<!--|&#x?[0-9a-fA-F]+;")
"""A tag, a markdown image, a fence, an HTML comment or entity."""
_ALLOWED_CONTROL: Final = frozenset("\n\t\r")
_HIDDEN: Final = frozenset("​‌‍‎‏‪‫‬‭‮⁠⁡⁢⁣⁤⁦⁧⁨⁩﻿")
_ORDER_FAMILIES: Final = ("takeover", "tools")
"""Of ``commands-v1``'s families, the two an answer of PrediGol never has a reason to contain: taking over a reader («ignore your
instructions», «SYSTEM:», «you are now») and ordering a tool, a function or a query. The others («the model should...», «mark him as out») are
how an honest post-mortem or a hypothesis talks, and stay with the surface's own reader."""


def _order_in(text: str) -> bool:
    for sentence in commands.sentences(text):
        folded = commands.fold(sentence)
        pieces = [folded, *(p for p in re.split(r"\s*:\s*", folded)[1:] if p)]
        for family in _ORDER_FAMILIES:
            if any(p.search(piece) for p in commands.FAMILIES[family] for piece in pieces):
                return True
    return False


def text_problems(text: str, coverage: Coverage) -> tuple[str, ...]:
    """What ``text-guard-v1`` finds in one string (reasons without the path). A control or invisible character is refused in every free text;
    links, markup and orders only in prose (a quote is a page's own words, an id or a date is a token: their verifiers read them)."""
    found: list[str] = []
    if any((unicodedata.category(c) == "Cc" and c not in _ALLOWED_CONTROL) or c in _HIDDEN for c in text):
        found.append("text_control")
    if coverage in PROSE:
        if _LINK.search(text):
            found.append("text_link")
        if _MARKUP.search(text):
            found.append("text_markup")
        if _order_in(text):
            found.append("text_order")
    return tuple(found)


# ── the surfaces ─────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Surface:
    """One schema a model answers in, where it is asked, what of it is kept and how each of its free texts is supported."""

    name: str
    versions: tuple[str, ...]
    """The prompt versions asked with this schema (what ``ai.usage.prompt_version`` says)."""
    sites: tuple[str, ...]
    """``module:function`` of every place that builds the request or makes the call (the static test finds them)."""
    schema: Callable[[], Mapping[str, Any]]
    reader: bool
    """Its output reaches a view of a person (a reader's page or an admin view): ``default`` mode ``shadow``. Otherwise ``enforce``."""
    keeps: str
    """Where what stands of an answer is kept."""
    texts: Mapping[str, Coverage]
    repeat: Repeat = "ledger"
    note: str = ""

    @property
    def default(self) -> Mode:
        return "shadow" if self.reader else "enforce"


def _contract(name: str) -> Callable[[], Mapping[str, Any]]:
    def get() -> Mapping[str, Any]:
        from fbi.ai.contracts import schema_of

        return schema_of(name)
    return get


def _attr(module: str, attr: str) -> Callable[[], Mapping[str, Any]]:
    def get() -> Mapping[str, Any]:
        import importlib

        value = getattr(importlib.import_module(module), attr)
        assert isinstance(value, Mapping)
        return value
    return get


_REFS_TEXT: Final[dict[str, Coverage]] = {"text": "refs", "refs[]": "id"}
_FACTS_TEXT: Final[dict[str, Coverage]] = {"text": "facts", "facts[]": "id"}


def _claims(*groups: str) -> dict[str, Coverage]:
    out: dict[str, Coverage] = {}
    for g in groups:
        out |= {f"{g}.{k}": v for k, v in _REFS_TEXT.items()}
    return out


_NARRATIVE_SECTIONS: Final = ("como_llega_local", "como_llega_visitante", "que_esta_en_juego", "claves_tacticas", "jugadores_importantes",
                              "riesgos", "mercados_interesantes", "conclusion")

SURFACES: Final[tuple[Surface, ...]] = (
    Surface("extract-v1", ("extract-v1",), ("fbi.ai.collectors:extract_request", "fbi.ai.collectors:collect_web"),
            _attr("fbi.ai.prompts", "EXTRACT_SCHEMA"), True, "evidence (the production packet reads it)",
            {"items[].result_id": "id", "items[].player": "id", "items[].claim": "shape", "items[].published_at": "date"},
            note="items[].claim is prose with no quote: the reason AD-A01 replaces it with extract-v4 (claim-v2, a checked quote)"),
    Surface("claim-v1", ("extract-v3",), ("fbi.ai.extract_v2:request", "fbi.ai.entity_research:_extract"),
            _contract("claim-v1"), False, "evidence (research v2, shadow)",
            {"claims[].quote": "quote", "claims[].page_id": "id", "claims[].published_on": "date"}),
    Surface("claim-v2", ("extract-v4",), ("fbi.ai.quarantine:request", "fbi.ai.quarantine:collect.ask"),
            _contract("claim-v2"), False, "evidence only under FBI_AI_EXTRACTOR=quarantine; counts in fixture_passes",
            {"call": "id", "claims[].quote": "quote"}),
    Surface("aa-v1", ("match-context-v4", "match-assess-v3", "stats-assess-v3"),
            ("fbi.ai.agents.match:_request", "fbi.ai.agents.stats:evaluation_request"),
            _contract("aa-v1"), False, "agent_runs (LAB shadow)",
            {"signals[].refs[]": "id", "candidates[].candidate": "id", "candidates[].refs[]": "id", "research[].refs[]": "id"}),
    Surface("pa-v1", ("player-assess-v1",), ("fbi.ai.agents.player:evaluation_request",),
            _contract("pa-v1"), False, "agent_runs (LAB shadow, agent off)",
            {"signals[].refs[]": "id", "candidates[].candidate": "id", "candidates[].refs[]": "id"}),
    Surface("cd-v1", ("council-v1", "council-opus-v1"), ("fbi.ai.agents.council:council_request",),
            _contract("cd-v1"), False, "agent_runs (LAB shadow)",
            {"verdicts[].candidate": "id", "verdicts[].refs[]": "id", "research[].refs[]": "id"}),
    Surface("pmr-v1", ("pmr-v1",), ("fbi.ai.agents.pmr:request_of", "fbi.ai.agents.pmr:task_of"),
            _contract("pmr-v1"), False, "agent_runs, attribution (LAB, admin view)",
            {"attributions[].candidate": "id", "attributions[].refs[]": "id", "narrative": "shape"},
            note="narrative: prose marked untrusted, never operational, never measured (fbi.ai.contracts.postmatch)"),
    Surface("la-v1", ("la-v1",), ("fbi.ai.agents.analyst:request_of", "fbi.ai.agents.analyst:task_of"),
            _contract("la-v1"), False, "agent_runs (LAB, hypotheses for the owner)",
            {"hypotheses[].title": "shape", "hypotheses[].hypothesis": "shape", "hypotheses[].rationale": "shape",
             "hypotheses[].agent_version": "id"},
            note="hypotheses: prose for the owner, untrusted, never operational"),
    Surface("brief-v8", ("brief-v8",), ("fbi.ai.brief:make_brief",),
            _attr("fbi.ai.prompts", "BRIEF_SCHEMA"), True, "match_briefs",
            {"summary": "shape", **_claims("context[]", "changes[]", "cards[].why[]", "cards[].risks[]", "research[].why"),
             "injuries[].player": "refs", "injuries[].refs[]": "id", "cards[].market": "id", "cards[].selection": "id", "cards[].line": "id",
             **{f"narrative.{k}": "numbers" for k in _NARRATIVE_SECTIONS}},
            repeat="retry_once",
            note="summary: prose without a reference (brief-v8 is retired by the single chronicle, AD-F02); narrative: numbers checked"),
    Surface("review-v2", ("review-v2",), ("fbi.ai.review:review_request", "fbi.ai.review:llm_review"),
            _attr("fbi.ai.claims", "REVIEW_SCHEMA"), True, "pick_reviews",
            {**_claims("positive_evidence[]", "negative_evidence[]", "uncertainties[]", "contradictions[]"), "reason": "shape"},
            note="reason: replaced by the server's own when the decision is recomputed (fbi.ai.claims, fbi.ai.review)"),
    Surface("postmortem-v3", ("postmortem-v3",), ("fbi.ai.postmortem:run_postmortems",),
            _attr("fbi.ai.prompts", "POSTMORTEM_SCHEMA"), True, "postmortems (admin view)",
            {"summary": "shape", "lessons[]": "shape"}),
    Surface("pick-postmortem-v4", ("pick-postmortem-v4",),
            ("fbi.ai.pick_postmortem:run_pick_postmortems", "fbi.ai.pm_narratives:run_narratives"),
            _attr("fbi.ai.prompts", "PICK_PM_SCHEMA"), True, "pick_postmortems, postmortem_narratives",
            {"summary": "shape", "lessons[]": "shape"}),
    Surface("learning-v2", ("learning-v2",), ("fbi.ai.learning:learn_day",),
            _attr("fbi.ai.prompts", "LEARNING_SCHEMA"), True, "learning_notes (admin view)",
            {"lessons[].title": "shape", "lessons[].body": "shape"}),
    Surface("patterns-v1", ("patterns-v1",), ("fbi.ai.patterns:run_patterns",),
            _attr("fbi.ai.patterns", "AI_SCHEMA"), False, "the report of the job (hypotheses for the owner)",
            {"hypotheses[].title": "shape", "hypotheses[].hypothesis": "shape", "hypotheses[].rationale": "shape"}),
    Surface("narrative", ("user-narrative-v3",), ("fbi.narrative.job:narrate",),
            _attr("fbi.narrative.job", "SCHEMA"), True, "user_narratives, evidence_translations",
            {**{f"{lang}.{sec}[].{k}": v for lang in ("es", "en") for sec in ("summary", "home", "away", "h2h", "risks")
                for k, v in _REFS_TEXT.items()},
             "news[].headline_es": "numbers", "news[].headline_en": "numbers", "news[].claim_en": "numbers"}),
    Surface("pick-why-v1", ("pick-why-v1",), ("fbi.narrator.prompt:request", "fbi.narrator.job:caller.call"),
            _attr("fbi.narrator.prompt", "SCHEMA"), True, "the narrator's report (FBI_NARRATOR)",
            {f"{lang}.{part}[].{k}": v for lang in ("es", "en") for part in ("why", "risks")
             for k, v in _FACTS_TEXT.items()}),
    Surface("lab-probe", ("probe-cache-v1", "probe-schema-v1"),
            ("fbi.ai.lab:probe_request", "fbi.ai.lab:probe_cache", "fbi.ai.lab:probe_schema", "fbi.ai.lab:probe_batch_tasks"),
            _attr("fbi.ai.lab", "PROBE_SCHEMA"), False, "feature_gates (the probe's verdict only)", {}, repeat="experiment"),
)
"""Every schema a model answers in, in ``backend/src/fbi``. A new call is a new row here (the static test refuses one that is not)."""

ROUTES: Final[dict[str, str]] = {
    "fbi.ai.usage:call_json": "the chokepoint of real time: the guard runs here",
    "fbi.ai.batch:_resolve": "the chokepoint of the Message Batches API: the guard runs here (the request it builds only decodes)",
    "fbi.ai.orchestrator:_Runner.ask.call": "carries the agents' requests (aa-v1, pa-v1, cd-v1) to call_json",
    "fbi.ai.orchestrator:_Runner.batch_add": "carries the agents' requests to the batch",
    "fbi.ai.battery.run:task_of": "the battery: pinned requests (an experiment), never altered",
    "fbi.ai.battery.v4_run:task_of": "battery-v4 (IA-065): pinned requests (an experiment), never altered",
    "fbi.ai.battery.simulate:simulate": "the battery offline: a fake provider, nothing kept",
    "fbi.ai.replay.harness:task_of": "the replay bank: pinned requests (an experiment), never altered",
    "fbi.ai.lab:equivalence_tasks": "the equivalence experiment of the LAB: pinned requests",
    "fbi.ai.providers.fake:FakeBatches._request": "the fake provider of the tests",
}
"""The places that make or carry a call without choosing its schema."""

BY_NAME: Final[dict[str, Surface]] = {s.name: s for s in SURFACES}


def fingerprint(schema: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                                     default=str).encode()).hexdigest()[:16]


@cache
def _by_fingerprint() -> dict[str, Surface]:
    return {fingerprint(s.schema()): s for s in SURFACES}


def surface_of(schema: Mapping[str, Any]) -> Surface | None:
    """The surface whose schema is ``schema``, or None for a schema nobody declared."""
    try:
        return _by_fingerprint().get(fingerprint(schema))
    except (ImportError, AssertionError, TypeError, ValueError):
        return None


def mode_of(switch: str, surface: Surface | None, *, pinned: bool) -> Mode:
    """``observe`` for an experiment; otherwise the switch, or the surface's own mode. A schema nobody declared is enforced: fail closed."""
    if pinned:
        return "observe"
    if switch == "shadow":
        return "shadow"
    if switch == "enforce" or surface is None:
        return "enforce"
    return surface.default


# ── the verdict ──────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Verdict:
    """What the guard says of one answer: its problems (``reason@path``) and the mode it was read in."""

    mode: Mode
    surface: str | None
    problems: tuple[str, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def refuses(self) -> bool:
        """The answer is NOT handed to its caller."""
        return bool(self.problems) and self.mode == "enforce"

    def error(self) -> str | None:
        """What the ledger row says: ``output_guard: ...`` when refused, ``output_guard(shadow): ...`` when only seen, else None."""
        if not self.problems or self.mode == "observe":
            return None
        return (ENFORCE_PREFIX if self.mode == "enforce" else SHADOW_PREFIX) + "; ".join(self.problems)


def _coverage(surface: Surface | None, path: str) -> Coverage:
    if surface is None:
        return "shape"
    return surface.texts.get(path, "shape")


def guard(schema: Mapping[str, Any], data: Any, *, switch: str = "default", pinned: bool = False) -> Verdict:
    """Rules 1 and 2 on one answer. Never raises."""
    surface = surface_of(schema)
    mode = mode_of(switch, surface, pinned=pinned)
    name = None if surface is None else surface.name
    if mode == "observe":
        return Verdict(mode, name)
    problems, texts = check(schema, data)
    found = list(problems)
    for path, text in texts:
        found += [f"{r}@{path or 'answer'}" for r in text_problems(text, _coverage(surface, path))]
    return Verdict(mode, name, tuple(dict.fromkeys(found)))


# ── 5. no second payment ─────────────────────────────────────────────────────────────────────────────────────────

REPEAT_SQL: Final = """
SELECT 1 FROM ai.usage
 WHERE at >= %(since)s AND at <= %(at)s AND status = 'invalid_output' AND prompt_version = %(version)s AND input_hash = %(input)s
   AND model = %(model)s AND workspace IS NOT DISTINCT FROM %(workspace)s
 LIMIT 1
"""
"""Uses the index ``ai_usage_at`` (about 9,500 rows in 14 days on 16-nov-2026)."""


def asked_invalid_before(conn: Any, *, at: datetime, prompt_version: str, input_hash: str, model: str,
                         workspace: str | None) -> bool:
    """Whether the same input of the same prompt, to the same model and workspace, got an invalid answer in the last ``REPEAT_DAYS`` days."""
    if not prompt_version or not input_hash or getattr(conn, "cursor", None) is None:
        return False  # no input to recognise, or no database (a pure test)
    with conn.cursor() as cur:
        cur.execute(REPEAT_SQL, {"since": at - timedelta(days=REPEAT_DAYS), "at": at, "version": prompt_version,
                                 "input": input_hash, "model": model, "workspace": workspace})
        return cur.fetchone() is not None


def repeat_policy(schema: Mapping[str, Any]) -> Repeat:
    surface = surface_of(schema)
    return "ledger" if surface is None else surface.repeat


__all__ = ["BY_NAME", "COVERAGES", "REASONS", "ROUTES", "SURFACES", "SWITCHES", "TEXT_VERSION", "VERSION", "Surface", "Verdict",
           "asked_invalid_before", "check", "closed_problems", "fingerprint", "free_text_paths", "guard", "mode_of", "repeat_policy",
           "surface_of", "switch_of", "text_problems"]
