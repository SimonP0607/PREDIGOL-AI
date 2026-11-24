"""C-10, the search v2 (AD-I02, IA-081): one search, in groups, three passes, with the names in force of IA-071.

``GET /api/v1/search/v2?q=`` answers the public projection; ``GET /api/v1/admin/search/v2?q=`` (``require_admin``) the
private one, with the score of each hit and the state of the index - for calibrating the bank of queries. The search of
today, ``GET /api/v1/search`` (a list of ``SearchHit``), is not changed.

The groups are those of the UX contract, in its order: Equipos, Selecciones, Jugadores, Competiciones, Entrenadores,
Árbitros, Estadios, Partidos, Noticias; up to 8 hits each. A group without hits says why (``sin_resultados``); every group
says ``no_entregado`` (``AD-I01``) while the index has not been built, and Noticias says ``no_entregado`` (``AD-G01``) until
its own items exist. Nothing here is private to a reader except what the private projection adds.

1.1.0 (C-10 1.1; AP-B02, AP-B07, AP-E02) - the same shape, more names and one order: the index also holds the Spanish and
English names of the national teams and of the main competitions (``alias_type`` ``localized``: «España» finds Spain,
«Inglaterra» England, «Alemania Sub-21» Germany U21, «Mundial» the World Cup; ``fbi.people.identity.localized``), and in
``national_teams`` the senior team comes before its age-group and women's teams unless the query asks for one. No field is
added, renamed or removed: an answer of 1.0.0 reads the same.
"""

from __future__ import annotations

from typing import ClassVar, Final, Literal

from pydantic import Field

from fbi.api.contracts.intelligence.base import (
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    Missing,
    UtcDatetime,
    private,
)

SearchKind = Literal["team", "national_team", "player", "competition", "coach", "referee", "venue"]
"""The kinds of the index (``core.search_entries.kind``); matches and news are their own groups."""

MatchPass = Literal["prefijo", "palabras", "trigramas"]
"""Which pass found the hit: the name begins with the query; every word of the query begins a word of the name; or the
name is close to it (trigrams: a typo)."""

AliasType = Literal["official", "full", "short", "code", "nickname", "transliteration", "localized", "former",
                    "alternative"]
"""The kind of the name that matched (``core.entity_aliases.alias_type`` of IA-071; ``official`` for an entity's own name,
``full`` for first + last name, ``alternative`` for the old alias tables)."""

GROUPS: Final[tuple[str, ...]] = ("teams", "national_teams", "players", "competitions", "coaches", "referees", "venues",
                                  "fixtures", "news")
"""The groups in the order the UX contract draws them."""

KIND_GROUP: Final[dict[str, str]] = {"team": "teams", "national_team": "national_teams", "player": "players",
                                     "competition": "competitions", "coach": "coaches", "referee": "referees",
                                     "venue": "venues"}


class SearchHitV2(IntelligenceModel):
    """One entity found: what to show and which of its names matched."""

    kind: SearchKind
    id: int = Field(description="The entity's own id (core.teams.id, core.players.id, core.competitions.id, ...).")
    label: str = Field(min_length=1, description="Its name as PrediGol shows it.")
    sublabel: str = Field(description="Country (team, competition), current team (player, coach), city (stadium); "
                                      "may be empty.")
    matched: str = Field(min_length=1, description="The name that matched the query (an alias, the full name...).")
    alias_type: AliasType
    match: MatchPass


class SearchHitV2Private(SearchHitV2):
    """The same hit as the owner sees it: the numbers that ordered it."""

    score: float = private(ge=0, le=1, description="Closeness of the pass: 1 prefix, 0.9 words, the word similarity "
                                                   "of the trigrams.")
    popularity: float = private(ge=0, description="Matches in tracked competitions (400 days back, 60 ahead) of the "
                                                  "entity or its current team; 1000 a tracked competition.")
    rank: float = private(description="The order inside the group (fbi.api.repositories.search_v2.POPULARITY_WEIGHT).")


class SearchFixtureHit(IntelligenceModel):
    """A match of one of the teams found, nearest to now first."""

    id: int
    label: str = Field(min_length=1, description="«Home v Away».")
    sublabel: str = Field(description="The competition.")
    kickoff_at: UtcDatetime
    home_team_id: int
    away_team_id: int


class SearchNewsHit(IntelligenceModel):
    """A news item found by its own headline and summary (AD-G01): never by the body of someone else's article."""

    id: int
    label: str = Field(min_length=1, description="The headline.")
    sublabel: str = Field(description="The source.")
    published_at: UtcDatetime


class SearchSuggestion(IntelligenceModel):
    """«¿Quisiste decir…?»: a name close to a query that found nothing."""

    text: str = Field(min_length=1)


class SearchGroups(IntelligenceModel):
    """The nine groups, in the UX contract's order, up to ``per_group`` hits each."""

    teams: ItemList[SearchHitV2]
    national_teams: ItemList[SearchHitV2]
    players: ItemList[SearchHitV2]
    competitions: ItemList[SearchHitV2]
    coaches: ItemList[SearchHitV2]
    referees: ItemList[SearchHitV2]
    venues: ItemList[SearchHitV2]
    fixtures: ItemList[SearchFixtureHit]
    news: ItemList[SearchNewsHit]


class SearchGroupsPrivate(SearchGroups):
    teams: ItemList[SearchHitV2Private]  # type: ignore[assignment]  # the private variant of each item
    national_teams: ItemList[SearchHitV2Private]  # type: ignore[assignment]
    players: ItemList[SearchHitV2Private]  # type: ignore[assignment]
    competitions: ItemList[SearchHitV2Private]  # type: ignore[assignment]
    coaches: ItemList[SearchHitV2Private]  # type: ignore[assignment]
    referees: ItemList[SearchHitV2Private]  # type: ignore[assignment]
    venues: ItemList[SearchHitV2Private]  # type: ignore[assignment]


class SearchIndexState(IntelligenceModel):
    """The index behind the answer (private): whether it is built, when, and the thresholds in force."""

    built: bool
    indexed_at: UtcDatetime | Missing = Field(description="When core.search_entries was last refreshed, or sin_datos.")
    rows_estimate: int = Field(ge=-1, description="The planner's estimate of its rows (-1: never analysed).")
    trigram_threshold: float = Field(ge=0, le=1)
    popularity_weight: float = Field(ge=0)
    elapsed_ms: int = Field(ge=0, description="What this answer took on the server.")


class SearchV2(IntelligenceContract):
    """C-10, public projection."""

    CONTRACT_ID: ClassVar[str] = "C-10"
    CONTRACT_VERSION: ClassVar[str] = "1.1.0"

    query: str = Field(min_length=2, max_length=60, description="The query as it was read (spaces collapsed).")
    normalized: str = Field(description="The query's key: lower case, no accents, no punctuation "
                                        "(core.search_key); empty when nothing is left.")
    per_group: int = Field(ge=1, le=8)
    groups: SearchGroups
    did_you_mean: ItemList[SearchSuggestion] = Field(
        description="Close names, only when no group has a hit; otherwise empty with sin_resultados.")


class SearchV2Private(SearchV2):
    """C-10, private projection: the public one with the score of each hit and the state of the index."""

    groups: SearchGroupsPrivate  # the private variant of each hit
    index: SearchIndexState = private(description="The index behind the answer and the thresholds in force.")
