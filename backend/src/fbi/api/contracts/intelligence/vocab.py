"""The closed vocabularies every Intelligence contract speaks (AD-J01, IA-057).

Each list is a ``Literal`` (what the API validates and the OpenAPI document publishes) and a tuple of the same codes (what
the tests and the owner's guide read). The web translates each code into its text (ES/EN) and never deduces one code from
others: if a value is not in the list, it does not travel. Adding a code is an additive change of the contract (minor
version); removing or renaming one breaks it (major version) - ``fbi.api.contracts.intelligence.versioning`` says which.

The codes are the ones agreed with the UX session (coordination of the 18 screens, «Vocabularios cerrados», 16-nov-2026).
"""

from __future__ import annotations

from typing import Final, Literal, get_args

LifecycleState = Literal["detectado", "en_investigacion", "en_evaluacion", "pendiente_alineaciones", "confirmada_sombra",
                         "retirada", "descartada", "en_juego", "liquidada", "evaluada"]
"""The ten states of a selection's cycle (AD-D02). Only the private projection carries them."""

PublicState = Literal["publicada", "en_juego", "liquidada"]
"""The only states a reader sees: published by the owner before kick-off, in play, settled. The server derives them from
the cycle (``public_state_of``); a selection without one never reaches the public projection."""

CalibrationSeal = Literal["calibrada", "sin_calibrar"]
"""The seal of every probability: calibrated by a champion calibrator, or the model's own number said as such."""

EvaluationStep = Literal["E1", "E2", "E3", "E4"]
"""E1 first reading (T-24/12 h), E2 a new fact, E3 the official line-up (code only), E4 closing (T-5) (AD-D06)."""

SettlementResult = Literal["pending", "win", "loss", "push", "void", "half_win", "half_loss"]
"""The results of ``settle-v4`` (``fbi.picks.settlement.Status``), as they are stored."""

ConfirmationLevel = Literal["oficial", "dos_origenes", "declaracion", "un_medio", "rumor"]
"""How confirmed a fact is (AD-C07, AD-G03). Syndication does not raise the level."""

FactCategory = Literal["hecho_confirmado", "informacion_probable", "rumor", "interpretacion_tactica", "hipotesis"]
"""The five categories of a context fact (plan RP-4.1, ``fbi.ai.factor_schema``): given by code from the state of the fact; a text and the registry
of factors write the last two, never evidence."""

StoryWarning = Literal["contradiccion", "desactualizada"]
"""Two notices a story can carry without being a level of confirmation."""

ValidationVerdict = Literal["VALIDADO", "NO_VALIDADO", "INSUFICIENTE"]
"""The market validation's verdict (AD-K02); it always travels with its sample and the sample it needs."""

MarketState = Literal["evaluable", "en_calibracion", "necesita_datos", "no_ofrecer"]
"""Where a market stands (AD-E01)."""

CapabilityState = Literal["construida", "en_sombra", "lista_revision", "autorizada"]
"""How far a capability has gone (AD-003): built, in the shadow, ready for review, authorised by the owner."""

AbstentionCode = Literal["SIN_PRECIO_VIGENTE", "UNA_SOLA_CASA", "VALOR_INSUFICIENTE", "MERCADO_NO_EVALUABLE",
                         "SIN_ALINEACION_A_TIEMPO", "NINGUNO_CUMPLE", "SIN_HECHO_QUE_LO_AUTORICE",
                         "CONTRADICCION_MATERIAL"]
"""Why the system does not produce something. Upper case so that they are never mistaken for a ``missing_reason``.
``SIN_OBJETIVO_DEMOSTRADO`` is not one: it is a statement only the scenario engine makes (AD-F01)."""

MissingReason = Literal["no_entregado", "aun_no_disponible", "sin_datos", "sin_cobertura", "reglamento_no_codificado",
                        "muestra_insuficiente", "pendiente_derechos", "retirado_por_derechos", "sin_publicados",
                        "sin_resultados", "sin_favoritos"]
"""Why a field has no value (``Missing``) or a list is empty (``ItemList``). Never a mute null."""

FactRelation = Literal["a_favor", "en_contra", "contexto", "no_usada"]
"""How a fact relates to the analysis (AD-G08)."""

Availability = Literal["disponible", "duda", "baja", "sancionado"]
"""A player's availability (AD-H05): the state, its source and its date - nothing medical."""

LineupDependency = Literal["baja", "media", "alta"]
"""How much a selection depends on the official line-up (AD-D03)."""

Projection = Literal["public", "private"]
"""Which projection an answer is: ``public`` under ``/api/v1/…``, ``private`` under ``/api/v1/admin/…``."""


LIST_ONLY_REASONS: Final[frozenset[str]] = frozenset({"sin_publicados", "sin_resultados", "sin_favoritos"})
"""Reasons that only an empty list gives (the reader's empty lists), never a single field."""

VOCABULARIES: Final[dict[str, tuple[str, ...]]] = {
    "lifecycle_state": get_args(LifecycleState),
    "public_state": get_args(PublicState),
    "calibration": get_args(CalibrationSeal),
    "evaluation": get_args(EvaluationStep),
    "settlement_result": get_args(SettlementResult),
    "confirmation_level": get_args(ConfirmationLevel),
    "fact_category": get_args(FactCategory),
    "story_warning": get_args(StoryWarning),
    "validation_verdict": get_args(ValidationVerdict),
    "market_state": get_args(MarketState),
    "capability_state": get_args(CapabilityState),
    "abstention_code": get_args(AbstentionCode),
    "missing_reason": get_args(MissingReason),
    "fact_relation": get_args(FactRelation),
    "availability": get_args(Availability),
    "lineup_dependency": get_args(LineupDependency),
    "projection": get_args(Projection),
}
"""Every closed list by the name the guide and the tests use."""

PRE_PUBLICATION_STATES: Final[frozenset[str]] = frozenset({"confirmada_sombra"})
"""The one state of the cycle a selection can be published from: it meets everything and waits for the owner."""


def public_state_of(state: str, *, authorised: bool) -> str | None:
    """The state a reader sees of a selection, or None when it must not reach the public projection.

    Nothing is public without the owner's authorisation. With it, a selection that meets everything before kick-off is
    ``publicada``, one whose match started is ``en_juego``, and one with a result (settled or already evaluated) is
    ``liquidada``. Every other state - detected, under investigation or evaluation, waiting for line-ups, withdrawn,
    discarded - stays private, authorised or not.
    """
    if state not in get_args(LifecycleState):
        raise ValueError(f"unknown lifecycle state {state!r}")
    if not authorised:
        return None
    if state in PRE_PUBLICATION_STATES:
        return "publicada"
    if state == "en_juego":
        return "en_juego"
    if state in ("liquidada", "evaluada"):
        return "liquidada"
    return None
