"""``name-match-v2`` (IA-088, plan piece AD-C06): the four fixed cases of the plan, homonyms, aliases and the end of the 30-player cap."""

from __future__ import annotations

import random

from fbi.ai.mentions import (
    VERSION,
    Candidate,
    Catalogue,
    legacy_tokens_link,
    mentions_in,
    non_distinctive,
    surname_of,
    validate,
)


def cat(*extra: Candidate, context: tuple[str, ...] = ("Copa del Rey", "LaLiga")) -> Catalogue:
    base = [
        Candidate("TEAM", 1, 1, ("Levante UD",)), Candidate("TEAM", 2, 2, ("Real Valladolid",)),
        Candidate("PLAYER", 10, 1, ("Oriol Rey",)),
        Candidate("PLAYER", 11, 1, ("Rodrigo Miguel Ferreira Rêgo", "Rodrigo Rêgo")),
        Candidate("PLAYER", 12, 2, ("D. Cásseres Jr.", "Cristian Cásseres")),
        Candidate("PLAYER", 15, 1, ("Lionel Messi", "Месси")),
    ]
    return Catalogue.of([*base, *extra], context_names=context)


def linked(text: str, c: Catalogue) -> set[int]:
    return {m.who.id for m in mentions_in(text, c) if m.who.kind == "PLAYER"}


def test_version_is_named() -> None:
    assert VERSION == "name-match-v2"


def test_copa_del_rey_is_not_oriol_rey() -> None:
    c = cat()
    assert linked("El Levante cae en la Copa del Rey ante un Segunda", c) == set()
    assert validate("El Levante cae en la Copa del Rey ante un Segunda", c.by_key("PLAYER", 10), c) == "quote_without_subject"  # type: ignore[arg-type]
    assert legacy_tokens_link("El Levante cae en la Copa del Rey", "Oriol Rey"), "the old validator took it: the case the plan fixes"
    assert linked("Oriol Rey es baja para el domingo", c) == {10}


def test_jesus_de_miguel_is_not_rodrigo_miguel_ferreira_rego() -> None:
    c = cat()
    assert linked("Jesús de Miguel pitará el partido del sábado", c) == set()
    assert legacy_tokens_link("Jesús de Miguel pitará el partido", "Rodrigo Miguel Ferreira Rêgo")
    assert linked("Rêgo vuelve a la convocatoria", c) == {11}


def test_casseres_jr_is_his_player() -> None:
    c = cat()
    assert linked("Cásseres Jr. no estará ante el Levante", c) == {12}
    assert surname_of("D. Cásseres Jr.") == "casseres"


def test_a_cyrillic_page_links_only_through_an_alias() -> None:
    c = cat()
    assert linked("Месси не сыграет в субботу", c) == {15}, "the alias in Cyrillic"
    no_alias = Catalogue.of([Candidate("PLAYER", 16, 1, ("Kylian Mbappé",))])
    assert linked("Мбаппе не сыграет в субботу", no_alias) == set(), "no transliteration by code: abstain"


def test_a_homonym_without_a_second_signal_is_never_linked() -> None:
    c = cat(Candidate("PLAYER", 13, 2, ("Kylian Mbappé",)), Candidate("PLAYER", 14, 1, ("Ethan Mbappé",)))
    assert linked("Mbappé está lesionado", c) == set()
    assert linked("K. Mbappé está lesionado", c) == {13}
    assert linked("Ethan Mbappé está lesionado", c) == {14}
    assert validate("Mbappé está lesionado", c.by_key("PLAYER", 13), c) == "ambiguous_subject"  # type: ignore[arg-type]


def test_property_homonyms_never_link_without_a_second_signal() -> None:
    rng = random.Random(20261116)
    given = ["Juan", "Pedro", "Luis", "Carlos", "Andrés", "Mario", "Jorge", "Diego"]
    surnames = ["Zapata", "Quintero", "Borja", "Arias", "Cuesta", "Mosquera", "Lucumí", "Murillo"]
    for _ in range(300):
        s = rng.choice(surnames)
        a, b = rng.sample(given, 2)
        c = Catalogue.of([Candidate("PLAYER", 1, 1, (f"{a} {s}",)), Candidate("PLAYER", 2, 2, (f"{b} {s}",))])
        filler = rng.choice(["no jugará el domingo", "es duda", "vuelve a entrenar", "será titular"])
        assert linked(f"{s} {filler}", c) == set()
        assert linked(f"{a} {s} {filler}", c) == {1}


def test_non_distinctive_words_are_generated_from_the_catalogue() -> None:
    stop = non_distinctive(["Valencia CF", "Cruz Azul"])
    assert {"valencia", "cruz", "azul", "rey", "copa", "real", "santos", "leon"} <= stop
    c = Catalogue.of([Candidate("TEAM", 1, 1, ("Valencia CF",)), Candidate("PLAYER", 5, 2, ("Enner Valencia",))])
    assert linked("El Valencia viaja sin su delantero", c) == set(), "the club, not the player"
    assert linked("Enner Valencia es baja", c) == {5}


def test_the_whole_squad_is_a_candidate_not_thirty() -> None:
    players = [Candidate("PLAYER", 100 + i, 1, (f"Jugador {chr(65 + i % 26)}{i:02d}x Apellidoúnico{i:02d}",)) for i in range(60)]
    c = Catalogue.of(players)
    assert linked("Apellidoúnico55 se perderá el partido", c) == {155}


def test_a_team_is_named_by_a_word_the_other_team_does_not_have() -> None:
    c = Catalogue.of([Candidate("TEAM", 1, 1, ("Atlético Nacional",)), Candidate("TEAM", 2, 2, ("Atlético Bucaramanga",))])
    names = {m.who.id for m in mentions_in("El Atlético recibe al Bucaramanga", c)}
    assert names == {2}


def test_a_quote_with_only_his_name_is_too_short() -> None:
    c = cat()
    assert validate("Oriol Rey", c.by_key("PLAYER", 10), c) == "quote_too_short"  # type: ignore[arg-type]
