"""C-07, the sources of an analysis (AD-G08, IA-122): the facts each evaluation E1-E4 of a match looked at, with their relation.

* public - ``GET /api/v1/matches/{fixture_id}/sources``, 404 while ``FBI_MATCH_INTELLIGENCE`` is off AND while the match's analysis is
  not published (no pick of it in a ``qualified`` set: none in the whole history on 16-nov-2026). It shows the facts of the evaluation in
  force when the analysis was published, linked by ``link-v1`` - their level, relation, when PrediGol knew them, the source and its link.
* private - ``GET /api/v1/admin/intelligence/matches/{fixture_id}/sources`` (``require_admin``, no switch): the newest evaluation's list,
  and what only the owner sees - each fact's effect on each selection (the selections are experimental), the facts the validator refused
  with their reason, every evaluation's counts and the ids of the evidence.

Every list was written by the evaluation itself, at the moment of its decision (revision 0160 refuses it at any other moment): nothing
here draws a relation afterwards, and a fact known after the moment is never in it. The fact's sentence (``fact_es``) is written by code
from its kind and its entity - never the source's words; the quote is ``pendiente_derechos``. Of an absence, only its state: nothing
medical. The example of every case is in ``tests/fixtures/contracts/intelligence/C-07``.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field, model_validator

from fbi.api.contracts.intelligence.base import (
    CODE_PATTERN,
    DatedFact,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    _absent,
    private,
)
from fbi.api.contracts.intelligence.vocab import (
    ConfirmationLevel,
    EvaluationStep,
    FactCategory,
    FactRelation,
    StoryWarning,
)

SourceType = Literal["oficial", "agencia", "prensa"]
EntityKind = Literal["team", "player"]
Rejection = Literal["otro_partido", "sin_entidad", "entidad_ajena", "sin_cita_literal", "cita_sin_nombre", "homonimo", "sin_fecha",
                    "fuera_de_ventana"]
"""Why the validator refused a fact (``fbi.factlinks.validate``; a fact known after the moment is never written)."""
E2Action = Literal["recalcula", "anota"]
LINE_PATTERN: Final = r"^-?\d+\.\d{2}$"
RULE_VERSION_PATTERN: Final = r"^link-v\d+$"

LEVEL_RULE_ES: Final = ("Oficial: lo dice la fuente oficial (club, liga o federación). Dos orígenes: lo cuentan dos fuentes independientes. "
                        "Un medio: lo cuenta una sola fuente. Rumor: nadie lo confirma; se lista, pero el análisis no lo usa.")
RELATION_RULE_ES: Final = ("A favor o en contra: el hecho cambia en dos puntos o más la probabilidad de una selección del análisis "
                           "(un jugador del que depende). Contexto: se tuvo en cuenta sin mover nada. No usada: un rumor.")


class SourceRef(IntelligenceModel):
    name: str = Field(min_length=1)
    type: SourceType
    url: str | Missing


class EntityRef(IntelligenceModel):
    type: EntityKind
    id: int = Field(ge=1)
    name: str | Missing


class LevelCount(IntelligenceModel):
    level: ConfirmationLevel
    n: int = Field(ge=0)


class Summary(IntelligenceModel):
    """Counted by the server over the facts listed."""

    facts: int = Field(ge=0)
    sources: int = Field(ge=0, description="Distinct outlets.")
    by_level: list[LevelCount]
    unused_rumours: int = Field(ge=0)


class UsedFact(DatedFact):
    """A fact the evaluation looked at and the validator linked: ``published_at`` is the source's date, ``known_at`` when PrediGol
    first had it (always before the evaluation's moment)."""

    n: int = Field(ge=1)
    fact_es: str = Field(min_length=1, description="Written by code from the kind and the entity, never the source's words.")
    entity: EntityRef
    team: str | Missing
    level: ConfirmationLevel | Missing
    category: FactCategory | None = Field(
        default=None, exclude_if=_absent,
        description="1.1: the category of the fact (RP-4.1), given by code from its level of confirmation; absent when the level is.")
    warnings: list[StoryWarning]
    relation: FactRelation
    contributed_es: str = Field(min_length=1)
    evaluation: EvaluationStep
    source: SourceRef
    quote: Missing = Field(description="A short quote, once the lawyer allows it (pendiente_derechos).")


class SelectionEffect(IntelligenceModel):
    market_key: str = Field(min_length=1, max_length=40)
    selection: str = Field(min_length=1, max_length=60)
    line: str = Field(pattern=LINE_PATTERN)
    relation: FactRelation
    shift: float = Field(description="The change of the selection's probability (proportion) the fact means.")


class UsedFactPrivate(UsedFact):
    evidence_id: int = private(ge=1, description="The row of ai.evidence.")
    item_id: int | Missing = private(description="The article of news.items it was read from (only rows written after 0146).")
    named_as: str = private(min_length=1, description="The words the quote names the entity by.")
    kind: str = private(pattern=CODE_PATTERN, description="The kind of the fact (injury, lineup ...).")
    assertion: str | Missing = private(description="out, doubtful, available, starts or info.")
    source_tier: str = private(min_length=1, description="The tier of its source (tiers-v1).")
    e2_action: E2Action | Missing = private(description="What E2 did with it: recalculated or only noted.")
    selections: list[SelectionEffect] = private(description="Its effect on each selection (experimental: never public).")


class RefusedFact(IntelligenceModel):
    evidence_id: int = Field(ge=1)
    rejection: Rejection
    kind: str = Field(pattern=CODE_PATTERN)
    source: SourceRef
    known_at: UtcDatetime
    entity: EntityRef | Missing


class EvaluationList(IntelligenceModel):
    evaluation: EvaluationStep
    evaluation_version: int = Field(ge=1)
    known_at: UtcDatetime
    candidates: int = Field(ge=0)
    linked: int = Field(ge=0)
    refused: int = Field(ge=0)
    rule_version: str = Field(pattern=RULE_VERSION_PATTERN)


class AnalysisSources(IntelligenceContract):
    """C-07, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-07"
    CONTRACT_VERSION: ClassVar[str] = "1.1.0"

    fixture_id: int = Field(ge=1)
    evaluation: EvaluationStep | Missing
    evaluation_version: int | Missing
    evaluated_at: UtcDatetime | Missing = Field(description="The moment the evaluation decided as of: every fact was known before it.")
    summary: Summary
    facts: ItemList[UsedFact]
    level_rule_es: str = LEVEL_RULE_ES
    relation_rule_es: str = RELATION_RULE_ES

    @model_validator(mode="after")
    def _known_before(self) -> AnalysisSources:
        if isinstance(self.evaluated_at, Missing) != isinstance(self.evaluation, Missing):
            raise ValueError("an evaluation and its moment are both given or both missing")
        when = self.evaluated_at
        for f in self.facts.items:
            if not isinstance(when, Missing) and f.known_at > when:
                raise ValueError(f"fact {f.n} was known after the evaluation: no relation is drawn afterwards")
            if f.level == "rumor" and f.relation != "no_usada":
                raise ValueError(f"fact {f.n}: a rumour is not used")
        return self


class AnalysisSourcesPrivate(AnalysisSources):
    """C-07, private projection (``require_admin``)."""

    facts: ItemList[UsedFactPrivate]  # type: ignore[assignment]  # the private variant of each item
    refused: ItemList[RefusedFact] = private(description="What the validator refused in that evaluation, with the reason.")
    evaluations: ItemList[EvaluationList] = private(description="Every evaluation's list of the match, newest first.")
    published_at: UtcDatetime | Missing = private(description="When the analysis was published to readers (never, today).")
    rule_version: str | Missing = private(description="The validator that wrote the list shown (link-v1).")
