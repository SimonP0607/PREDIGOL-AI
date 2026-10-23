"""The one door through which a family reads how finished matches ended (plan F10).

What a finished match turned out to be (its goals by half, its corners, its cards) is the training material of a family and the label that
grades it: not an input of what is said about the NEXT match. F9 put it in one view, ``market.fixture_outcomes``, and kept the model packages
from naming it (``tests/unit/test_knowledge_isolation.py``). F10 opens that door on purpose, in this module and in no other, and the door
carries its own lock:

* a match comes through only once its result is KNOWN: ``cutoff - OUTCOME_KNOWN_AFTER`` is the latest kick-off it will return (the rule of
  ``fit.fit_family`` applies it a second time on purpose: two independent guards, because this is where a future would leak);
* what is read is the number the settlement rule compares a line with: the columns come from ``market.settlement_rules`` as the code holds them
  (``fbi.market.rules``), so a family is trained on exactly the quantity that grades its bets, with the same unknown-is-never-zero convention;
* a match with either count unknown is not returned (it would have to be invented).

The cards by period come, through the view, from the events of the match once F7 has classified them: they are outcomes too, and they enter
here as numbers of a match that is over, never as a fact about a match that is not.

A count of cards is read only when it is COMPLETE (23 Oct 2026, corrected twice the same day). Where a match has no team statistics and its cards
come from the events alone, the count is incomplete (22,427 matches of the followed competitions: 3.7 cards a match against 5.1-5.9 where the
statistics back them up) and for the clubs' friendlies the provider reports almost no card at all (83.5 % of 4,840 matches at zero). So the yellow
cards, and the cards counted as lines, are read from the TEAM STATISTICS - the number the provider gives for the whole match - for every match
that has them and was not decided in extra time (the provider does not say whether its total includes the extra half hour); the events only
split a count by period and are not asked for a full-time total. Two filters that look safer were selections and were dropped: asking the
red cards to be REPORTED (the provider leaves a red EMPTY when there was none - of 15,427 matches whose statistics left both reds empty the events
show a red in 0.0 % - so only the matches that had one were kept: a history of 5.5-6.3 cards a match until August 2026 and 4.0-4.3 after the
provider began to write the zeros, the population being 4.3-4.5) and asking the events to AGREE with the statistics (a match with more cards
has more chances to disagree, so the agreeing ones are lighter than the rest: 4.0 a match against 4.3). The cards counted as lines add the reds of
the statistics, an empty one being none. A measure the statistics cannot give (reds alone, a card measure by period) still needs events whose yellow
cards agree with the statistics team by team.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.families.fit import OUTCOME_KNOWN_AFTER, Match
from fbi.market.rules import RULES_BY_MEASURE

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")

CARD_PREFIXES: Final = frozenset({"cards", "yellow", "red"})
"""The measures made of cards: their columns start with one of these words."""
STATS_MEASURES: Final = frozenset({"yellow_ft", "cards_lines_ft"})
"""The card measures that the team statistics give by themselves: the yellow cards are the statistic, and the cards counted as lines add the
reds, which the provider leaves empty when there was none."""
STATS_JOIN: Final = (
    "LEFT JOIN LATERAL (SELECT t.yellow_cards, t.red_cards FROM core.fixture_team_stats t WHERE t.fixture_id = o.fixture_id "
    "AND t.team_side = 'home' ORDER BY (t.source = 'api-football') DESC LIMIT 1) sh ON true "
    "LEFT JOIN LATERAL (SELECT t.yellow_cards, t.red_cards FROM core.fixture_team_stats t WHERE t.fixture_id = o.fixture_id "
    "AND t.team_side = 'away' ORDER BY (t.source = 'api-football') DESC LIMIT 1) sa ON true ")
"""The team statistics of a finished match (``sh`` the home side, ``sa`` the away side), the provider's own first, as the view reads them."""
REFEREE_JOIN: Final = ("LEFT JOIN LATERAL (SELECT r.referee_id FROM core.fixture_referees r WHERE r.fixture_id = o.fixture_id "
                       "ORDER BY r.observed_at DESC LIMIT 1) fr ON true")
"""The referee of a finished match: the identity the platform settled on (F3), whenever it was observed (the match is over)."""


class UnknownMeasureError(ValueError):
    """The measure is not one a family can be trained on."""


def columns_of(measure: str) -> tuple[str, str]:
    """The (home, away) columns of the view that the rule of ``measure`` compares a line with."""
    rule = RULES_BY_MEASURE.get(measure)
    if rule is None:
        raise UnknownMeasureError(f"no settlement rule measures {measure!r}")
    if not rule.liquidable or len(rule.columns) != 2:
        raise UnknownMeasureError(f"{measure!r} is not a pair of counts (home, away): {rule.columns!r}")
    home, away = rule.columns
    if not (_IDENTIFIER.match(home) and _IDENTIFIER.match(away)):
        raise UnknownMeasureError(f"the columns of {measure!r} are not plain identifiers: {rule.columns!r}")
    return home, away


def needs_corroboration(measure: str) -> bool:
    """Whether the counts of ``measure`` are cards, which a family reads only when complete (see the module docstring)."""
    return columns_of(measure)[0].split("_")[0] in CARD_PREFIXES


def count_expressions(measure: str) -> tuple[str, str]:
    """The SQL of the (home, away) count of ``measure``: the column of the view, except the yellow cards and the cards counted as lines, which are
    the team statistics' (the cards as lines add the reds, an empty red being none)."""
    home_col, away_col = columns_of(measure)
    if measure == "yellow_ft":
        return "sh.yellow_cards", "sa.yellow_cards"
    if measure == "cards_lines_ft":
        return "sh.yellow_cards + COALESCE(sh.red_cards, 0)", "sa.yellow_cards + COALESCE(sa.red_cards, 0)"
    return f"o.{home_col}", f"o.{away_col}"


def complete_condition(measure: str) -> str:
    """The SQL condition that makes a match's count of ``measure`` fit to train on: both counts known and, for a card measure, complete."""
    home_col, away_col = columns_of(measure)
    known = f"o.{home_col} IS NOT NULL AND o.{away_col} IS NOT NULL"
    if not needs_corroboration(measure):
        return known
    if measure in STATS_MEASURES:
        return "(NOT o.extra_time AND sh.yellow_cards IS NOT NULL AND sa.yellow_cards IS NOT NULL)"
    return (f"(o.cards_source = 'events' AND {known} AND sh.yellow_cards IS NOT NULL AND sa.yellow_cards IS NOT NULL "
            "AND o.yellow_ft_home = sh.yellow_cards AND o.yellow_ft_away = sa.yellow_cards)")


def latest_kickoff(cutoff: datetime) -> datetime:
    """The latest kick-off whose result is known at ``cutoff``."""
    return cutoff - OUTCOME_KNOWN_AFTER


def load(conn: psycopg.Connection[Any], measure: str, *, since: datetime, cutoff: datetime, use_neutral: bool = False,
         with_referee: bool = False) -> dict[int, list[Match]]:
    """The finished matches of the followed competitions with a kick-off in ``[since, cutoff - OUTCOME_KNOWN_AFTER]``, by competition.

    ``use_neutral`` reads the neutral-venue flag (``core.fixtures.is_neutral``). It is off: the owner has not promoted the neutral-venue rule
    (plan F0, defect 1) and a family must not decide that for the goal models.
    """
    home_expr, away_expr = count_expressions(measure)
    referee = "fr.referee_id" if with_referee else "NULL::bigint"
    sql = (f"SELECT o.competition_id, o.fixture_id, o.kickoff_at, f.home_team_id, f.away_team_id, f.is_neutral, "
           f"{home_expr} AS home, {away_expr} AS away, {referee} AS referee_id "
           "FROM market.fixture_outcomes o JOIN core.fixtures f ON f.id = o.fixture_id "
           f"{STATS_JOIN if needs_corroboration(measure) else ''}{REFEREE_JOIN if with_referee else ''} "
           "WHERE o.is_tracked AND o.kickoff_at >= %(since)s AND o.kickoff_at <= %(latest)s "
           f"AND {complete_condition(measure)} "
           "ORDER BY o.competition_id, o.kickoff_at, o.fixture_id")
    out: dict[int, list[Match]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"since": since, "latest": latest_kickoff(cutoff)})
        for r in cur.fetchall():
            out.setdefault(int(r["competition_id"]), []).append(
                Match(int(r["fixture_id"]), r["kickoff_at"], int(r["home_team_id"]), int(r["away_team_id"]), int(r["home"]), int(r["away"]),
                      bool(r["is_neutral"]) if use_neutral else False, None if r["referee_id"] is None else int(r["referee_id"])))
    return out


def export_statement(measure: str, *, since: datetime, cutoff: datetime, use_neutral: bool = False, with_referee: bool = False) -> str:
    """The same read as ``load``, written as one ``COPY ... TO STDOUT`` statement (CSV, with a header) whose columns are those of
    ``scripts.families`` exports: to run it with ``psql`` where Python is not at hand, read-only, and bring the history out as a file. The
    window is written in as literals (they are instants made by the caller, not text from anywhere), so the statement is self-contained.
    """
    home_expr, away_expr = count_expressions(measure)
    start, latest = since.astimezone(UTC).isoformat(), latest_kickoff(cutoff).astimezone(UTC).isoformat()
    neutral = "CASE WHEN f.is_neutral THEN 1 ELSE 0 END" if use_neutral else "0"
    referee = ", fr.referee_id AS referee_id" if with_referee else ""
    return ("COPY (SELECT o.competition_id, o.fixture_id, "
            "to_char(o.kickoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS') || '+00:00' AS kickoff_at, "
            f"f.home_team_id AS home_id, f.away_team_id AS away_id, {home_expr} AS home, {away_expr} AS away, {neutral} AS neutral{referee} "
            "FROM market.fixture_outcomes o JOIN core.fixtures f ON f.id = o.fixture_id "
            f"{STATS_JOIN if needs_corroboration(measure) else ''}{REFEREE_JOIN if with_referee else ''} "
            f"WHERE o.is_tracked AND o.kickoff_at >= TIMESTAMPTZ '{start}' AND o.kickoff_at <= TIMESTAMPTZ '{latest}' "
            f"AND {complete_condition(measure)} "
            "ORDER BY o.competition_id, o.kickoff_at, o.fixture_id) "
            "TO STDOUT WITH (FORMAT csv, HEADER true)")
