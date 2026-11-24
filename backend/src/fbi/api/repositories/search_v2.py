"""The queries of the search v2 (C-10; AD-I01/AD-I02, IA-078): ``core.search_entries`` in three passes, the matches of the
teams found, and the suggestion when nothing is found.

The three passes, over the name key (``core.search_key``: lower case, no accents, no punctuation):

1. ``prefijo``   - the key starts with the query's key (``atletico`` -> ``atletico madrid``); btree ``text_pattern_ops``.
2. ``palabras``  - every word of the query begins a word of the name, in any order (``jam rod`` -> ``james rodriguez``);
   GIN on ``to_tsvector('simple', name_key)``, no stemming. Only from 3 letters of key or two words: one or two letters
   alone are pass 1 only (a two-letter prefix of any word matches a large share of the index).
3. ``trigramas`` - ``word_similarity(query, name) >= TRIGRAM_THRESHOLD`` (typos: ``mesi`` -> ``messi``); GIN
   ``gin_trgm_ops``. From 4 letters of key.

Each entity keeps its best pass; within a group the order is ``rank`` (``POPULARITY_WEIGHT``: the pass and its closeness,
the kind of name - official < full/short < code/nickname < transliteration/localized < other - and the popularity), then
the shorter label. In ``national_teams`` the senior team comes first (C-10 1.1, AP-B07): an age-group or women's team
(« U21», « W» in the provider's name) goes after every senior hit unless the query itself asks for one (``sub 21``, ``u21``,
``femenina``, ``women``…).
Everything is parametrised; the query is normalised in SQL by the same function the index was built with, so the two can
never disagree.
"""

from __future__ import annotations

from typing import Final

from fbi.api.repositories import Conn, Row, fetch_all, fetch_one

TRIGRAM_THRESHOLD: Final = 0.6
"""The initial threshold of pass 3 (plan AD-I02: 0.6, to be calibrated with the bank of labelled queries). It is also
``pg_trgm``'s default ``word_similarity_threshold``, so the index operator and the filter agree."""

POPULARITY_WEIGHT: Final = 0.35
"""How much popularity weighs in the order of a group: rank = match (prefix 1.0, words 0.9, trigrams 0.85 x similarity)
+ 0.15 when the name is the query / 0.10 when the query is a whole word of it - 0.03 x kind of name + 0.35 x popularity on
a log scale capped at 100 matches. A popular team found by its words beats an
unknown one found by its prefix; a typo still ranks below an exact hit of the same popularity."""

SUGGEST_THRESHOLD: Final = 0.3
"""«¿Quisiste decir…?»: the closest name above this similarity, only when no group has a hit."""

MIN_TRIGRAM_KEY: Final = 4
MIN_WORDS_KEY: Final = 3

STATE_SQL = """
SELECT c.relispopulated AS populated, c.reltuples::bigint AS rows_estimate
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'core' AND c.relname = 'search_entries' AND c.relkind = 'm'
"""

KEY_SQL = "SELECT core.search_key(%(q)s) AS key"

ENTITIES_SQL = """
WITH q AS (SELECT %(key)s::text AS key,
                  %(key)s::text ~ '(^| )(u ?[0-9][0-9]|sub ?[0-9][0-9]|w|women|womens|femenina|femenino|femenil)( |$)' AS asks_junior),
words AS (
    SELECT to_tsquery('simple', string_agg(quote_literal(w) || ':*', ' & ')) AS tq
      FROM q, regexp_split_to_table(q.key, ' ') AS w
     WHERE w <> ''
),
hits AS (
    SELECT e.kind, e.entity_id, e.label, e.sublabel, e.popularity, e.matched_name, e.name_key, e.alias_type,
           e.alias_rank, 0 AS pass, 1.0::real AS score
      FROM core.search_entries e, q
     WHERE e.name_key LIKE %(prefix)s
    UNION ALL
    SELECT e.kind, e.entity_id, e.label, e.sublabel, e.popularity, e.matched_name, e.name_key, e.alias_type,
           e.alias_rank, 1, 0.9::real
      FROM core.search_entries e, words
     WHERE %(words)s AND to_tsvector('simple'::regconfig, e.name_key) @@ words.tq
    UNION ALL
    SELECT e.kind, e.entity_id, e.label, e.sublabel, e.popularity, e.matched_name, e.name_key, e.alias_type,
           e.alias_rank, 2, public.word_similarity(q.key, e.name_key)
      FROM core.search_entries e, q
     WHERE %(trigrams)s AND e.name_key OPERATOR(public.%%>) q.key
       AND public.word_similarity(q.key, e.name_key) >= %(threshold)s
),
scored AS (
    SELECT h.*,
           (CASE h.pass WHEN 0 THEN 1.0 WHEN 1 THEN 0.9 ELSE 0.85 * h.score END)
           + CASE WHEN h.name_key = q.key THEN 0.15
                  WHEN position(' ' || q.key || ' ' IN ' ' || h.name_key || ' ') > 0 THEN 0.1 ELSE 0 END
           - 0.03 * h.alias_rank AS quality
      FROM hits h, q
),
best AS (
    SELECT DISTINCT ON (kind, entity_id) *
      FROM scored
     ORDER BY kind, entity_id, quality DESC, matched_name
),
ranked AS (
    SELECT best.*,
           row_number() OVER (PARTITION BY kind ORDER BY junior, rank DESC, length(label), label, entity_id) AS rn
      FROM (SELECT b.*, b.quality + %(pop_weight)s * least(1.0, ln(1 + b.popularity) / ln(101.0)) AS rank,
                   CASE WHEN b.kind = 'national_team' AND NOT q.asks_junior AND b.label ~ ' (W|U[0-9][0-9])( |$)'
                        THEN 1 ELSE 0 END AS junior
              FROM best b, q) best
)
SELECT kind, entity_id, label, sublabel, popularity, matched_name, alias_type, pass, score, rank
  FROM ranked
 WHERE rn <= %(per_group)s
 ORDER BY kind, rn
"""

FIXTURES_SQL = """
WITH fx AS (SELECT f.id FROM core.fixtures f WHERE f.home_team_id = ANY(%(teams)s)
            UNION
            SELECT f.id FROM core.fixtures f WHERE f.away_team_id = ANY(%(teams)s))
SELECT f.id, f.kickoff_at, f.home_team_id, f.away_team_id, th.name AS home, ta.name AS away, c.name AS competition
  FROM fx JOIN core.fixtures f ON f.id = fx.id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
 ORDER BY abs(extract(epoch FROM f.kickoff_at - now())), f.id
 LIMIT %(limit)s
"""
"""The matches of the teams found (the best ones of each group, at most 8), nearest to now first - the same path through the
(team, kick-off) indexes as the search of today (about 30 ms, 7-oct-2026)."""

SUGGEST_SQL = """
SELECT e.matched_name, public.similarity(e.name_key, %(key)s) AS score
  FROM core.search_entries e
 WHERE e.name_key OPERATOR(public.%%) %(key)s AND public.similarity(e.name_key, %(key)s) >= %(threshold)s
 ORDER BY score DESC, e.popularity DESC, e.matched_name
 LIMIT 3
"""


INDEXED_AT_SQL = "SELECT e.indexed_at FROM core.search_entries e LIMIT 1"
"""Read only once the view is populated: an unpopulated one refuses even a plan that would never scan it."""


def index_state(conn: Conn) -> Row | None:
    """Whether the index exists and has rows (``populated``), when it was refreshed and its size; None: no index."""
    state = fetch_one(conn, STATE_SQL)
    if state is not None:
        found = fetch_one(conn, INDEXED_AT_SQL) if state["populated"] else None
        state["indexed_at"] = None if found is None else found["indexed_at"]
    return state


def search_key(conn: Conn, q: str) -> str | None:
    row = fetch_one(conn, KEY_SQL, {"q": q})
    return None if row is None else row["key"]


def like_prefix(key: str) -> str:
    """``key%`` for pass 1 as a bound constant, so that the btree ``text_pattern_ops`` serves it. A key has no ``%``, ``_``
    or backslash (``core.search_key`` turns punctuation into spaces); they are escaped anyway."""
    return key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def passes_for(key: str) -> tuple[bool, bool]:
    """Whether passes 2 (words) and 3 (trigrams) run for this key."""
    parts = key.split()
    words = len(parts) >= 2 or len(key) >= MIN_WORDS_KEY
    return words, len("".join(parts)) >= MIN_TRIGRAM_KEY


def entities(conn: Conn, key: str, per_group: int, threshold: float = TRIGRAM_THRESHOLD) -> list[Row]:
    words, trigrams = passes_for(key)
    conn.execute("SELECT set_config('pg_trgm.word_similarity_threshold', %s, true)", (str(threshold),))
    return fetch_all(conn, ENTITIES_SQL, {"key": key, "prefix": like_prefix(key), "words": words, "trigrams": trigrams, "threshold": threshold,
                                          "per_group": per_group, "pop_weight": POPULARITY_WEIGHT})


def fixtures(conn: Conn, team_ids: list[int], limit: int) -> list[Row]:
    if not team_ids:
        return []
    return fetch_all(conn, FIXTURES_SQL, {"teams": team_ids, "limit": limit})


def suggestions(conn: Conn, key: str) -> list[Row]:
    if len(key.replace(" ", "")) < MIN_TRIGRAM_KEY - 1:
        return []
    conn.execute("SELECT set_config('pg_trgm.similarity_threshold', %s, true)", (str(SUGGEST_THRESHOLD),))
    return fetch_all(conn, SUGGEST_SQL, {"key": key, "threshold": SUGGEST_THRESHOLD})
