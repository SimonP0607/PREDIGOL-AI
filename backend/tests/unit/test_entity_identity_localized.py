"""The Spanish and English names of national teams and competitions (C-10 1.1; AP-B02, AP-B07, AP-E02): what the table
gives for the provider's names, and what it refuses to guess."""

from __future__ import annotations

import pytest

from fbi.people.identity import localized as lz
from fbi.people.identity import names as nm


def texts(names: object) -> list[tuple[str, str]]:
    return [(n.text, n.language) for n in names]  # type: ignore[attr-defined]


@pytest.mark.parametrize(("provider", "spanish"), [
    ("Spain", "España"), ("England", "Inglaterra"), ("Germany", "Alemania"), ("Scotland", "Escocia"), ("Wales", "Gales"),
    ("Northern Ireland", "Irlanda del Norte"), ("Netherlands", "Países Bajos"), ("Ivory Coast", "Costa de Marfil"),
    ("USA", "Estados Unidos"), ("Türkiye", "Turquía"), ("Rep. Of Ireland", "Irlanda"), ("Korea Republic U17", "Corea del Sur Sub-17"),
    ("Germany U21", "Alemania Sub-21"), ("Mexico W U17", "México Femenina Sub-17"), ("Brazil", "Brasil"),
])
def test_a_national_team_gets_its_spanish_name(provider: str, spanish: str) -> None:
    assert (spanish, "es") in texts(lz.team_names(provider))


@pytest.mark.parametrize(("provider", "english"), [
    ("Türkiye", "Turkey"), ("USA", "United States"), ("Czech Republic", "Czechia"), ("Korea Republic", "South Korea"),
    ("Mexico W U17", "Mexico Women U17"), ("Cape Verde Islands", "Cape Verde"), ("Bosnia & Herzegovina", "Bosnia and Herzegovina"),
])
def test_a_national_team_gets_its_usual_english_names(provider: str, english: str) -> None:
    assert (english, "en") in texts(lz.team_names(provider))


@pytest.mark.parametrize("provider", ["Alo Egypt", "France Aizenay", "Mação", "Atlantis", "", "Spain B"])
def test_an_unknown_name_gets_nothing(provider: str) -> None:
    assert list(lz.team_names(provider)) == []


def test_every_provider_name_has_its_country_and_every_country_has_both_languages() -> None:
    assert set(lz.PROVIDER_COUNTRY.values()) <= set(lz.COUNTRY_NAMES)
    for code, (es, en) in lz.COUNTRY_NAMES.items():
        assert es and en, code
        assert all(nm.alias_key(n) for n in es + en), code


@pytest.mark.parametrize(("name", "country", "alias"), [
    ("World Cup", "World", "Mundial"), ("World Cup", "World", "Copa del Mundo"), ("UEFA Champions League", "World", "Liga de Campeones"),
    ("Euro Championship", "World", "Eurocopa"), ("UEFA Nations League", "World", "Liga de Naciones"),
    ("DFB Pokal", "Germany", "Copa de Alemania"), ("Super Cup", "Spain", "Supercopa de España"),
    ("Copa America", "World", "Copa América"), ("FIFA Club World Cup", "World", "Mundial de Clubes"),
])
def test_a_competition_gets_its_spanish_names(name: str, country: str, alias: str) -> None:
    assert (alias, "es") in texts(lz.competition_names(name, country))


def test_a_competition_is_matched_by_its_name_and_country() -> None:
    assert ("Supercopa de Italia", "es") in texts(lz.competition_names("Super Cup", "Italy"))
    assert list(lz.competition_names("Super Cup", "Atlantis")) == []
    assert list(lz.competition_names("Liga Ficticia", "Ejemplandia")) == []


def test_the_source_is_the_one_migration_0173_allows() -> None:
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0173_localized_aliases.py"
    spec = spec_from_file_location("migration_0173", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert lz.SOURCE in module.NEW_SOURCES and lz.SOURCE not in module.SOURCES_BEFORE
