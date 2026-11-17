"""The dynamic selector of sources (IA-086, AD-C04), against the pinned directory v2 of the image.

The contract test is the example of the plan's card (Atlético Bucaramanga - Atlético Nacional): the sources it returns for each type of
claim, their authority and what may be done with them today. Then twenty matches of other leagues, the properties (an AI-reserved source
never goes to extraction, a rumour never comes as a fact from a source without authority), the budget (no Exa at 95 % of the envelope)
and the names (a homonym is not the team)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.ai import source_policy as sp
from fbi.ai import source_registry as registry
from fbi.ai import source_select as ss

AT = datetime(2026, 11, 16, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def policy() -> sp.SourcePolicy:
    loaded = sp.load(None)
    assert loaded is not None and loaded.origin == "bundled" and not loaded.signed
    return loaded


def signed_policy(policy: sp.SourcePolicy, ids: list[str]) -> sp.SourcePolicy:
    return sp.SourcePolicy(list(policy.by_domain.values()), list(policy.rules.values()), ids, directory_version=policy.directory_version,
                           exclusion_version=policy.exclusion_version, origin="test")


def everything_authorised(policy: sp.SourcePolicy) -> sp.SourcePolicy:
    """The worst case for the properties: every source of the directory authorised AND signed."""
    from dataclasses import replace

    sources = [replace(s, state="verificada_autorizada", automated_access="permitido_robots") for s in policy.by_domain.values()]
    return sp.SourcePolicy(sources, list(policy.rules.values()), [s.source_id for s in sources],
                           directory_version=policy.directory_version, exclusion_version=policy.exclusion_version, origin="test")


def match(home: tuple[str, str, str | None], away: tuple[str, str, str | None], competition: str, country: str | None, *,
          national: bool = False, hours: float = 30) -> ss.MatchContext:
    return ss.MatchContext(None, AT + timedelta(hours=hours), competition, country,
                           ss.Team(1, home[0], (), home[1], home[2], national), ss.Team(2, away[0], (), away[1], away[2], national))


BUC_NAC = match(("Bucaramanga", "Colombia", "Bucaramanga"), ("Atletico Nacional", "Colombia", "Medellín"), "Primera A", "Colombia")


def domains(sel: ss.Selection, **where: object) -> set[str]:
    return {p.domain for p in sel.picks if all(getattr(p, k) == v for k, v in where.items())}


def pick(sel: ss.Selection, domain: str) -> ss.Pick:
    found = [p for p in sel.picks if p.domain == domain]
    assert found, f"{domain} not chosen: {sorted(p.domain for p in sel.picks)}"
    return found[0]


# ── the contract: the example of the card ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("claim", ["alineaciones", "convocatorias", "lesiones", "declaraciones"])
def test_the_clubs_confirm_what_is_their_own_and_today_are_only_a_link(policy: sp.SourcePolicy, claim: str) -> None:
    sel = ss.select(BUC_NAC, claim, at=AT, policy=policy)
    clubs = domains(sel, role="club_oficial")
    assert clubs == {"atleticobucaramanga.com.co", "atlnacional.com.co"}
    for d, side in (("atleticobucaramanga.com.co", "home"), ("atlnacional.com.co", "away")):
        p = pick(sel, d)
        assert (p.authority, p.side, p.as_fact) == ("confirma", side, True)
        assert (p.state, p.via, p.would_via, p.may_extract) == ("verificada_pendiente_derechos", "link", "official", False)
    assert sel.picks[0].role == "club_oficial", "a club confirms its own line-up: it comes first"


@pytest.mark.parametrize("claim", ["sanciones", "calendario", "arbitraje", "reglamento"])
def test_dimayor_confirms_sanctions_calendar_referees_and_rules_with_its_verified_rss(policy: sp.SourcePolicy, claim: str) -> None:
    sel = ss.select(BUC_NAC, claim, at=AT, policy=policy)
    dimayor = pick(sel, "dimayor.com.co")
    assert (dimayor.role, dimayor.authority, dimayor.via, dimayor.would_via) == ("liga", "confirma", "link", "rss")
    assert dimayor.feed == "https://dimayor.com.co/feed/"
    assert dimayor.state == "verificada_pendiente_derechos" and not dimayor.may_fetch and not dimayor.may_extract
    assert "difutbol.org" not in domains(sel), "the amateur division is not the league of Primera A"
    if claim in ("sanciones", "reglamento"):
        assert domains(sel) == {"dimayor.com.co"}, "only the organiser has authority: the press never confirms a sanction alone"


def test_the_press_of_santander_antioquia_and_the_nation_informs(policy: sp.SourcePolicy) -> None:
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=policy)
    assert {"vanguardia.com", "elfrente.com.co", "canaltro.com"} <= domains(sel, role="regional", side="home")
    assert {"elcolombiano.com", "telemedellin.tv", "minuto30.com", "teleantioquia.co"} <= domains(sel, role="regional", side="away")
    assert {"futbolred.com", "elespectador.com", "semana.com", "bluradio.com", "deportesrcn.com", "winsports.co"} <= domains(
        sel, role="nacional")
    assert {"eltiempo.com", "noticiascaracol.com", "espn.com.co"} <= domains(sel, role="nacional")
    for d in ("vanguardia.com", "futbolred.com", "semana.com"):
        p = pick(sel, d)
        assert (p.authority, p.via, p.store, p.publish) == ("informa", "link", "link", "link")
    assert pick(sel, "elespectador.com").would_via == "sitemap"
    assert pick(sel, "deportesrcn.com").would_via == "sitemap"
    assert "mx-vanguardia" not in {p.source_id for p in sel.picks} and "vanguardia.com.mx" not in domains(sel)


def test_ai_reserved_media_are_a_link_for_ever_and_teleantioquia_is_nothing(policy: sp.SourcePolicy) -> None:
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=signed_policy(policy, ["eltiempo", "golcaracol", "co-espn-colombia"]))
    for d in ("eltiempo.com", "noticiascaracol.com", "espn.com.co", "minuto30.com"):
        p = pick(sel, d)
        assert (p.state, p.via, p.would_via, p.reason, p.may_extract) == ("solo_referencia", "link", "link", "ai_reserved", False)
    tele = pick(sel, "teleantioquia.co")
    assert (tele.state, tele.via, tele.would_via, tele.priority) == ("bloqueada", "none", "none", 0.0)


def test_el_colombiano_counts_with_the_stricter_reading_of_the_contradiction(policy: sp.SourcePolicy) -> None:
    every = everything_authorised(policy)
    p = pick(ss.select(BUC_NAC, "lesiones", at=AT, policy=every), "elcolombiano.com")
    assert (p.via, p.would_via, p.reason, p.may_extract) == ("link", "link", "stricter_reading", False)
    assert {"elcolombiano.com"} <= set(ss.STRICTER_READINGS)


def test_today_nothing_of_that_match_can_be_read_or_extracted(policy: sp.SourcePolicy) -> None:
    for claim in ss.FACT_CLAIMS:
        c = ss.select(BUC_NAC, claim, at=AT, policy=policy).counts()
        assert (c["readable_now"], c["extractable_now"], c["exa_queries"]) == (0, 0, 0), claim


def test_rumours_come_from_any_of_them_and_none_counts_as_a_fact(policy: sp.SourcePolicy) -> None:
    sel = ss.select(BUC_NAC, "rumores", at=AT, policy=policy)
    assert sel.picks and not any(p.as_fact for p in sel.picks)
    assert {"atleticobucaramanga.com.co", "dimayor.com.co", "vanguardia.com"} <= domains(sel)
    assert pick(sel, "atleticobucaramanga.com.co").authority == "sin_autoridad"
    assert pick(sel, "vanguardia.com").authority == "solo_rumor"


def test_a_club_has_no_authority_on_the_other_side(policy: sp.SourcePolicy) -> None:
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=policy, entity_side="away")
    assert "atleticobucaramanga.com.co" not in domains(sel), "lesiones: confirma (solo del propio club)"
    assert "atlnacional.com.co" in domains(sel)


def test_explain_says_in_spanish_why_each_source_is_there(policy: sp.SourcePolicy) -> None:
    sel = ss.select(BUC_NAC, "sanciones", at=AT, policy=policy)
    lines = ss.explain(sel, BUC_NAC)
    assert len(lines) == len(sel.picks) and "liga organizadora" in lines[0] and "habría leído" in lines[0] and "su RSS" in lines[0]
    assert ss.explain(ss.select(match(("X", "Colombia", None), ("Y", "Colombia", None), "Z", None), "sanciones", at=AT,
                                policy=policy))[0].startswith("Ninguna fuente")


# ── twenty matches of other leagues ────────────────────────────────────────────────────────────────────────────────────────

OTHERS = [
    (("Arsenal", "England", "London"), ("Chelsea", "England", "London"), "Premier League", "England",
     {"arsenal.com", "chelseafc.com"}, {"premierleague.com"}),
    (("Real Madrid", "Spain", "Madrid"), ("Barcelona", "Spain", "Barcelona"), "La Liga", "Spain",
     {"realmadrid.com", "fcbarcelona.com"}, {"laliga.com"}),
    (("Inter", "Italy", "Milano"), ("Juventus", "Italy", "Torino"), "Serie A", "Italy", {"juventus.com"}, {"legaseriea.it"}),
    (("Bayern München", "Germany", "München"), ("Borussia Dortmund", "Germany", "Dortmund"), "Bundesliga", "Germany",
     {"fcbayern.com", "bvb.de"}, {"bundesliga.com", "dfl.de"}),
    (("Paris Saint Germain", "France", "Paris"), ("Marseille", "France", "Marseille"), "Ligue 1", "France", {"psg.fr"},
     {"lfp.fr", "ligue1.com"}),
    (("Club America", "Mexico", "Ciudad de México"), ("Guadalajara Chivas", "Mexico", "Guadalajara"), "Liga MX", "Mexico",
     {"clubamerica.com.mx"}, {"ligamx.net"}),
    (("Flamengo", "Brazil", "Rio de Janeiro"), ("Palmeiras", "Brazil", "São Paulo"), "Serie A", "Brazil",
     {"flamengo.com.br", "palmeiras.com.br"}, {"cbf.com.br", "stjd.org.br"}),
    (("River Plate", "Argentina", "Buenos Aires"), ("Boca Juniors", "Argentina", "Buenos Aires"), "Liga Profesional Argentina",
     "Argentina", {"cariverplate.com.ar", "bocajuniors.com.ar"}, {"ligaprofesional.ar"}),
    (("Kashima", "Japan", "Kashima"), ("Urawa", "Japan", "Saitama"), "J1 League", "Japan", set(), {"data.j-league.or.jp"}),
    (("Ulsan Hyundai FC", "South-Korea", "Ulsan"), ("Jeonbuk Motors", "South-Korea", "Jeonju"), "K League 1", "South-Korea", set(),
     {"kleague.com"}),
    (("Inter Miami", "USA", "Fort Lauderdale"), ("Los Angeles Galaxy", "USA", "Carson"), "Major League Soccer", "USA",
     {"intermiamicf.com"}, {"mlssoccer.com"}),
    (("Ajax", "Netherlands", "Amsterdam"), ("PSV Eindhoven", "Netherlands", "Eindhoven"), "Eredivisie", "Netherlands", {"ajax.nl"},
     {"eredivisie.nl"}),
    (("Benfica", "Portugal", "Lisboa"), ("FC Porto", "Portugal", "Porto"), "Primeira Liga", "Portugal", {"fcporto.pt"},
     {"ligaportugal.pt"}),
    (("Galatasaray", "Turkey", "İstanbul"), ("Fenerbahçe", "Turkey", "İstanbul"), "Süper Lig", "Turkey",
     {"galatasaray.org", "fenerbahce.org"}, {"tff.org"}),
    (("Club Brugge KV", "Belgium", "Brugge"), ("Anderlecht", "Belgium", "Bruxelles"), "Jupiler Pro League", "Belgium",
     {"clubbrugge.be"}, {"proleague.be"}),
    (("Colo Colo", "Chile", "Santiago"), ("Universidad de Chile", "Chile", "Santiago"), "Primera Division", "Chile", {"udechile.cl"},
     {"anfp.cl"}),
    (("Barcelona SC", "Ecuador", "Guayaquil"), ("Emelec", "Ecuador", "Guayaquil"), "Liga Pro", "Ecuador",
     {"barcelonasc.com.ec", "emelec.com.ec"}, {"ligapro.ec"}),
    (("Millonarios", "Colombia", "Bogotá"), ("Independiente Santa Fe", "Colombia", "Bogotá"), "Primera A", "Colombia",
     {"millonarios.com.co", "independientesantafe.com"}, {"dimayor.com.co"}),
    (("Celtic", "Scotland", "Glasgow"), ("Rangers", "Scotland", "Glasgow"), "Premiership", "Scotland",
     {"celticfc.com", "rangers.co.uk"}, {"spfl.co.uk"}),
    (("FC Copenhagen", "Denmark", "København"), ("FC Midtjylland", "Denmark", "Herning"), "Superliga", "Denmark", {"fcm.dk"},
     {"superliga.dk"}),
]


@pytest.mark.parametrize(("home", "away", "competition", "country", "clubs", "league"), OTHERS,
                         ids=[f"{o[0][0]}-{o[1][0]}" for o in OTHERS])
def test_twenty_matches_of_other_leagues_give_their_clubs_and_their_league(policy: sp.SourcePolicy, home: tuple[str, str, str],
                                                                          away: tuple[str, str, str], competition: str, country: str,
                                                                          clubs: set[str], league: set[str]) -> None:
    ctx = match(home, away, competition, country)
    assert domains(ss.select(ctx, "alineaciones", at=AT, policy=policy), role="club_oficial") == clubs
    sanctions = ss.select(ctx, "sanciones", at=AT, policy=policy)
    assert {p.domain for p in sanctions.picks if p.role in ("liga", "federacion")} == league
    assert all(p.authority in ("confirma", "informa") for p in sanctions.picks)


def test_homonyms_of_another_country_or_city_are_not_the_team(policy: sp.SourcePolicy) -> None:
    clubs = domains(ss.select(BUC_NAC, "alineaciones", at=AT, policy=policy), role="club_oficial")
    assert not clubs & {"cdnacional.pt", "clubnacional.com.py", "nacional.uy"}
    madrid = domains(ss.select(OTHERS_CTX["Real Madrid"], "alineaciones", at=AT, policy=policy), role="club_oficial")
    assert "atleticodemadrid.com" not in madrid, "Real Madrid is not Atlético de Madrid"
    assert ss.same_club("Atlético Bucaramanga", "Bucaramanga") and ss.same_club("Independiente Medellín (DIM)", "Independiente Medellin")
    assert not ss.same_club("América de Cali", "Deportivo Cali") and not ss.same_club("Manchester City", "Manchester United")
    assert ss.same_club("Luton", "Luton Town FC") and not ss.same_club("Bristol City", "Bristol Rovers")
    assert not ss.same_club("", "") and not ss.same_club("FC", "Club")
    nowhere = match(("Atletico Nacional", "", None), ("Bucaramanga", "", None), "Primera A", "Colombia")
    assert not domains(ss.select(nowhere, "alineaciones", at=AT, policy=policy), role="club_oficial"), "no country: abstain"


OTHERS_CTX = {o[0][0]: match(o[0], o[1], o[2], o[3]) for o in OTHERS}


def test_national_teams_get_their_federations_the_confederation_and_their_press(policy: sp.SourcePolicy) -> None:
    nl = match(("Denmark", "Denmark", None), ("Norway", "Norway", None), "UEFA Nations League", "World", national=True)
    sel = ss.select(nl, "convocatorias", at=AT, policy=policy)
    assert domains(sel, role="federacion") == {"dbu.dk", "fotball.no"}
    assert {"uefa.com"} <= domains(sel, role="confederacion")
    assert not domains(sel, role="club_oficial") and not domains(sel, role="regional")
    assert pick(sel, "fotball.no").via == "none", "the Norwegian federation is blocked in the directory"
    friendly = match(("Chile", "Chile", None), ("Colombia", "Colombia", None), "Friendlies", "World", national=True)
    f = ss.select(friendly, "convocatorias", at=AT, policy=policy)
    assert domains(f, role="federacion") == {"anfp.cl", "fcf.com.co"}
    assert pick(f, "fcf.com.co").would_via == "rss"
    assert not domains(f, role="confederacion")
    us = match(("USA", "USA", None), ("Haiti", "Haiti", None), "CONCACAF Nations League", "World", national=True)
    u = ss.select(us, "convocatorias", at=AT, policy=policy)
    assert {"concacaf.com"} <= set(domains(u)) and not {"justwomenssports.com"} & set(domains(u)), "a women's medium is not a source of a men's match"


# ── properties ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

ALL_MATCHES = [BUC_NAC, *OTHERS_CTX.values(),
               match(("Denmark", "Denmark", None), ("Norway", "Norway", None), "UEFA Nations League", "World", national=True),
               match(("Chile", "Chile", None), ("Colombia", "Colombia", None), "Friendlies", "World", national=True)]


def test_property_an_ai_reserved_source_never_goes_to_extraction_even_if_everything_were_signed(policy: sp.SourcePolicy) -> None:
    every = everything_authorised(policy)
    cat = ss.bundled_catalog()
    reserved = {s.domain for s in cat.sources if s.ai_reserved} | set(ss.STRICTER_READINGS)
    seen = 0
    for ctx in ALL_MATCHES:
        for claim in (*ss.FACT_CLAIMS, "rumores"):
            for p in ss.select(ctx, claim, at=AT, policy=every, exa=ss.ExaAllowance.of(True, Decimal(1), Decimal(35))).picks:
                st = every.standing(p.domain)
                if p.domain in reserved or st.hard_reason:
                    seen += 1
                    assert p.via == "link" and p.would_via == "link" and not p.may_extract and not p.may_fetch, p
    assert seen > 50, "the property was exercised"


def test_property_a_fact_never_comes_from_a_source_without_authority(policy: sp.SourcePolicy) -> None:
    for ctx in ALL_MATCHES:
        for claim in ss.FACT_CLAIMS:
            for p in ss.select(ctx, claim, at=AT, policy=policy).picks:
                assert p.as_fact and p.authority in ("confirma", "informa"), p


def test_property_pending_sources_are_links_never_extractor_input(policy: sp.SourcePolicy) -> None:
    for ctx in ALL_MATCHES:
        for claim in ss.FACT_CLAIMS:
            for p in ss.select(ctx, claim, at=AT, policy=policy).picks:
                if p.state != "verificada_autorizada" or not p.signed:
                    assert p.via in ("link", "none") and not p.may_extract


def test_without_a_registry_nothing_may_be_read() -> None:
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=None)
    assert sel.picks and all(p.via == "none" and p.reason == "registry_unavailable" and not p.may_extract for p in sel.picks)


# ── budget and queries ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _signed_vanguardia(policy: sp.SourcePolicy) -> sp.SourcePolicy:
    from dataclasses import replace

    sources = [replace(s, state="verificada_autorizada", automated_access="permitido_robots") if s.source_id == "vanguardia" else s
               for s in policy.by_domain.values()]
    return sp.SourcePolicy(sources, list(policy.rules.values()), ["vanguardia"], directory_version="t", exclusion_version="t", origin="t")


def test_exa_is_proposed_only_for_a_signed_source_restricted_to_its_domain_and_written_by_the_server(policy: sp.SourcePolicy) -> None:
    pol = _signed_vanguardia(policy)
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=pol, exa=ss.ExaAllowance.of(True, Decimal("12.92"), Decimal(35)))
    v = pick(sel, "vanguardia.com")
    assert (v.via, v.may_extract, v.signed) == ("exa", True, True)
    assert len(sel.exa) == 1
    q = sel.exa[0]
    assert q.include_domains == ("vanguardia.com",) and q.query == "Bucaramanga lesionados bajas" and q.lang == "es"
    assert len(sel.exa) <= ss.MAX_EXA


@pytest.mark.parametrize(("spent", "allowed"), [("33.24", True), ("33.25", False), ("34.99", False), ("0", True)])
def test_the_selector_stops_proposing_exa_at_95_percent_of_the_envelope(policy: sp.SourcePolicy, spent: str, allowed: bool) -> None:
    allowance = ss.ExaAllowance.of(True, Decimal(spent), Decimal(35))
    assert allowance.allowed is (Decimal(spent) < Decimal("33.25"))
    sel = ss.select(BUC_NAC, "lesiones", at=AT, policy=_signed_vanguardia(policy), exa=allowance)
    v = pick(sel, "vanguardia.com")
    if allowance.allowed:
        assert v.via == "exa" and sel.exa
    else:
        assert v.via == "link" and v.would_via == "exa" and v.reason == "exa:cut_at_95" and not sel.exa
        assert any(n.startswith("exa_closed") for n in sel.notes)
    assert allowed is allowance.allowed
    assert not ss.ExaAllowance.of(True, Decimal(0), Decimal(0)).allowed
    assert ss.ExaAllowance.closed().allowed is False


def test_priority_follows_the_proximity_of_the_match(policy: sp.SourcePolicy) -> None:
    near = ss.select(match(("Bucaramanga", "Colombia", "Bucaramanga"), ("Atletico Nacional", "Colombia", "Medellín"), "Primera A",
                           "Colombia", hours=3), "sanciones", at=AT, policy=policy)
    far = ss.select(match(("Bucaramanga", "Colombia", "Bucaramanga"), ("Atletico Nacional", "Colombia", "Medellín"), "Primera A",
                          "Colombia", hours=100), "sanciones", at=AT, policy=policy)
    assert near.picks[0].priority > far.picks[0].priority > 0
    assert [ss.band(AT + timedelta(hours=h), AT) for h in (2, 20, 100, 400)] == ["le6h", "6_36h", "36h_7d", "none"]
    assert ss.band(None, AT) == "none"


def test_a_market_ranks_its_claims_first(policy: sp.SourcePolicy) -> None:
    base = ss.select(BUC_NAC, "arbitraje", at=AT, policy=policy).picks[0].priority
    assert ss.select(BUC_NAC, "arbitraje", at=AT, policy=policy, market="cards").picks[0].priority == base
    assert ss.select(BUC_NAC, "arbitraje", at=AT, policy=policy, market="1x2").picks[0].priority < base


def test_claim_words_of_the_code_and_unknown_ones() -> None:
    assert ss.claim_word("OUT") == "lesiones" and ss.claim_word("suspension") == "sanciones" and ss.claim_word("lesiones") == "lesiones"
    with pytest.raises(ValueError):
        ss.claim_word("apuestas")


# ── the catalogue ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_country_code_of_the_map_is_a_country_of_the_directory_and_back() -> None:
    codes = {str(s.record.get("pais_codigo") or "") for s in registry.bundled_directory().sources} - {"INT", ""}
    assert set(ss.COUNTRY_CODES.values()) == codes
    assert ss.country_code("South-Korea") == "KR" and ss.country_code("Saudi-Arabia") == "SA" and ss.country_code("World") is None


def test_the_sitemaps_are_read_from_the_notes_of_the_directory() -> None:
    by_id = ss.bundled_catalog().by_id()
    assert by_id["co-elespectador"].sitemaps == ("https://www.elespectador.com/arc/outboundfeeds/news-sitemap/?outputType=xml",)
    assert by_id["co-deportesrcn"].sitemaps == ("https://www.deportesrcn.com/sitemapnews",)
    assert by_id["liga-dimayor"].rss_url == "https://dimayor.com.co/feed/" and by_id["liga-dimayor"].route == "rss"
    assert by_id["club-co-bucaramanga"].route == "official"


def test_summarize_counts_a_day(policy: sp.SourcePolicy) -> None:
    s = ss.summarize([BUC_NAC, OTHERS_CTX["Arsenal"]], at=AT, policy=policy)
    assert s["matches"] == 2 and s["matches_with_no_source"] == 0 and s["readable_now_per_match"] == 0.0
    assert s["distinct_readable_now"] == 0 and s["distinct_readable_if_signed"] > 0 and s["exa_queries"] == 0
    assert s["per_match"][0]["roles"]["club_oficial"] == 2
