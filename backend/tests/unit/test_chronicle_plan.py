"""The content plan made by code (IA-103, AD-F01, ``content-plan-v1``) and the table «class of claim -> fact that authorises it»
(``claim-classes-v1``): no fact, no class; «nothing at stake» only from the engine's proof; a rumour only with its level; nothing known after
the plan's moment; pertinence by market; a deterministic plan."""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from fbi.api.services.story import Fact
from fbi.chronicle import claims
from fbi.chronicle import plan as cp

AT = datetime(2026, 11, 17, 12, tzinfo=UTC)
HOME, AWAY, COMP = "Getafe", "Osasuna", "La Liga"
HOME_ID, AWAY_ID, FIXTURE = 11, 22, 7001


def F(ref: str, section: str, code: str, **params: Any) -> Fact:  # noqa: N802 - a constructor
    return Fact(ref, section, code, params)


STORY: tuple[Fact, ...] = (
    F("P:fixture", "summary", "match_intro", competition=COMP, round="Jornada 13", neutral=False),
    F("P:stakes.home", "home", "stakes_zone", side="home", team=HOME, zone="relegation", rank=17),
    F("P:stakes.away", "away", "stakes_pressure", side="away", team=AWAY, pressure="settled"),
    F("P:form.home", "home", "form", side="home", team=HOME, sequence="LLDLL", n=5, ppg=0.2, goals_for=0.6, goals_against=1.8,
      wins=0, draws=1, losses=4),
    F("P:form.away", "away", "form", side="away", team=AWAY, sequence="WDWWD", n=5, ppg=2.2, goals_for=1.6, goals_against=0.8,
      wins=3, draws=2, losses=0),
    F("P:streak.away", "away", "streak_unbeaten", side="away", team=AWAY, n=7),
    F("P:xg.home", "home", "xg", side="home", team=HOME, xg_for=0.9, xg_against=1.7, n=12),
    F("P:results.home.1", "home", "result", side="home", team=HOME, opponent="Sevilla", venue="away", goals_for=0, goals_against=2,
      outcome="L", competition=COMP, order=1),
    F("P:results.away.1", "away", "result", side="away", team=AWAY, opponent="Betis", venue="home", goals_for=2, goals_against=1,
      outcome="W", competition=COMP, order=1),
    F("P:absences.home", "home", "key_absences", side="home", team=HOME, count=1, players=["Mauro Arambarri"]),
    F("P:absences.home.1", "home", "absence", side="home", team=HOME, player="Mauro Arambarri", status="out", reason="Knee Injury",
      kind="injury", key=True),
    F("P:absences.away.1", "away", "absence", side="away", team=AWAY, player="Ante Budimir", status="doubtful", reason="Knock",
      kind="injury", key=True),
    F("P:h2h", "h2h", "h2h", n=8, home=HOME, home_wins=2, draws=3, away=AWAY, away_wins=3),
    F("P:h2h.meeting.1", "h2h", "h2h_meeting", home=HOME, away=AWAY, goals_home=1, goals_away=1, winner="draw", months_ago=7,
      competition=COMP),
)


def news(i: int, status: str, *, minutes: int = 60, may_read: bool = True, published: datetime | None = None) -> cp.NewsIn:
    seen = AT - timedelta(minutes=minutes)
    return cp.NewsIn(i, status, "injury", "home", "Marca", seen, published or seen - timedelta(hours=1), f"{i:064x}", may_read)


def figure(sel: str, p: float, market: str = "1X2", line: float = 0.0) -> cp.FigureIn:
    rid = hashlib.sha256(f"{market}|{sel}|{line}".encode()).hexdigest()[:12]
    return cp.FigureIn(rid, market, sel, line, p, "calibrada", "forecast-v2")


def objective(name: str, state: str, *, proved: bool, conditional: bool = False) -> dict[str, Any]:
    return {"objetivo": name, "zona": "relegation", "estado": state, "condicional": conditional,
            "decidido": {"valor": proved, "demostrado": proved, "motivos": []},
            "necesita": {"puntos_actuales": 10, "puntos_maximos": 25, "partidos_restantes": 5, "puntos_que_lo_aseguran": 9},
            "depende_de": {"tipo": "de_si_mismo", "rivales": []}, "probabilidad": 0.71}


def reading(*, home: list[dict[str, Any]] | None = None, away: list[dict[str, Any]] | None = None, away_no_objective: bool = False,
            at: datetime = AT - timedelta(hours=3), status: str = "ok", effects: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"version": "scenarios-v2", "at": at.isoformat(), "status": status,
            "tables": [{"key": "general", "name": "Clasificación", "matches": effects or {},
                        "teams": [{"team": HOME_ID, "puesto": 17, "puntos": 10, "partidos_restantes": 5, "objetivos": home or []},
                                  {"team": AWAY_ID, "puesto": 9, "puntos": 30, "partidos_restantes": 5, "objetivos": away or []}]}],
            "teams": {str(HOME_ID): {"hecho": None, "demostrado": False, "motivos": ["objetivo_abierto:general:evitar_descenso"]},
                      str(AWAY_ID): {"hecho": "SIN_OBJETIVO_DEMOSTRADO" if away_no_objective else None, "demostrado": away_no_objective,
                                     "alcance": "tablas_codificadas", "motivos": []}}}


def inp(**changes: Any) -> cp.PlanInput:
    base: dict[str, Any] = {"fixture_id": FIXTURE, "at": AT, "home": HOME, "away": AWAY, "competition": COMP, "home_team_id": HOME_ID,
                            "away_team_id": AWAY_ID, "packet_id": 70, "data_at": AT - timedelta(hours=2), "story": STORY, "thin": False,
                            "news": (news(101, "CONFIRMED"), news(102, "PROBABLE"), news(103, "RUMOR")), "lineups_confirmed": False}
    base.update(changes)
    return cp.PlanInput(**base)


def kinds(plan: cp.ContentPlan) -> list[str]:
    return [f.kind for f in plan.planned]


def excluded(plan: cp.ContentPlan) -> dict[str, str]:
    return {e.ref: e.reason for e in plan.excluded}


# ── «nothing at stake»: only the engine ─────────────────────────────────────────────────────────────────────────────────────

def test_nothing_at_stake_without_the_engine_never_enters_the_plan() -> None:
    plan = cp.build(inp())
    assert excluded(plan)["P:stakes.away"] == "sin_certificacion_motor"
    assert "SIN_OBJETIVO_DEMOSTRADO" not in plan.allowed_classes
    assert "scenario.no_objective" not in kinds(plan) and "table.pressure" not in kinds(plan)
    assert "unknown.scenarios" in kinds(plan), "the plan says the computation of what is at stake is missing"


def test_nothing_at_stake_enters_only_from_the_engines_proof_and_is_mandatory() -> None:
    plan = cp.build(inp(scenarios=reading(away_no_objective=True)))
    fact = plan.by_id()["S:away.sin_objetivo"]
    assert fact.kind == "scenario.no_objective" and fact.mandatory and fact.source == "scenarios-v2"
    assert "SIN_OBJETIVO_DEMOSTRADO" in plan.allowed_classes
    assert "S:away.sin_objetivo" in next(s for s in plan.sections if s.code == "que_se_juega").mandatory
    unproved = cp.build(inp(scenarios=reading(away_no_objective=False)))
    assert "SIN_OBJETIVO_DEMOSTRADO" not in unproved.allowed_classes


def test_a_decided_objective_needs_the_proof_and_an_unproved_one_is_not_decided() -> None:
    plan = cp.build(inp(scenarios=reading(home=[objective("evitar_descenso", "descartado", proved=True)])))
    assert "scenario.lost" in kinds(plan) and "OBJETIVO_DESCARTADO" in plan.allowed_classes
    plan = cp.build(inp(scenarios=reading(home=[objective("evitar_descenso", "descartado", proved=False)])))
    assert "scenario.lost" not in kinds(plan) and excluded(plan)["S:home.general.evitar_descenso"] == "no_demostrado"
    assert "OBJETIVO_CONSEGUIDO" not in plan.allowed_classes
    plan = cp.build(inp(scenarios=reading(home=[objective("evitar_descenso", "abierto", proved=False)])))
    fact = next(f for f in plan.facts if f.kind == "scenario.open")
    assert fact.params["puntos_que_lo_aseguran"] == 9 and fact.params["depende_de"] == "de_si_mismo"
    assert "probabilidad" not in fact.params, "the engine's simulated probability never reaches the writer"


def test_what_this_match_decides_comes_from_the_engines_result_rows() -> None:
    effects = {str(FIXTURE): {"home": {"team": HOME_ID, "objetivos": [
        {"objetivo": "evitar_descenso", "terminar_entre_los": 17, "condicional": False, "victoria": {"estado": "abierto"},
         "empate": {"estado": "abierto"}, "derrota": {"estado": "descartado"}},
        {"objetivo": "plaza_continental", "terminar_entre_los": 7, "condicional": True, "victoria": {"estado": "abierto"},
         "empate": {"estado": "descartado"}, "derrota": {"estado": "descartado"}}]}}}
    plan = cp.build(inp(scenarios=reading(effects=effects)))
    effect = [f for f in plan.facts if f.kind == "scenario.result_effect"]
    assert len(effect) == 1 and effect[0].params["derrota"] == "descartado" and effect[0].section == "que_puede_definir"
    assert effect[0].mandatory is False and effect[0].rarity == 1.0


def test_a_reading_after_the_plan_or_a_regulation_not_coded_gives_no_stakes() -> None:
    late = cp.build(inp(scenarios=reading(away_no_objective=True, at=AT + timedelta(minutes=1))))
    assert "scenario.no_objective" not in kinds(late) and excluded(late)["S:reading"] == "posterior_al_plan"
    not_coded = cp.build(inp(scenarios=reading(status="reglamento_no_codificado")))
    assert "unknown.rules" in kinds(not_coded) and not any(k.startswith("scenario.") for k in kinds(not_coded))


# ── every class, only with its fact ─────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", claims.CLASSES, ids=lambda c: c.code)
def test_no_fact_no_class(cls: claims.ClaimClass) -> None:
    """For every class: a plan whose facts are filtered of the kinds that authorise it does not let the class in."""
    plan = cp.build(inp(scenarios=reading(away_no_objective=True, home=[objective("evitar_descenso", "descartado", proved=True)]),
                        figures=(figure("Home", 0.31),)))
    stripped = dataclasses.replace(plan, facts=tuple(f for f in plan.facts if f.kind not in cls.authorised_by),
                                   sections=tuple(dataclasses.replace(s, mandatory=tuple(i for i in s.mandatory if plan.by_id()[i].kind
                                                                                       not in cls.authorised_by),
                                                                      optional=tuple(i for i in s.optional if plan.by_id()[i].kind
                                                                                     not in cls.authorised_by))
                                                  for s in plan.sections))
    assert cls.code not in stripped.allowed_classes
    assert cp.unsupported_high_risk(plan) == [] and cp.unsupported_high_risk(stripped) == []
    if cls.authorised_by and set(cls.authorised_by) & set(kinds(plan)):
        assert cls.code in plan.allowed_classes


def test_the_table_is_closed_versioned_and_superlatives_and_medical_detail_are_never_authorised() -> None:
    assert set(cp.SECTION_OF) == set(claims.KINDS) and set(cp.RELEVANCE) == set(claims.KINDS)
    assert {k for c in claims.CLASSES for k in c.authorised_by} <= set(claims.KINDS)
    assert {"SUPERLATIVO", "DETALLE_MEDICO"} == claims.NOT_AUTHORISED
    assert claims.BY_CODE["SIN_OBJETIVO_DEMOSTRADO"].authorised_by == ("scenario.no_objective",)
    assert len(claims.table_hash()) == 64 and claims.VERSION == "claim-classes-v1"
    assert {"SIN_OBJETIVO_DEMOSTRADO", "OBJETIVO_CONSEGUIDO", "OBJETIVO_DESCARTADO", "SUPERLATIVO", "RUMOR", "CIFRA_PRONOSTICO",
            "DETALLE_MEDICO"} == claims.HIGH_RISK


@pytest.mark.parametrize(("text", "lang", "code"), [
    ("El Osasuna ya no tiene nada en juego en la liga.", "es", "SIN_OBJETIVO_DEMOSTRADO"),
    ("Osasuna have nothing left to play for.", "en", "SIN_OBJETIVO_DEMOSTRADO"),
    ("El Getafe ya está clasificado para la Copa.", "es", "OBJETIVO_CONSEGUIDO"),
    ("Getafe are already relegated.", "en", "OBJETIVO_DESCARTADO"),
    ("Es la mejor racha de su historia.", "es", "SUPERLATIVO"),
    ("They have never won there.", "en", "SUPERLATIVO"),
    ("Lleva siete partidos seguidos sin perder.", "es", "RACHA"),
])
def test_the_cues_read_the_class_of_a_sentence(text: str, lang: str, code: str) -> None:
    from fbi.narrative.job import fold

    assert code in claims.classes_stated(fold(text), lang)


# ── the news: by reference, with its level, known by the plan's moment ──────────────────────────────────────────────────────

def test_a_rumour_enters_only_as_a_rumour_with_its_level_and_only_among_the_risks() -> None:
    plan = cp.build(inp(news=(news(103, "RUMOR"), news(104, "CONTRADICTORY"))))
    rumours = [f for f in plan.facts if f.id in ("E:103", "E:104")]
    assert [f.kind for f in rumours] == ["news.rumour", "news.rumour"]
    assert [f.params["level"] for f in rumours] == ["rumor", "contradictorio"] and {f.section for f in rumours} == {"riesgos"}
    assert not any(f.kind in ("news.confirmed", "news.probable") for f in plan.facts)


def test_no_text_of_the_internet_enters_the_plan_and_nothing_known_after_it() -> None:
    plan = cp.build(inp(news=(news(1, "CONFIRMED", minutes=-5), news(2, "CONFIRMED", published=AT + timedelta(minutes=1)),
                              dataclasses.replace(news(3, "CONFIRMED"), retrieved_at=None), news(4, "CONFIRMED", may_read=False),
                              news(5, "OUTDATED"), news(6, "CONFIRMED"))))
    assert excluded(plan).items() >= {"E:1": "posterior_al_plan", "E:2": "posterior_al_plan", "E:3": "sin_momento",
                                      "E:4": "fuente_sin_permiso", "E:5": "caducada"}.items()
    fact = plan.by_id()["E:6"]
    assert set(fact.params) == {"evidence_id", "status", "topic", "side", "source", "content_hash", "published"}
    assert fact.mandatory and fact.known_at is not None and fact.known_at <= plan.at
    assert all(f.known_at is None or f.known_at <= plan.at for f in plan.facts)


def test_an_absence_is_a_state_the_providers_reason_never_reaches_the_writer() -> None:
    plan = cp.build(inp())
    out, doubt = plan.by_id()["P:absences.home.1"], plan.by_id()["P:absences.away.1"]
    assert out.kind == "absence.out" and out.mandatory and out.section == "jugadores"
    assert doubt.kind == "absence.doubtful" and doubt.section == "riesgos"
    for f in (out, doubt):
        assert "reason" not in f.params and f.params["kind"] == "injury" and "Knee" not in str(f.for_writer())
    assert excluded(plan)["P:absences.home"] == "duplicado"


# ── sections, scores, determinism ───────────────────────────────────────────────────────────────────────────────────────────

def test_an_empty_section_abstains_with_its_code_and_risks_are_never_invented() -> None:
    quiet = [f for f in STORY if f.code not in ("absence",)]
    plan = cp.build(inp(story=tuple(quiet), news=(), lineups_confirmed=True))
    sections = {s.code: s for s in plan.sections}
    assert sections["riesgos"].abstention == "SIN_RIESGOS" and sections["riesgos"].cap == 0
    assert sections["novedades"].abstention == "SIN_NOVEDADES"
    assert sections["como_llega"].abstention is None and 0 < sections["como_llega"].cap <= cp.CAPS["como_llega"]
    assert plan.abstention is None


def test_no_story_no_plan_and_only_what_is_missing_is_no_data() -> None:
    assert cp.build(inp(thin=True)).abstention == cp.NO_PLAN
    late_packet = cp.build(inp(data_at=AT + timedelta(minutes=5)))
    assert late_packet.abstention == cp.NO_PLAN and excluded(late_packet)["P:packet"] == "posterior_al_plan"
    assert cp.build(inp(story=(), news=())).abstention == cp.NO_DATA


def test_pertinence_is_by_market_and_a_figure_only_for_its_own() -> None:
    figs = (figure("Home", 0.31), figure("Over", 0.48, "OU", 2.5), figure("Over", 0.2, "OU", 3.5))
    plan = cp.build(inp(figures=figs))
    xg = plan.by_id()["P:xg.home"]
    assert set(xg.markets) == {"OU", "BTTS"} and xg.pertinence == 0.9
    assert {f.params["market"] for f in plan.facts if f.kind == "figure"} == {"1X2", "OU"}, "only the core lines"
    only_goals = cp.build(inp(figures=figs, markets=("OU",)))
    assert {f.params["market"] for f in only_goals.facts if f.kind == "figure"} == {"OU"}
    assert only_goals.by_id()["P:form.home"].pertinence == 0.6
    fig = next(f for f in plan.facts if f.kind == "figure")
    assert fig.params["cita"].endswith(f"[cifra forecast-v2 {fig.params['reading_id']}]") and "p" not in fig.params
    assert fig.value is not None and "value" not in fig.for_writer() and plan.readings()[fig.params["reading_id"]] == fig.value


def test_novelty_follows_the_previous_plan_and_the_news_age() -> None:
    first = cp.build(inp())
    again = cp.build(inp(previous=cp.keys(first)))
    assert all(f.novelty <= 0.8 for f in again.facts if not f.kind.startswith("news.") and f.kind != "result")
    assert first.by_id()["E:101"].novelty == 1.0
    old = cp.build(inp(news=(news(101, "CONFIRMED", minutes=60 * 24 * 5),)))
    assert old.by_id()["E:101"].novelty == 0.5


def test_the_plan_is_deterministic_and_reads_back() -> None:
    a, b = cp.build(inp()), cp.build(inp())
    assert a.hash == b.hash and a.as_json() == b.as_json()
    moved = cp.build(inp(at=AT + timedelta(minutes=10)))
    assert moved.hash == a.hash, "the clock alone is not another plan"
    back = cp.from_json(a.as_json())
    assert back.hash == a.hash and back.allowed_classes == a.allowed_classes
    assert a.as_json()["classes_hash"] == claims.table_hash() and a.version == "content-plan-v1"


def test_the_mandatory_facts_come_first_and_the_rest_by_score_within_the_cap() -> None:
    plan = cp.build(inp())
    for s in plan.sections:
        facts = [plan.by_id()[i] for i in s.facts]
        assert len(facts) <= cp.CAPS[s.code] * cp.FACTS_PER_SENTENCE
        optional = [f.score for f in facts if not f.mandatory]
        assert optional == sorted(optional, reverse=True)
        assert all(f.mandatory for f in facts[: len(s.mandatory)])


def test_the_same_facts_make_the_same_plan_whatever_was_stored_before() -> None:
    first = cp.build(inp())
    stored = first.as_json()
    same = cp.build(inp(previous=cp.previous_for(cp.keys(first), stored)))
    assert same.hash == first.hash, "the newest plan had the same facts: its own previous is given again"
    changed = cp.build(inp(news=()))
    after = cp.build(inp(news=(), previous=cp.previous_for(cp.keys(changed), stored)))
    assert after.previous == tuple(sorted(cp.keys(first))) and after.hash != changed.hash
    again = cp.build(inp(news=(), previous=cp.previous_for(cp.keys(after), after.as_json())))
    assert again.hash == after.hash
    assert cp.previous_for(cp.keys(first), None) == frozenset()
