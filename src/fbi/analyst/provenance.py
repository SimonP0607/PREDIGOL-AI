"""Provenance: a claim about the world is kept only with the source it came from.

The model never writes a URL. ``web_research`` registers every result it returns under a
source id (S1, S2, ...) for the run, and a claim cites source ids; the server resolves them
here, so a claim can only point at a page the run actually retrieved, with the publisher,
``published_at`` (as the source states it) and ``retrieved_at`` (our clock) of that page.

Grades, from the sources alone (the model may propose a grade; the server can only lower it):

  CONFIRMED  an official source (league, federation or club domain in ``OFFICIAL_DOMAINS``),
             or two independent reputable outlets (``REPUTABLE_DOMAINS``) carrying the claim;
  REPORTED   one reputable outlet, or an official source without a publication date;
  RUMOR      anything else.

Web text is data, never instructions: a page that tells the model to do something is just
a page (OWASP LLM01). The allowlists are plain data, extended by the owner, never by a run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any
from urllib.parse import urlparse

from fbi.analyst.search import SearchResult

OFFICIAL_DOMAINS: frozenset[str] = frozenset({
    # confederations and federations
    "fifa.com", "uefa.com", "conmebol.com", "concacaf.com", "the-afc.com", "cafonline.com",
    "thefa.com", "rfef.es", "figc.it", "dfb.de", "fff.fr", "fcf.com.co", "afa.com.ar", "cbf.com.br",
    "fmf.mx", "ussoccer.com", "fpf.pt", "knvb.nl",
    # leagues
    "premierleague.com", "efl.com", "laliga.com", "legaseriea.it", "bundesliga.com", "ligue1.com",
    "dimayor.com.co", "ligamx.net", "mlssoccer.com", "ligaportugal.pt", "eredivisie.nl", "spfl.co.uk",
    "superlig.org.tr", "ligaprofesional.ar", "brasileirao.cbf.com.br",
    # clubs (the owner adds more; a club page is official for its own news)
    "arsenal.com", "chelseafc.com", "liverpoolfc.com", "manutd.com", "mancity.com", "tottenhamhotspur.com",
    "realmadrid.com", "fcbarcelona.com", "atleticodemadrid.com", "juventus.com", "acmilan.com", "inter.it",
    "fcbayern.com", "bvb.de", "psg.fr", "atlnacional.com.co", "millonarios.com.co", "americadecali.co",
})
REPUTABLE_DOMAINS: frozenset[str] = frozenset({
    "bbc.co.uk", "bbc.com", "skysports.com", "espn.com", "espn.co.uk", "theathletic.com", "nytimes.com",
    "reuters.com", "apnews.com", "theguardian.com", "telegraph.co.uk", "independent.co.uk",
    "marca.com", "as.com", "mundodeportivo.com", "sport.es", "relevo.com", "elpais.com",
    "gazzetta.it", "corrieredellosport.it", "tuttosport.com", "football-italia.net", "sky.it",
    "kicker.de", "sportschau.de", "spox.com", "lequipe.fr", "rmcsport.bfmtv.com", "footmercato.net",
    "eltiempo.com", "elespectador.com", "futbolred.com", "semana.com", "winsports.co", "elcolombiano.com",
    "ole.com.ar", "tycsports.com", "globo.com", "uol.com.br", "lance.com.br", "record.pt", "abola.pt",
    "ojogo.pt", "mediotiempo.com", "record.com.mx", "voetbalinternational.nl", "goal.com",
})


class Grade(IntEnum):
    RUMOR = 0
    REPORTED = 1
    CONFIRMED = 2


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host.removeprefix("www.")


def _in(host: str, domains: frozenset[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def kind_of(url: str) -> str:
    h = _host(url)
    return "official" if _in(h, OFFICIAL_DOMAINS) else "reputable" if _in(h, REPUTABLE_DOMAINS) else "other"


def allowed_grade(sources: list[SearchResult]) -> Grade:
    """The best grade these sources can support."""
    official = [s for s in sources if kind_of(s.url) == "official"]
    if any(s.published_at for s in official):
        return Grade.CONFIRMED
    reputable_publishers = {_host(s.url) for s in sources if kind_of(s.url) == "reputable"}
    if len(reputable_publishers) >= 2:
        return Grade.CONFIRMED
    if reputable_publishers or official:
        return Grade.REPORTED
    return Grade.RUMOR


@dataclass
class SourceRegistry:
    """Every page ``web_research`` returned in one run, by source id."""

    sources: dict[str, SearchResult] = field(default_factory=dict)

    def add(self, result: SearchResult) -> str:
        for sid, s in self.sources.items():
            if s.url == result.url:
                return sid
        sid = f"S{len(self.sources) + 1}"
        self.sources[sid] = result
        return sid

    def get(self, sid: str) -> SearchResult | None:
        return self.sources.get(sid)


@dataclass(frozen=True, slots=True)
class Claim:
    """A claim the server accepted: what the model said, where it is written, and the grade
    the sources support."""

    ref: str
    claim: str
    source: SearchResult
    also: tuple[SearchResult, ...]
    grade: Grade
    proposed: Grade
    fixture_id: int | None
    team_id: int | None

    def as_json(self) -> dict[str, Any]:
        return {"ref": self.ref, "claim": self.claim, "source_url": self.source.url,
                "publisher": self.source.publisher, "published_at": self.source.published_at,
                "retrieved_at": self.source.retrieved_at, "also_urls": [s.url for s in self.also],
                "confidence": self.grade.name, "proposed": self.proposed.name,
                "fixture_id": self.fixture_id, "team_id": self.team_id}


@dataclass(frozen=True, slots=True)
class Rejected:
    ref: str
    reason: str


def accept_claims(raw: list[dict[str, Any]], registry: SourceRegistry, *, fixture_ids: set[int],
                  team_ids: set[int]) -> tuple[list[Claim], list[Rejected]]:
    """Resolve and grade the claims the model submitted. A claim is refused - and listed, not
    silently dropped - when it cites no source, a source this run did not retrieve, or a
    fixture or team outside the report's scope."""
    accepted: list[Claim] = []
    rejected: list[Rejected] = []
    seen: set[str] = set()
    for i, c in enumerate(raw, start=1):
        ref = str(c.get("ref") or f"C{i}")
        if ref in seen:
            rejected.append(Rejected(ref, "duplicate claim id"))
            continue
        seen.add(ref)
        text = " ".join(str(c.get("claim") or "").split())
        ids = [str(x) for x in (c.get("source_ids") or [])][:3]
        resolved = [registry.get(x) for x in ids]
        if not 5 <= len(text) <= 600:
            rejected.append(Rejected(ref, "a claim is 5 to 600 characters"))
            continue
        if not ids:
            rejected.append(Rejected(ref, "no source cited"))
            continue
        missing = [x for x, r in zip(ids, resolved, strict=True) if r is None]
        if missing:
            rejected.append(Rejected(ref, f"source {', '.join(missing)} was not retrieved in this run"))
            continue
        sources = [r for r in resolved if r is not None]
        fixture_id = c.get("fixture_id")
        team_id = c.get("team_id")
        if fixture_id is not None and int(fixture_id) not in fixture_ids:
            rejected.append(Rejected(ref, f"fixture {fixture_id} is not in this report"))
            continue
        if team_id is not None and int(team_id) not in team_ids:
            rejected.append(Rejected(ref, f"team {team_id} is not in this report"))
            continue
        try:
            proposed = Grade[str(c.get("confidence") or "RUMOR").upper()]
        except KeyError:
            proposed = Grade.RUMOR
        grade = min(proposed, allowed_grade(sources))
        accepted.append(Claim(ref, text, sources[0], tuple(sources[1:]), grade, proposed,
                              None if fixture_id is None else int(fixture_id),
                              None if team_id is None else int(team_id)))
    return accepted, rejected
