"""Contract C-07, the sources of an analysis (AD-G08, IA-122), built from the lists the evaluations wrote (``fbi.factlinks.views``).

Read only: nothing here links a fact, draws a relation or reads ``ai.evidence`` - every row was written by its evaluation at the moment of
its decision (``fbi.factlinks.store``, revision 0160). The fact's sentence is written here by code from its kind, its assertion and the
entity's name in PrediGol's tables: never the source's words, nothing medical (an absence is ``baja``, ``en duda``, ``sancionado``).

* ``private`` - the newest evaluation's list of the match, with the effect on each selection, what was refused and every evaluation.
* ``public`` - 404 while ``FBI_MATCH_INTELLIGENCE`` is off, and 404 while the match's analysis is not published (no pick of it in a
  ``qualified`` set); otherwise the list of the evaluation in force when it was published, projected by the server (``to_public``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, cast, get_args

from fbi.ai import factor_schema
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.sources import (
    AnalysisSources,
    AnalysisSourcesPrivate,
    E2Action,
    EntityKind,
    EntityRef,
    EvaluationList,
    LevelCount,
    RefusedFact,
    Rejection,
    SelectionEffect,
    SourceRef,
    SourceType,
    Summary,
    UsedFactPrivate,
)
from fbi.api.contracts.intelligence.vocab import (
    ConfirmationLevel,
    EvaluationStep,
    FactRelation,
    StoryWarning,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn
from fbi.api.switches import match_intelligence_on
from fbi.core.clock import now
from fbi.factlinks import views

NO_DATA: Final = Missing(missing_reason="sin_datos")
NOT_YET: Final = Missing(missing_reason="no_entregado", expected_piece="AD-G08")
NO_QUOTE: Final = Missing(missing_reason="pendiente_derechos")
LEVELS: Final = get_args(ConfirmationLevel)
STATE_ES: Final = {"out": "baja", "doubtful": "en duda", "available": "disponible", "starts": "titular"}
KIND_ES: Final = {"suspension": "sancionado", "coach": "novedad del cuerpo técnico", "lineup": "alineación", "transfer": "fichajes",
                  "motivation": "motivación", "weather": "clima", "travel": "viaje", "schedule": "calendario"}
CONTRIBUTED_ES: Final[dict[str, str]] = {
    "a_favor": "Mueve a favor una selección del análisis (dos puntos o más).",
    "en_contra": "Mueve en contra una selección del análisis (dos puntos o más).",
    "contexto": "Se tuvo en cuenta como contexto: no movió ninguna selección.",
    "no_usada": "No se usó: es un rumor.",
}
FIXTURE_SQL: Final = "SELECT id, kickoff_at FROM core.fixtures WHERE id = %(f)s"


def fact_es(entity_name: str | None, entity_type: str | None, kind: str, assertion: str | None) -> str:
    """The fact in PrediGol's own words: who, and the state or the kind. Pure."""
    who = entity_name or ("Un jugador" if entity_type == "player" else "El equipo")
    if kind == "suspension" and assertion == "out":
        what = "sancionado"
    elif assertion in STATE_ES:
        what = STATE_ES[assertion]
    else:
        what = KIND_ES.get(kind, "novedad")
    return f"{who}: {what}"


def _line(x: Any) -> str:
    return str(Decimal(str(x)).quantize(Decimal("0.01")))


def _entity(r: views.SourceRow) -> EntityRef | Missing:
    if r.entity_type is None or r.entity_id is None:
        return NO_DATA
    return EntityRef(type=cast(EntityKind, r.entity_type), id=r.entity_id, name=r.entity_name or NO_DATA)


def _source(r: views.SourceRow) -> SourceRef:
    return SourceRef(name=r.source_name, type=cast(SourceType, r.source_type), url=r.source_url or NO_DATA)


def used(rows: Sequence[views.SourceRow], evaluation: str) -> list[UsedFactPrivate]:
    """The linked facts of a list, in the order they were known. Pure."""
    out: list[UsedFactPrivate] = []
    for r in [r for r in rows if r.linked]:
        assert r.entity_type is not None and r.entity_id is not None and r.relation is not None and r.named_as is not None
        warnings: list[StoryWarning] = ["contradiccion"] if r.warning == "contradiccion" else []
        out.append(UsedFactPrivate(
            n=len(out) + 1, fact_es=fact_es(r.entity_name, r.entity_type, r.kind, r.assertion),
            entity=EntityRef(type=cast(EntityKind, r.entity_type), id=r.entity_id, name=r.entity_name or NO_DATA),
            team=r.team_name or NO_DATA, level=cast(ConfirmationLevel, r.level) if r.level in LEVELS else NO_DATA,
            category=factor_schema.category_of_level(r.level), warnings=warnings,
            relation=cast(FactRelation, r.relation), contributed_es=CONTRIBUTED_ES[r.relation],
            evaluation=cast(EvaluationStep, evaluation), source=_source(r), quote=NO_QUOTE,
            published_at=r.fact_at if r.fact_at is not None else NO_DATA, known_at=r.fact_known_at, fact_at=NO_DATA,
            valid_until=NO_DATA, evidence_id=r.evidence_id, item_id=r.item_id if r.item_id is not None else NO_DATA,
            named_as=r.named_as, kind=r.kind, assertion=r.assertion or NO_DATA, source_tier=r.source_tier,
            e2_action=cast(E2Action, r.e2_action) if r.e2_action else NO_DATA,
            selections=[SelectionEffect(market_key=str(s["market_key"]), selection=str(s["selection"]), line=_line(s["line"]),
                                        relation=cast(FactRelation, s["relation"]), shift=float(s["shift"]))
                        for s in r.selections]))
    return out


def summary(facts: Sequence[UsedFactPrivate]) -> Summary:
    levels = Counter(f.level for f in facts if isinstance(f.level, str))
    return Summary(facts=len(facts), sources=len({f.source.name for f in facts}),
                   by_level=[LevelCount(level=lv, n=levels[lv]) for lv in LEVELS if levels[lv]],
                   unused_rumours=sum(1 for f in facts if f.level == "rumor" and f.relation == "no_usada"))


def refused(rows: Sequence[views.SourceRow]) -> list[RefusedFact]:
    return [RefusedFact(evidence_id=r.evidence_id, rejection=cast(Rejection, r.rejection), kind=r.kind, source=_source(r),
                        known_at=r.fact_known_at, entity=_entity(r)) for r in rows if not r.linked]


def _list[T](items: list[T], empty: Missing) -> ItemList[T]:
    if items:
        return ItemList[T](items=items)
    return ItemList[T](items=[], missing_reason=empty.missing_reason, expected_piece=empty.expected_piece)


def assemble(fixture_id: int, lists: Sequence[views.SourceList], shown: views.SourceList | None, rows: Sequence[views.SourceRow],
             *, published: datetime | None, at: datetime, delivered: bool = True) -> AnalysisSourcesPrivate:
    """The private answer of C-07 from what was read. Pure."""
    empty = NO_DATA if delivered else NOT_YET
    facts = used(rows, shown.evaluation) if shown is not None else []
    return AnalysisSourcesPrivate(
        freshness=Freshness(generated_at=at, stale=False), fixture_id=fixture_id,
        evaluation=cast(EvaluationStep, shown.evaluation) if shown else empty,
        evaluation_version=shown.evaluation_version if shown else empty, evaluated_at=shown.known_at if shown else empty,
        summary=summary(facts), facts=_list(facts, empty), refused=_list(refused(rows), empty),
        evaluations=_list([EvaluationList(evaluation=cast(EvaluationStep, x.evaluation), evaluation_version=x.evaluation_version,
                                          known_at=x.known_at, candidates=x.candidates, linked=x.linked, refused=x.rejected,
                                          rule_version=x.version) for x in lists], empty),
        published_at=published if published is not None else NO_DATA, rule_version=shown.version if shown else empty)


def build(conn: Conn, fixture_id: int, *, at: datetime | None = None, until: datetime | None = None) -> AnalysisSourcesPrivate:
    """The private answer as of ``at``; ``until``: show the newest evaluation up to that moment (the published one)."""
    at = at or now()
    if conn.execute(FIXTURE_SQL, {"f": fixture_id}).fetchone() is None:
        raise ApiError(404, "not_found", "no such match")
    if not views.tables_exist(conn):
        return assemble(fixture_id, [], None, [], published=None, at=at, delivered=False)
    published = views.published_at(conn, fixture_id, at)
    lists = views.lists(conn, fixture_id, until=at)
    shown = next((x for x in lists if until is None or x.known_at <= until), None)
    rows = views.rows(conn, [shown.id]) if shown is not None else []
    return assemble(fixture_id, lists, shown, rows, published=published, at=at)


def private(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[AnalysisSourcesPrivate]:
    answer = build(conn, fixture_id, at=at)
    return ok(answer, data_as_of=None if isinstance(answer.evaluated_at, Missing) else answer.evaluated_at)


def public(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[AnalysisSources]:
    """404 while the switch is off or the analysis is not published: the route does not exist for a reader."""
    if not match_intelligence_on():
        raise ApiError(404, "not_found", "not found")
    at = at or now()
    published = views.published_at(conn, fixture_id, at) if views.tables_exist(conn) else None
    if published is None:
        raise ApiError(404, "not_found", "not found")
    answer = to_public(build(conn, fixture_id, at=at, until=published), AnalysisSources)
    return ok(answer, data_as_of=None if isinstance(answer.evaluated_at, Missing) else answer.evaluated_at)
