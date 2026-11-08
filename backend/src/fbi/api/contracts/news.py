"""The news of a match for the reader (plan UX, A10; section 27): what PrediGol Intelligence already found and verified outside
the numbers, as cards - PrediGol's own summary, the source and its standing, the time, the relevance for the match, the status
the server decided and the link to the original. Never an article's text, title or picture."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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


class NewsSearch(Contract):
    """Whether PrediGol Intelligence searched the web for this match's news, and when (IA-016): «not searched yet» and «searched, nothing
    found» are not the same answer."""
    searched: Literal["yes", "no", "unknown"] = Field(description=(
        "yes: the web was searched for this match (a search paid for it, or a pass answered by a search still fresh); no: no search for it "
        "is recorded - a match is searched only on its day, and only with a market; unknown: the record could not be read."))
    last_searched_at: datetime | None = Field(default=None, description="The newest search of this match; null unless searched is yes.")
    searches: int | None = Field(default=None, description="Web searches paid for this match; null when unknown.")
    sources_read: int | None = Field(default=None, description=(
        "Pages PrediGol read for this match (each one once). Null when unknown - a pass recorded before this count existed, or research "
        "that does not count it."))


class MatchNews(Contract):
    fixture_id: int
    items: list[NewsItem] = Field(description="Confirmed and most relevant first, then probable, contradictions, rumours and "
                                              "the outdated last.")
    counts: dict[NewsStatus, int] = Field(description="How many items of each status.")
    search: NewsSearch | None = Field(default=None, description="Whether and when the web was searched for this match (IA-016).")


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
    items: list[TodayNewsItem] = Field(description="Home's «Noticias» as a summary (plan de Inicio, 3.3): the best confirmed or "
                                                   "probable news of the matches not yet over - and, with room left, one "
                                                   "rumour (status RUMOR, the web labels it) - from three hours ago to 36 hours "
                                                   "ahead. Two at most for the reader's own leagues and teams, three for the "
                                                   "suggested ones; at most two per match. «CONFIRMED» means an official source "
                                                   "or two distinct outlets; any other reads PROBABLE.")
    suggested: bool = Field(default=True, description="The matches are the suggested ones for Colombia (the reader chose "
                                                      "none, or FBI_PERSONALIZATION=0): labelled so.")


# ── the owner's diagnosis of a match's news (IA-019) ─────────────────────────────────────────────────────────────────

PassKind = Literal["first", "pre", "final"]
DiagnosisCode = Literal["searched", "not_tracked", "no_market", "kicked_off", "day_not_open", "exa_spent", "first_pending",
                        "near_budget", "covered_not_searched", "not_covered"]


class DiagnosisMatch(Contract):
    fixture_id: int
    kickoff_at: datetime
    status_group: str
    home: str
    away: str
    competition: str
    provider_league_id: int | None = Field(description="The competition's API-Football id: what decides its priority group.")
    priority_group: int = Field(description="The owner's priority group of the competition (``fbi.intel.day_priority``): 1 to 4.")
    tracked: bool = Field(description="The competition is one PrediGol follows: only those enter the AI's day.")


class DiagnosisCoverage(Contract):
    covered: bool = Field(description="Searched at its first and pre passes whatever the day's caps say (IA-016): the switch on and a "
                                      "competition of the guaranteed groups.")
    switch_on: bool = Field(description="FBI_AI_NEWS_PRIORITY.")
    groups: list[int] = Field(description="The priority groups the guaranteed coverage takes.")


class DiagnosisDay(Contract):
    day: date = Field(description="The match's day for the AI (America/Bogota).")
    opens_at: datetime = Field(description="When that day opens for the AI: 00:05 in Bogotá.")
    opened: bool
    has_market: bool | None = Field(description="Whether the match has a market by the AI's own rule (a consensus price of the last 36 "
                                                "hours). Null: the match is not in the AI's day (its competition is not followed).")
    odds_at: datetime | None = Field(default=None, description="The newest consensus price the rule saw.")


class DiagnosisPass(Contract):
    kind: PassKind
    day: date
    started_at: datetime
    finished_at: datetime
    status: str = Field(description="ok, partial, skipped or failed, as the pass recorded it.")
    web: dict[str, int] = Field(description="The pass's web counts (every ``web_*`` key it recorded): web_asked, web_searches, "
                                            "web_priority, web_read, web_items, web_new, web_press...")
    near_budget: bool = Field(description="The pass saved its paid depth near the budget (``marginal_saved``): no web for it.")


class DiagnosisNextPass(Contract):
    kind: PassKind
    window_from: datetime = Field(description="The earliest moment the pass may run (the worker looks every 15 minutes).")
    window_until: datetime = Field(description="The last moment it may run.")
    lineups_until: datetime | None = Field(default=None, description="The final pass: without confirmed line-ups it waits until then.")
    due_now: bool = Field(description="The window has opened: the next cycle runs it.")


class DiagnosisSearches(Contract):
    searches: int = Field(description="Web searches paid for this match (``ai.usage``, purpose web_search, status ok).")
    failed: int = Field(description="Searches tried that did not answer (never paid).")
    first_at: datetime | None = None
    last_at: datetime | None = None
    cost_usd: Decimal
    sources_read: int | None = Field(default=None, description="Pages read across the passes; null when a pass did not count them.")


class DiagnosisExa(Contract):
    allowed: bool = Field(description="Exa's envelope still allows a search now.")
    reason: str = Field(description="ok, month_spent, day_cap or no_envelope.")
    budget_usd: Decimal = Field(description="FBI_AI_EXA_MONTHLY_BUDGET_USD.")
    spent_month_usd: Decimal
    spent_today_usd: Decimal
    daily_cap_usd: Decimal


class DiagnosisVerdict(Contract):
    code: DiagnosisCode = Field(description="Why the match has news or not, the first reason that applies.")
    at: datetime | None = Field(default=None, description="searched: the newest search.")
    searches: int | None = None
    pages: int | None = Field(default=None, description="searched: pages read; null when not known.")
    items: int | None = Field(default=None, description="searched: web items kept for the match.")
    next_pass: PassKind | None = None
    next_at: datetime | None = Field(default=None, description="When the next pass may run, when there is one.")
    exa_reason: str | None = None


class NewsDiagnosis(Contract):
    """Why a match has news or not (IA-019), for the owner alone: what the AI's day, its passes, the ledger and Exa's envelope say."""
    as_of: datetime
    match: DiagnosisMatch
    coverage: DiagnosisCoverage
    day: DiagnosisDay
    passes: list[DiagnosisPass] = Field(description="Every pass of the match, oldest first.")
    next_pass: DiagnosisNextPass | None = Field(description="The pass the match is waiting for; null when none is left or it has no market.")
    searches: DiagnosisSearches
    exa: DiagnosisExa | None = Field(description="Null when the envelope could not be read.")
    evidence: dict[NewsStatus, int] = Field(description="The web items kept for the match (``ai.evidence``, origin web), by status.")
    evidence_newest_at: datetime | None = None
    verdict: DiagnosisVerdict
