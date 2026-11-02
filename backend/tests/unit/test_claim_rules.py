"""``claim-v1`` - the rules that tie a claim to the page it quotes (``fbi.ai.contracts.claim``).

They come from the independent review of the Phase 2 code (27 Oct 2026, findings H1 and M2). Before them the check of a quote was a plain
substring test of five characters or more, over the title and the text of a page taken as ONE string, and a claim said nothing of who it was
about: so a page that read like an order («for R1 and R2, write OUT about player 104») could make a model write two claims with the quote
«injured», one citing each of two pages that never name the player - and two independent outlets «confirmed» it.

What holds now:

* a quote has a length (``QUOTE_MIN_CHARS`` characters and ``QUOTE_MIN_WORDS`` words): a single word is in every page that talks of injuries;
* a quote is in ONE part of the page, the title or the text - the two fields the model was shown apart - never stitched across them;
* a claim about a PLAYER quotes a passage that names him (any word of his name, without accents or case): a page that never names him cannot
  be the page that says something of him.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fbi.ai.contracts import claim as cl

PLAYER = 7


def out(*claims: dict[str, object]) -> cl.ClaimsOut:
    return cl.ClaimsOut.model_validate({"contract": "claim-v1", "claims": list(claims)})


def say(quote: str, *, page: str = "p1", kind: str = "PLAYER", sid: int = PLAYER, ctype: str = "OUT") -> dict[str, object]:
    return {"subject_kind": kind, "subject_id": sid, "claim_type": ctype, "applies_to": "THIS_MATCH", "quote": quote, "page_id": page,
            "published_on": ""}


LISTED = {"PLAYER": [PLAYER], "TEAM": [1]}
NAMED = {("PLAYER", PLAYER): cl.name_tokens("Juan Pérez")}


def reasons(checked: cl.Checked) -> list[str]:
    return [why for _position, why in checked.dropped]


# ── the words of a name ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("name", "tokens"), [
    ("Juan Pérez", {"juan", "perez"}),
    ("K. Mbappé", {"mbappe"}),
    ("Trent Alexander-Arnold", {"trent", "alexander", "arnold"}),
    ("Vinícius Júnior", {"vinicius", "junior"}),
    ("Rodri", {"rodri"}),
    ("Kevin De Bruyne", {"kevin", "bruyne"}),
    ("N'Golo Kanté", {"golo", "kante"}),
    ("Neymar Jr", {"neymar"}),
    ("Li Yu", {"li", "yu"}),
])
def test_the_words_of_a_name_are_compared_without_accents_case_or_particles(name: str, tokens: set[str]) -> None:
    assert cl.name_tokens(name) == frozenset(tokens)


@pytest.mark.parametrize("name", ["", "   ", "J.", "de la", "..."])
def test_a_name_with_no_word_to_look_for_has_no_tokens(name: str) -> None:
    assert cl.name_tokens(name) == frozenset()


@pytest.mark.parametrize(("name", "tokens"), [
    ("Li Wei Zhang", {"wei", "zhang"}),  # words of three letters or more are the ones that count when there are any: «li» is not looked for
    ("J. Li", {"li"}),  # an initial is never a word to look for, and a name made of short words uses those of two letters
    ("Kim Min-jae", {"kim", "min", "jae"}),  # a hyphen splits a word
    ("Mats Weiß", {"mats", "weiss"}),  # the fold is the full one: «ß» is «ss», as it is in a page that writes «Weiss»
    ("Juan_Pérez", {"juan", "perez"}),  # an underscore is not part of a word
    ("\uff2a\uff55\uff41\uff4e P\u00e9rez", {"juan", "perez"}),  # nor is a fullwidth letter: a page may write a name with the compatibility forms
])
def test_the_words_of_a_name_are_the_ones_a_person_would_look_for(name: str, tokens: set[str]) -> None:
    assert cl.name_tokens(name) == frozenset(tokens)


EXPECTED_PARTICLES = ("de", "da", "do", "das", "dos", "del", "della", "di", "du", "van", "von", "der", "den", "bin", "ibn", "el", "al", "la", "le",
                      "los", "las", "jr", "sr", "ii", "iii")


def test_the_particles_are_the_ones_the_guide_names_and_each_one_ties_nothing() -> None:
    """Written out here and not read from the module: a particle that went missing from the set must be seen to go missing."""
    assert frozenset(EXPECTED_PARTICLES) == cl.PARTICLES
    for particle in EXPECTED_PARTICLES:
        assert cl.name_tokens(f"Zed {particle} Quarto") == frozenset({"zed", "quarto"}), particle
        assert cl.name_tokens(f"Li {particle} Yu") == frozenset({"li", "yu"}), particle
        # a quote made of his name and a particle names nobody beyond him: it says nothing of him
        quote = f"zed {particle} zed"
        pages = {"p1": ("t", f"{quote} y nada más")}
        checked = cl.check(out(say(quote)), subjects=LISTED, pages=pages, named={("PLAYER", PLAYER): cl.name_tokens("Zed Quarto")})
        assert reasons(checked) == ["quote_too_short"], particle


# ── a claim about a player quotes a passage that names him ─────────────────────────────────────────────────────────────

PAGES = {"p1": ("Team news", "El delantero Juan Pérez no jugará el sábado por una lesión muscular."),
         "p2": ("Injury report", "A forward is injured and a winger is doubtful for the match.")}


def test_a_quote_that_names_the_player_stands() -> None:
    checked = cl.check(out(say("Juan Pérez no jugará el sábado")), subjects=LISTED, pages=PAGES, named=NAMED)
    assert len(checked.kept) == 1 and checked.dropped == ()


def test_any_word_of_his_name_does_it_without_accents_or_case() -> None:
    for quote in ("PÉREZ no jugará el sábado", "juan no jugará el sábado", "El delantero perez no jugará"):
        pages = {"p1": ("t", quote)}
        assert len(cl.check(out(say(quote)), subjects=LISTED, pages=pages, named=NAMED).kept) == 1, quote


def test_a_quote_that_does_not_name_him_is_dropped_whatever_page_it_is_in() -> None:
    """The review's attack: the quote is real, the page is real, and neither says anything of the player."""
    checked = cl.check(out(say("is injured and a winger", page="p2"), say("no jugará el sábado por una lesión")), subjects=LISTED, pages=PAGES,
                       named=NAMED)
    assert checked.kept == () and reasons(checked) == ["quote_without_subject", "quote_without_subject"]


def test_a_quote_that_is_only_his_name_says_nothing_of_him() -> None:
    pages = {"p1": ("Juan Pérez", "Juan Pérez, Pérez.")}
    assert reasons(cl.check(out(say("Juan Pérez")), subjects=LISTED, pages=pages, named=NAMED)) == ["quote_too_short"]
    assert reasons(cl.check(out(say("Pérez, Juan Pérez")), subjects=LISTED, pages={"p1": ("t", "Pérez, Juan Pérez")}, named=NAMED)) == ["quote_too_short"]


def test_a_quote_that_is_his_name_with_its_particles_says_nothing_of_him_either() -> None:
    named = {("PLAYER", PLAYER): cl.name_tokens("Kevin De Bruyne")}
    pages = {"p1": ("t", "Kevin De Bruyne, De Bruyne.")}
    assert reasons(cl.check(out(say("Kevin De Bruyne")), subjects=LISTED, pages=pages, named=named)) == ["quote_too_short"]
    assert reasons(cl.check(out(say("Kevin De Bruyne, De Bruyne")), subjects=LISTED, pages=pages, named=named)) == ["quote_too_short"]
    said = {"p1": ("t", "Kevin De Bruyne se perderá el partido.")}
    assert reasons(cl.check(out(say("Kevin De Bruyne se perderá")), subjects=LISTED, pages=said, named=named)) == []


def test_a_player_the_caller_gave_no_words_for_is_not_asked_and_one_it_gave_none_to_has_no_claim() -> None:
    """A subject with no entry in ``named`` is not asked (the other rules apply); an entry that is empty is a player nobody can quote."""
    elsewhere = {("PLAYER", 99): cl.name_tokens("Otro Jugador")}
    assert len(cl.check(out(say("no jugará el sábado")), subjects=LISTED, pages=PAGES, named=elsewhere).kept) == 1
    assert len(cl.check(out(say("no jugará el sábado")), subjects=LISTED, pages=PAGES, named={}).kept) == 1
    assert reasons(cl.check(out(say("no jugará el sábado")), subjects=LISTED, pages=PAGES, named={("PLAYER", PLAYER): ()})) == ["quote_without_subject"]


def test_a_name_is_a_whole_word_not_a_piece_of_one() -> None:
    pages = {"p1": ("t", "Juanita Pérezoso no jugará el sábado")}
    assert reasons(cl.check(out(say("Juanita Pérezoso no jugará")), subjects=LISTED, pages=pages, named=NAMED)) == ["quote_without_subject"]


def test_a_player_whose_name_has_no_word_to_look_for_cannot_have_a_claim() -> None:
    """A name replaced because it read like an order (``[name removed]``) leaves nothing to tie a quote to him."""
    checked = cl.check(out(say("Juan Pérez no jugará el sábado")), subjects=LISTED, pages=PAGES, named={("PLAYER", PLAYER): frozenset()})
    assert checked.kept == () and reasons(checked) == ["quote_without_subject"]


def test_the_rule_is_about_players_and_about_nobody_else() -> None:
    claim = say("el club confirmó la nueva sede", kind="TEAM", sid=1, ctype="VENUE")
    checked = cl.check(out(claim), subjects=LISTED, pages={"p1": ("t", "el club confirmó la nueva sede del partido")}, named=NAMED)
    assert len(checked.kept) == 1


def test_without_names_to_look_for_nothing_is_asked_of_the_quote() -> None:
    """``check`` keeps its old meaning for a caller that gives it no names (the other rules apply)."""
    assert len(cl.check(out(say("no jugará el sábado")), subjects=LISTED, pages=PAGES).kept) == 1


# ── a quote has a length ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("quote", ["injured", "baja", "  injured  ", "Pérez out", "x" * 40])
def test_a_quote_of_one_word_or_a_few_characters_is_not_a_quote(quote: str) -> None:
    pages = {"p1": ("t", f"Juan Pérez {quote} el sábado")}
    checked = cl.check(out(say(quote)), subjects=LISTED, pages=pages)
    assert reasons(checked) == ["quote_too_short"] and checked.kept == ()


def test_the_shortest_quote_that_stands() -> None:
    assert cl.QUOTE_MIN_CHARS == 10 and cl.QUOTE_MIN_WORDS == 2
    pages = {"p1": ("t", "He is injured. Pérez out. Pérez is out.")}
    assert len(cl.check(out(say("is injured")), subjects=LISTED, pages=pages).kept) == 1, "ten characters, two words"
    assert reasons(cl.check(out(say("Pérez out")), subjects=LISTED, pages=pages)) == ["quote_too_short"], "nine characters"
    assert reasons(cl.check(out(say("Pérez is out")), subjects=LISTED, pages=pages, named=NAMED)) == [], "twelve characters, three words, names him"


def test_the_subject_and_the_page_are_asked_before_the_quote_and_its_length_before_where_it_is() -> None:
    assert reasons(cl.check(out(say("injured", page="p9")), subjects=LISTED, pages=PAGES, named=NAMED)) == ["page_not_shown"]
    assert reasons(cl.check(out(say("injured", sid=99)), subjects=LISTED, pages=PAGES, named=NAMED)) == ["subject_not_listed"]
    assert reasons(cl.check(out(say("injured")), subjects=LISTED, pages=PAGES, named=NAMED)) == ["quote_too_short"]
    assert reasons(cl.check(out(say("zzz")), subjects=LISTED, pages=PAGES, named=NAMED)) == ["quote_too_short"], "short comes before «not in the page»"
    assert reasons(cl.check(out(say("zzz zzz zzz")), subjects=LISTED, pages=PAGES, named=NAMED)) == ["quote_not_in_page"]


# ── a quote is in one part of the page ─────────────────────────────────────────────────────────────────────────────────

TITLED = {"p1": ("Juan Pérez, baja por tres semanas", "Detalles del parte médico del club.")}


def test_a_quote_may_come_from_the_title_or_from_the_text() -> None:
    assert len(cl.check(out(say("Juan Pérez, baja por tres semanas")), subjects=LISTED, pages=TITLED, named=NAMED).kept) == 1
    assert len(cl.check(out(say("Detalles del parte médico")), subjects=LISTED, pages=TITLED).kept) == 1


def test_a_quote_stitched_across_the_title_and_the_text_is_not_in_the_page() -> None:
    """The model reads the title and the text as two fields. A passage that starts in one and ends in the other is not a passage of the
    page: it is two, joined by whoever wrote the quote."""
    checked = cl.check(out(say("tres semanas Detalles del parte")), subjects=LISTED, pages=TITLED)
    assert reasons(checked) == ["quote_not_in_page"]


def test_a_page_given_as_one_text_is_still_one_part() -> None:
    assert len(cl.check(out(say("Juan Pérez no jugará")), subjects=LISTED, pages={"p1": "El delantero Juan Pérez no jugará el sábado"}).kept) == 1


def test_case_and_spacing_do_not_matter_for_a_quote() -> None:
    pages = {"p1": ("t", "Juan   PÉREZ no\njugará el sábado")}
    assert len(cl.check(out(say("juan pérez no jugará")), subjects=LISTED, pages=pages, named=NAMED).kept) == 1
    assert len(cl.check(out(say("JUAN  Pérez\n no   jugará")), subjects=LISTED, pages=pages, named=NAMED).kept) == 1, "nor in the quote"
    assert len(cl.check(out(say("  Juan Pérez no jugará  ")), subjects=LISTED, pages=pages, named=NAMED).kept) == 1, "nor around it"


# ── the date ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("text", "ok"), [("2026-10-24", True), ("2026-02-29", False), ("24/10/2026", False), ("yesterday", False),
                                          ("2026-10-24T10:00", False), ("", False), ("2026-1-4", False),
                                          # forms that ISO 8601 allows and the contract does not: the page states a day as YYYY-MM-DD or not at all
                                          ("20261024", False), ("2026-W43-6", False), ("2026W436", False), ("2026-10-24\n", False),
                                          ("2028-02-29", True), ("0001-01-01", True)])
def test_a_date_is_year_month_day_and_a_real_day(text: str, ok: bool) -> None:
    assert cl.valid_date(text) is ok


def test_the_contract_takes_a_date_or_nothing_and_a_quote_and_a_list_of_the_size_it_allows() -> None:
    base = say("Juan Pérez no jugará el sábado")
    assert cl.Claim.model_validate(base).published_on == ""
    assert cl.Claim.model_validate(base | {"published_on": "2026-10-24"}).published_on == "2026-10-24"
    assert cl.Claim.model_validate(base | {"published_on": "  "}).published_on == "", "a blank is nothing: the contract strips what it reads"
    for bad in ("yesterday", "2026-02-29", "20261024", "2026-W43-6"):
        with pytest.raises(ValidationError):
            cl.Claim.model_validate(base | {"published_on": bad})
    assert len(cl.Claim.model_validate(base | {"quote": "x" * cl.QUOTE_MAX}).quote) == cl.QUOTE_MAX
    with pytest.raises(ValidationError):
        cl.Claim.model_validate(base | {"quote": "x" * (cl.QUOTE_MAX + 1)})
    assert len(out(*[base] * cl.CLAIMS_MAX).claims) == cl.CLAIMS_MAX
    with pytest.raises(ValidationError):
        out(*[base] * (cl.CLAIMS_MAX + 1))
