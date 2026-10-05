"""Whether a fixture's venue name and an identified venue are the same ground (fbi.api.repositories.fixtures)."""

from fbi.api.repositories.fixtures import _same_place


def test_spellings_of_one_ground_are_the_same_place() -> None:
    assert _same_place("Estadio Ciudad de Lanus", "Estadio Ciudad de Lanús - Néstor Díaz Pérez")
    assert _same_place("Diego Armando Maradona", "Estadio Diego Armando Maradona")
    assert _same_place("Estadio Marcelo Bielsa", "Estadio Marcelo Alberto Bielsa")
    assert _same_place("Estadio Monumental Jose Fierro", "Estadio Monumental Presidente José Fierro")
    assert _same_place("Stadio Giuseppe  Meazza", "Stadio Giuseppe Meazza")


def test_different_grounds_are_not_and_a_rename_is_not_guessed() -> None:
    assert not _same_place("Optus Stadium", "Stadio Giuseppe Meazza"), "Milan v Como in Perth"
    assert not _same_place("Wheatsheaf Park", "Stamford Bridge")
    assert not _same_place("Estadio Banorte", "Estadio Azteca"), "renamed: not guessed"
    assert not _same_place("Estadio", "Estadio Azteca"), "a generic word alone names nothing"
    assert not _same_place(None, "Old Trafford")
