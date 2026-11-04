"""The news cards of a match (plan UX, A10; section 27), pure: the order (confirmed and most relevant first, rumours and the
outdated last), one card per story with every source, a contradiction as one card with both claims and their sources, the
relevance said from what an item is about, a day-only date never read as an hour, and PrediGol's own summary sent only when it
reads as Spanish, carries no link and does not repeat the source's title. The samples are the server's own (25 Oct 2026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.api.contracts.news import NewsTeam
from fbi.api.services import news

NOW = datetime(2026, 10, 25, 18, 0, tzinfo=UTC)
TEAMS = {1: NewsTeam(id=1, name="Tenerife", side="home"), 2: NewsTeam(id=2, name="Zaragoza", side="away")}
_ids = iter(range(100, 10_000))


def row(*, status: str = "PROBABLE", kind: str = "injury", assertion: str = "out", player: str | None = "Baba Diocou",
        team: int | None = 1, claim: str = "Según Sport, Baba Diocou es baja por lesión para este partido.",
        source: str = "www.sport.es", url: str | None = "https://www.sport.es/es/noticias/1", tier: str = "media",
        published: datetime | None = None, retrieved: datetime | None = None, story: str | None = None,
        title: str | None = "Diocou, baja ante el Zaragoza", rid: int | None = None) -> news.Row:
    side = "home" if team == 1 else "away"
    return news.Row(id=rid or next(_ids), fixture_id=7, team_id=team, kind=kind, claim=claim, source_name=source,
                    source_url=url, tier=tier, published_at=published, retrieved_at=retrieved or NOW - timedelta(hours=1),
                    last_seen_at=None, story_key=story or f"web:7:{side}:{news.name_key(player) or 'team'}:{kind}:{assertion}",
                    status=status, assertion=assertion, player=player, title=title)


SPANISH = [
    "Según Sport, Baba Diocou es baja por lesión para este partido.",
    "La alineación probable de NEC (3-4-2-1) incluye a Crettaz, Fonville, Schuurs, Kaplan, Bischoff, Nejašmić, Storm, "
    "Monteiro, Lebreton y Linssen; la fuente es una predicción",
    "Según el artículo, Dominik Albrecht ha regresado, aunque el texto no indica si está disponible para este partido.",
    "Dick Lukkien, entrenador de Groningen, dice esperar un partido caótico; el texto no informa de bajas ni de alineación.",
    "Según Radio Marca Tenerife, César podría jugar pese a sus molestias, según Álvaro Cervera.",
    "Geiger aparece con un signo de interrogación en la alineación probable de NEC, con Kers como posible alternativa.",
]
NOT_SPANISH = [
    # what the server stored for a Turkish source: the extraction answered in the source's language
    "Gençlerbirliği'nden iki futbolcunun sakatlık nedeniyle kadroda olmaması bekleniyor; isimleri metinde belirtilmiyor.",  # noqa: RUF001
    "Gençlerbirliği'nde cezalı oyuncu bulunmadığı, sakatlığı nedeniyle tedavisi süren iki futbolcunun kadroda olmasının "  # noqa: RUF001
    "beklenmediği bildiriliyor; isimler metinde yer almıyor.",  # noqa: RUF001
    "According to the club, the player will miss the match with a hamstring injury.",
    "Segundo o clube, o jogador não vai jogar por causa de uma lesão muscular.",
    "Secondo il club, il giocatore non giocherà per un infortunio muscolare.",
    "Selon le club, le joueur est forfait pour le match à cause d'une blessure.",
    "Volgens de club is de speler geblesseerd en mist hij de wedstrijd.",
    "Laut dem Verein fällt der Spieler mit einer Verletzung aus und ist nicht dabei.",
]


@pytest.mark.parametrize("text", SPANISH)
def test_a_spanish_summary_reads_as_spanish(text: str) -> None:
    assert news.reads_as_spanish(text)


@pytest.mark.parametrize("text", NOT_SPANISH)
def test_a_summary_in_another_language_does_not(text: str) -> None:
    assert not news.reads_as_spanish(text)


def test_the_summary_sent_is_predigols_own_sentence_never_the_sources_words_or_a_link() -> None:
    claim = "Según Sport, Baba Diocou es baja por lesión para este partido."
    assert news.own_summary(claim, "Diocou, baja ante el Zaragoza") == claim
    assert news.own_summary("  Según Sport,\n Baba Diocou es baja  ", None) == "Según Sport, Baba Diocou es baja"
    repeats = "El medio titula: Baba Diocou, baja por lesión ante el Real Zaragoza este domingo"
    assert news.own_summary(repeats, "Baba Diocou, baja por lesión ante el Real Zaragoza") is None, "the source's title"
    assert news.own_summary("Según https://x.es Diocou es baja por lesión", None) is None, "no link inside a summary"
    assert news.own_summary(NOT_SPANISH[0], None) is None
    assert news.own_summary(None, None) is None and news.own_summary("baja", None) is None


def test_a_date_without_an_hour_is_never_read_as_midnight() -> None:
    assert news.day_only(datetime(2026, 10, 24, tzinfo=UTC))
    assert not news.day_only(datetime(2026, 10, 24, 13, 4, tzinfo=UTC))
    assert not news.day_only(None)


def test_relevance_is_said_from_what_the_item_is_about() -> None:
    assert news.relevance_of("injury", "Baba Diocou") == "high"
    assert news.relevance_of("lineup", None) == "high", "the team's eleven says who plays"
    assert news.relevance_of("suspension", None) == "medium", "an absence without a name"
    assert news.relevance_of("coach", "Álvaro Cervera") == "medium"
    for kind in ("news", "transfer", "motivation", "weather", "travel", "schedule", "other"):
        assert news.relevance_of(kind, "Anyone") == "low"


def test_the_order_of_section_27() -> None:
    rows = [
        row(status="RUMOR", player="Rumoured", tier="aggregator", source="besoccer.com", url="https://besoccer.com/1"),
        row(status="OUTDATED", player="Old News", published=NOW - timedelta(days=12)),
        row(status="PROBABLE", kind="news", assertion="info", player=None, claim="El entrenador dice esperar un partido "
            "difícil; el texto no informa de bajas."),
        row(status="PROBABLE", player="Older", published=NOW - timedelta(days=2)),
        row(status="PROBABLE", player="Newer", published=NOW - timedelta(hours=2)),
        row(status="PROBABLE", player=None, claim="Según la fuente, dos jugadores del equipo son baja por lesión."),
        row(status="CONFIRMED", player="Confirmed", tier="club", source="cdtenerife.es", url="https://cdtenerife.es/1"),
    ]
    items = news.cards(rows, TEAMS)
    assert [(i.status, i.player, i.relevance) for i in items] == [
        ("CONFIRMED", "Confirmed", "high"),
        ("PROBABLE", "Newer", "high"), ("PROBABLE", "Older", "high"),
        ("PROBABLE", None, "medium"), ("PROBABLE", None, "low"),
        ("RUMOR", "Rumoured", "high"),
        ("OUTDATED", "Old News", "high"),
    ]
    assert news.counts(items) == {"CONFIRMED": 1, "PROBABLE": 4, "CONTRADICTORY": 0, "RUMOR": 1, "OUTDATED": 1}


def test_one_card_per_story_with_every_source_newest_first() -> None:
    story = "web:7:home:baba diocou:injury:out"
    rows = [row(story=story, source="www.sport.es", url="https://www.sport.es/1", published=NOW - timedelta(hours=5)),
            row(story=story, source="as.com", url="https://as.com/1", published=NOW - timedelta(hours=3),
                claim="Según As, Baba Diocou no estará ante el Zaragoza por una lesión muscular."),
            row(story=story, source="as.com", url="https://as.com/1", published=NOW - timedelta(hours=4)),
            row(story=story, source="marca.com", url="https://www.marca.com/1", published=NOW - timedelta(hours=6)),
            row(story=story, source="relevo.com", url="https://www.relevo.com/1", published=NOW - timedelta(hours=7)),
            row(story=story, source="mundodeportivo.com", url="https://www.mundodeportivo.com/1",
                published=NOW - timedelta(hours=8))]
    [item] = news.cards(rows, TEAMS)
    [claim] = item.claims
    assert [s.name for s in claim.sources] == ["as.com", "sport.es", "marca.com", "relevo.com"], "four at most, one each"
    assert claim.text == "Según As, Baba Diocou no estará ante el Zaragoza por una lesión muscular.", "the newest says it"
    assert item.team == TEAMS[1] and item.player == "Baba Diocou" and item.kind == "injury"
    assert item.published_at == NOW - timedelta(hours=3) and item.published_day_only is False
    assert item.id == f"n{min(r.id for r in rows)}"


def test_a_contradiction_is_one_card_with_both_claims_and_their_sources() -> None:
    out = row(status="CONTRADICTORY", kind="suspension", assertion="out", player="Luis Suárez", team=2,
              claim="Según Marca, Luis Suárez cumple sanción y no jugará este partido.", source="marca.com",
              url="https://www.marca.com/2", published=NOW - timedelta(hours=6))
    back = row(status="CONTRADICTORY", kind="suspension", assertion="available", player="Luis Suarez", team=2,
               claim="Según As, Luis Suárez ya cumplió su sanción y está disponible para este partido.", source="as.com",
               url="https://as.com/2", published=NOW - timedelta(hours=2))
    other = row(status="PROBABLE", player="Someone Else")
    items = news.cards([out, back, other], TEAMS)
    assert [i.status for i in items] == ["PROBABLE", "CONTRADICTORY"]
    card = items[1]
    assert [(c.assertion, [s.name for s in c.sources]) for c in card.claims] == [("available", ["as.com"]),
                                                                                ("out", ["marca.com"])]
    assert card.team == TEAMS[2] and card.relevance == "high"


def test_a_summary_that_cannot_be_sent_keeps_its_card() -> None:
    turkish = row(status="PROBABLE", player=None, claim=NOT_SPANISH[0], source="www.hakimiyet.com",
                  url="https://www.hakimiyet.com/1", tier="unknown")
    [item] = news.cards([turkish], TEAMS)
    assert item.claims[0].text is None and item.claims[0].lang == "es"
    assert item.claims[0].sources[0].name == "hakimiyet.com" and item.claims[0].sources[0].tier == "unknown"
    assert item.relevance == "medium"


def test_a_link_that_is_not_a_plain_web_address_is_never_sent() -> None:
    [item] = news.cards([row(url="javascript:alert(1)")], TEAMS)
    assert item.claims[0].sources[0].url is None
