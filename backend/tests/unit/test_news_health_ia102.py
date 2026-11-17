"""IA-102 (AD-G05): an injury is a STATE - the filter ``health-filter-v1`` on sentences with a diagnosis, a part of the body, a treatment,
a medical report or a time off. Only what the club or the player communicated, attributed, may be said; a time off is never estimated."""

from __future__ import annotations

import pytest

from fbi.news import health
from fbi.news.health import Communicated

PRESS = [Communicated("Pérez sufrió una rotura de ligamento cruzado de la rodilla y estará seis meses de baja", "press")]
CLUB = [Communicated("El club informa: Pérez sufrió una distensión en el isquiotibial derecho; baja de tres semanas", "club")]


@pytest.mark.parametrize("sentence", [
    "Pérez es baja para el domingo.",
    "Pérez está en duda para la final, según el diario.",
    "Gómez cumple sanción y no jugará.",
    "Pérez vuelve a estar disponible.",
    "Pérez is out for Sunday's game, the paper reported.",
    "Pérez, lesionado, no viaja con el equipo.",
])
def test_a_state_source_and_date_pass(sentence: str) -> None:
    assert health.check(sentence, PRESS, injury=True) is None


@pytest.mark.parametrize(("sentence", "why"), [
    ("Pérez sufrió una rotura de ligamento cruzado.", "medical_detail_unattributed"),
    ("Pérez tiene un desgarro en el isquiotibial, según el diario.", "medical_detail_unattributed"),
    ("Pérez será operado de la rodilla.", "medical_detail_unattributed"),
    ("El parte médico de Pérez no es bueno.", "medical_detail_unattributed"),
    ("Pérez tore his ACL and needs surgery.", "medical_detail_unattributed"),
    ("Pérez estará seis meses de baja.", "duration_not_communicated"),
    ("Pérez se perderá el resto de la temporada.", "duration_not_communicated"),
    ("Pérez will be out for 6 weeks.", "duration_not_communicated"),
    ("Una resonancia confirmará el alcance de la lesión de Pérez.", "medical_detail_unattributed"),
])
def test_a_medical_detail_or_a_time_off_from_the_press_is_refused(sentence: str, why: str) -> None:
    assert health.check(sentence, PRESS, injury=True) == why


def test_what_the_club_communicated_may_be_said_attributed_and_only_as_it_said_it() -> None:
    ok = "Según informó el club, Pérez sufrió una distensión en el isquiotibial; baja de tres semanas."
    assert health.check(ok, CLUB, injury=True) is None
    assert health.check("Pérez sufrió una distensión en el isquiotibial.", CLUB, injury=True) == "medical_detail_unattributed", \
        "even the club's word must be attributed"
    assert health.check("Según informó el club, Pérez tiene una rotura en la rodilla.", CLUB, injury=True) == \
        "medical_detail_not_communicated", "a detail the club did not give is inferred"
    assert health.check("Según informó el club, Pérez estará seis semanas fuera.", CLUB, injury=True) == "duration_not_communicated", \
        "a time off the club did not give is an estimate"


def test_a_medical_word_has_no_place_in_another_kind_of_story_either() -> None:
    assert health.check("El fichaje se cerró tras la revisión de su rodilla.", PRESS, injury=False) == "medical_detail_unattributed"
    assert health.check("El Norte ficha a Pérez por tres temporadas.", PRESS, injury=False) is None, "a contract length is not a time off"


def test_the_words_found() -> None:
    assert health.details("Rotura fibrilar en el gemelo; será operado") == ["rotura", "gemelo", "operado"]
    assert health.durations("Estará de baja tres semanas, quizá un mes") == ["tres semanas", "un mes"]
    assert health.details("Ganó de cabeza y el técnico dio la vuelta") == [], "a header and the head coach are not a body"
