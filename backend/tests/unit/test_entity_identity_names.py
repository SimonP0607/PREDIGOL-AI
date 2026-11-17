"""AD-H02 (IA-071): the one key names are stored and compared by, and the name checks of the identity rules."""

from __future__ import annotations

from fbi.people.countries import plain
from fbi.people.identity.names import alias_key, names_compatible, script_of, tokens


def test_accents_case_and_punctuation_do_not_make_two_names() -> None:
    assert alias_key("James Rodríguez") == alias_key("James Rodriguez") == "james rodriguez"
    assert alias_key("  JAMES   RODRÍGUEZ ") == "james rodriguez"
    assert alias_key("D'Amico") == "damico"
    assert alias_key("Relja Obrić") == "relja obric"
    assert alias_key("Müller-Wohlfahrt") == "muller wohlfahrt"
    assert alias_key("Ødegaard") == "odegaard"


def test_latin_text_gives_exactly_the_referee_key() -> None:
    for text in ("Michael Oliver", "Jesús Gil Manzano", "Szymon Marciniak", "Clément Turpin", "Danny Makkelie"):
        assert alias_key(text) == plain(text)


def test_other_scripts_keep_their_letters() -> None:
    assert alias_key("Дибала, Пауло") == "дибала пауло"
    assert alias_key("محمد صلاح") == "محمد صلاح"
    assert alias_key("ガ") != alias_key("カ"), "a Japanese voicing mark is a sound, not an accent"
    assert script_of("Дибала") == "cyrillic"
    assert script_of("محمد") == "arabic"
    assert script_of("孫興慜") == "cjk"
    assert script_of("손흥민") == "hangul"
    assert script_of("Son Heung-min") == "latin"


def test_nicknames_are_their_own_keys() -> None:
    assert alias_key("Millos") == "millos"
    assert alias_key("«Cucho»") == "cucho"
    assert tokens("Juan Camilo Hernández") == ["juan", "camilo", "hernandez"]


def test_a_short_name_and_the_full_name_are_compatible() -> None:
    assert names_compatible(["M. Salah"], ["Mohamed Salah", "Mohamed Salah Hamed Ghaly"])
    assert names_compatible(["Pedri"], ["Pedro González López", "Pedri"])
    assert names_compatible(["Sy"], ["Seydou Sy"]), "a two-letter surname is a surname (IA-041's false alarms)"


def test_names_that_share_no_surname_are_a_doubt() -> None:
    assert not names_compatible(["M. Salah"], ["Mohamed Elneny"])
    assert not names_compatible(["J. Rodríguez"], ["James de Jesús"]), "a particle is not a shared surname"
    assert not names_compatible(["Mohamed Elneny"], ["Mohamed Salah"]), "a shared given name is not a surname"
    assert names_compatible(["Vinícius Júnior"], ["Vinícius José Paixão de Oliveira Júnior", "Vinicius Junior"])


def test_teams_are_compared_without_the_words_every_club_has() -> None:
    assert names_compatible(["Bayern München"], ["FC Bayern Munich"], person=False)
    assert names_compatible(["Millonarios"], ["Millonarios FC"], person=False)
    assert not names_compatible(["Real Madrid"], ["Real Sociedad"], person=False)
    assert not names_compatible(["Manchester United"], ["Leeds United"], person=False)


def test_a_team_written_as_its_initials_is_its_name() -> None:
    for short, long in (("QPR", "Queens Park Rangers"), ("VVOG", "Voetbal Vereniging Ons Genoegen"),
                        ("HIK", "Hellerup IK"), ("OKS", "Odense Kammeraternes SK"), ("MP", "Mikkelin Palloilijat")):
        assert names_compatible([short], [long], person=False), short
    assert not names_compatible(["QPR"], ["Leeds United"], person=False)
    assert not names_compatible(["Qpr"], ["Queens Park Rangers"], person=False), "only a name in capitals is initials"
    assert not names_compatible(["SOA"], ["Sporting Lisbon"], person=False)
