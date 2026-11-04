"""The readers' narrative (plan UX, A11): what the server checks before a reader may read a sentence the AI wrote - pure, no
database, no model.

A good narrative passes whole. Each check is shown failing on its own: a reference not given, a number the cited facts do not
hold (small ones too, and a share never stands for a whole number), certainty and betting words in either language, the system's
codes, a DESCRIPTIVE factor made a cause or put in the conclusion, a rumour outside the risks or not called one, a probable item
told as a fact, an uncalibrated probability without its label, the forecast's other side, and a Spanish and an English that do
not say the same. A translation is kept or dropped on its own."""

from __future__ import annotations

import ast
import copy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from apps.worker import scheduler

from fbi.ai import user_budget
from fbi.ai.usage import Budget
from fbi.api.services import reading
from fbi.narrative import job as un
from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

MU, LIV = "Manchester United", "Liverpool"


def F(ref: str, section: str, code: str, **params: Any) -> un.Fact:  # noqa: N802 - a constructor
    return un.Fact(ref, section, code, params)


FACTS = (
    F("P:fixture", "summary", "match_intro", competition="Premier League", round="Regular Season - 9", neutral=None),
    F("P:forecast.1X2", "summary", "expected_result", outcome="home", team=MU, probability=0.5, calibrated=False),
    F("P:stakes.home", "context", "stakes_zone", side="home", team=MU, rank=4, zone="europe"),
    F("P:stakes.away", "context", "stakes_pressure", side="away", team=LIV, pressure="title"),
    F("P:scenarios.table", "context", "table_after", result="home_win", home=MU, home_points=20, home_best=2, home_worst=4,
      away=LIV, away_points=22, away_best=1, away_worst=2),
    F("P:schedule.home", "context", "rest_days", side="home", team=MU, days=3.0, matches_14d=4, at_most=False),
    F("P:form.home", "data", "form", side="home", team=MU, sequence="WWDLW", n=5, ppg=2.0, goals_for=1.8, goals_against=1.0),
    F("P:form.away", "data", "form", side="away", team=LIV, sequence="WWWWD", n=5, ppg=2.6, goals_for=2.4, goals_against=0.6),
    F("P:h2h", "data", "h2h", n=8, n_effective=2.4, home=MU, home_wins=2, draws=3, away=LIV, away_wins=3),
    F("P:absences.home", "data", "key_absences", side="home", team=MU, count=1, players=["Lisandro Martínez"]),
    F("P:market.1X2", "market", "market_favourite", outcome="away", team=LIV, probability=0.42, bookmakers=11),
    F("P:market.1X2", "market", "market_moved", outcome="home", team=MU, opening=0.352, now=0.318),
    F("P:lineups", "risks", "lineups_unconfirmed"),
    F("P:evidence", "risks", "rumours", count=1),
    F("P:forecast", "risks", "uncalibrated", markets=["1X2"]),
    F("P:forecast.1X2", "conclusion", "likely", market="1X2", outcome="home", team=MU, line=None, probability=0.5,
      calibrated=False),
    F("P:forecast.OU", "conclusion", "likely", market="OU", outcome="over", team=None, line="2.5", probability=0.585,
      calibrated=True),
)

INJURY = "Lisandro Martínez es baja por lesión para este partido."
DOUBT = "Según Marca, Mohamed Salah está en duda por unas molestias en el tobillo."
RUMOUR = "Se dice que el portero titular no viajó con el equipo."
TITLE = "Lisandro Martínez se pierde el partido ante el Liverpool por lesión"


def news(i: int, status: str, claim: str, *, translated: bool = False, title: str | None = None) -> un.NewsItem:
    return un.NewsItem(i, f"E:{i}", "injury", status, "home", claim, "media", f"{i:064x}", title, translated)


def inp(**changes: Any) -> un.NarrativeInput:
    base: dict[str, Any] = {
        "fixture_id": 7, "packet_id": 70, "data_at": __import__("datetime").datetime(2026, 10, 26, 18, 0),
        "reading_hash": "b" * 64, "home": MU, "away": LIV, "competition": "Premier League", "facts": FACTS,
        "news": (news(101, "CONFIRMED", INJURY, title=TITLE), news(102, "PROBABLE", DOUBT), news(103, "RUMOR", RUMOUR)),
        "sections": ("summary", "context", "data", "market", "risks", "conclusion")}
    base.update(changes)
    return un.NarrativeInput(**base)


def S(text: str, *refs: str) -> dict[str, Any]:  # noqa: N802 - a constructor
    return {"text": text, "refs": list(refs)}


def good() -> dict[str, Any]:
    return {
        "es": {
            "summary": [S("Partido de la Premier League, jornada 9.", "P:fixture"),
                        S("PrediGol ve como más probable la victoria del Manchester United, con un 50 % sin calibrar.",
                          "P:forecast.1X2")],
            "context": [S("Manchester United es 4.º y está en la zona de plazas internacionales.", "P:stakes.home"),
                        S("Liverpool pelea el título.", "P:stakes.away"),
                        S("Si gana el local, Manchester United sumaría 20 puntos y Liverpool 22.", "P:scenarios.table")],
            "data": [S("Manchester United suma 2,0 puntos por partido en sus últimos 5 y Liverpool 2,6.", "P:form.home",
                       "P:form.away"),
                     S("En el cara a cara hubo 8 partidos: 2 victorias de Manchester United, 3 empates y 3 de Liverpool.",
                       "P:h2h"),
                     S("Lisandro Martínez es baja importante del Manchester United.", "P:absences.home", "E:101")],
            "market": [S("El mercado da un 42 % a la victoria de Liverpool, según 11 casas.", "P:market.1X2"),
                       S("Desde la apertura, la victoria del Manchester United bajó del 35,2 % al 31,8 %.", "P:market.1X2")],
            "risks": [S("Las alineaciones aún no están confirmadas.", "P:lineups"),
                      S("Hay un rumor sin confirmar sobre el portero titular del Manchester United.", "P:evidence", "E:103"),
                      S("Según Marca, Mohamed Salah está en duda.", "E:102")],
            "conclusion": [S("Lo más probable según PrediGol es la victoria del Manchester United (50 %, sin calibrar).",
                             "P:forecast.1X2"),
                           S("En goles, lo más probable es que haya más de 2,5 (58,5 %).", "P:forecast.OU")],
        },
        "en": {
            "summary": [S("A Premier League match, round 9.", "P:fixture"),
                        S("PrediGol sees a Manchester United win as the most likely result, at 50 % uncalibrated.",
                          "P:forecast.1X2")],
            "context": [S("Manchester United are 4th, in the international places.", "P:stakes.home"),
                        S("Liverpool are fighting for the title.", "P:stakes.away"),
                        S("If the home side wins, Manchester United would have 20 points and Liverpool 22.",
                          "P:scenarios.table")],
            "data": [S("Manchester United average 2.0 points per match over their last 5, Liverpool 2.6.", "P:form.home",
                       "P:form.away"),
                     S("The head-to-head has 8 matches: 2 Manchester United wins, 3 draws and 3 for Liverpool.", "P:h2h"),
                     S("Lisandro Martínez is an important absence for Manchester United.", "P:absences.home", "E:101")],
            "market": [S("The market gives a Liverpool win 42 %, from 11 bookmakers.", "P:market.1X2"),
                       S("Since the opening, a Manchester United win fell from 35.2 % to 31.8 %.", "P:market.1X2")],
            "risks": [S("The line-ups are not confirmed yet.", "P:lineups"),
                      S("There is an unconfirmed rumour about Manchester United's first-choice goalkeeper.", "P:evidence",
                        "E:103"),
                      S("According to Marca, Mohamed Salah is doubtful.", "E:102")],
            "conclusion": [S("PrediGol's most likely outcome is a Manchester United win (50 %, uncalibrated).",
                             "P:forecast.1X2"),
                           S("For goals, the most likely is over 2.5 (58.5 %).", "P:forecast.OU")],
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


def test_a_good_narrative_passes_whole_with_its_translations() -> None:
    v = verdict(good())
    assert v.ok, [p.as_json() for p in v.problems]
    assert v.content is not None and list(v.content) == ["es", "en"]
    assert [s["key"] for s in v.content["es"]] == list(un.SECTIONS)
    assert v.content["en"][5]["sentences"][0]["refs"] == ["P:forecast.1X2"]
    assert {t.evidence_id for t in v.translations} == {101, 102, 103} and not v.dropped
    t = next(t for t in v.translations if t.evidence_id == 101)
    assert t.headline_es == "Lisandro Martínez, baja por lesión" and t.claim_en is not None


@pytest.mark.parametrize(("lang", "section", "i", "text", "refs", "why"), [
    ("es", "context", 0, "Manchester United es 4.º en la tabla.", ["P:stakes.middle"], "references not given"),
    ("es", "data", 0, "Manchester United suma 2,0 puntos por partido en sus últimos 6 y Liverpool 2,6.", None,
     "numbers not in what it cites: 6"),
    ("es", "data", 1, "En el cara a cara hubo 8 partidos: 4 victorias de Manchester United.", None,
     "numbers not in what it cites: 4"),
    ("es", "market", 0, "El mercado da 1 opción clara a la victoria de Liverpool.", None, "numbers not in what it cites: 1"),
    ("es", "data", 0, "Manchester United suma cuatro victorias seguidas.", None, "numbers not in what it cites: cuatro"),
    ("es", "summary", 1, "La victoria del Manchester United es segura.", None, "forbidden phrase"),
    ("es", "summary", 1, "Una victoria garantizada del Manchester United, con un 50 % sin calibrar.", None,
     "forbidden phrase"),
    ("es", "market", 0, "Hay valor en la victoria de Liverpool (42 %).", None, "forbidden phrase"),
    ("es", "market", 0, "Conviene una apuesta a Liverpool (42 %).", None, "forbidden phrase"),
    ("en", "summary", 1, "A Manchester United win is a sure thing at 50 % uncalibrated.", None, "forbidden phrase"),
    ("en", "market", 0, "Liverpool look like value at 42 %, from 11 bookmakers.", None, "forbidden phrase"),
    ("en", "market", 0, "Bet on Liverpool at 42 %, from 11 bookmakers.", None, "forbidden phrase"),
    ("en", "summary", 1, "Manchester United will win, at 50 % uncalibrated.", None, "forbidden phrase"),
    ("es", "market", 0, "El 1X2 da un 42 % a Liverpool según 11 casas.", None, "only the system says"),
    ("es", "risks", 0, "Las alineaciones (P:lineups) no están confirmadas.", None, "only the system says"),
    ("es", "context", 2, "Con home_win, Manchester United sumaría 20 puntos y Liverpool 22.", None, "only the system says"),
    ("es", "risks", 2, "Según Marca (https://marca.com/1), Salah está en duda.", None, "only the system says"),
    ("es", "context", 2, "Manchester United sumaría 20 puntos y Liverpool 22, porque la tabla lo favorece.", None,
     "DESCRIPTIVE factor, a cause"),
    ("en", "data", 1, "The head-to-head has 8 matches: 2 Manchester United wins, 3 draws and 3 for Liverpool, so Liverpool "
                      "is favoured because of it.", None, "DESCRIPTIVE factor, a cause"),
    ("es", "conclusion", 0, "Lo más probable es la victoria del Manchester United tras 2 victorias en 8 partidos.",
     ["P:forecast.1X2", "P:h2h"], "the conclusion rests on h2h"),
    ("es", "conclusion", 0, "Lo más probable es un partido cerrado.", ["P:lineups"], "must rest on PrediGol's forecast"),
    ("es", "data", 2, "Hay un rumor sin confirmar sobre el portero titular.", ["E:103"], "outside the risks"),
    ("es", "risks", 1, "El portero titular no viajó con el equipo.", None, "not called one"),
    ("es", "risks", 2, "Mohamed Salah no jugará.", None, "told as a fact"),
    ("es", "conclusion", 0, "Lo más probable según PrediGol es la victoria del Manchester United (50 %).", None,
     "uncalibrated probability without its label"),
    ("es", "conclusion", 0, "Lo más probable según PrediGol es la victoria de Liverpool (50 %, sin calibrar).", None,
     "names Liverpool where PrediGol's forecast says Manchester United"),
    ("es", "conclusion", 1, "En goles, lo más probable es que haya menos de 2,5 (58,5 %).", None, "the other side"),
    ("es", "risks", 0, "Corto.", None, "length"),
])
def test_each_check_refuses_on_its_own(lang: str, section: str, i: int, text: str, refs: list[str] | None, why: str) -> None:
    data = good()
    set_text(data, lang, section, i, text, refs)
    other = "en" if lang == "es" else "es"
    if refs is not None:  # the other language cites the same, so only the check under test speaks
        data[other][section][i]["refs"] = refs
    v = verdict(data)
    assert not v.ok and v.content is None
    reasons = [p.why for p in v.problems if p.where.startswith(f"{lang}.{section}[{i}]")]
    assert any(why in r for r in reasons), [p.as_json() for p in v.problems]


def test_a_name_with_digits_is_a_name_and_a_share_is_written_as_its_percentage() -> None:
    schalke = inp(home="Schalke 04", facts=tuple(
        un.Fact(f.ref, f.section, f.code, {k: ("Schalke 04" if v == MU else v) for k, v in f.params.items()}) for f in FACTS))
    s = un.SentenceOut(text="Schalke 04 es 4.º y está en la zona de plazas internacionales.", refs=["P:stakes.home"])
    assert un.check_sentence(s, lang="es", section="context", inp=schalke) is None
    pct = un.SentenceOut(text="El mercado da un 42,0 % a la victoria de Liverpool.", refs=["P:market.1X2"])
    assert un.check_sentence(pct, lang="es", section="market", inp=inp()) is None
    share = un.SentenceOut(text="El mercado da 0,42 a la victoria de Liverpool.", refs=["P:market.1X2"])
    assert un.check_sentence(share, lang="es", section="market", inp=inp()) is None, "a share written with its decimals"
    assert un.stated(un.Figure("1", 1.0, 0), {0.54}) is False, "1 never stands for 0.54"
    assert un.stated(un.Figure("4", 4.0, 0), {3.5}) is True, "3.5 rounded"
    assert un.stated(un.Figure("-2", 2.0, 0), {2.0}) is True


def test_a_block_above_a_fact_covers_it_and_a_fact_below_one_is_not_given() -> None:
    above = un.SentenceOut(text="Manchester United suma 2,0 puntos por partido y Liverpool 2,6.", refs=["P:form"])
    assert un.check_sentence(above, lang="es", section="data", inp=inp()) is None
    below = un.SentenceOut(text="Manchester United suma 2,0 puntos por partido.", refs=["P:form.home.ppg"])
    assert "references not given" in (un.check_sentence(below, lang="es", section="data", inp=inp()) or "")


def test_the_spanish_and_the_english_say_the_same() -> None:
    fewer = good()
    fewer["en"]["risks"].pop()
    assert any("3 sentences in Spanish, 2 in English" in p.why for p in verdict(fewer).problems)
    refs = good()
    refs["en"]["data"][2]["refs"] = ["P:absences.home"]
    assert any("other references" in p.why for p in verdict(refs).problems)
    numbers = good()
    numbers["en"]["market"][0]["text"] = "The market gives a Liverpool win 42 %, from 11 bookmakers, or 0.42."
    assert any("other numbers" in p.why for p in verdict(numbers).problems)


def test_the_sections_follow_the_reading() -> None:
    no_market = tuple(f for f in FACTS if f.section != "market")
    sections = ("summary", "context", "data", "risks", "conclusion")
    data = good()
    v = verdict(data, facts=no_market, sections=sections)
    assert any(p.why == "a section the reading does not have" for p in v.problems)
    for lang in ("es", "en"):
        data[lang]["market"] = []
    assert verdict(data, facts=no_market, sections=sections).ok
    empty = good()
    empty["es"]["risks"] = []
    empty["en"]["risks"] = []
    assert any(p.where == "es.risks" and p.why == "empty" for p in verdict(empty).problems), "risks are never empty"
    many = good()
    for lang in ("es", "en"):
        many[lang]["summary"] = many[lang]["summary"] * 2
    assert any("at most 3" in p.why for p in verdict(many).problems)


def test_a_translation_is_kept_or_dropped_on_its_own() -> None:
    data = good()
    data["news"][0]["claim_en"] = "Lisandro Martínez is out for 3 weeks."  # a number the claim does not hold
    data["news"][1]["headline_en"] = "Lisandro Martínez se pierde el partido ante el Liverpool por lesión"  # the source's title? no
    data["news"][2]["claim_en"] = "Se dice que el portero titular no viajó con el equipo."  # the Spanish, not a translation
    data["news"].append({"id": 999, "headline_es": "Otra", "headline_en": "Another", "claim_en": "Another item."})
    v = verdict(data, news=(news(101, "CONFIRMED", INJURY, title=TITLE), news(102, "PROBABLE", DOUBT, title=TITLE),
                            news(103, "RUMOR", RUMOUR)))
    assert v.ok, "the narrative does not depend on its translations"
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


def test_the_input_is_the_facts_and_the_news_and_its_hash_ignores_what_is_left_to_translate() -> None:
    body = inp().body()
    assert set(body) == {"match", "sections", "facts", "news", "translate", "note"}
    assert body["facts"][0] == {"ref": "P:fixture", "section": "summary", "code": "match_intro",
                                "params": {"competition": "Premier League", "round": "Regular Season - 9", "neutral": None}}
    assert [n["ref"] for n in body["news"]] == ["E:101", "E:102", "E:103"] and len(body["translate"]) == 3
    done = inp(news=(news(101, "CONFIRMED", INJURY, translated=True), news(102, "PROBABLE", DOUBT, translated=True),
                     news(103, "RUMOR", RUMOUR, translated=True)))
    assert done.body()["translate"] == [] and done.hash == inp().hash, "a kept translation does not make the reading new"
    assert inp(packet_id=71).hash != inp().hash, "another packet is another input"
    assert un.fact_ref("packet:form.home") == "P:form.home" and un.fact_ref("forecast:1X2") == "P:forecast.1X2"
    assert un.fact_ref("forecast") == "P:forecast" and un.fact_ref("packet") == "P:packet"


def reading_codes() -> set[str]:
    tree = ast.parse(Path(reading.__file__).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add"
                and len(node.args) >= 2 and all(isinstance(a, ast.Constant) for a in node.args[:2])):
            found.add(str(node.args[1].value))  # type: ignore[attr-defined]
    return found


def test_the_prompt_explains_every_code_the_reading_writes_and_the_schema_has_no_bound() -> None:
    codes = reading_codes()
    assert len(codes) > 35, codes
    assert codes <= set(un.GLOSSARY), sorted(codes - set(un.GLOSSARY))
    for code in un.GLOSSARY:
        assert f"- {code}: " in un.SYSTEM

    def keys(x: Any) -> set[str]:
        if isinstance(x, dict):
            return set(x) | {k for v in x.values() for k in keys(v)}
        if isinstance(x, list):
            return {k for v in x for k in keys(v)}
        return set()

    assert not keys(un.SCHEMA) & {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"}
    assert un.VERSION == reading.NARRATIVE_VERSION == "user-narrative-v1"


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
