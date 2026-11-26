"""The Intelligence console, C-11 (AD-J08, IA-079; ``GET /admin/intelligence/console``): one read-only answer that brings together what the
owner checks first - «nada sale de la sombra», the registry of capabilities, the costs against their envelopes, the safety controls - and
says what does not exist yet (the news engine, the queue of private alerts) with its reason.

It READS and decides nothing: it writes no row, changes no switch and records no gate (the panel's evaluators run the way their scripts run
them without ``--record``). Each block is read in its own savepoint: a block that fails is a ``ReadFailure`` with the class of its error, and
the rest of the console is still served - a database that lacks a table says so here instead of answering 500. The protocols block (IA-143)
reads the register of the owner's signatures of protocols: whether each one is signed in its fingerprint of now; it signs nothing.

Switches are read with the code's own parsers (a typo reads as the default) and shown as the word they read as, never as their raw value:
no key, URL or label can travel. The panel of the gates (about five seconds on production's data, 16 Nov 2026) is kept five minutes per
process; its ``as_of`` says when it was read."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

import psycopg
import structlog

from fbi.ai import capability_budget as caps_budget
from fbi.ai import costs_v3, gates_panel, gates_panel_readers
from fbi.ai.budget_v3 import JOINT_CEILING_PENDING, EnvelopeFigure
from fbi.ai.config import AGENTS, KNOWN_ENGINES, AiSettings
from fbi.ai.gating import enforcement
from fbi.api import switches as reader_switches
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.console import (
    AiEnforcement,
    Battery,
    Capabilities,
    CapabilityCap,
    CapabilityView,
    ConsoleContract,
    ConsoleProtocol,
    ConsoleProtocols,
    CostPart,
    Costs,
    Cycle,
    Declared,
    EnvelopeView,
    Flow,
    FlowStage,
    GateReading,
    Gates,
    GateView,
    JointCeiling,
    LeakAudit,
    LeakRule,
    ReadFailure,
    Schema,
    Security,
    Shadow,
    ShadowBreak,
    StateCount,
    StatusCount,
    SwitchState,
    WorkerLedger,
)
from fbi.api.contracts.intelligence.vocab import CapabilityState
from fbi.api.envelope import Envelope, ok
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.core.clock import now
from fbi.core.config.picks import INTELLIGENCE, PicksSourceSettings
from fbi.core.env import environment
from fbi.intel import capabilities as registry
from fbi.ops import freshness
from fbi.protosign import NOTICE as PROTOCOLS_NOTICE
from fbi.protosign import VERSION as PROTOCOLS_VERSION
from fbi.protosign import store as protocol_signatures

log = structlog.get_logger(__name__)

NO_DATA: Final = Missing(missing_reason="sin_datos")
NEWS_ENGINE: Final = Missing(missing_reason="no_entregado", expected_piece="AD-G01")
ALERT_QUEUE: Final = Missing(missing_reason="no_entregado", expected_piece="AD-D08")
GATES_TTL: Final = timedelta(minutes=5)

STATE_WORDS: Final[dict[str, str]] = {"construida": "construida", "en_sombra": "en_sombra", "lista_para_revision": "lista_revision",
                                      "autorizada": "autorizada"}
"""The registry's states (``fbi.intel.capabilities.STATES``) in the contract's closed list (``CapabilityState``): the registry writes
``lista_para_revision``, the contracts agreed with UX say ``lista_revision``. A state not in this table is an error, never a guess."""

FAMILY_MODES: Final = ("off", "shadow")
"""``FBI_FAMILY_DECISIONS`` as ``fbi.familydecisions.decide.mode`` reads it (held equal by a test: the console does not import the families)."""

CONSOLE_RELATIONS: Final[tuple[str, ...]] = (
    "ai.feature_gates", "ai.shadow_reports", "ai.usage_scoped", "ai.user_usage", "ai.shadow_assignments", "intel.audit_checks",
    "intel.capabilities", "intel.capability_transitions", "intel.family_postmortems", "intel.family_memory", "intel.agent_attributions",
    "picks.picks")
"""Tables the console and the AI pages of the Admin Console read whose absence answers 500: ``ai.shadow_assignments`` (revision 0119),
``intel.family_*`` (0118) and ``intel.agent_attributions`` (0120) are the ones a database behind the code lacked in QA (IA-079)."""

MIGRATIONS: Final = Path(__file__).resolve().parents[4] / "migrations" / "versions"
REVISION = re.compile(r"^revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)[\"']", re.MULTILINE)
DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*[\"']([^\"']+)[\"']", re.MULTILINE)

PUBLISHED_SQL: Final = "SELECT count(*) AS n FROM picks.picks WHERE status IN ('qualified', 'published')"
WORKER_SQL: Final = "SELECT id, at, evidence FROM ai.feature_gates WHERE gate = 'switches' ORDER BY at DESC, id DESC LIMIT 1"
AUDIT_SQL: Final = """
SELECT DISTINCT ON (rule) day, rule, version, n_checked, n_violations
  FROM intel.audit_checks WHERE day = (SELECT max(day) FROM intel.audit_checks)
 ORDER BY rule, checked_at DESC
"""
REVISION_SQL: Final = """
SELECT CASE WHEN to_regclass('public.alembic_version') IS NULL THEN NULL
            ELSE (SELECT string_agg(version_num, ',' ORDER BY version_num) FROM public.alembic_version) END AS revision
"""
RELATIONS_SQL: Final = "SELECT r AS relation FROM unnest(%(names)s::text[]) AS r WHERE to_regclass(r) IS NULL ORDER BY r"


def attempt[T](conn: Conn, fn: Callable[[], T]) -> T | ReadFailure:
    """``fn()`` in a savepoint, or the class of what it raised: a statement that fails rolls back to the savepoint and the rest of the
    console is read in the same transaction."""
    try:
        with conn.transaction():
            return fn()
    except (psycopg.Error, ValueError, KeyError, TypeError) as exc:
        log.warning("console.block_failed", error=type(exc).__name__)
        return ReadFailure(error=type(exc).__name__)


def _usd(x: Decimal | str) -> str:
    return str(Decimal(x).quantize(Decimal("0.01")))


def _alert(level: int | None) -> str:
    return "ninguno" if level is None else str(level)


def _share(x: float | None) -> float | Missing:
    return NO_DATA if x is None else x


# ── «nada sale de la sombra» ──────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Spec:
    switch: str
    audience: str
    default: str
    effect: str
    worker_key: str | None = None
    """The word of the worker's ledger (``fbi.ai.gates.switch_words``) that says the same, when it keeps one."""


def _yes(on: bool) -> str:
    return "on" if on else "off"


def _names(values: Iterable[str]) -> str:
    joined = ",".join(values)
    return joined or "ninguno"


def _repeat_word(raw: str | None) -> str:
    """``FBI_CHRONICLE_REPEAT`` as ``fbi.chronicle.repetition.mode`` reads it: shadow by default, on or off only when written."""
    word = (raw or "shadow").strip().lower()
    return word if word in ("on", "off") else "shadow"


def switch_words(settings: AiSettings, env: Mapping[str, str]) -> dict[str, str]:
    """What each switch of the console reads as, with the code's own parsers. Words only."""
    family = (env.get("FBI_FAMILY_DECISIONS") or "off").strip().lower()
    return {
        "FBI_PICKS_SOURCE": INTELLIGENCE if PicksSourceSettings().from_intelligence else "legacy",
        "FBI_AI_MODE": settings.mode,
        "FBI_AI_RESEARCH_V2": settings.research_v2,
        "FBI_AI_AGENTS": _names(settings.agents),
        "FBI_AI_ENGINES": _names(settings.engines),
        "FBI_FAMILY_DECISIONS": family if family in FAMILY_MODES else "off",
        "FBI_AI_PM_REVIEWER": _yes(settings.pm_reviewer),
        "FBI_AI_LEARNING_ANALYST": _yes(settings.learning_analyst),
        "FBI_AI_ENVELOPES_INDEPENDENT": _yes(settings.envelopes_independent),
        "FBI_CHRONICLE_V4": "shadow" if (env.get("FBI_CHRONICLE_V4") or "").strip().lower() == "shadow" else "off",
        "FBI_CHRONICLE_LINEUP": "shadow" if (env.get("FBI_CHRONICLE_LINEUP") or "").strip().lower() == "shadow" else "off",
        "FBI_CHRONICLE_REPEAT": _repeat_word(env.get("FBI_CHRONICLE_REPEAT")),
        "FBI_CHRONICLE_REVIEW_V2": "shadow" if (env.get("FBI_CHRONICLE_REVIEW_V2") or "").strip().lower() == "shadow" else "off",
        reader_switches.MATCH_INTELLIGENCE: _yes(reader_switches.user_switch(reader_switches.MATCH_INTELLIGENCE, default=False)),
        reader_switches.NEWS_V2: _yes(reader_switches.user_switch(reader_switches.NEWS_V2, default=False)),
        reader_switches.SEARCH: _yes(reader_switches.user_switch(reader_switches.SEARCH, default=False)),
        reader_switches.PROFILES: _yes(reader_switches.user_switch(reader_switches.PROFILES, default=False)),
    }


SPECS: Final[tuple[Spec, ...]] = (
    Spec("FBI_PICKS_SOURCE", "lector", "legacy", "intelligence: la página de Picks lee la decisión de Intelligence (decision-v1); apagado: "
         "la de siempre. Sigue apagado: lo enciende solo el dueño."),
    Spec("FBI_AI_MODE", "intelligence", "shadow", "enforce: la revisión de la IA puede quitar un pick a los lectores, solo si el último "
         "informe de combined dice pass; shadow: revisa sin efecto; off: no revisa.", "mode"),
    Spec("FBI_AI_RESEARCH_V2", "intelligence", "off", "Research v2 (AD-C05): shadow corre al lado de la v1 sin mover nada de ella.",
         "research_v2"),
    Spec("FBI_AI_AGENTS", "intelligence", "ninguno", "Los agentes que pueden correr (partido, estadísticas, Council), solo en sombra.",
         "agents"),
    Spec("FBI_AI_ENGINES", "intelligence", "rules,llm", "Los motores que revisan: rules y llm siempre; los demás, solo en sombra.",
         "engines"),
    Spec("FBI_FAMILY_DECISIONS", "intelligence", "off", "Familias de conteos (AD-B07): shadow decide en sombra con versiones propias que "
         "ningún pick lee."),
    Spec("FBI_AI_PM_REVIEWER", "intelligence", "off", "La revisión mecánica de los post-mortems y la atribución (attr-v1).", "pm_reviewer"),
    Spec("FBI_AI_LEARNING_ANALYST", "intelligence", "off", "El analista de aprendizaje semanal: propone, nunca aplica.",
         "learning_analyst"),
    Spec("FBI_AI_ENVELOPES_INDEPENDENT", "intelligence", "on", "Decisión del dueño del 17-nov-2026 (IA-141): los sobres 185 / 55 / 35 "
         "sustituyen al techo conjunto de 190 y el LAB no cede ante producción; off es la vuelta atrás al techo conjunto."),
    Spec("FBI_CHRONICLE_V4", "intelligence", "off", "La crónica única (AD-F01/F02): shadow planifica los hechos por código y escribe una "
         "crónica verificada frase por frase en ai.chronicles, tope de US$ 1 al día; ningún lector la ve."),
    Spec("FBI_CHRONICLE_LINEUP", "intelligence", "off", "La crónica tras la alineación (AD-F03): shadow añade, en cada E3, una versión nueva "
         "con el párrafo de la alineación y el porqué de cada selección, por plantilla y sin modelo; ningún lector la ve."),
    Spec("FBI_CHRONICLE_REPEAT", "intelligence", "shadow", "Coletillas y repeticiones (AD-F04): shadow las mide en cada crónica sin quitar "
         "nada; on las quita como frases sin apoyo (umbral sin firmar); off no mide."),
    Spec("FBI_CHRONICLE_REVIEW_V2", "intelligence", "off", "La evaluación factual de la crónica única (AD-F06): shadow la juzga tras el "
         "partido sobre los hechos que cita, en ai.chronicle_reviews; sin modelo ni coste."),
    Spec(reader_switches.MATCH_INTELLIGENCE, "lector", "off", "La pestaña «Intelligence» del partido para lectores (solo lo publicado)."),
    Spec(reader_switches.NEWS_V2, "lector", "off", "Noticias como las maquetas 08-10."),
    Spec(reader_switches.SEARCH, "lector", "off", "La búsqueda global de los lectores."),
    Spec(reader_switches.PROFILES, "lector", "off", "Las páginas de club, selección y jugador."),
)
SPEC_OF: Final[dict[str, Spec]] = {s.switch: s for s in SPECS}


WORKER_WORDS: Final[dict[str, frozenset[str]]] = {
    "FBI_AI_MODE": frozenset({"off", "shadow", "enforce"}), "FBI_AI_RESEARCH_V2": frozenset({"off", "shadow", "on"}),
    "FBI_AI_AGENTS": frozenset(AGENTS), "FBI_AI_ENGINES": frozenset(KNOWN_ENGINES)}
"""The words the worker's ledger may hold for each switch (``fbi.ai.gates.switch_words``): anything else is not shown."""


def worker_word(words: Mapping[str, Any] | None, spec: Spec) -> str | Missing:
    """The word the worker wrote for this switch in its newest row of the ledger. A word at its default is not written there
    (``fbi.ai.gates.shadow_words``): absent from a row that exists, it is the default."""
    if spec.worker_key is None or words is None:
        return NO_DATA
    value = words.get(spec.worker_key)
    if value is None:
        return spec.default
    if isinstance(value, bool):
        return _yes(value)
    word = str(value).strip().lower()
    allowed = WORKER_WORDS.get(spec.switch, frozenset())
    return word if word and all(part in allowed for part in word.split(",")) else NO_DATA


def switch_state(spec: Spec, reads_as: str, words: Mapping[str, Any] | None) -> SwitchState:
    return SwitchState(switch=spec.switch, audience=spec.audience, reads_as=reads_as, default=spec.default,  # type: ignore[arg-type]
                       at_default=reads_as == spec.default, worker_recorded=worker_word(words, spec), effect=spec.effect)


def breaks_of(picks_source: str, enforced: AiEnforcement | ReadFailure, published: int | ReadFailure) -> list[ShadowBreak]:
    out: list[ShadowBreak] = []
    if picks_source == INTELLIGENCE:
        out.append("picks_source_intelligence")
    if isinstance(enforced, AiEnforcement) and enforced.enforced:
        out.append("ai_enforced")
    if isinstance(published, int) and published > 0:
        out.append("picks_published")
    return out


def shadow(conn: Conn, settings: AiSettings, env: Mapping[str, str]) -> Shadow:
    words = switch_words(settings, env)

    def read_enforcement() -> AiEnforcement:
        e = enforcement(conn, settings)
        verdict = (e.gate or {}).get("verdict")
        return AiEnforcement(mode=settings.mode, enforced=e.enforced, reason=e.reason,
                             gate_verdict=NO_DATA if verdict is None else str(verdict))

    def read_published() -> int:
        row = fetch_one(conn, PUBLISHED_SQL)
        return int(row["n"]) if row else 0

    def read_ledger() -> tuple[WorkerLedger, Mapping[str, Any]] | None:
        row = fetch_one(conn, WORKER_SQL)
        if row is None:
            return None
        evidence = row["evidence"] if isinstance(row["evidence"], Mapping) else {}
        recorded = evidence.get("words")
        return WorkerLedger(row=int(row["id"]), at=row["at"]), recorded if isinstance(recorded, Mapping) else {}

    enforced = attempt(conn, read_enforcement)
    published = attempt(conn, read_published)
    ledger = attempt(conn, read_ledger)
    recorded = ledger[1] if isinstance(ledger, tuple) else None
    states = {s.switch: switch_state(s, words[s.switch], recorded) for s in SPECS}
    breaks = breaks_of(words["FBI_PICKS_SOURCE"], enforced, published)
    unread = isinstance(enforced, ReadFailure) or isinstance(published, ReadFailure)
    return Shadow(verdict="no_se_cumple" if breaks else "sin_comprobar" if unread else "se_cumple", breaks=breaks,
                  picks_source=states["FBI_PICKS_SOURCE"], ai_mode=states["FBI_AI_MODE"], ai_enforcement=enforced,
                  published_picks=published,
                  switches=[v for k, v in states.items() if k not in ("FBI_PICKS_SOURCE", "FBI_AI_MODE")],
                  worker_ledger=ledger[0] if isinstance(ledger, tuple) else ledger if isinstance(ledger, ReadFailure) else NO_DATA)


# ── capabilities ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _gate_reading(g: Mapping[str, Any]) -> GateReading:
    return GateReading(gate=str(g["gate"]), verdict=NO_DATA if g.get("verdict") is None else g["verdict"],
                       row=NO_DATA if g.get("row") is None else int(g["row"]), at=NO_DATA if g.get("at") is None else g["at"])


def state_word(state: str) -> CapabilityState:
    if state not in STATE_WORDS:
        raise ValueError(f"unknown capability state {state!r}")
    return cast(CapabilityState, STATE_WORDS[state])


def capability_view(item: Mapping[str, Any]) -> CapabilityView:
    """One capability of ``fbi.intel.capabilities.overview`` in the contract's words."""
    safety, validation = item["safety"], item["validation"]
    live = item["live"]

    def maybe(x: Any) -> Any:
        return NO_DATA if x is None else x

    return CapabilityView(
        key=item["key"], piece=item["piece"], title=item["title"], switch=maybe(item["switch"]),
        state=NO_DATA if item["state"] is None else state_word(str(item["state"])),
        since=maybe(item["since"]), decided_by=maybe(item["decided_by"]), signed_by_owner=bool(item["signed_by_owner"]),
        safety=maybe(safety["verdict"]), validation=maybe(validation["verdict"]), validation_sample=maybe(validation["sample"]),
        safety_gates=[_gate_reading(g) for g in live["safety_gates"]],
        validation_gates=[_gate_reading(g) for g in live["validation_gates"]], warnings=[str(w) for w in item["warnings"]])


def capabilities_of(view: Mapping[str, Any]) -> Capabilities:
    items = [capability_view(i) for i in view["capabilities"]]
    by_state = view["by_state"]
    counts = [StateCount(state=state_word(s), count=int(by_state.get(s, 0))) for s in registry.STATES]
    return Capabilities(registry_version=str(view["version"]), by_state=counts, unregistered=list(view["unregistered"]),
                        not_in_code=list(view["not_in_code"]),
                        items=ItemList[CapabilityView](items=items) if items else
                        ItemList[CapabilityView](items=[], missing_reason="sin_datos"))


# ── costs ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def envelope_view(f: EnvelopeFigure) -> EnvelopeView:
    j = f.as_json()
    parts = [CostPart(name=k, spent_usd=_usd(v)) for k, v in f.parts.items()]  # type: ignore[arg-type]
    return EnvelopeView(scope=f.scope, spent_usd=_usd(f.spent), budget_usd=_usd(f.budget), decided_usd=_usd(f.decided),  # type: ignore[arg-type]
                        matches_decision=bool(j["matches_decision"]), share=_share(j["share"]), alert=_alert(f.alert),  # type: ignore[arg-type]
                        parts=parts)


def costs_of(month: costs_v3.Month, settings: AiSettings) -> Costs:
    caps = [CapabilityCap(key=c["key"], piece=c["piece"], envelope=c["envelope"], monthly_usd=_usd(c["monthly_usd"]),
                          spent_usd=_usd(c["spent_usd"]), share=_share(c["share"]), alert=_alert(c["alert"]),  # type: ignore[arg-type]
                          tagged=bool(c["tagged"]), source=str(c["source"])) for c in month.capabilities]
    declared = [Declared(envelope=e, declared_usd=_usd(d["declared_usd"]), envelope_usd=_usd(d["envelope_usd"]),  # type: ignore[arg-type]
                         fits=Decimal(d["declared_usd"]) <= Decimal(d["envelope_usd"])) for e, d in caps_budget.declared().items()]
    ceiling = JointCeiling(usd=_usd(settings.joint_ceiling), applies=not settings.envelopes_independent, pending_owner=JOINT_CEILING_PENDING,
                           production_plus_lab_usd=_usd(settings.monthly_budget + settings.lab_monthly_budget))
    return Costs(month=month.month, budget_version=caps_budget.VERSION, envelopes=[envelope_view(f) for f in month.figures],
                 capabilities=caps, declared=declared, joint_ceiling=ceiling)


# ── security ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def battery_of(rows: Mapping[str, gates_panel.Row]) -> Battery:
    r = rows.get("battery")
    if r is None:
        return Battery(verdict=NO_DATA, row=NO_DATA, at=NO_DATA)
    return Battery(verdict="PASA" if r.passed else "NO PASA", row=r.id, at=r.at)


def leak_audit_of(rows: list[dict[str, Any]]) -> LeakAudit | Missing:
    if not rows:
        return NO_DATA
    found = sorted((LeakRule(rule=str(r["rule"]), checked=int(r["n_checked"]), violations=int(r["n_violations"]))
                    for r in rows if int(r["n_violations"]) > 0), key=lambda x: (-x.violations, x.rule))
    day = rows[0]["day"]
    return LeakAudit(day=day if isinstance(day, date) else date.fromisoformat(str(day)), versions=sorted({str(r["version"]) for r in rows}),
                     rules=len(rows), violations=sum(int(r["n_violations"]) for r in rows), with_violations=found)


def _recorded(e: Mapping[str, Any]) -> tuple[int | Missing, datetime | Missing]:
    rec = e.get("recorded")
    if isinstance(rec, Mapping) and isinstance(rec.get("id"), int) and isinstance(rec.get("at"), str):
        return int(rec["id"]), datetime.fromisoformat(str(rec["at"]))
    return NO_DATA, NO_DATA


def gates_of(doc: Mapping[str, Any], at: datetime) -> Gates:
    """The panel of the gates (``gates_panel.panel``) in the contract's words: every gate with its status and why, and the rule that no pending
    gate is shown as approved."""
    items = []
    for e in doc["gates"]:
        row, row_at = _recorded(e)
        evaluable = e.get("evaluable_on")
        items.append(GateView(id=str(e["id"]), name=str(e["name"]), piece=str(e["piece"]), status=e["status"], approved=bool(e["approved"]),
                              recorded_row=row, recorded_at=row_at,
                              evaluable_on=NO_DATA if not evaluable else date.fromisoformat(str(evaluable)), why=[str(w) for w in e["why"]]))
    summary = [StatusCount(status=s, count=int(n)) for s, n in doc["summary"].items()]
    return Gates(version=str(doc["version"]), as_of=at, rule_holds=bool(doc["rule_holds"]), summary=summary, items=items)


_gates_lock = threading.Lock()
_gates_cache: tuple[datetime, Gates] | None = None


def clear_cache() -> None:
    global _gates_cache
    with _gates_lock:
        _gates_cache = None


def gates_block(conn: Conn, settings: AiSettings, at: datetime) -> Gates:
    """The panel, read again when the kept one is older than five minutes."""
    global _gates_cache
    with _gates_lock:
        kept = _gates_cache
    if kept is not None and timedelta(0) <= at - kept[0] < GATES_TTL:
        return kept[1]
    doc = gates_panel.panel(gates_panel_readers.read(conn, settings, at=at))
    fresh = gates_of(doc, at)
    with _gates_lock:
        _gates_cache = (at, fresh)
    return fresh


def code_head(directory: Path = MIGRATIONS) -> str | None:
    """The head of the code's migrations (the revision no other names as its parent), read from the files; None without them."""
    if not directory.is_dir():
        return None
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in directory.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if (m := REVISION.search(text)) is not None:
            revisions.add(m.group(1))
        parents.update(DOWN.findall(text))
    heads = sorted(revisions - parents)
    return ",".join(heads) if heads else None


def schema_of(conn: Conn) -> Schema:
    row = fetch_one(conn, REVISION_SQL)
    database = None if row is None or row["revision"] is None else str(row["revision"])
    missing = [str(r["relation"]) for r in fetch_all(conn, RELATIONS_SQL, {"names": list(CONSOLE_RELATIONS)})]
    head = code_head()
    return Schema(database_revision=NO_DATA if database is None else database, code_head=NO_DATA if head is None else head,
                  up_to_date=database is not None and database == head and not missing, missing_relations=missing)


def security(conn: Conn, settings: AiSettings, at: datetime) -> Security:
    rows = attempt(conn, lambda: gates_panel_readers.newest_rows(conn))
    return Security(battery=rows if isinstance(rows, ReadFailure) else battery_of(rows),
                    leak_audit=attempt(conn, lambda: leak_audit_of(fetch_all(conn, AUDIT_SQL))),
                    gates=attempt(conn, lambda: gates_block(conn, settings, at)), schema_check=attempt(conn, lambda: schema_of(conn)))


# ── protocols ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def protocols_of(items: Iterable[Mapping[str, Any]]) -> ConsoleProtocols:
    """The register of the owner's signatures (``fbi.protosign.store.overview``) in the contract's words. Pure."""
    out = []
    for i in items:
        sig = i.get("signature")
        out.append(ConsoleProtocol(
            key=str(i["key"]), version=str(i["version"]), framework=i["framework"], title=str(i["title"]),
            registered_on=date.fromisoformat(str(i["registered_on"])), fingerprint=str(i["fingerprint"]),
            signed_by_owner=bool(i["signed_by_owner"]), signed_at=NO_DATA if sig is None else sig["signed_at"],
            signature_row=NO_DATA if sig is None else int(sig["id"]), other_fingerprints=int(i["other_fingerprints"])))
    signed = sum(1 for p in out if p.signed_by_owner)
    return ConsoleProtocols(register_version=PROTOCOLS_VERSION, signed=signed, pending=len(out) - signed, items=out,
                            notice_es=PROTOCOLS_NOTICE)


def protocols(conn: Conn) -> ConsoleProtocols | Missing:
    if not protocol_signatures.exists(conn):
        return NO_DATA
    return protocols_of(protocol_signatures.overview(conn))


# ── flow of the learning cycle ────────────────────────────────────────────────────────────────────────────

def _or_missing[T](value: T | None) -> T | Missing:
    return NO_DATA if value is None else value


def cycle_of(readings: Iterable[freshness.Reading]) -> Cycle:
    """The twelve readings of ``fbi.ops.freshness`` in the contract's words. A figure the stage does not have is ``sin_datos``."""
    stages = [FlowStage(number=r.stage.number, key=r.stage.key, name_es=r.stage.name_es, alarm_es=r.stage.alarm_es, status=r.status,
                        detail_es=r.detail_es, value=_or_missing(r.value), limit=_or_missing(r.limit), unit=_or_missing(r.unit),
                        last_at=_or_missing(r.last_at)) for r in readings]
    return Cycle(rule_version=freshness.VERSION, stopped=sum(x.status == "parada" for x in stages), stages=stages)


def flow_of(readings: Iterable[freshness.Reading]) -> Flow:
    return Flow(cycle=cycle_of(readings))


def flow(conn: Conn, at: datetime) -> Flow:
    return flow_of(freshness.read_all(conn, at=at))


# ── the console ───────────────────────────────────────────────────────────────────────────────────────────────────────────────

def build(conn: Conn, *, at: datetime, settings: AiSettings | None = None) -> ConsoleContract:
    """C-11 at ``at``: every block in its own savepoint of one read-only transaction."""
    settings = settings or AiSettings.from_env()
    return ConsoleContract(
        freshness=Freshness(generated_at=at, stale=False),
        shadow=shadow(conn, settings, environment()),
        capabilities=attempt(conn, lambda: capabilities_of(registry.overview(conn, at=at))),
        costs=attempt(conn, lambda: costs_of(costs_v3.month_of(conn, at=at, settings=settings), settings)),
        security=security(conn, settings, at),
        protocols=attempt(conn, lambda: protocols(conn)),
        flow=attempt(conn, lambda: flow(conn, at)),
        news_engine=NEWS_ENGINE, alert_queue=ALERT_QUEUE)


def console(conn: Conn) -> Envelope[ConsoleContract]:
    return ok(build(conn, at=now()))


__all__ = ["ALERT_QUEUE", "CONSOLE_RELATIONS", "FAMILY_MODES", "NEWS_ENGINE", "SPECS", "STATE_WORDS", "attempt", "build", "capabilities_of",
           "clear_cache", "code_head", "console", "costs_of", "cycle_of", "flow", "flow_of", "gates_of", "leak_audit_of", "protocols", "protocols_of", "schema_of", "switch_words",
           "worker_word"]
