"""API-Football as a structured source of the SAME model of facts (IA-128, plan piece AD-C10): its line-ups, its injury report (absences and
suspensions) and its events as typed assertions of ``assertions-v1`` / ``ladder-v2`` (``fbi.ai.assertions``, AD-C07), with their authority,
their four dates and their moment of knowledge - and its coverage per competition as a fact of its own.

WHY. The provider already enters ``ai.evidence`` (its line-up per team, its absences per player) and the evidence engine reads it by the
rules of ``tiers-v1`` (line-up A, injury report B). But it is not an assertion of the model the unified research speaks: it has no type
of claim, no authority per type, no four dates, and a competition whose injury report the provider does not give looks exactly like a
competition where nobody is injured.

WHAT IT IS (pure: ``facts_of`` and ``coverage_facts``; the reads are ``fbi.ai.provider_facts_reads``):

* **The source** (``PROVIDER``): API-Football as a source of the registry, with its authority per type of claim in the directory's words
  (``AUTHORITY``): its registered line-up CONFIRMS (``alineaciones``: the clubs' own team sheet), its absences and suspensions INFORM
  (``lesiones``, ``sanciones``: the provider's word, B in ``tiers-v1``), its events CONFIRM (``resultados``: what happened). It is not
  a row of the directory v2 (that file is pinned; a new directory is a new file): it is written here, versioned with the code.
* **One datum, one assertion.** Each starter of a registered line-up is ``STARTER`` and each substitute ``AVAILABLE``; an absence listed
  ``Missing Fixture`` is ``OUT`` - or ``SUSPENSION`` when its reason is a card or a ban, by the same words as today's evidence
  (``fbi.ai.collectors.SUSPENSION_WORDS``) -, a ``Questionable`` is ``DOUBT``; a goal, a card, a substitution or a VAR decision of a
  player is ``EVENT_<TYPE>``. A datum the code cannot type (an absence type it does not know, an event without a player) is not guessed:
  it is counted apart (``untyped``) with why.
* **Four dates and the moment of knowledge** (``four_dates``, AD-C07): no publication date (the provider gives none: ``none``, never today),
  ``seen_at`` = when PrediGol first knew it - the line-up's first arrival (``core.fixture_lineup_arrivals``, else ``first_seen_at``, AD-D05;
  only if neither exists, its ``fetched_at``, which is never earlier than the first sight), the observation of the injury report, the fetch
  of the events -, ``fact_at`` the kick-off, ``valid_until`` the window of its topic or, for an absence, the next change the provider
  reported (cleared or re-typed), whichever comes first. ``assertions.as_of`` drops what was seen after the moment of a decision.
* **No medical detail.** The reason of an absence is read only to tell a suspension from an injury and is never kept: no assertion
  carries it (a test holds it). An injury is a state, a source and a date.
* **Coverage as a fact** (``coverage_facts``, ``availability_word``): ``raw.league_coverage`` says per competition and season whether the
  provider gives injuries, line-ups and events. A competition it does not cover is ``sin_dato`` - «el proveedor no da bajas en esta
  competición» -, never «sin bajas»; neither is a covered one whose report was not asked for.

Nothing here writes, and nothing that decides, publishes or serves a reader reads it: the evidence engine and the statuses of
``ai.evidence`` keep reading the provider by ``tiers-v1`` (the reversion is to do nothing). ``scripts/ia_provider_facts.py`` prints the
facts of a match, the coverage and the replay against today's states.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

from fbi.ai import assertions
from fbi.ai.collectors import SUSPENSION_WORDS

VERSION: Final = "provider-facts-v1"
DOMAIN: Final = "api-football.com"
AUTHORITY: Final[dict[str, dict[str, str]]] = {
    "alineaciones": {"level": "confirma", "note": "alineación registrada (la hoja del club)"},
    "convocatorias": {"level": "confirma", "note": "titulares y suplentes de la alineación registrada"},
    "lesiones": {"level": "informa", "note": "parte de bajas del proveedor"},
    "sanciones": {"level": "informa", "note": "parte de bajas del proveedor"},
    "resultados": {"level": "confirma", "note": "eventos del partido"},
}
PROVIDER: Final = assertions.SourceFacts(DOMAIN, "api-football", "API-Football", "proveedor", AUTHORITY, tier="A")
"""API-Football as a source of the registry (AD-C01). ``tier`` A: it is never a D source (D never lifts); its rung per type is its authority."""

Origin = Literal["lineup", "injuries", "events"]
AUTHORITY_OF: Final[dict[str, str]] = {"STARTER": "alineaciones", "AVAILABLE": "convocatorias", "OUT": "lesiones", "DOUBT": "lesiones",
                                      "SUSPENSION": "sanciones"}
EVENT_TYPES: Final[dict[str, str]] = {"goal": "EVENT_GOAL", "card": "EVENT_CARD", "subst": "EVENT_SUBST", "var": "EVENT_VAR"}
COVERAGE_DATASETS: Final = ("injuries", "lineups", "events")
CoverageState = Literal["cubre", "no_cubre", "desconocida"]


def authority_of(claim_type: str) -> str:
    word = AUTHORITY_OF.get(claim_type, "resultados" if claim_type.startswith("EVENT_") else "")
    return str((AUTHORITY.get(word) or {}).get("level") or "desconocida")


@dataclass(frozen=True, slots=True)
class ProviderFact:
    """One datum of the provider as an assertion, with where its moment of knowledge comes from and what row it was made of."""

    assertion: assertions.Assertion
    origin: Origin
    known_from: str
    """``arrival`` | ``first_seen_at`` | ``fetched_at`` (line-ups), ``observed_at`` (injury report), ``fetched_at`` (events)."""
    ref: str

    @property
    def known_at(self) -> datetime:
        return self.assertion.seen_at

    def as_json(self) -> dict[str, Any]:
        a = self.assertion
        return {"origin": self.origin, "ref": self.ref, "subject": [a.subject_kind, a.subject_id], "team_id": a.team_id, "claim_type": a.claim_type,
                "authority": a.authority, "authority_why": a.authority_why, "source": a.source.source_id,
                "published_at": None if a.published_at is None else a.published_at.isoformat(), "published_from": a.published_from,
                "seen_at": a.seen_at.isoformat(), "known_from": self.known_from,
                "fact_at": None if a.fact_at is None else a.fact_at.isoformat(),
                "valid_until": None if a.valid_until is None else a.valid_until.isoformat(), "quote": a.quote}


@dataclass
class Made:
    facts: list[ProviderFact] = field(default_factory=list)
    untyped: Counter[str] = field(default_factory=Counter)

    def counts(self) -> dict[str, Any]:
        return {"facts": len(self.facts), "by_origin": dict(sorted(Counter(f.origin for f in self.facts).items())),
                "by_type": dict(sorted(Counter(f.assertion.claim_type for f in self.facts).items())),
                "by_known_from": dict(sorted(Counter(f"{f.origin}:{f.known_from}" for f in self.facts).items())),
                "untyped": dict(sorted(self.untyped.items()))}


def _assertion(*, fixture_id: int, team_id: int | None, player_id: int, claim_type: str, seen_at: datetime, kickoff_at: datetime,
               quote: str, ref: str, until: datetime | None = None) -> assertions.Assertion:
    published, origin, seen, fact, valid = assertions.four_dates(published_at=None, seen_at=seen_at, kickoff_at=kickoff_at,
                                                                 applies_to="THIS_MATCH", claim_type=claim_type)
    if until is not None and until < valid:
        valid = until
    return assertions.Assertion("PLAYER", player_id, team_id, claim_type, f"provider://{DOMAIN}/{ref}", PROVIDER, authority_of(claim_type),
                                f"provider:{AUTHORITY_OF.get(claim_type, 'resultados')}", seen, published, origin, fact, valid, "THIS_MATCH",
                                fixture_id, None, None, quote)


def absence_type_of(absence_type: str | None, reason: str | None) -> str | None:
    """The type of claim of an entry of the injury report (None: a type the code does not know). The reason decides only suspension or not
    - the same words as today's evidence (``fbi.ai.collectors``) - and is dropped here."""
    kind = (absence_type or "").strip().lower()
    if kind.startswith("question"):
        return "DOUBT"
    if kind == "missing fixture":
        r = (reason or "").lower()
        return "SUSPENSION" if any(w in r for w in SUSPENSION_WORDS) else "OUT"
    return None


def lineup_facts(made: Made, *, fixture_id: int, kickoff_at: datetime, team_id: int | None, side: str, players: Sequence[tuple[int | None, bool]],
                 seen_at: datetime, known_from: str) -> None:
    """A registered line-up: (provider player id, starter?) of one team."""
    if not any(starter for _, starter in players):
        made.untyped["lineup_without_starters"] += 1
        return
    for pid, starter in players:
        if pid is None:
            made.untyped["lineup_player_without_id"] += 1
            continue
        kind = "STARTER" if starter else "AVAILABLE"
        ref = f"lineup/{fixture_id}/{side}/{pid}"
        made.facts.append(ProviderFact(_assertion(fixture_id=fixture_id, team_id=team_id, player_id=pid, claim_type=kind, seen_at=seen_at,
                                                  kickoff_at=kickoff_at, quote="titular" if starter else "suplente", ref=ref),
                                       "lineup", known_from, ref))


def injury_facts(made: Made, *, fixture_id: int, kickoff_at: datetime, team_of: Mapping[int, int], observations: Sequence[Mapping[str, Any]]) -> None:
    """The injury report's history of one match (rows of ``core.player_availability_obs``: one per change), each LISTED entry an
    assertion valid until the provider's next change about that player."""
    by_player: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for o in observations:
        by_player[int(o["provider_player_id"])].append(o)
    for pid, rows in sorted(by_player.items()):
        rows = sorted(rows, key=lambda o: o["observed_at"])
        for i, o in enumerate(rows):
            if o["status"] != "LISTED":
                continue
            kind = absence_type_of(o.get("absence_type"), o.get("reason"))
            if kind is None:
                made.untyped["absence_type_unknown"] += 1
                continue
            nxt = rows[i + 1]["observed_at"] if i + 1 < len(rows) else None
            ref = f"injuries/{fixture_id}/{pid}/{o['observed_at'].isoformat()}"
            team = team_of.get(int(o["provider_team_id"])) if o.get("provider_team_id") is not None else None
            made.facts.append(ProviderFact(_assertion(fixture_id=fixture_id, team_id=team, player_id=pid, claim_type=kind,
                                                      seen_at=o["observed_at"], kickoff_at=kickoff_at, quote="", ref=ref, until=nxt),
                                           "injuries", "observed_at", ref))


def event_facts(made: Made, *, fixture_id: int, kickoff_at: datetime, team_of: Mapping[str, int], events: Sequence[Mapping[str, Any]]) -> None:
    """The events of a match (``core.fixture_events``): a goal, a card, a substitution or a VAR decision of a player."""
    for e in events:
        kind = EVENT_TYPES.get(str(e.get("event_type") or "").strip().lower())
        if kind is None:
            made.untyped["event_type_unknown"] += 1
            continue
        if e.get("provider_player_id") is None:
            made.untyped["event_without_player"] += 1
            continue
        minute = f"{e['minute']}'" + (f"+{e['extra_minute']}" if e.get("extra_minute") else "")
        quote = " ".join(str(x) for x in (e.get("detail"), minute) if x)[:120]
        ref = f"events/{fixture_id}/{e['seq']}"
        made.facts.append(ProviderFact(_assertion(fixture_id=fixture_id, team_id=team_of.get(str(e.get("team_side") or "")),
                                                  player_id=int(e["provider_player_id"]), claim_type=kind, seen_at=e["fetched_at"],
                                                  kickoff_at=kickoff_at, quote=quote, ref=ref), "events", "fetched_at", ref))


def as_of(facts: Iterable[ProviderFact], known_at: datetime) -> list[ProviderFact]:
    """What existed at ``known_at``: a fact first known after it does not exist for a decision taken then."""
    return [f for f in facts if f.known_at <= known_at]


def rungs(facts: Iterable[ProviderFact], *, at: datetime) -> list[assertions.Fact]:
    """The ladder-v2 facts of the provider's assertions as of ``at`` (live only)."""
    return assertions.facts([f.assertion for f in as_of(facts, at)], at=at)


# ── coverage ────────────────────────────────────────────────────────────────────────────────────────────────────────

def coverage_state(flag: bool | None) -> CoverageState:
    return "cubre" if flag is True else "no_cubre" if flag is False else "desconocida"


COVERAGE_WORDS: Final[dict[str, dict[str, str]]] = {
    "injuries": {"no_cubre": "el proveedor no da bajas en esta competición", "desconocida": "no se sabe si el proveedor da bajas aquí"},
    "lineups": {"no_cubre": "el proveedor no da alineaciones en esta competición", "desconocida": "no se sabe si da alineaciones aquí"},
    "events": {"no_cubre": "el proveedor no da eventos en esta competición", "desconocida": "no se sabe si da eventos aquí"},
}


def coverage_facts(row: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    """The coverage of a competition and season (a row of ``raw.league_coverage``, or None) as facts: per dataset its state and, when it is
    not covered, what that means in words."""
    out: dict[str, dict[str, str]] = {}
    for ds in COVERAGE_DATASETS:
        state = coverage_state(None if row is None else row.get(ds))
        out[ds] = {"state": state, "means": "" if state == "cubre" else COVERAGE_WORDS[ds][state]}
    return out


AvailabilityWord = Literal["sin_dato", "sin_bajas_listadas", "con_bajas"]


def availability_word(coverage: Mapping[str, Mapping[str, str]], *, checked_at: datetime | None, listed: int) -> tuple[AvailabilityWord, str]:
    """What the provider says of a team's absences for a match: ``sin_dato`` when it does not cover the competition, when its coverage is
    unknown or when the report was not asked for by then; ``sin_bajas_listadas`` only when it covers it, was asked and lists nobody - never
    «sin bajas» from an absence of data."""
    inj = coverage.get("injuries") or {}
    if inj.get("state") != "cubre":
        return "sin_dato", str(inj.get("means") or COVERAGE_WORDS["injuries"]["desconocida"])
    if listed > 0:
        return "con_bajas", f"{listed} en el parte del proveedor"
    if checked_at is None:
        return "sin_dato", "el parte de bajas no se había pedido"
    return "sin_bajas_listadas", f"el proveedor no lista a nadie (parte pedido {checked_at.isoformat()})"


# ── the replay against today's states ───────────────────────────────────────────────────────────────────────────────

EXPECTED: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("lineup", "CONFIRMED"): frozenset({"OFICIAL"}),
    ("injury", "PROBABLE"): frozenset({"REPORTE"}),
    ("suspension", "PROBABLE"): frozenset({"REPORTE"}),
    ("doubtful", "PROBABLE"): frozenset({"REPORTE"}),
    ("injury", "OUTDATED"): frozenset({"retirada"}),
    ("suspension", "OUTDATED"): frozenset({"retirada"}),
    ("doubtful", "OUTDATED"): frozenset({"retirada"}),
}
"""Today's status of the provider's evidence and the rung its assertion takes: a line-up confirmed is OFICIAL (the provider confirms
line-ups), an absence probable is a REPORTE (the provider informs, one origin), an absence the report no longer names is withdrawn (its
assertion is no longer live). Anything else is a difference that the replay lists with its reason."""
KIND_OF: Final[dict[str, str]] = {"OUT": "injury", "DOUBT": "doubtful", "SUSPENSION": "suspension", "STARTER": "lineup", "AVAILABLE": "lineup"}


def _rung_of(e: Mapping[str, Any], facts: Sequence[ProviderFact], at: datetime) -> tuple[str, str]:
    """(rung, kind) of one stored item of the provider, from the assertions of its match as of ``at``."""
    known = as_of(facts, at)
    live = assertions.live([f.assertion for f in known], at)
    kind = str(e["kind"])
    if kind == "lineup":
        team = e.get("team_id")
        if any(a.claim_type == "STARTER" and a.team_id == team for a in live):
            return "OFICIAL", "lineup"
        if any(f.assertion.claim_type == "STARTER" and f.assertion.team_id == team for f in known):
            return "caducada", "lineup"
        return "sin_afirmacion", "lineup"
    pid = e.get("provider_player_id")
    if pid is None:
        return "sin_afirmacion", kind
    mine = [a for a in live if a.subject_id == int(pid) and a.claim_type in ("OUT", "DOUBT", "SUSPENSION")]
    if mine:
        return assertions.rung(mine)[0], KIND_OF[max(mine, key=lambda a: a.seen_at).claim_type]
    if any(f.origin == "injuries" and f.assertion.subject_id == int(pid) for f in known):
        return "retirada", kind
    return "sin_afirmacion", kind


def replay(evidence: Sequence[Mapping[str, Any]], facts: Sequence[ProviderFact]) -> dict[str, Any]:
    """Today's statuses of the provider's evidence (``ai.evidence``, origin provider: a line-up per team, an absence per player) against
    the rungs of its assertions AT THE MOMENT each status was decided (``status_changed_at``): the matrix, and every pair outside
    ``EXPECTED`` with its reason."""
    by_fixture: dict[int | None, list[ProviderFact]] = defaultdict(list)
    for f in facts:
        by_fixture[f.assertion.fixture_id].append(f)
    matrix: Counter[str] = Counter()
    diffs: list[dict[str, Any]] = []
    for e in evidence:
        kind, status, fixture = str(e["kind"]), str(e["status"]), e.get("fixture_id")
        at = e.get("status_changed_at") or e["retrieved_at"]
        rung, kind_v2 = _rung_of(e, by_fixture.get(fixture, []), at)
        matrix[f"{kind}:{status}->{rung}"] += 1
        if rung in EXPECTED.get((kind, status), frozenset()) and kind_v2 == kind:
            continue
        reason = ("tipo_distinto" if kind_v2 != kind else "caducada_por_ventana" if rung == "caducada" else
                  "sin_afirmacion" if rung == "sin_afirmacion" else "retirada_por_el_parte" if rung == "retirada" else
                  "estado_retirado_hoy" if status == "OUTDATED" else "otro")
        diffs.append({"evidence_id": e.get("id"), "fixture_id": fixture, "kind": kind, "status": status, "rung": rung, "kind_v2": kind_v2,
                      "reason": reason, "at": at.isoformat()})
    return {"version": VERSION, "evidence": len(evidence), "facts": len(facts), "matrix": dict(sorted(matrix.items())),
            "differences": len(diffs), "by_reason": dict(sorted(Counter(d["reason"] for d in diffs).items())), "listed": diffs[:200],
            "decides": False}


__all__ = ["AUTHORITY", "DOMAIN", "EXPECTED", "PROVIDER", "VERSION", "Made", "ProviderFact", "absence_type_of", "as_of", "authority_of",
           "availability_word", "coverage_facts", "event_facts", "injury_facts", "lineup_facts", "replay", "rungs"]
