"""The readers' chronicle (plan UX, A11 and UX-025): what the server checks before a reader may read a sentence the AI wrote -
pure, no database, no model.

A good chronicle passes whole. Each check is shown failing on its own: a reference not given or a block where a result's own
reference is needed, a number the cited facts do not hold (a score of another match, small numbers too, and a share never stands
for a whole number), certainty and betting words in either language, the system's codes, a DESCRIPTIVE factor made a cause, a
rumour outside the risks or not called one, a probable item told as a fact, a player in doubt told as a certain absence, an injury
the provider's reason does not give, a section longer than its ceiling or one the story does not have, and a Spanish and an
English that do not say the same. A translation is kept or dropped on its own."""

from __future__ import annotations

import ast
import copy
import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import user_budget
from fbi.ai.usage import Budget
from fbi.api.services import reading, story
from fbi.narrative import job as un
from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

MU, LIV = "Manchester United", "Liverpool"


def F(ref: str, section: str, code: str, **params: Any) -> story.Fact:  # noqa: N802 - a constructor
    return story.Fact(ref, section, code, params)


FACTS = (
    F("P:fixture", "summary", "match_intro", competition="Premier League", round="Regular Season - 9", neutral=None),
    F("P:stakes.home", "home", "stakes_zone", side="home", team=MU, rank=4, zone="europe"),
    F("P:stakes.away", "away", "stakes_pressure", side="away", team=LIV, pressure="title"),
    F("P:form.home", "home", "form", side="home", team=MU, sequence="WWDLW", n=5, ppg=2.0, goals_for=1.8,
      goals_against=1.0, wins=3, draws=1, losses=1),
    F("P:form.away", "away", "form", side="away", team=LIV, sequence="WWWWD", n=5, ppg=2.6, goals_for=2.4,
      goals_against=0.6, wins=4, draws=1, losses=0),
    F("P:results.home.1", "home", "result", side="home", team=MU, opponent="Fulham", venue="home", goals_for=2,
      goals_against=1, outcome="W", competition="Premier League", order=1),
    F("P:results.home.2", "home", "result", side="home", team=MU, opponent="Brighton", venue="away", goals_for=0,
      goals_against=0, outcome="D", competition="Premier League", order=2),
    F("P:results.away.1", "away", "result", side="away", team=LIV, opponent="Everton", venue="away", goals_for=3,
      goals_against=0, outcome="W", competition="Premier League", order=1),
    F("P:absences.home", "home", "key_absences", side="home", team=MU, count=1, players=["Lisandro Martínez"]),
    F("P:absences.home.1", "home", "absence", side="home", team=MU, player="Lisandro Martínez", status="out",
      reason="Hamstring Injury", kind="injury", key=True),
    F("P:absences.away.1", "away", "absence", side="away", team=LIV, player="Mohamed Salah", status="doubtful",
      reason="Knock", kind="injury", key=True),
    F("P:absences.away.2", "away", "absence", side="away", team=LIV, player="Trent Alexander-Arnold", status="out",
      reason="Yellow Cards", kind="suspension", key=False),
    F("P:h2h", "h2h", "h2h", n=8, home=MU, home_wins=2, draws=3, away=LIV, away_wins=3),
    F("P:h2h.meeting.1", "h2h", "h2h_meeting", home=MU, away=LIV, goals_home=1, goals_away=2, winner="away",
      home_was="away", months_ago=8, competition="Premier League", after_extra_time=None),
)
CAPS = {"summary": 2, "home": 4, "away": 4, "h2h": 2, "risks": 3}

INJURY = "Lisandro Martínez es baja por lesión para este partido."
DOUBT = "Según Marca, Mohamed Salah está en duda por unas molestias en el tobillo."
RUMOUR = "Se dice que el portero titular no viajó con el equipo."
TITLE = "Lisandro Martínez se pierde el partido ante el Liverpool por lesión"


def news(i: int, status: str, claim: str, *, translated: bool = False, title: str | None = None,
         source: str | None = "Marca") -> un.NewsItem:
    return un.NewsItem(i, f"E:{i}", "injury", status, "home", claim, "media", f"{i:064x}", title, translated, source)


def inp(**changes: Any) -> un.NarrativeInput:
    base: dict[str, Any] = {
        "fixture_id": 7, "packet_id": 70, "data_at": dt.datetime(2026, 10, 26, 18, 0, tzinfo=dt.UTC), "story_hash": "b" * 64,
        "home": MU, "away": LIV, "competition": "Premier League", "facts": FACTS,
        "news": (news(101, "CONFIRMED", INJURY, title=TITLE), news(102, "PROBABLE", DOUBT), news(103, "RUMOR", RUMOUR)),
        "caps": CAPS}
    base.update(changes)
    return un.NarrativeInput(**base)


def S(text: str, *refs: str) -> dict[str, Any]:  # noqa: N802 - a constructor
    return {"text": text, "refs": list(refs)}


def good() -> dict[str, Any]:
    return {
        "es": {
            "summary": [S("Manchester United recibe al Liverpool en la jornada 9 de la Premier League.", "P:fixture"),
                        S("Los locales son cuartos y pelean por plazas internacionales; los visitantes, por el título.",
                          "P:stakes.home", "P:stakes.away")],
            "home": [S("Manchester United llega tras ganar 2-1 al Fulham en casa y empatar 0-0 con el Brighton fuera.",
                       "P:results.home.1", "P:results.home.2"),
                     S("Su baja más importante es Lisandro Martínez, lesionado en el isquiotibial.", "P:absences.home.1"),
                     S("Marca confirma que se pierde el partido.", "E:101")],
            "away": [S("El Liverpool viene de golear 3-0 al Everton como visitante.", "P:results.away.1"),
                     S("Mohamed Salah es duda por unas molestias y Trent Alexander-Arnold está sancionado por acumulación "
                       "de tarjetas.", "P:absences.away.1", "P:absences.away.2")],
            "h2h": [S("En 8 duelos hay 2 victorias del Manchester United, 3 empates y 3 del Liverpool.", "P:h2h"),
                    S("El último cruce, hace 8 meses, lo ganó el Liverpool por 1-2 como visitante.", "P:h2h.meeting.1")],
            "risks": [S("La duda de Mohamed Salah y la baja de Trent Alexander-Arnold pueden pesar en el Liverpool.",
                        "P:absences.away.1", "P:absences.away.2"),
                      S("Hay un rumor sin confirmar sobre el portero titular del Manchester United.", "E:103"),
                      S("Según Marca, Mohamed Salah está en duda.", "E:102")],
        },
        "en": {
            "summary": [S("Manchester United host Liverpool in round 9 of the Premier League.", "P:fixture"),
                        S("The home side is fourth and fights for the international places; the visitors fight for the "
                          "title.", "P:stakes.home", "P:stakes.away")],
            "home": [S("Manchester United arrive after beating Fulham 2-1 at home and drawing 0-0 at Brighton.",
                       "P:results.home.1", "P:results.home.2"),
                     S("Their most important absence is Lisandro Martínez, with a hamstring injury.", "P:absences.home.1"),
                     S("Marca confirms he will miss the match.", "E:101")],
            "away": [S("Liverpool come off a 3-0 win away at Everton.", "P:results.away.1"),
                     S("Mohamed Salah is doubtful with a knock and Trent Alexander-Arnold is suspended for accumulated "
                       "cards.", "P:absences.away.1", "P:absences.away.2")],
            "h2h": [S("In 8 meetings there are 2 Manchester United wins, 3 draws and 3 for Liverpool.", "P:h2h"),
                    S("The last meeting, 8 months ago, was won by Liverpool 1-2 away from home.", "P:h2h.meeting.1")],
            "risks": [S("Mohamed Salah's doubt and Trent Alexander-Arnold's absence may weigh on Liverpool.",
                        "P:absences.away.1", "P:absences.away.2"),
                      S("There is an unconfirmed rumour about Manchester United's first-choice goalkeeper.", "E:103"),
                      S("According to Marca, Mohamed Salah is doubtful.", "E:102")],
        },
        "news": [
            {"id": 101, "headline_es": "Lisandro Martínez, baja por lesión", "headline_en": "Lisandro Martínez out injured",
             "claim_en": "Lisandro Martínez is out injured for this match."},
            {"id": 102, "headline_es": "Mohamed Salah, en duda", "headline_en": "Mohamed Salah a doubt",
             "claim_en": "According to Marca, Mohamed Salah is doubtful with discomfort in his ankle."},
            {"id": 103, "headline_es": "Rumor sobre el portero titular", "headline_en": "A rumour about the goalkeeper",
             "claim_en": "It is said that the first-choice goalkeeper did not travel with the team."},
        ],
    }


def verdict(data: dict[str, Any], **changes: Any) -> un.Verdict:
    return un.validate(un.NarrativeOut.model_validate(data), inp(**changes))


def set_text(data: dict[str, Any], lang: str, section: str, i: int, text: str, refs: list[str] | None = None) -> None:
    data[lang][section][i]["text"] = text
    if refs is not None:
        data[lang][section][i]["refs"] = refs


def test_a_good_chronicle_passes_whole_with_its_translations_and_its_sources() -> None:
    v = verdict(good())
    assert v.ok, [p.as_json() for p in v.problems]
    assert v.content is not None and list(v.content) == ["es", "en", "sources"]
    assert [s["key"] for s in v.content["es"]] == list(un.SECTIONS)
    assert v.content["en"][1]["sentences"][0]["refs"] == ["P:results.home.1", "P:results.home.2"]
    assert v.content["sources"] == [{"name": "Marca"}], "the outlet of the news it cites, once"
    assert {t.evidence_id for t in v.translations} == {101, 102, 103} and not v.dropped
    t = next(t for t in v.translations if t.evidence_id == 101)
    assert t.headline_es == "Lisandro Martínez, baja por lesión" and t.claim_en is not None


@pytest.mark.parametrize(("lang", "section", "i", "text", "refs", "why"), [
    ("es", "home", 0, "Manchester United ganó 2-1 al Fulham.", ["P:results.home.9"], "references not given"),
    ("es", "home", 0, "Manchester United llega tras ganar 3-1 al Fulham en casa.", ["P:results.home.1"],
     "numbers not in what it cites: 3"),
    ("es", "home", 0, "Manchester United llega tras ganar 3-0 al Everton.", ["P:results.home.1"],
     "numbers not in what it cites: 3"),
    ("es", "home", 0, "Manchester United llega tras ganar 2-1 al Fulham en casa y empatar 0-0 con el Brighton fuera.",
     ["P:results"], "block where the fact's own reference is needed"),
    ("es", "home", 0, "Manchester United llega tras ganar 2-1 al Fulham en casa y empatar 0-0 con el Brighton fuera.",
     ["P:results.home"], "block where the fact's own reference is needed"),
    ("es", "h2h", 1, "El último cruce lo ganó el Liverpool por 1-2.", ["P:h2h.meeting"], "block where the fact's own"),
    ("es", "home", 0, "Manchester United suma cuatro victorias seguidas.", ["P:form.home"],
     "numbers not in what it cites: cuatro"),
    ("es", "home", 0, "Manchester United ganó tres de sus últimos 5.", ["P:form.home"], None),
    ("es", "summary", 0, "La victoria del Manchester United es segura.", None, "forbidden phrase"),
    ("es", "summary", 0, "Una victoria garantizada del Manchester United.", None, "forbidden phrase"),
    ("es", "home", 0, "Hay valor en el Manchester United, que ganó 2-1 al Fulham.", ["P:results.home.1"], "forbidden phrase"),
    ("es", "home", 0, "Conviene una apuesta al Manchester United, que ganó 2-1 al Fulham.", ["P:results.home.1"],
     "forbidden phrase"),
    ("es", "home", 0, "Este pick del Manchester United viene de ganar 2-1 al Fulham.", ["P:results.home.1"],
     "forbidden phrase"),
    ("en", "summary", 0, "A Manchester United win is a sure thing.", None, "forbidden phrase"),
    ("en", "home", 0, "Manchester United look like value after a 2-1 win over Fulham.", ["P:results.home.1"],
     "forbidden phrase"),
    ("en", "home", 0, "Bet on Manchester United after a 2-1 win over Fulham.", ["P:results.home.1"], "forbidden phrase"),
    ("en", "summary", 0, "Manchester United will win.", None, "forbidden phrase"),
    ("es", "home", 0, "Con home_win el Manchester United suma 2-1 al Fulham.", ["P:results.home.1"],
     "only the system says"),
    ("es", "home", 0, "El Manchester United (P:results.home.1) ganó 2-1 al Fulham.", ["P:results.home.1"],
     "only the system says"),
    ("es", "risks", 2, "Según Marca (https://marca.com/1), Salah está en duda.", None, "only the system says"),
    ("es", "h2h", 0, "En 8 duelos hay 2 victorias del Manchester United, 3 empates y 3 del Liverpool, por eso el Liverpool "
                     "es favorito.", None, "DESCRIPTIVE factor, a cause"),
    ("en", "h2h", 1, "The last meeting, 8 months ago, was won by Liverpool 1-2 because of its tactics.", None,
     "DESCRIPTIVE factor, a cause"),
    ("es", "away", 0, "Hay un rumor sin confirmar sobre el portero titular.", ["E:103"], "outside the risks"),
    ("es", "risks", 1, "El portero titular no viajó con el equipo.", None, "not called one"),
    ("es", "risks", 2, "Mohamed Salah no jugará.", None, "told as a fact"),
    ("es", "away", 1, "Mohamed Salah y Trent Alexander-Arnold están fuera del partido.", None,
     "a player in doubt told as a certain absence"),
    ("en", "away", 1, "Mohamed Salah and Trent Alexander-Arnold are out of the match.", None,
     "a player in doubt told as a certain absence"),
    ("es", "away", 1, "Trent Alexander-Arnold está lesionado y no jugará el partido.", ["P:absences.away.2"],
     "calls an injury what the provider's reason does not"),
    ("en", "away", 1, "Trent Alexander-Arnold is out with a muscle injury.", ["P:absences.away.2"],
     "calls an injury what the provider's reason does not"),
    ("es", "risks", 0, "Corto.", None, "length"),
])
def test_each_check_refuses_on_its_own(lang: str, section: str, i: int, text: str, refs: list[str] | None,
                                       why: str | None) -> None:
    data = good()
    set_text(data, lang, section, i, text, refs)
    other = "en" if lang == "es" else "es"
    if refs is not None:  # the other language cites the same, so only the check under test speaks
        data[other][section][i]["refs"] = refs
    v = verdict(data)
    if why is None:  # «tres de sus últimos 5»: counted in words by the form's own wins and n - allowed
        reasons = [p.why for p in v.problems if p.where.startswith(f"{lang}.{section}[{i}]")]
        assert not reasons, reasons
        return
    assert not v.ok and v.content is None
    reasons = [p.why for p in v.problems if p.where.startswith(f"{lang}.{section}[{i}]")]
    assert any(why in r for r in reasons), [p.as_json() for p in v.problems]


def test_a_name_with_digits_is_a_name_and_a_share_is_written_as_its_percentage() -> None:
    mainz = inp(facts=tuple(
        story.Fact(f.ref, f.section, f.code, {k: ("Mainz 05" if v == "Fulham" else v) for k, v in f.params.items()})
        for f in FACTS))
    s = un.SentenceOut(text="Manchester United llega tras ganar 2-1 al Mainz 05 en casa.", refs=["P:results.home.1"])
    assert un.check_sentence(s, lang="es", section="home", inp=mainz) is None, "an opponent's number is no number"
    assert un.stated(un.Figure("1", 1.0, 0), {0.54}) is False, "1 never stands for 0.54"
    assert un.stated(un.Figure("4", 4.0, 0), {3.5}) is True, "3.5 rounded"
    assert un.stated(un.Figure("-2", 2.0, 0), {2.0}) is True
    zero = un.SentenceOut(text="Manchester United empató 0-0 con el Brighton fuera.", refs=["P:results.home.2"])
    assert un.check_sentence(zero, lang="es", section="home", inp=inp()) is None, "a goalless draw is told with its zeros"


def test_a_block_above_a_fact_covers_it_but_a_result_a_meeting_and_a_fact_below_one_are_not_that_block() -> None:
    above = un.SentenceOut(text="Manchester United suma 2,0 puntos por partido y Liverpool 2,6.", refs=["P:form"])
    assert un.check_sentence(above, lang="es", section="home", inp=inp()) is None
    below = un.SentenceOut(text="Manchester United suma 2,0 puntos por partido.", refs=["P:form.home.ppg"])
    assert "references not given" in (un.check_sentence(below, lang="es", section="home", inp=inp()) or "")
    record = un.SentenceOut(text="En 8 duelos hay 2 victorias del Manchester United.", refs=["P:h2h"])
    assert un.check_sentence(record, lang="es", section="h2h", inp=inp()) is None, "the record is cited by its block"


def test_the_spanish_and_the_english_say_the_same() -> None:
    fewer = good()
    fewer["en"]["risks"].pop()
    assert any("3 sentences in Spanish, 2 in English" in p.why for p in verdict(fewer).problems)
    refs = good()
    refs["en"]["home"][1]["refs"] = ["P:absences.home"]
    assert any("other references" in p.why for p in verdict(refs).problems)
    numbers = good()
    numbers["en"]["h2h"][0]["text"] = "In 8 meetings there are 2 Manchester United wins, 3 draws and 3 for Liverpool, or 0.42."
    assert any("other numbers" in p.why for p in verdict(numbers).problems)


def test_the_sections_follow_the_story_and_none_is_longer_than_its_ceiling() -> None:
    data = good()
    short = {k: v for k, v in CAPS.items() if k != "h2h"}
    v = verdict(data, caps=short)
    assert any(p.why == "a section the story does not have" for p in v.problems)
    for lang in ("es", "en"):
        data[lang]["h2h"] = []
    assert verdict(data, caps=short).ok
    empty = good()
    empty["es"]["risks"] = []
    empty["en"]["risks"] = []
    assert any(p.where == "es.risks" and p.why == "empty" for p in verdict(empty).problems)
    many = good()
    for lang in ("es", "en"):
        many[lang]["summary"] = many[lang]["summary"] * 2
    assert any("at most 2" in p.why for p in verdict(many).problems)
    tight = verdict(good(), caps={**CAPS, "home": 2})
    assert any("at most 2" in p.why and p.where == "es.home" for p in tight.problems), "a poor side takes fewer sentences"


def test_a_translation_is_kept_or_dropped_on_its_own() -> None:
    data = good()
    data["news"][0]["claim_en"] = "Lisandro Martínez is out for 3 weeks."  # a number the claim does not hold
    data["news"][1]["headline_en"] = "Lisandro Martínez se pierde el partido ante el Liverpool por lesión"  # the source's title? no
    data["news"][2]["claim_en"] = "Se dice que el portero titular no viajó con el equipo."  # the Spanish, not a translation
    data["news"].append({"id": 999, "headline_es": "Otra", "headline_en": "Another", "claim_en": "Another item."})
    v = verdict(data, news=(news(101, "CONFIRMED", INJURY, title=TITLE), news(102, "PROBABLE", DOUBT, title=TITLE),
                            news(103, "RUMOR", RUMOUR)))
    assert v.ok, "the chronicle does not depend on its translations"
    by = {t.evidence_id: t for t in v.translations}
    assert by[101].claim_en is None and by[101].headline_en == "Lisandro Martínez out injured"
    assert by[102].headline_en is None, "the source's title is never written, in any language"
    assert by[103].claim_en is None and by[103].headline_en is not None
    whys = {p.where: p.why for p in v.dropped}
    assert "numbers not in the claim" in whys["news.E:101.claim_en"]
    assert whys["news.E:102.headline_en"] == "repeats the source's title"
    assert whys["news.E:103.claim_en"] == "not English"
    assert whys["news.999"] == "not an item to translate"
    already = verdict(good(), news=(news(101, "CONFIRMED", INJURY, translated=True), news(102, "PROBABLE", DOUBT),
                                    news(103, "RUMOR", RUMOUR)))
    assert 101 not in {t.evidence_id for t in already.translations}, "an item translated already is not asked again"


def test_the_sources_are_the_outlets_of_the_news_it_cites_once_and_none_when_it_cites_none() -> None:
    other = (news(101, "CONFIRMED", INJURY, source="Marca"), news(102, "PROBABLE", DOUBT, source="AS"),
             news(103, "RUMOR", RUMOUR, source="Marca"))
    v = verdict(good(), news=other)
    assert v.content is not None and v.content["sources"] == [{"name": "Marca"}, {"name": "AS"}]
    none = good()
    for lang in ("es", "en"):
        none[lang]["home"][2] = S("Su plantel llega sin otras novedades." if lang == "es" else "The squad has no other news.",
                                  "P:form.home")
        none[lang]["risks"] = [S("Hay un rumor sin confirmar sobre el portero titular." if lang == "es" else
                                 "There is an unconfirmed rumour about the first-choice goalkeeper.", "P:absences.home.1")]
    v = verdict(none)
    assert v.ok, [p.as_json() for p in v.problems]
    assert v.content is not None and v.content["sources"] == []


def test_the_input_is_the_facts_and_the_news_and_its_hash_ignores_what_is_left_to_translate() -> None:
    body = inp().body()
    assert set(body) == {"match", "limits", "facts", "news", "translate", "note"}
    assert body["limits"] == CAPS
    assert body["facts"][0] == {"ref": "P:fixture", "section": "summary", "code": "match_intro",
                                "params": {"competition": "Premier League", "round": "Regular Season - 9", "neutral": None}}
    assert [n["ref"] for n in body["news"]] == ["E:101", "E:102", "E:103"] and len(body["translate"]) == 3
    assert body["news"][0]["source"] == "Marca"
    done = inp(news=(news(101, "CONFIRMED", INJURY, translated=True), news(102, "PROBABLE", DOUBT, translated=True),
                     news(103, "RUMOR", RUMOUR, translated=True)))
    assert done.body()["translate"] == [] and done.hash == inp().hash, "a kept translation does not make the story new"
    assert inp(story_hash="c" * 64).hash != inp().hash, "another story is another input"
    assert inp(caps={**CAPS, "home": 2}).hash != inp().hash, "another ceiling is another input"
    assert "Marca" in inp().names and "Fulham" in inp().names, "the outlets and the opponents are names, never numbers"


def test_the_prompt_explains_every_code_of_the_story_and_the_schema_has_no_bound() -> None:
    codes = set(story.READING_CODES) | {"result", "absence", "h2h_meeting"}
    assert codes == set(un.GLOSSARY), sorted(codes ^ set(un.GLOSSARY))
    for code in un.GLOSSARY:
        assert f"- {code}: " in un.SYSTEM
    in_story = {f.code for f in FACTS}
    assert in_story <= set(un.GLOSSARY), sorted(in_story - set(un.GLOSSARY))

    def keys(x: Any) -> set[str]:
        if isinstance(x, dict):
            return set(x) | {k for v in x.values() for k in keys(v)}
        if isinstance(x, list):
            return {k for v in x for k in keys(v)}
        return set()

    assert not keys(un.SCHEMA) & {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
    assert set(un.SCHEMA["properties"]["es"]["required"]) == set(story.SECTIONS) == set(un.LanguageOut.model_fields)
    assert un.VERSION == reading.NARRATIVE_VERSION == "user-narrative-v3"


def test_the_story_never_names_what_the_chronicle_must_not_know() -> None:
    """The prompt and the facts hold no forecast, price, pick or Elo: the chronicle cannot tell what it was never given."""
    for word in ("expected_result", "likely", "market_favourite", "market_moved", "uncalibrated", "forecast_missing"):
        assert word not in un.GLOSSARY
    assert not any(f.ref.startswith(("P:forecast", "P:market", "P:models", "P:elo")) for f in FACTS)
    assert not {"expected_result", "likely", "market_favourite", "market_total"} & story.READING_CODES


def row(fixture: int, *, pick: bool = False, tier: int = 3, absences: int = 0, web: int = 0, hour: int = 20) -> dict[str, Any]:
    return {"fixture_id": fixture, "has_pick": pick, "tier": tier, "absences": absences, "news": web,
            "kickoff_at": dt.datetime(2026, 11, 7, hour, 0, tzinfo=dt.UTC)}


def test_the_money_goes_first_to_a_match_with_a_pick_then_the_first_tier_then_where_there_is_more_to_say() -> None:
    rows = [row(1, tier=5), row(2, tier=3, absences=6, web=2), row(3, tier=1), row(4, tier=4, pick=True),
            row(5, tier=2, absences=9), row(6, tier=1, hour=15), row(7, tier=5, hour=12)]
    order = [r["fixture_id"] for r in sorted(rows, key=un.priority)]
    assert order == [4, 6, 3, 2, 5, 7, 1], order
    assert un.priority(row(8, tier=9, absences=50, web=50))[1] == -(8 + 8), "what a match can claim is capped"


@pytest.mark.parametrize(("raw", "mode"), [(None, "off"), ("", "off"), ("0", "off"), ("off", "off"), ("maybe", "off"),
                                           ("shadow", "shadow"), (" Shadow ", "shadow"), ("1", "on"), ("on", "on"),
                                           ("TRUE", "on")])
def test_the_switch_is_off_unless_written_shadow_or_on(raw: str | None, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if raw is None:
        monkeypatch.delenv(reading.NARRATIVE_SWITCH, raising=False)
    else:
        monkeypatch.setenv(reading.NARRATIVE_SWITCH, raw)
    assert reading.narrative_mode() == mode


@pytest.mark.parametrize(("raw", "cap"), [("", "0"), ("abc", "0"), ("-5", "0"), ("NaN", "0"), ("Infinity", "0"),
                                          ("30", "30"), (" 12.5 ", "12.5")])
def test_the_readers_budget_is_zero_unless_the_owner_wrote_an_amount(raw: str, cap: str) -> None:
    assert user_budget.monthly_budget({user_budget.BUDGET_VAR: raw}) == Decimal(cap)
    assert user_budget.monthly_budget({}) == Decimal(0)


def test_the_owner_hears_of_each_threshold_once_with_amounts_and_nothing_of_a_reader() -> None:
    import datetime as dt

    def b(spent: str, monthly: str = "30") -> Budget:
        return Budget("NORMAL", Decimal(0), Decimal(spent), Decimal(1), Decimal(monthly), day=dt.date(2026, 11, 3))

    assert user_budget.alert_drafts(b("10")) == []
    half = user_budget.alert_drafts(b("16"))
    assert [d.dedup_key for d in half] == ["ai_user_budget:2026-11:50"] and half[0].kind == "ai_user_budget"
    assert "US$ 16,00 de US$ 30,00" in half[0].body and "Intelligence" in half[0].body
    full = user_budget.alert_drafts(b("30"))
    assert [d.payload["threshold"] for d in full] == [50, 70, 85, 95, 100]
    assert "se detuvo" in full[-1].body
    assert user_budget.alert_drafts(b("5", monthly="0")) == [], "no budget, no notice"


def test_the_readers_ledger_takes_every_argument_intelligences_ledger_is_given() -> None:
    """call_json records every call through the ledger it is handed, with what Intelligence's ledger takes (the IA plan's Phase 0
    added the workspace, the key, a Batch's ids and an agent's run): the readers' ledger must take all of it, or a narrative already
    paid for would end in a TypeError and its spend would go unrecorded."""
    import inspect

    from fbi.ai.usage import UsageLedger

    theirs = inspect.signature(UsageLedger.record).parameters
    ours = inspect.signature(user_budget.UserUsageLedger.record).parameters
    assert list(ours) == list(theirs)
    assert all(ours[n].kind is theirs[n].kind and ours[n].default == theirs[n].default for n in theirs)


def test_the_worker_runs_it_every_ten_minutes_only_while_the_switch_is_not_off() -> None:
    source = Path(scheduler.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_deadline" and isinstance(n.args[0], ast.Constant) and n.args[0].value == "user_narrative"]
    assert len(calls) == 1 and isinstance(calls[0].args[1], ast.Constant) and calls[0].args[1].value == un.JOB_TYPE
    assert un.JOB_TYPE in scheduler.WORKER_JOB_TYPES and un.JOB_TYPE in JOB_TIMEOUTS
    assert scheduler.USER_NARRATIVE_MINUTES == 10
    assert un.RUN_SECONDS < scheduler.USER_NARRATIVE_MINUTES * 60 < timeout_for(un.JOB_TYPE).total_seconds()
    assert 'if narrative_mode() != "off":' in source, "nothing runs, nothing is spent, while the switch is off"


def test_the_checks_never_read_a_flag_the_model_could_set() -> None:
    """The verdict depends on the input and the answer only: a copy of the answer validates the same."""
    data = good()
    a, b = verdict(data), verdict(copy.deepcopy(data))
    assert a.ok and b.ok and a.content == b.content


def test_a_quantity_is_the_same_whether_it_is_a_digit_or_a_word_in_either_language() -> None:
    """IA-024: «2 empates» and «two draws», «once meses» and «eleven months» say the same; a different number still does not."""
    key = un._numbers_key
    assert key("Hubo 2 empates y tres victorias hace once meses.", "es") == key("There were two draws and 3 wins eleven months ago.", "en")
    assert key("Ganó 2-1 en casa.", "es") == key("It won 2-1 at home.", "en")
    assert key("Empató 0-0 ante el Brighton.", "es") == key("A goalless draw against Brighton.", "en"), "zero and one are not compared"
    assert key("Una victoria en seis partidos.", "es") == key("One win in its last 6 matches.", "en")
    assert key("Lleva diecisiete partidos.", "es") == key("It has played 17 matches.", "en")
    assert key("Lleva cuatro partidos.", "es") != key("It has played five matches.", "en"), "a different quantity is still refused"
    assert key("Ganó 3-1 en casa.", "es") != key("It won 3-2 at home.", "en"), "a different score is still refused"
    assert key("Suma 1,8 puntos por partido.", "es") != key("It takes 1.9 points per game.", "en"), "a decimal is still compared"
    assert key("Suma 1,8 puntos por partido.", "es") == key("It takes 1.8 points per game.", "en")


def test_twice_and_what_only_looks_like_a_number_compare_as_they_mean_ia032() -> None:
    """IA-032: «dos veces» is «twice»; «ninguno de los dos» has no two in English and «el once» is the starting XI. «ambos» and «both» are not
    counted (counting them refused approved chronicles that say the same thing), so «los dos» beside «both» is still refused: the comparison errs
    on the side of refusing. A different quantity is still refused, and each language's own figures are still checked against the facts."""
    key = un._numbers_key
    assert key("Los dos equipos se han enfrentado dos veces.", "es") == key("The two sides have met twice.", "en")
    assert key("Se han enfrentado dos veces.", "es") == key("They have met twice.", "en")
    assert key("No hay posición en la tabla para ninguno de los dos.", "es") == key("No table position is given for either side.", "en")
    assert key("Ninguna de las dos aparece en la lista.", "es") == key("Neither of the two is on the list.", "en")
    assert key("Leyton Orient podría repetir el once que goleó.", "es") == key("Leyton Orient could keep the side that won big.", "en")
    assert key("Su once inicial no se conoce.", "es") == key("Its starting XI is not known.", "en")
    assert key("Es el único precedente entre ambos.", "es") == key("It is the only meeting between them.", "en"), "«ambos» is not a count"
    assert key("Ambos equipos pelean por el ascenso.", "es") == key("Both teams are chasing promotion.", "en")
    assert key("Lleva once partidos sin perder.", "es") == key("It is eleven matches unbeaten.", "en"), "eleven of something is still eleven"
    assert key("Notts County ganó los dos partidos.", "es") != key("Notts County have won both matches.", "en"), "still refused: errs on refusing"
    assert key("Ganó los dos partidos.", "es") != key("It won all three matches.", "en"), "a different quantity is still refused"
