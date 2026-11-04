"""The news of a match for the reader (plan UX, A10; section 27): what PrediGol Intelligence already found and verified outside
the numbers, as cards - PrediGol's own summary, the source and its standing, the time, the relevance for the match, the status
the server decided and the link to the original. Never an article's text, title or picture."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.today import FollowReason

NewsStatus = Literal["CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR", "OUTDATED"]
NewsKind = Literal["injury", "suspension", "doubtful", "lineup", "coach", "news", "transfer", "motivation", "weather",
                   "travel", "schedule", "other"]
Assertion = Literal["out", "doubtful", "available", "starts", "info"]
Tier = Literal["official", "competition", "club", "provider", "journalist", "media", "aggregator", "social", "unknown"]


class NewsTeam(Contract):
    id: int
    name: str
    side: Literal["home", "away"]


class NewsSource(Contract):
    name: str = Field(description="The outlet as the search named it (often its address, without www.).")
    tier: Tier = Field(description="Its standing, as PrediGol Intelligence classifies sources: official, competition, club, "
                                   "provider, journalist, media, aggregator, social or unknown (the web says it in words).")
    url: str | None = Field(description="The original page, to open in a new tab. Null: the source has no public page.")
    published_at: datetime | None = Field(description="When the source published it, as it said; null when it did not say.")
    published_day_only: bool = Field(description="True: the source gave only the day (the time reads 00:00 UTC) - say the "
                                                 "day, never an hour.")


class NewsClaim(Contract):
    text: str | None = Field(description="PrediGol's own one-sentence summary of what the source asserts, in Spanish - never "
                                         "the article's words or title. Null when the stored summary does not read as "
                                         "Spanish or repeats the source's title: the web words it from kind, assertion, "
                                         "player and team.")
    lang: Literal["es"] = Field(description="The language of text: Spanish (the English is text_en).")
    text_en: str | None = Field(default=None, description=(
        "The same summary in English (plan UX, A11), written with the readers' narrative and checked against the Spanish - its "
        "numbers, no title, no link. Null when there is none, or while the owner keeps the narrative off: the English page then "
        "shows the Spanish, labelled."))
    assertion: Assertion = Field(description="What it asserts about who plays: out, doubtful, available, starts, or info.")
    sources: list[NewsSource] = Field(description="Where it was read, newest first (at most four).")


class NewsItem(Contract):
    id: str = Field(description="Stable within the match: changes only if the item itself changes.")
    kind: NewsKind
    status: NewsStatus = Field(description="Decided by the server from the sources, never by a model: CONFIRMED (an "
                                           "official source with a date, the confirmed line-up or two independent media), "
                                           "PROBABLE (one outlet or journalist), CONTRADICTORY (sources of comparable "
                                           "standing disagree), RUMOR (only aggregators, social posts or unknown sites) "
                                           "or OUTDATED (superseded, or too old for the match).")
    relevance: Literal["high", "medium", "low"] = Field(description=(
        "For this match, from what the item is about: high - who plays or does not (an absence, a doubt, a return or a "
        "line-up, of a named player or the team's eleven); medium - the same without naming a player, or the coach; low - "
        "the rest of the context."))
    team: NewsTeam | None
    player: str | None = Field(description="The player as the source wrote him; null for the team as a whole.")
    claims: list[NewsClaim] = Field(description="One; two or more when the sources contradict each other (CONTRADICTORY), "
                                                "each with its own sources.")
    headline_es: str | None = Field(default=None, description=(
        "PrediGol's own headline of the item in Spanish, at most 80 characters (A11) - never the source's. Null for a "
        "contradiction (it would take a side), when there is none, or while the owner keeps the narrative off: the web words "
        "the headline from the kind and the player."))
    headline_en: str | None = Field(default=None, description="The same headline in English (A11); null as headline_es.")
    published_at: datetime | None = Field(description="The newest publication among its sources.")
    published_day_only: bool
    seen_at: datetime = Field(description="When PrediGol last read it.")


class MatchNews(Contract):
    fixture_id: int
    items: list[NewsItem] = Field(description="Confirmed and most relevant first, then probable, contradictions, rumours and "
                                              "the outdated last.")
    counts: dict[NewsStatus, int] = Field(description="How many items of each status.")


class TodayNewsMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    home: str
    away: str
    competition: str
    followed: FollowReason | None = Field(default=None, description="Why the match is the reader's (plan UX, B2): a team "
                                                                    "they follow plays it, or it belongs to a league they "
                                                                    "follow - the suggested ones while they chose none.")


class TodayNewsItem(Contract):
    match: TodayNewsMatch
    item: NewsItem


class TodayNews(Contract):
    items: list[TodayNewsItem] = Field(description="Home's «Noticias» (plan section 24, block 4): confirmed or probable news "
                                                   "of the reader's matches not yet over - their leagues and teams (B2), the "
                                                   "suggested ones while they chose none - from three hours ago to 36 hours "
                                                   "ahead, kick-off order, at most three per match.")
    suggested: bool = Field(default=True, description="The matches are the suggested ones for Colombia (the reader chose "
                                                      "none, or FBI_PERSONALIZATION=0): labelled so.")
