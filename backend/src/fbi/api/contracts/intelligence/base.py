"""The base types every Intelligence contract is built from (AD-J01, IA-057).

* ``IntelligenceModel`` - frozen, and an unknown field is refused, never ignored.
* ``private(...)`` - marks a field that only the private projection carries (``fbi.api.contracts.intelligence.projection``
  builds the public one without it).
* ``Missing`` - a field without value says why: ``{"missing_reason": "no_entregado", "expected_piece": "AD-B02"}``.
* ``ItemList`` - a list that is empty says why: ``{"items": [], "missing_reason": "sin_publicados"}``.
* ``Probability`` - every probability travels sealed: value, the percentage already rounded by the server, the calibration
  seal, its time, the evaluation step and its version, and where it came from. The web draws it; it never recomputes it.
* ``DatedFact`` - the four dates of a fact (``published_at``, ``known_at``, ``fact_at``, ``valid_until``).
* ``Freshness`` - the server says whether what it answers is old.
* ``MarketValidation`` - a verdict always with its sample and the sample it needs.
* ``IntelligenceContract`` - the head of every answer: ``contract``, ``contract_version``, ``projection``, ``freshness``.

Times are UTC, ISO 8601 with the zone (``2026-11-21T23:00:00Z``): a time without a zone is refused.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any, ClassVar, Final, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticUndefined

from fbi.api.contracts.intelligence.vocab import (
    LIST_ONLY_REASONS,
    CalibrationSeal,
    ConfirmationLevel,
    EvaluationStep,
    FactRelation,
    MissingReason,
    Projection,
    ValidationVerdict,
)

PRIVATE_MARK: Final = "x-projection"
"""The key a private field carries in its JSON Schema (``"x-projection": "private"``): the web's generated types see it."""

PIECE_PATTERN: Final = r"^AD-[0-9A-Z]{2,4}$"
"""A piece of the plan: ``AD-001``, ``AD-B02``, ``AD-J01``."""

VERSION_PATTERN: Final = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
CODE_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
ORIGIN_PATTERN: Final = r"^[a-z][a-z0-9_]*(-v\d+)?$"


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]
"""A time with its zone, kept and served in UTC."""


def _absent(value: object) -> bool:
    return value is None


def private(default: Any = PydanticUndefined, *, description: str, **kwargs: Any) -> Any:
    """A field only the private projection carries. The public projection is built without it: it does not travel, not
    even as a ``missing_reason``."""
    return Field(default, description=description, json_schema_extra={PRIVATE_MARK: "private"}, **kwargs)


def is_private(model: type[BaseModel], name: str) -> bool:
    extra = model.model_fields[name].json_schema_extra
    return isinstance(extra, dict) and extra.get(PRIVATE_MARK) == "private"


class IntelligenceModel(BaseModel):
    """Every model of an Intelligence contract: frozen, and a field it does not declare is an error. In the schema of
    the answer, a field with a default is always present (it is always served); one left out when absent is not."""

    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)

    def shown_in_public(self) -> bool:
        """False: this item is left out of a list in the public projection (a selection the owner did not publish).
        A model that answers False where it is not an item of a list cannot be projected (``ProjectionError``)."""
        return True


# ── absent with a reason ─────────────────────────────────────────────────────────────────────────────────────────────

REQUIRED_WITH: Final[dict[str, frozenset[str]]] = {
    "no_entregado": frozenset({"expected_piece"}),
    "aun_no_disponible": frozenset({"expected_at"}),
    "muestra_insuficiente": frozenset({"sample", "min_sample"}),
}
"""What each reason must say besides itself."""

ALLOWED_WITH: Final[dict[str, frozenset[str]]] = {
    "no_entregado": frozenset({"expected_piece", "expected_at"}),
    "aun_no_disponible": frozenset({"expected_at"}),
    "muestra_insuficiente": frozenset({"sample", "min_sample"}),
}
"""What each reason may say besides itself; every other reason says nothing more."""

ACCOMPANYING: Final = ("expected_piece", "expected_at", "sample", "min_sample")


def reason_problems(reason: str | None, values: dict[str, object]) -> list[str]:
    """What is wrong with a reason and the fields that go with it (empty: nothing)."""
    given = {name for name in ACCOMPANYING if values.get(name) is not None}
    if reason is None:
        return [f"{', '.join(sorted(given))} without a missing_reason"] if given else []
    problems = [f"{reason} needs {name}" for name in sorted(REQUIRED_WITH.get(reason, frozenset()) - given)]
    problems += [f"{reason} does not take {name}" for name in sorted(given - ALLOWED_WITH.get(reason, frozenset()))]
    sample, needed = values.get("sample"), values.get("min_sample")
    if isinstance(sample, int) and isinstance(needed, int) and sample >= needed:
        problems.append(f"sample {sample} is not below min_sample {needed}")
    return problems


class Missing(IntelligenceModel):
    """A field without value and the reason why. The accompanying fields that do not apply are left out of the JSON."""

    missing_reason: MissingReason
    expected_piece: str | None = Field(
        default=None, pattern=PIECE_PATTERN, exclude_if=_absent,
        description="The piece that will compute it (with no_entregado).")
    expected_at: UtcDatetime | None = Field(
        default=None, exclude_if=_absent,
        description="When it is expected (with aun_no_disponible; optional with no_entregado).")
    sample: int | None = Field(default=None, ge=0, exclude_if=_absent,
                               description="The sample there is (with muestra_insuficiente).")
    min_sample: int | None = Field(default=None, ge=1, exclude_if=_absent,
                                   description="The sample the contract needs (with muestra_insuficiente).")

    @model_validator(mode="after")
    def _accompanied(self) -> Missing:
        if self.missing_reason in LIST_ONLY_REASONS:
            raise ValueError(f"{self.missing_reason} is the reason of an empty list (ItemList), not of a field")
        if problems := reason_problems(self.missing_reason, self.__dict__):
            raise ValueError("; ".join(problems))
        return self


class ItemList[T](IntelligenceModel):
    """A list that says why when it is empty, and only then."""

    items: list[T]
    missing_reason: MissingReason | None = Field(default=None, exclude_if=_absent,
                                                 description="Why the list is empty: present exactly when it is.")
    expected_piece: str | None = Field(default=None, pattern=PIECE_PATTERN, exclude_if=_absent)
    expected_at: UtcDatetime | None = Field(default=None, exclude_if=_absent)
    sample: int | None = Field(default=None, ge=0, exclude_if=_absent)
    min_sample: int | None = Field(default=None, ge=1, exclude_if=_absent)

    @model_validator(mode="after")
    def _reason_when_empty(self) -> ItemList[T]:
        if not self.items and self.missing_reason is None:
            raise ValueError("an empty list needs a missing_reason")
        if self.items and self.missing_reason is not None:
            raise ValueError("a list with items carries no missing_reason")
        if problems := reason_problems(self.missing_reason, self.__dict__):
            raise ValueError("; ".join(problems))
        return self


# ── the sealed probability ───────────────────────────────────────────────────────────────────────────────────────────

def rounded_pct(value: float, decimals: int = 0) -> int | float:
    """The percentage the web draws: ``value`` x 100 rounded half up to 0 or 1 decimals (0.785 -> 79, or 78.5)."""
    if decimals not in (0, 1):
        raise ValueError("a percentage is drawn with 0 or 1 decimals")
    pct = (Decimal(repr(value)) * 100).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return int(pct) if decimals == 0 else float(pct)


class PctInterval(IntelligenceModel):
    """The range around a probability, in whole percentage points, already rounded by the server."""

    low: int = Field(ge=0, le=100)
    high: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _ordered(self) -> PctInterval:
        if self.low > self.high:
            raise ValueError("an interval's low is above its high")
        return self


class Probability(IntelligenceModel):
    """One probability with its seal. The web draws ``pct`` as it comes: it never recomputes, rounds otherwise,
    combines or chooses between probabilities."""

    value: float = Field(ge=0, le=1, description="The proportion, to draw with (0.57).")
    pct: int | float = Field(description="The percentage the web paints, rounded half up by the server from value "
                                         "(57, or 78.5 when the contract shows one decimal).")
    interval_pct: PctInterval | Missing = Field(description="The range in percentage points, or why there is none.")
    calibration: CalibrationSeal = Field(description="calibrada: a champion calibrator's output; sin_calibrar: the "
                                                     "model's own number, said as such once.")
    as_of: UtcDatetime = Field(description="When this figure was computed.")
    evaluation: EvaluationStep | Missing = Field(description="The evaluation step (E1-E4) the figure belongs to.")
    evaluation_version: int | Missing = Field(description="The version of that evaluation: each one adds a version, "
                                                          "none is rewritten.")
    origin: str = Field(pattern=ORIGIN_PATTERN, description="What computed it: forecast-v1 (the common view today), "
                                                            "market_view from AD-B05.")

    @classmethod
    def of(cls, value: float, *, calibration: CalibrationSeal, as_of: datetime, origin: str,
           evaluation: EvaluationStep | Missing, evaluation_version: int | Missing,
           interval: tuple[int, int] | Missing, decimals: int = 0) -> Probability:
        """The sealed figure, with the percentage rounded here - the one place it is rounded."""
        band = interval if isinstance(interval, Missing) else PctInterval(low=interval[0], high=interval[1])
        return cls(value=value, pct=rounded_pct(value, decimals), interval_pct=band, calibration=calibration,
                   as_of=as_of, evaluation=evaluation, evaluation_version=evaluation_version, origin=origin)

    @model_validator(mode="after")
    def _consistent(self) -> Probability:
        decimals = 0 if float(self.pct).is_integer() else 1
        if float(self.pct) != float(rounded_pct(self.value, decimals)):
            raise ValueError(f"pct {self.pct} is not {self.value} rounded half up by the server")
        if isinstance(self.evaluation, Missing) != isinstance(self.evaluation_version, Missing):
            raise ValueError("evaluation and evaluation_version are both given or both missing")
        if isinstance(self.evaluation_version, int) and self.evaluation_version < 1:
            raise ValueError("evaluation_version starts at 1")
        band = self.interval_pct
        if isinstance(band, PctInterval) and not band.low <= float(self.pct) <= band.high:
            raise ValueError(f"pct {self.pct} lies outside its interval {band.low}-{band.high}")
        return self


# ── dates, freshness, validation ─────────────────────────────────────────────────────────────────────────────────────

def _midnight(value: datetime | Missing) -> bool:
    return isinstance(value, datetime) and (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)


class DatedFact(IntelligenceModel):
    """The four dates of a fact. Nothing is presented as known before its ``known_at``. When the source gave only the
    day, ``*_day_only`` is true, the time reads 00:00 UTC and the web shows the day, never an hour."""

    published_at: UtcDatetime | Missing = Field(description="When the source published it.")
    published_day_only: bool = False
    known_at: UtcDatetime = Field(description="When PrediGol incorporated it (mandatory, AD-A04).")
    fact_at: UtcDatetime | Missing = Field(description="When it happens.")
    fact_day_only: bool = False
    valid_until: UtcDatetime | Missing = Field(description="Until when it holds.")

    @model_validator(mode="after")
    def _day_only_is_a_day(self) -> DatedFact:
        for name in ("published", "fact"):
            if getattr(self, f"{name}_day_only") and not _midnight(getattr(self, f"{name}_at")):
                raise ValueError(f"{name}_day_only needs {name}_at at 00:00 UTC")
        return self


class Freshness(IntelligenceModel):
    """The server says whether the answer is old; the web only shows its notice."""

    generated_at: UtcDatetime
    stale: bool
    stale_reason: str | None = Field(default=None, pattern=CODE_PATTERN,
                                     description="A code, given exactly when stale is true (null otherwise).")

    @model_validator(mode="after")
    def _reason_when_stale(self) -> Freshness:
        if self.stale != (self.stale_reason is not None):
            raise ValueError("stale_reason is given exactly when stale is true")
        return self


class MarketValidation(IntelligenceModel):
    """Whether a market's edge is validated (AD-K02). VALIDADO and NO_VALIDADO need the full sample; below it the
    verdict is INSUFICIENTE. A hit never validates a market."""

    verdict: ValidationVerdict
    sample: int = Field(ge=0)
    needed: int = Field(ge=1)

    @model_validator(mode="after")
    def _sample_decides(self) -> MarketValidation:
        if (self.verdict == "INSUFICIENTE") != (self.sample < self.needed):
            raise ValueError(f"{self.verdict} does not agree with a sample of {self.sample} of {self.needed}")
        return self


class Source(IntelligenceModel):
    """Where a fact was read."""

    name: str = Field(min_length=1)
    url: str | Missing


class CitedFact(DatedFact):
    """A fact the analysis cites: its words, its level of confirmation, how it relates to the analysis and its source."""

    text: str = Field(min_length=1)
    confirmation: ConfirmationLevel
    relation: FactRelation
    source: Source


# ── the head of every contract ───────────────────────────────────────────────────────────────────────────────────────

class IntelligenceContract(IntelligenceModel):
    """What every Intelligence answer starts with. A contract's class sets ``CONTRACT_ID`` and ``CONTRACT_VERSION``
    once; the answer repeats them, and an example with another version does not validate. ``projection`` says which of
    the two projections it is: private when anything reachable from the class is a private field (or the contract has
    no public projection at all, ``PRIVATE_ONLY``), public otherwise."""

    CONTRACT_ID: ClassVar[str]
    CONTRACT_VERSION: ClassVar[str]
    PRIVATE_ONLY: ClassVar[bool] = False

    # The three heads are filled from the class when the builder leaves them out (the defaults are never served: the
    # validator below puts the class's values in first, and refuses any other).
    contract: str = Field(default="", description="The contract's id (C-01 ... C-12).")
    contract_version: str = Field(default="0.0.0", pattern=VERSION_PATTERN,
                                  description="MAJOR.MINOR.PATCH: an additive change raises the minor, one that breaks "
                                              "raises the major.")
    projection: Projection = Field(default="public", description="public under /api/v1/..., private under "
                                                                 "/api/v1/admin/... (require_admin).")
    freshness: Freshness

    @model_validator(mode="before")
    @classmethod
    def _head(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {"contract": cls.CONTRACT_ID, "contract_version": cls.CONTRACT_VERSION,
                    "projection": cls.expected_projection()} | data
        return data

    @classmethod
    def expected_projection(cls) -> Literal["public", "private"]:
        from fbi.api.contracts.intelligence.projection import has_private

        return "private" if cls.PRIVATE_ONLY or has_private(cls) else "public"

    @model_validator(mode="after")
    def _is_what_it_says(self) -> IntelligenceContract:
        cls = type(self)
        if (self.contract, self.contract_version) != (cls.CONTRACT_ID, cls.CONTRACT_VERSION):
            raise ValueError(f"{self.contract} {self.contract_version} is not {cls.CONTRACT_ID} {cls.CONTRACT_VERSION}")
        if self.projection != cls.expected_projection():
            raise ValueError(f"{cls.__name__} is the {cls.expected_projection()} projection, not {self.projection}")
        return self
