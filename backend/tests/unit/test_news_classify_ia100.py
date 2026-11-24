"""IA-100 (AD-G03): category, language, country and level of a story, ``classify-v1`` - pure.

The level is the ladder of AD-C07 by ORIGIN: a wire story reprinted by outlets of one editorial group (or with near-duplicate titles) is one
origin and never climbs to «Dos orígenes»; a title written as a rumour stays a rumour whatever the source; only a source that CONFIRMS that
type of claim makes it «Oficial». Every story gets the four fields (the closure criterion: 100 %)."""

from __future__ import annotations

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fbi.ai import source_registry as registry
from fbi.ai.source_policy import SourcePolicy
from fbi.news import canonical, classify, grouping, vocab
from fbi.news.classify import TeamFacts
from fbi.news.grouping import ItemSignal

AT = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)
INFORMS = {k: {"level": "informa"} for k in ("lesiones", "sanciones", "fichajes", "declaraciones", "contexto", "resultados")}


def src(sid: str, domain: str, *, group: str = "", authority: dict[str, dict[str, str]] | None = None, kind: str = "medio",
        country: str = "Colombia", langs: str = "es", clubs: str = "") -> registry.Source:
    return registry.Source(source_id=sid, domain=domain, name=sid, family="B", source_type=kind, state="verificada_pendiente_derechos",
                           automated_access="permitido", ai_extraction="permitido", storage="", publication="",
                           authority=authority if authority is not None else INFORMS, last_reviewed=None, country=country,
                           record={"grupo_editorial": group, "idiomas": langs, "clubes_cubiertos": clubs})


POLICY = SourcePolicy(
    (src("diario-a", "diarioa.invalid", group="Grupo Uno"), src("diario-b", "diariob.invalid", group="Grupo Uno"),
     src("radio-c", "radioc.invalid", group="Grupo Dos"), src("tv-d", "tvd.invalid", group="Grupo Tres"),
     src("club-n", "clubnorte.invalid", kind="oficial", authority={"lesiones": {"level": "confirma", "note": "solo lo propio"}},
         clubs="Club Norte"),
     src("liga", "liga.invalid", kind="oficial", authority={"sanciones": {"level": "confirma"}, "lesiones": {"level": "informa"}}),
     src("world", "world.invalid", country="England", langs="en")),
    (), (), directory_version="dir-t", exclusion_version="ex-t", origin="db")
TEAMS = {11: TeamFacts("Colombia", False, "Club Norte"), 12: TeamFacts("Colombia", False, "Club Sur"),
         21: TeamFacts("England", False, "Town FC"), 90: TeamFacts("Colombia", True, "Colombia")}


def it(n: int, title: str, domain: str, *, minutes: int = 0, teams: frozenset[int] = frozenset({11}), lang: str | None = "es",
       claim: str | None = None) -> ItemSignal:
    url = f"https://{domain}/n/{n}"
    return ItemSignal(n, canonical.url_sha256(url), canonical.fingerprint(f"{title} {n}"), domain, AT + timedelta(minutes=minutes), None,
                      title, lang, claim, teams)


def level(items: list[ItemSignal]) -> str:
    return classify.classify(items, policy=POLICY, teams=TEAMS).level


def test_one_outlet_that_informs_is_one_medium() -> None:
    assert level([it(1, "Pérez, baja ante el Sur por lesión", "diarioa.invalid")]) == "un_medio"


def test_a_syndicated_story_does_not_climb_two_outlets_of_one_group_are_one_origin() -> None:
    items = [it(1, "Pérez, baja ante el Sur por lesión", "diarioa.invalid"),
             it(2, "Pérez será baja ante el Sur: lesión", "diariob.invalid", minutes=10)]
    assert level(items) == "un_medio"


def test_near_duplicate_titles_of_independent_groups_are_still_one_origin() -> None:
    title = "Pérez baja ante el Sur por una lesión en la semana"
    items = [it(1, title, "diarioa.invalid"), it(2, title, "radioc.invalid", minutes=5), it(3, title, "tvd.invalid", minutes=9)]
    assert level(items) == "un_medio", "five copies of one wire are one origin"


def test_two_independent_origins_are_two_origins() -> None:
    items = [it(1, "Pérez, baja ante el Sur por lesión", "diarioa.invalid"),
             it(2, "El Norte pierde a su goleador para el clásico", "radioc.invalid", minutes=30)]
    assert level(items) == "dos_origenes"


def test_a_rumour_never_climbs_whatever_the_sources() -> None:
    items = [it(1, "Se especula con la salida de Pérez", "diarioa.invalid", claim="fichajes"),
             it(2, "Pérez podría salir en enero, según rumores", "radioc.invalid", claim="fichajes"),
             it(3, "Rumores: Pérez interesa en Europa", "tvd.invalid", claim="fichajes")]
    assert level(items) == "rumor"
    assert level([it(1, "Pérez, el rumor del día", "diarioa.invalid", claim="rumores")]) == "rumor"


def test_only_the_source_that_confirms_that_type_makes_it_official() -> None:
    assert level([it(1, "Parte: Pérez, baja por lesión", "clubnorte.invalid")]) == "oficial"
    assert level([it(1, "Pérez, suspendido dos fechas", "liga.invalid")]) == "oficial"
    assert level([it(1, "Pérez, baja por lesión", "liga.invalid")]) == "un_medio", "the league informs about injuries, it does not confirm"


def test_a_club_confirms_only_its_own_team() -> None:
    other = classify.classify([it(1, "El Sur pierde a Gómez por lesión", "clubnorte.invalid", teams=frozenset({12}))], policy=POLICY,
                              teams=TEAMS)
    assert other.level == "un_medio"


def test_a_statement_reported_by_several_outlets_is_a_statement() -> None:
    items = [it(1, "El técnico dijo que el equipo está listo", "diarioa.invalid"),
             it(2, "Declaraciones del técnico en rueda de prensa", "radioc.invalid", minutes=20)]
    assert level(items) == "declaracion"


def test_the_category_follows_the_topic_then_the_national_team_then_the_competition_then_the_country() -> None:
    c = classify.classify
    assert c([it(1, "Pérez, baja por lesión", "diarioa.invalid")], policy=POLICY, teams=TEAMS).category == "bajas_y_sanciones"
    assert c([it(1, "El Norte ficha a un lateral", "diarioa.invalid")], policy=POLICY, teams=TEAMS).category == "fichajes"
    assert c([it(1, "La selección viaja a Quito", "diarioa.invalid", teams=frozenset({90}))], policy=POLICY,
             teams=TEAMS).category == "selecciones"
    assert c([it(1, "Horario de la jornada 5", "diarioa.invalid")], policy=POLICY, teams=TEAMS).category == "competiciones"
    assert c([it(1, "Una tarde en el estadio", "diarioa.invalid")], policy=POLICY, teams=TEAMS).category == "colombia"
    town = c([it(1, "A quiet afternoon at the ground", "world.invalid", teams=frozenset({21}), lang="en")], policy=POLICY, teams=TEAMS)
    assert (town.category, town.country, town.lang) == ("internacional", "England", "en")
    assert all(cat != "resultados_y_proximos" for cat in classify.TOPIC.values()), "that block comes from API-Football, never the press"


def test_country_of_several_countries_is_international_and_language_falls_back_to_the_words() -> None:
    mixed = classify.classify([it(1, "Norte y Town, amistoso", "diarioa.invalid", teams=frozenset({11, 21}), lang=None)], policy=POLICY,
                              teams=TEAMS)
    assert mixed.country == classify.INTERNATIONAL and mixed.lang == "es"
    assert classify.guess_lang(["The coach of the club said that the team is ready"]) == "en"


@pytest.mark.parametrize("seed", range(5))
def test_every_story_gets_category_level_language_and_country(seed: int) -> None:
    rnd = random.Random(seed)
    words = ["baja", "lesión", "ficha", "dijo", "horario", "rumor", "estadio", "selección", "suspendido", "partido", "gol", "once"]
    domains = [s.domain for s in POLICY.by_domain.values()] + ["nadie.invalid"]
    for n in range(60):
        items = [it(n * 10 + k, " ".join(rnd.sample(words, 4)), rnd.choice(domains), teams=frozenset(rnd.sample([11, 12, 21, 90, 99], 2)),
                    lang=rnd.choice(["es", "en", None])) for k in range(rnd.randint(1, 4))]
        got = classify.classify(items, policy=rnd.choice([POLICY, None]), teams=TEAMS)
        assert got.category in vocab.CATEGORIES and got.level in vocab.LEVELS and got.lang and got.country
        if any(grouping.claim_type_of_title(i.title) == "rumores" for i in items) and grouping.story_kind(items) == "rumores":
            assert got.level == "rumor"


# ── classify-v2 (C-06 1.1): the general categories ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("title", "expected"), [
    ("J. Ejemplo gana el Balón de Oro", "premios"), ("Ejemplo named player of the month", "premios"),
    ("La gala de los premios de la Liga Ficticia", "premios"),
    ("Así será la ceremonia de inauguración", "ceremonias"), ("Sorteo de la Copa Ficticia: los cruces", "ceremonias"),
    ("Polémica por el arbitraje del clásico", "polemicas"), ("El club denuncia insultos racistas", "polemicas"),
    ("Club Ejemplo, multado por la federación", "polemicas"),
    ("Galatasaray empata en casa", None), ("Club Ejemplo entrena a puerta cerrada", None),
])
def test_the_words_of_the_title_give_a_general_category(title: str, expected: str | None) -> None:
    assert classify.general_category([title]) == expected


def test_a_story_that_names_no_team_or_player_is_actualidad_and_a_topic_still_wins() -> None:
    plain = grouping.ItemSignal(item_id=1, url_sha256="a", content_sha256="b", domain="x.invalid", seen_at=AT,
                                title="El fútbol mundial ante el nuevo calendario")
    assert classify.category("contexto", [plain], {}, "Internacional") == "actualidad"
    named = replace(plain, teams=frozenset({7}))
    assert classify.category("contexto", [named], {7: classify.TeamFacts("Colombia", False)}, "Colombia") == "colombia"
    award = replace(plain, title="Balón de Oro: los candidatos", teams=frozenset({7}))
    assert classify.category("contexto", [award], {7: classify.TeamFacts("Colombia", True)}, "Colombia") == "premios"
    transfer = replace(plain, title="Balón de Oro ficha por el club")
    assert classify.category("fichajes", [transfer], {}, "Colombia") == "fichajes"
    assert classify.VERSION == "classify-v2"
