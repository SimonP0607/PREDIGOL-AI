"""The fictitious world of the examples of C-06 (IA-121) and C-07 (IA-122): stories, articles and evaluation lists built in memory and turned
into answers by the same pure functions the services use. ``tests/unit/test_news_contract_ia121.py`` holds every example under
``tests/fixtures/contracts/intelligence/C-06`` and ``C-07`` equal to what these builders give - the examples are what the server serves.

Teams, players and outlets are fictitious; every address is under ``.invalid``. Regenerate the examples after a deliberate change with
``python -m tests.unit.news_contract_world``."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fbi.api.contracts.intelligence.base import Freshness, IntelligenceContract, ItemList
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.sources import AnalysisSources, AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.stories import (
    LEVEL_EXPLANATION_ES,
    MatchStoriesPrivate,
    News,
    NewsPrivate,
    RelatedStory,
    StoryDetailPrivate,
)
from fbi.api.contracts.news import NewsSearch
from fbi.api.services import analysis_sources as c07
from fbi.api.services import news_v2 as c06
from fbi.factlinks import views
from fbi.newsdesk.reads import Bundle, Entity, Item, Story, Version

AT = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)
NORTE, SUR = 770001, 770002
J_EJEMPLO, A_EJEMPLO, L_EJEMPLO = 880009, 880010, 880020
FIXTURE = 990001
KICKOFF = AT + timedelta(hours=20)
EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence"


def story(key: str, *, level: str | None, category: str | None, at: datetime, status: str = "activa", headline: str | None = None,
          summary: str | None = None, reason: str | None = None, version: int = 3, headline_en: str | None = None,
          summary_en: str | None = None, claim_type: str = "convocatorias", country: str = "Colombia") -> Story:
    return Story(key=key, id=sum(map(ord, key)), version=version, at=at, first_seen_at=at - timedelta(hours=1), event_at=None,
                 valid_until=None, claim_type=claim_type, category=category, level=level, lang="es", country=country,
                 headline_es=headline, summary_es=summary, text_version="news-text-v1" if headline else None, status=status,
                 status_reason=reason, headline_en=headline_en, summary_en=summary_en)


def item(iid: int, key: str, name: str, url: str, *, seen: datetime, published: datetime | None, structured: bool = True,
         level: str = "summary", state: str = "verificada_autorizada", author: str | None = None) -> Item:
    return Item(id=iid, story_key=key, canonical_url=url, source_name=name, source_state=state, publish_level=level, author=author,
                published_at=published, published_day_only=False, published_structured=structured and published is not None,
                seen_at=seen)


def bundle(s: Story, items: list[Item], entities: list[Entity], publish: dict[int, str] | None = None) -> Bundle:
    return Bundle(s, items, entities, publish or {i.id: i.publish_level for i in items})


def ent(item_id: int, kind: str, eid: int, name: str | None, role: str = "protagonista", method: str = "proveedor",
        confidence: str = "1") -> Entity:
    return Entity(item_id, kind, eid, name, role, method, Decimal(confidence))


# ── the stories of the window ────────────────────────────────────────────────────────────────────────────────────────

def convocatoria() -> Bundle:
    key = "st-ej-convocatoria-norte"
    s = story(key, level="oficial", category="selecciones", at=AT - timedelta(minutes=34),
              headline="Club Ejemplo Norte cita a sus dos atacantes titulares",
              summary="La convocatoria oficial incluye a J. Ejemplo y A. Ejemplo. El club no informó bajas nuevas.",
              headline_en="Club Ejemplo Norte calls up its two first-choice forwards",
              summary_en="The official squad includes J. Ejemplo and A. Ejemplo. The club reported no new absences.")
    items = [
        item(11, key, "Club Ejemplo Norte (oficial)", "https://oficial.ejemplo.invalid/noticias/convocatoria", seen=AT - timedelta(minutes=34),
             published=AT - timedelta(minutes=40)),
        item(12, key, "Radio Ejemplo", "https://radio.ejemplo.invalid/deportes/club-norte-atacantes", seen=AT - timedelta(minutes=20),
             published=AT - timedelta(minutes=25), level="link", state="verificada_pendiente_derechos", author="R. Ejemplo"),
        item(13, key, "Diario Reservado Ejemplo", "https://reservado.ejemplo.invalid/futbol/convocatoria-club-norte",
             seen=AT - timedelta(minutes=14), published=None, level="link", state="solo_referencia"),
    ]
    entities = [ent(11, "team", NORTE, "Club Ejemplo Norte"), ent(11, "player", J_EJEMPLO, "J. Ejemplo", method="alias", confidence="0.98"),
                ent(11, "player", A_EJEMPLO, "A. Ejemplo", method="alias", confidence="0.95"),
                ent(12, "player", J_EJEMPLO, "J. Ejemplo", role="mencionado", method="alias", confidence="0.9")]
    return bundle(s, items, entities)


def sancion() -> Bundle:
    key = "st-ej-sancion-sur"
    s = story(key, level="un_medio", category="bajas_y_sanciones", at=AT - timedelta(hours=5))
    items = [item(21, key, "Radio Ejemplo", "https://radio.ejemplo.invalid/deportes/lateral-sur", seen=AT - timedelta(hours=5),
                  published=AT - timedelta(hours=5, minutes=10), structured=False, level="link", state="verificada_pendiente_derechos")]
    return bundle(s, items, [ent(21, "team", SUR, "Club Ejemplo Sur"), ent(21, "player", L_EJEMPLO, "L. Ejemplo", method="alias",
                                                                          confidence="0.92")])


def rumor() -> Bundle:
    key = "st-ej-rumor-fichaje"
    s = story(key, level="rumor", category="fichajes", at=AT - timedelta(hours=9))
    items = [item(31, key, "Portal Ejemplo", "https://portal.ejemplo.invalid/rumor-fichaje", seen=AT - timedelta(hours=9),
                  published=AT - timedelta(hours=9, minutes=5), level="link", state="verificada_pendiente_derechos")]
    return bundle(s, items, [ent(31, "team", SUR, "Club Ejemplo Sur", role="mencionado", method="alias", confidence="0.7")])


def en_moderacion() -> Bundle:
    key = "st-ej-lesion-en-cola"
    s = story(key, level="un_medio", category="bajas_y_sanciones", at=AT - timedelta(hours=2), status="en_moderacion",
              headline="Club Ejemplo Norte espera a su portero",
              summary="El club informó que su portero está en duda para el sábado.",
              reason="texto propio de una lesión: revisar que diga solo el estado, la fuente y la fecha")
    items = [item(41, key, "Club Ejemplo Norte (oficial)", "https://oficial.ejemplo.invalid/noticias/portero", seen=AT - timedelta(hours=2),
                  published=AT - timedelta(hours=2, minutes=5))]
    return bundle(s, items, [ent(41, "team", NORTE, "Club Ejemplo Norte")])


UPCOMING = {NORTE: KICKOFF, SUR: KICKOFF}


def front(*, followed: c06.Followed | None) -> NewsPrivate:
    body = c06.front_of([convocatoria(), sancion(), rumor()], [en_moderacion()], at=AT, followed=followed, upcoming=UPCOMING)
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="portada", front=body, story_status=c06.NO_DATA)


def front_empty() -> NewsPrivate:
    """Only a single outlet's story without a structured date and a rumour: no lead, nothing in «Última hora»."""
    body = c06.front_of([sancion(), rumor()], [], at=AT, followed=None, upcoming={})
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="portada", front=body, story_status=c06.NO_DATA)


def noticia() -> NewsPrivate:
    b = convocatoria()
    versions = [Version(AT - timedelta(minutes=34), None), Version(AT - timedelta(minutes=30), "oficial"),
                Version(AT - timedelta(minutes=10), "oficial")]
    fields = c06.card_fields(b, AT)
    uses = [views.ItemUse(11, FIXTURE, KICKOFF, "E2", 1, AT - timedelta(minutes=12), "contexto", "J. Ejemplo", "player", "lineup", "starts")]
    detail = StoryDetailPrivate(
        **fields, essentials_es=fields["summary_es"], level_explanation_es=LEVEL_EXPLANATION_ES["oficial"],
        match_impact=c06.impact_of(uses, {FIXTURE: False}, AT), timeline=c06.timeline(b, versions),
        related=ItemList(items=[RelatedStory(id="st-ej-sancion-sur", headline_es=c06.NO_DATA, level="un_medio")]),
        analyses=c06.analysis_links(uses))
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="noticia", story=detail, story_status="activa")


def noticia_retirada() -> NewsPrivate:
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="noticia", story=c06.WITHDRAWN, story_status="retirada")


def busqueda() -> NewsPrivate:
    f = c06.Filters(q="Ejémplo Sur", category="bajas_y_sanciones")
    ranks = {"st-ej-sancion-sur": 0.6, "st-ej-rumor-fichaje": 0.3}
    body = c06.search_of([convocatoria(), sancion(), rumor()], ranks, f, None)
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="busqueda", search=body, story_status=c06.NO_DATA)


def partido() -> NewsPrivate:
    bundles = [convocatoria(), sancion()]
    uses = [views.ItemUse(11, FIXTURE, KICKOFF, "E2", 1, AT - timedelta(minutes=12), "contexto", "J. Ejemplo", "player", "lineup", "starts")]
    searched_at, sources_checked = c06.search_fields(NewsSearch(searched="yes", last_searched_at=AT - timedelta(hours=3), searches=2,
                                                                sources_read=14))
    body = MatchStoriesPrivate(fixture_id=FIXTURE, kickoff_at=KICKOFF, window_from=AT - timedelta(days=6),
                               stories=ItemList(items=[c06.card(b, AT) for b in bundles]), analyses=c06.analysis_links(uses),
                               searched_at=searched_at, sources_checked=sources_checked)
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="partido", match=body, story_status=c06.NO_DATA)


def premio() -> Bundle:
    """C-06 1.1: a general story with no match - an award of a player of the Club Ejemplo Norte, in both languages."""
    key = "st-ej-premio-j-ejemplo"
    s = story(key, level="oficial", category="premios", at=AT - timedelta(hours=7), claim_type="contexto",
              headline="J. Ejemplo, elegido mejor jugador del mes de la Liga Ficticia",
              summary="La Liga Ficticia eligió a J. Ejemplo mejor jugador de octubre. Es su segundo premio de la temporada.",
              headline_en="J. Ejemplo named Liga Ficticia player of the month",
              summary_en="Liga Ficticia named J. Ejemplo its player of October. It is his second award of the season.")
    items = [item(51, key, "Liga Ficticia (oficial)", "https://liga.ejemplo.invalid/premios/octubre", seen=AT - timedelta(hours=7),
                  published=AT - timedelta(hours=7, minutes=5))]
    return bundle(s, items, [ent(51, "player", J_EJEMPLO, "J. Ejemplo", method="alias", confidence="0.97"),
                             ent(51, "team", NORTE, "Club Ejemplo Norte", role="mencionado")])


def general() -> NewsPrivate:
    """C-06 1.1: the stories of a player outside any match - the search by ``player`` - with the English text."""
    f = c06.Filters(player=J_EJEMPLO)
    body = c06.search_of([convocatoria(), premio(), rumor()], None, f, None)
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="busqueda", search=body, story_status=c06.NO_DATA)


def partido_sin_busqueda() -> NewsPrivate:
    """C-06 1.1: a match the web was never searched for: «buscamos y no hubo nada» is not said - sin_datos and 0 pages."""
    searched_at, sources_checked = c06.search_fields(NewsSearch(searched="no", searches=0, sources_read=0))
    body = MatchStoriesPrivate(fixture_id=FIXTURE, kickoff_at=KICKOFF, window_from=AT - timedelta(days=6),
                               stories=ItemList(items=[], missing_reason="sin_resultados"), analyses=c06.analysis_links([]),
                               searched_at=searched_at, sources_checked=sources_checked)
    return NewsPrivate(freshness=Freshness(generated_at=AT, stale=False), view="partido", match=body, story_status=c06.NO_DATA)


def c06_cases() -> dict[str, NewsPrivate]:
    return {"portada": front(followed=c06.Followed(frozenset({NORTE}), frozenset())), "portada_vacia": front_empty(),
            "noticia": noticia(), "noticia_retirada": noticia_retirada(), "busqueda": busqueda(), "partido": partido(),
            "general": general(), "partido_sin_busqueda": partido_sin_busqueda()}


# ── C-07 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

E3_AT = KICKOFF - timedelta(minutes=55)


def source_row(sid: int, evidence: int, *, linked: bool, relation: str | None = None, level: str | None = None, rejection: str | None = None,
               entity: tuple[str, int, str] | None = ("player", J_EJEMPLO, "J. Ejemplo"), team: tuple[int, str] = (NORTE, "Club Ejemplo Norte"),
               kind: str = "injury", assertion: str | None = "out", name: str = "Club Ejemplo Norte (oficial)",
               url: str = "https://oficial.ejemplo.invalid/noticias/parte", tier: str = "club", stype: str = "oficial",
               fact_at: datetime | None = None, known: datetime | None = None, e2: str | None = None,
               selections: list[dict[str, Any]] | None = None) -> views.SourceRow:
    return views.SourceRow(
        id=sid, list_id=1, evidence_id=evidence, item_id=None, linked=linked, rejection=rejection, relation=relation, level=level,
        warning=None, entity_type=entity[0] if entity else None, entity_id=entity[1] if entity else None,
        entity_name=entity[2] if entity else None, team_id=team[0], team_name=team[1], named_as=entity[2].lower() if entity and linked else None,
        kind=kind, assertion=assertion, source_name=name, source_url=url, source_tier=tier, source_type=stype,
        fact_at=fact_at or E3_AT - timedelta(hours=6), fact_known_at=known or E3_AT - timedelta(hours=5, minutes=50), decided_at=E3_AT,
        e2_action=e2, selections=selections or [], version="link-v1")


def c07_published() -> AnalysisSourcesPrivate:
    lists = [views.SourceList(2, 502, "E3", 1, E3_AT, 4, 3, 1, {"en_contra": 1, "contexto": 1, "no_usada": 1}, {"homonimo": 1}, "link-v1"),
             views.SourceList(1, 501, "E1", 1, KICKOFF - timedelta(hours=14), 1, 1, 0, {"contexto": 1}, {}, "link-v1")]
    rows = [
        source_row(1, 7001, linked=True, relation="en_contra", level="oficial", e2="recalcula",
                   selections=[{"market_key": "OU", "selection": "Over", "line": "2.5", "relation": "en_contra", "shift": -0.034}]),
        source_row(2, 7002, linked=True, relation="contexto", level="dos_origenes", entity=("team", SUR, "Club Ejemplo Sur"),
                   team=(SUR, "Club Ejemplo Sur"), kind="coach", assertion="info", name="Radio Ejemplo",
                   url="https://radio.ejemplo.invalid/deportes/tecnico-sur", tier="media", stype="prensa", e2="anota"),
        source_row(3, 7003, linked=True, relation="no_usada", level="rumor", entity=("player", L_EJEMPLO, "L. Ejemplo"),
                   team=(SUR, "Club Ejemplo Sur"), kind="doubtful", assertion="doubtful", name="Portal Ejemplo",
                   url="https://portal.ejemplo.invalid/l-ejemplo-duda", tier="aggregator", stype="prensa"),
        source_row(4, 7004, linked=False, rejection="homonimo", entity=("player", A_EJEMPLO, "A. Ejemplo"), kind="injury",
                   name="Portal Ejemplo", url="https://portal.ejemplo.invalid/ejemplo-lesion", tier="aggregator", stype="prensa"),
    ]
    return c07.assemble(FIXTURE, lists, lists[0], rows, published=KICKOFF - timedelta(minutes=40), at=KICKOFF - timedelta(minutes=30))


def c07_empty() -> AnalysisSourcesPrivate:
    return c07.assemble(FIXTURE, [], None, [], published=None, at=AT)


def c07_cases() -> dict[str, AnalysisSourcesPrivate]:
    return {"publicada": c07_published(), "sin_evaluaciones": c07_empty()}


def dumped(model: IntelligenceContract) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def write() -> None:
    for contract, cases, public in (("C-06", c06_cases(), News), ("C-07", c07_cases(), AnalysisSources)):
        folder = EXAMPLES / contract
        folder.mkdir(parents=True, exist_ok=True)
        for case, answer in cases.items():
            for projection, model in (("private", answer), ("public", to_public(answer, public))):
                (folder / f"{case}.{projection}.json").write_text(json.dumps(dumped(model), ensure_ascii=False, indent=2) + "\n",
                                                                  encoding="utf-8")


if __name__ == "__main__":
    write()
