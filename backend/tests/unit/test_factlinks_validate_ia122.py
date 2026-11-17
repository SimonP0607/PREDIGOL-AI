"""The validator ``link-v1`` (IA-122, AD-G08): a fact links to an evaluation only with its entity by id, a literal quote that names it and a
date inside the match's window; a homonym without a signal, a surname alone, a club's news of an earlier match and a fact known after the
decision are refused; the relation is code (a rumour is never used, an absence of a player a selection depends on goes against it)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.evalcycle import dependency
from fbi.factlinks import validate as v
from fbi.factlinks.validate import Fact, Person, SelectionDependency, World

KICKOFF = datetime(2026, 11, 22, 20, 0, tzinfo=UTC)
DECIDED = KICKOFF - timedelta(hours=13)
NORTE, SUR = 11, 12
JUAN = Person(9001, 501, NORTE, ("Juan Ejemplo",))
JOSE = Person(9002, 502, SUR, ("José Ejemplo",))
LUIS = Person(9003, 503, NORTE, ("Luis Otro",))
WORLD = World(fixture_id=77, kickoff_at=KICKOFF, decided_at=DECIDED,
              teams={NORTE: ("Club Ejemplo Norte",), SUR: ("Deportivo Sur",)}, people=(JUAN, JOSE, LUIS),
              previous_kickoff={NORTE: KICKOFF - timedelta(days=4), SUR: KICKOFF - timedelta(days=7)})
OVER: v.Key = ("OU", "Over", Decimal("2.50"))
DEPS = (SelectionDependency(OVER, {9001: (-0.034, 0.012), 9003: (0.004, -0.001)}),)


def fact(**kw: object) -> Fact:
    base = {"evidence_id": 1, "fixture_id": 77, "team_id": NORTE, "provider_player_id": 9001, "kind": "injury", "assertion": "out",
            "text": "Juan Ejemplo no estará ante el Deportivo Sur por una molestia", "literal": True,
            "published_at": DECIDED - timedelta(hours=3), "known_at": DECIDED - timedelta(hours=2), "status": "CONFIRMED",
            "tier": "club", "source_name": "Club Ejemplo Norte (oficial)", "source_url": "https://oficial.ejemplo.invalid/parte"}
    base.update(kw)
    return Fact(**base)  # type: ignore[arg-type]


def test_a_fact_with_its_three_conditions_links_with_its_level_and_its_relation() -> None:
    link = v.validate(fact(), WORLD, DEPS)
    assert link.linked and (link.entity_type, link.entity_id, link.team_id, link.named_as) == ("player", 501, NORTE, "juan ejemplo")
    assert (link.level, link.relation, link.source_type) == ("oficial", "en_contra", "oficial")
    assert [(e.key, e.relation, e.shift) for e in link.effects] == [(OVER, "en_contra", -0.034)]


def test_an_initial_and_the_surname_name_him_but_the_surname_alone_does_not() -> None:
    alone_juan = replace(WORLD, people=(JUAN, LUIS))
    assert v.validate(fact(text="J. Ejemplo, baja confirmada por el club"), alone_juan, DEPS).named_as == "j ejemplo"
    alone = v.validate(fact(text="Ejemplo se queda fuera de la convocatoria", provider_player_id=9003, team_id=NORTE), WORLD, DEPS)
    assert alone.rejection == "cita_sin_nombre"


def test_a_homonym_without_a_signal_is_refused() -> None:
    """«Ejemplo» is the surname of two players of the match: the surname alone, or an initial both share, is no signal."""
    assert v.validate(fact(text="Ejemplo, baja para el sábado"), WORLD, DEPS).rejection == "homonimo"
    assert v.validate(fact(text="J. Ejemplo, baja para el sábado"), WORLD, DEPS).rejection == "homonimo", "Juan and José"
    assert v.validate(fact(text="Juan Ejemplo, baja para el sábado"), WORLD, DEPS).linked, "the whole name is the signal"


def test_the_entity_is_by_id_inside_the_match_and_never_by_a_word() -> None:
    assert v.validate(fact(provider_player_id=4242), WORLD, DEPS).rejection == "entidad_ajena", "a player outside the two squads"
    assert v.validate(fact(provider_player_id=None, team_id=99), WORLD, DEPS).rejection == "entidad_ajena", "a team of another match"
    assert v.validate(fact(provider_player_id=None, team_id=None), WORLD, DEPS).rejection == "sin_entidad"
    no_id = replace(WORLD, people=(replace(JUAN, player_id=None), JOSE, LUIS))
    assert v.validate(fact(), no_id, DEPS).rejection == "entidad_ajena", "without PrediGol's own id there is nothing to link to"


def test_a_team_needs_its_own_words_not_the_words_every_club_has() -> None:
    team = fact(provider_player_id=None, kind="coach", assertion="info", text="El técnico del Club Ejemplo Norte habló del partido")
    assert v.validate(team, WORLD, DEPS).named_as == "ejemplo norte"
    assert v.validate(replace(team, text="El técnico del club habló del partido"), WORLD, DEPS).rejection == "cita_sin_nombre"
    same = replace(WORLD, teams={NORTE: ("Club Ejemplo",), SUR: ("Ejemplo FC",)})
    assert v.validate(replace(team, text="Ejemplo ganó"), same, DEPS).rejection == "homonimo"


def test_a_model_s_sentence_is_not_a_literal_quote() -> None:
    assert v.validate(fact(literal=False), WORLD, DEPS).rejection == "sin_cita_literal"


def test_a_club_s_news_is_not_hung_from_all_its_matches() -> None:
    """Dated before the team's previous match, it was that match's news; without a date it cannot be placed; of another match, never."""
    assert v.validate(fact(published_at=KICKOFF - timedelta(days=5)), WORLD, DEPS).rejection == "fuera_de_ventana"
    assert v.validate(fact(published_at=None), WORLD, DEPS).rejection == "sin_fecha"
    assert v.validate(fact(fixture_id=78), WORLD, DEPS).rejection == "otro_partido"
    lone = replace(WORLD, previous_kickoff={})
    assert v.validate(fact(published_at=KICKOFF - v.WINDOW - timedelta(minutes=1)), lone, DEPS).rejection == "fuera_de_ventana"


def test_nothing_known_or_published_after_the_decision_exists_for_it() -> None:
    assert v.validate(fact(known_at=DECIDED + timedelta(seconds=1)), WORLD, DEPS).rejection == "posterior_a_la_decision"
    assert v.validate(fact(published_at=DECIDED + timedelta(minutes=1), known_at=DECIDED), WORLD, DEPS).rejection == \
        "posterior_a_la_decision"


@pytest.mark.parametrize(("status", "tier", "level", "warning"), [
    ("CONFIRMED", "club", "oficial", None), ("CONFIRMED", "media", "dos_origenes", None), ("PROBABLE", "media", "un_medio", None),
    ("RUMOR", "official", "rumor", None), ("CONTRADICTORY", "media", None, "contradiccion"), ("WHATEVER", "media", "rumor", None)])
def test_the_level_never_rises_above_what_the_status_says(status: str, tier: str, level: str | None, warning: str | None) -> None:
    assert v.level_of(status, tier) == (level, warning)


def test_a_rumour_is_listed_as_not_used_and_a_contradiction_as_context() -> None:
    rumour = v.validate(fact(status="RUMOR"), WORLD, DEPS)
    assert rumour.linked and (rumour.level, rumour.relation, rumour.effects) == ("rumor", "no_usada", ())
    contra = v.validate(fact(status="CONTRADICTORY"), WORLD, DEPS)
    assert (contra.level, contra.warning, contra.relation) == (None, "contradiccion", "contexto")


def test_the_relation_follows_the_dependency_and_is_context_when_nothing_moves() -> None:
    starts = v.validate(fact(assertion="starts", text="Juan Ejemplo será titular"), WORLD, DEPS)
    assert starts.relation == "contexto", "his start moves the over by 1,2 points: under two, it is context"
    luis = v.validate(fact(provider_player_id=9003, text="Luis Otro, baja"), WORLD, DEPS)
    assert luis.relation == "contexto"
    favour = (SelectionDependency(OVER, {9001: (0.05, 0.0)}),)
    assert v.validate(fact(), WORLD, favour).relation == "a_favor", "an absence that raises the selection's probability"
    mixed = (*DEPS, SelectionDependency(("OU", "Under", Decimal("2.50")), {9001: (0.034, -0.012)}))
    link = v.validate(fact(), WORLD, mixed)
    assert link.relation == "contexto" and {e.relation for e in link.effects} == {"a_favor", "en_contra"}
    assert v.validate(fact(), WORLD, ()).relation == "contexto"


def test_the_material_shift_is_the_cycle_s_and_the_words_are_the_migration_s() -> None:
    import importlib.util
    from pathlib import Path

    assert v.MATERIAL == dependency.MATERIAL
    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0160_eval_sources.py"
    spec = importlib.util.spec_from_file_location("migration_0160", path)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert (m.revision, m.down_revision) == ("0160", "0159")
    assert m.RELATIONS == v.RELATIONS and m.LEVELS == v.LEVELS and m.REJECTIONS == v.REJECTIONS and m.SOURCE_TYPES == v.SOURCE_TYPES
