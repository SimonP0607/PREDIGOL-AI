"""``windows-v1`` (IA-087, plan piece AD-C05): the clean page, the windows chosen by code, the fingerprint and the near-duplicates."""

from __future__ import annotations

from fbi.ai.deep_pages import (
    MAX_WINDOWS,
    PAGE_CHARS,
    WINDOW_CHARS,
    choose,
    clean,
    common_lines,
    fingerprint,
    near_duplicate,
    simhash,
)
from fbi.ai.mentions import Candidate, Catalogue

CAT = Catalogue.of([Candidate("TEAM", 1, 1, ("Alfa FC",)), Candidate("TEAM", 2, 2, ("Beta FC",)),
                    Candidate("PLAYER", 91001, 1, ("Delantero Uno",)), Candidate("PLAYER", 92001, 2, ("Extremo Zubizarreta",))])
FILLER = "El club informó de la venta de abonos para la próxima temporada y del horario de la tienda oficial. "


def test_clean_drops_the_repeated_title_and_the_domains_common_lines() -> None:
    title = "Alfa FC: baja en el ataque"
    raw = f"{title}\n\n# {title}\n\nSuscríbete a nuestro boletín diario\nDelantero Uno no jugará ante Beta FC.\n"
    others = [("diario.example", raw), ("diario.example", "Otra cosa\nSuscríbete a nuestro boletín diario\n"),
              ("diario.example", "Más\nSuscríbete a nuestro boletín diario\n")]
    common = common_lines(others)["diario.example"]
    out = clean(title, raw, common=common)
    assert out.startswith("Delantero Uno no jugará")
    assert "boletín" not in out
    assert len(clean("t", "x" * 20_000)) == PAGE_CHARS


def test_a_fact_after_the_700th_character_is_in_a_window() -> None:
    text = FILLER * 12 + "\n\nDelantero Uno no jugará ante Beta FC por lesión muscular.\n\n" + FILLER * 5
    assert text.index("Delantero Uno") > 700
    windows = choose(text, CAT)
    assert windows and any("Delantero Uno no jugará" in w.text for w in windows)
    assert all(len(w.text) <= WINDOW_CHARS for w in windows)
    assert ("PLAYER", 91001) in windows[0].subjects


def test_a_page_that_names_nobody_has_no_window() -> None:
    assert choose(FILLER * 10, CAT) == []


def test_at_most_four_windows_in_the_order_of_the_page() -> None:
    blocks = [FILLER * 25 + f"\n\nDelantero Uno {i} no jugará.\n\n" for i in range(8)]
    windows = choose("".join(blocks), CAT)
    assert 1 <= len(windows) <= MAX_WINDOWS
    assert [w.start for w in windows] == sorted(w.start for w in windows)
    assert all(len(w.text) <= WINDOW_CHARS for w in windows)


def test_one_page_one_fingerprint_whatever_the_address() -> None:
    a = clean("Titular", "Titular\n\nDelantero Uno es baja.")
    b = clean("Titular", "Delantero Uno es baja.")
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint("") is None


def test_a_wire_story_with_another_footer_is_a_near_duplicate() -> None:
    story = ("Delantero Uno se perderá el partido ante Beta FC por una lesión muscular, informó el club en un comunicado. "
             "El jugador sufrió la lesión en el entrenamiento del martes y estará de baja entre dos y tres semanas. ") * 3
    a, b = simhash(story + "Fuente: agencia."), simhash("Última hora. " + story + "Lea también nuestra edición impresa.")
    other = simhash("Extremo Zubizarreta renovó su contrato hasta 2029 con Beta FC tras una gran temporada en la liga. " * 3)
    assert near_duplicate(a, b)
    assert not near_duplicate(a, other)
