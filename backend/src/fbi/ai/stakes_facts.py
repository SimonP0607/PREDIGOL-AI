"""What each team of a match plays for, said as a calculated context fact (plan RP-4.2, findings H16 and H18, ``stakes-facts-v1``).

``FBI_STAKES_FACTS`` (off by default): nothing is written until the switch is turned on with the audited kit. The facts are PRIVATE: they feed the
packet and the fact sheet of a match, never a probability.

SITUATION, NEVER A PREDICTION. The engine ``fbi.competitions.scenarios`` (``scenarios-v2``) already proves, from the table, the matches left and the
points system, which objectives of a regulation a team has secured, has lost or still has open. This module only SAYS that, per team and per match,
as one fact under the schema of RP-4.1 (``fbi.ai.factor_schema``): origin «own calculation», kind ``stakes``, the entity (the team), the side it
affects (home or away), the source's date (the moment of the reading) and the validity (until kick-off). The calculation travels in the fact's
attributes, so anybody can recompute it from the reading it cites (``reading_hash``).

What a fact never says: that a team «will perform more», «is motivated» or «has nothing to lose» as a forecast. «Sin objetivo demostrado» is the
engine's own fact (``SIN_OBJETIVO_DEMOSTRADO``) and is written only when the engine proved it; a competition whose regulation is not coded
(``reglamento_no_codificado``) and a team the reading cannot place in a table produce NO fact: the absence is counted (``Counts.not_coded``,
``Counts.no_table``) and never filled in.

AS OF A MOMENT: the newest reading of the match's competition season computed by ``at`` and not older than ``MAX_AGE``; nothing of the match's own
result. Reads ``intel.scenario_readings`` and ``core.fixtures``; writes ``ai.evidence`` only through ``fbi.ai.evidence.store`` and only on ``on``.
0 requests.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai import evidence, factor_schema
from fbi.competitions.scenarios import FACT_NO_OBJECTIVE, NOT_CODED

SWITCH: Final = "FBI_STAKES_FACTS"
VERSION: Final = "stakes-facts-v1"
SOURCE_NAME: Final = "PrediGol · escenarios (scenarios-v2)"
MAX_AGE: Final = timedelta(days=3)
"""A reading older than this says nothing about the table of today; the same bound the chronicle uses for the same reading."""
AHEAD: Final = timedelta(days=3)
"""Matches that kick off within this long after ``at`` get their facts."""
MAX_CLAIM: Final = 560
"""The store keeps 600 characters of a claim; a fact never relies on being cut."""
TABLES: Final = ("intel.scenario_readings", "core.fixtures", "ai.evidence")

PHRASE: Final[Mapping[str, str]] = {
    "titulo": "ganar el título", "clasificacion": "clasificar a la siguiente fase", "plaza_de_playoff": "entrar a la fase de playoff",
    "plaza_continental": "lograr una plaza continental", "ascenso": "ascender", "desempate_por_el_titulo": "jugar el desempate por el título",
    "evitar_descenso": "evitar el descenso", "evitar_promocion_de_descenso": "evitar el playoff de descenso",
    "evitar_eliminacion": "evitar la eliminación",
}
"""Each objective of the engine, as the infinitive phrase the sentence uses."""
RULE: Final = ("Hecho calculado, no una probabilidad ni un juicio sobre el rendimiento: lo que ya está demostrado (asegurado o perdido) o sigue "
               "abierto según la tabla, los partidos que faltan y el reglamento codificado, a la fecha de la lectura.")


def mode(env: Mapping[str, str] | None = None) -> str:
    """``off`` unless the switch says on (``1``, ``on``, ``true``, ``yes``): born off."""
    e = os.environ if env is None else env
    return "on" if e.get(SWITCH, "0").strip().lower() in ("1", "on", "true", "yes") else "off"


@dataclass(frozen=True, slots=True)
class Match:
    """The match a fact is about, as ``core.fixtures`` has it."""

    fixture_id: int
    kickoff: datetime
    home_id: int
    away_id: int


@dataclass(frozen=True, slots=True)
class Stake:
    """One team's situation in one table: the objectives still open, the ones secured and the ones lost, as the engine proved them."""

    table: str
    team: int
    place: int | None
    points: int
    left: int
    open: tuple[str, ...]
    secured: tuple[str, ...]
    lost: tuple[str, ...]
    conditional: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StakeFact:
    """A fact ready to be stored: the sentence and the calculation behind it."""

    match: Match
    team: int
    side: str
    claim: str
    relevance: float
    calculation: Mapping[str, Any]


@dataclass(slots=True)
class Counts:
    """What a run did, so a gap is visible and never filled in."""

    matches: int = 0
    facts: int = 0
    created: int = 0
    not_coded: int = 0
    no_reading: int = 0
    no_table: int = 0
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "matches": self.matches, "facts": self.facts, "created": self.created, "not_coded": self.not_coded,
                "no_reading": self.no_reading, "no_table": self.no_table, "errors": self.errors}


# ── pure facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _phrase(objective: Mapping[str, Any], *, qualify: bool = False) -> str:
    """The objective as a phrase. When a table holds two objectives of one kind (two continental places, say) each says how far up it has to finish, so that
    «secured» and «still open» never name the same thing twice."""
    base = PHRASE.get(str(objective["objetivo"]), str(objective["objetivo"]))
    within = objective.get("terminar_entre_los")
    return f"{base} (entre los {within} primeros)" if qualify and within is not None else base


def stakes_of(reading: Mapping[str, Any], team: int) -> list[Stake]:
    """The team's situation in every table of the reading it is in (empty when the reading has none or is not ``ok``)."""
    if reading.get("status") != "ok":
        return []
    out: list[Stake] = []
    for table in reading.get("tables", []):
        for row in table.get("teams", []):
            if int(row["team"]) != team:
                continue
            opened, secured, lost, conditional = [], [], [], []
            kinds = Counter(str(o["objetivo"]) for o in row.get("objetivos", []))
            for o in row.get("objetivos", []):
                qualify = kinds[str(o["objetivo"])] > 1
                proved = bool(o.get("decidido", {}).get("demostrado"))
                if o.get("condicional"):
                    conditional.append(_phrase(o, qualify=qualify))
                elif proved and o["estado"] == "conseguido":
                    secured.append(_phrase(o, qualify=qualify))
                elif proved and o["estado"] == "descartado":
                    lost.append(_phrase(o, qualify=qualify))
                else:
                    opened.append(_phrase(o, qualify=qualify))
            out.append(Stake(str(table["key"]), team, row.get("puesto"), int(row["puntos"]), int(row["partidos_restantes"]), tuple(opened),
                             tuple(secured), tuple(lost), tuple(conditional)))
    return out


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def sentence(stake: Stake, *, name: str, multiple: bool) -> str:
    """One table's situation in Spanish: what is still open first, then what is secured, then what is lost."""
    where = f" en {stake.table}" if multiple else ""
    place = f"{stake.place}.º con " if stake.place is not None else ""
    base = f"{name}{where}: {place}{stake.points} puntos y {stake.left} partido{'' if stake.left == 1 else 's'} por jugar"
    parts: list[str] = []
    if stake.open:
        parts.append(f"sigue en juego {_join(stake.open)}")
    if stake.secured:
        parts.append(f"ya tiene asegurado {_join(stake.secured)}")
    if stake.lost:
        parts.append(f"ya no puede {_join(stake.lost)}")
    if stake.conditional:
        parts.append(f"{_join(stake.conditional)} depende de otra competición y no está decidido")
    return base + ("; " + "; ".join(parts) if parts else "") + "."


def fact_of(reading: Mapping[str, Any], match: Match, side: str, name: str) -> StakeFact | None:
    """The fact of one side of one match, or None when the reading cannot say (not coded, or the team is in no table)."""
    team = match.home_id if side == "home" else match.away_id
    stakes = stakes_of(reading, team)
    verdict = reading.get("teams", {}).get(str(team), {})
    proved_none = verdict.get("hecho") == FACT_NO_OBJECTIVE and bool(verdict.get("demostrado"))
    if stakes:
        claim = " ".join(sentence(s, name=name, multiple=len(stakes) > 1) for s in stakes)
        if proved_none:
            claim += f" No le queda ningún objetivo abierto, demostrado ({FACT_NO_OBJECTIVE})."
        relevance = 0.8 if any(s.open for s in stakes) else 0.6
    elif proved_none:
        claim = f"{name}: sin objetivo por jugar en las tablas codificadas; todos están decididos y demostrados ({FACT_NO_OBJECTIVE})."
        relevance = 0.5
    else:
        return None
    if len(claim) > MAX_CLAIM:
        claim = claim[: MAX_CLAIM - 1].rstrip() + "…"
    effects = {str(t["key"]): t["matches"][str(match.fixture_id)][side] for t in reading.get("tables", [])
               if str(match.fixture_id) in t.get("matches", {}) and side in t["matches"][str(match.fixture_id)]}
    calculation = {
        "version": VERSION, "engine": reading.get("version"), "reading_at": reading.get("at"), "reading_hash": reading.get("input_hash"),
        "rules": (reading.get("rules") or {}).get("sha256"), "team": team, "side": side, "rule": RULE,
        "tables": [{"key": s.table, "place": s.place, "points": s.points, "left": s.left, "open": list(s.open), "secured": list(s.secured),
                    "lost": list(s.lost), "conditional": list(s.conditional)} for s in stakes],
        "no_objective": bool(verdict.get("demostrado")), "by_result": effects}
    return StakeFact(match, team, side, claim, relevance, calculation)


def facts_of(reading: Mapping[str, Any] | None, match: Match, names: Mapping[int, str]) -> tuple[list[StakeFact], str | None]:
    """Both sides' facts of a match and, when there is none, why (``no_reading``, ``not_coded`` or ``no_table``)."""
    if reading is None:
        return [], "no_reading"
    if reading.get("status") == NOT_CODED:
        return [], NOT_CODED
    out = [f for side, team in (("home", match.home_id), ("away", match.away_id))
           if (f := fact_of(reading, match, side, names.get(team, f"equipo {team}"))) is not None]
    return out, None if out else "no_table"


def item_of(fact: StakeFact, *, at: datetime) -> evidence.EvidenceIn:
    """The fact as the item the store takes: complete in the seven attributes, or ``store`` refuses it."""
    published = datetime.fromisoformat(str(fact.calculation["reading_at"]))
    return evidence.EvidenceIn(
        fixture_id=fact.match.fixture_id, team_id=fact.team, kind="stakes", claim=fact.claim, origin="own_calc", source_name=SOURCE_NAME,
        retrieved_at=at, story_key=f"stakes:{fact.match.fixture_id}:{fact.team}", assertion="info", published_at=published,
        confidence=0.95, relevance=fact.relevance, attributes={"calculation": VERSION, **fact.calculation}, claim_type="OTHER",
        subject_type="TEAM", subject_id=fact.team, fresh_until=fact.match.kickoff, side=fact.side, fact_schema=factor_schema.VERSION)


# ── the database ───────────────────────────────────────────────────────────────────────────────────────────────────────

MATCHES_SQL: Final = """
SELECT f.id AS fixture_id, f.kickoff_at, f.home_team_id, f.away_team_id, f.competition_season_id,
       h.name AS home_name, a.name AS away_name, c.name AS competition
  FROM core.fixtures f
  JOIN core.teams h ON h.id = f.home_team_id
  JOIN core.teams a ON a.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.kickoff_at >= %(at)s AND f.kickoff_at < %(until)s AND f.competition_season_id IS NOT NULL
 ORDER BY f.kickoff_at, f.id
"""
READING_SQL: Final = """
SELECT reading FROM intel.scenario_readings
 WHERE competition_season_id = %(cs)s AND computed_at <= %(at)s AND computed_at > %(since)s
 ORDER BY computed_at DESC, id DESC LIMIT 1
"""
"""Through ``intel_scenario_readings_season`` (competition season, id DESC), the same access the chronicle uses."""


@dataclass(frozen=True, slots=True)
class Read:
    """One match with what the reading says about it (``facts`` empty and ``why`` set when it says nothing)."""

    match: Match
    competition: str
    home: str
    away: str
    facts: list[StakeFact]
    why: str | None


def collect(conn: psycopg.Connection[Any], *, at: datetime, ahead: timedelta = AHEAD) -> list[Read]:
    """The facts of the matches that kick off within ``ahead`` of ``at``, as of ``at``. Reads only."""
    readings: dict[int, Mapping[str, Any] | None] = {}
    out: list[Read] = []
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(MATCHES_SQL, {"at": at, "until": at + ahead}).fetchall()
        for r in rows:
            cs = int(r["competition_season_id"])
            if cs not in readings:
                found = cur.execute(READING_SQL, {"cs": cs, "at": at, "since": at - MAX_AGE}).fetchone()
                readings[cs] = found["reading"] if found and isinstance(found["reading"], Mapping) else None
            match = Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]))
            facts, why = facts_of(readings[cs], match, {match.home_id: r["home_name"], match.away_id: r["away_name"]})
            out.append(Read(match, str(r["competition"]), str(r["home_name"]), str(r["away_name"]), facts, why))
    return out


def run(conn: psycopg.Connection[Any], *, at: datetime, write: bool | None = None, ahead: timedelta = AHEAD) -> Counts:
    """The facts of the matches that kick off within ``ahead`` of ``at``. Nothing is written unless ``write`` (default: the switch is ``on``)
    and a match whose fact the store refuses is counted in ``errors`` and does not stop the others. The caller commits."""
    do_write = mode() == "on" if write is None else write
    counts = Counts()
    for read in collect(conn, at=at, ahead=ahead):
        counts.matches += 1
        if read.why == "no_reading":
            counts.no_reading += 1
        elif read.why == NOT_CODED:
            counts.not_coded += 1
        elif read.why == "no_table":
            counts.no_table += 1
        counts.facts += len(read.facts)
        if not do_write:
            continue
        for fact in read.facts:
            try:
                with conn.transaction():
                    _, created = evidence.store(conn, item_of(fact, at=at), at=at)
            except (factor_schema.IncompleteFactError, psycopg.Error, ValueError) as exc:
                counts.errors.append(f"{read.match.fixture_id}:{fact.side}:{type(exc).__name__}")
                continue
            counts.created += int(created)
    return counts


__all__ = ["AHEAD", "MAX_AGE", "NOT_CODED", "SWITCH", "TABLES", "VERSION", "Counts", "Match", "Read", "Stake", "StakeFact", "collect", "fact_of", "facts_of",
           "item_of", "mode", "run", "sentence", "stakes_of"]
