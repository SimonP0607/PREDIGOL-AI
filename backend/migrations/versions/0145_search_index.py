"""Search index: ``unaccent``, ``pg_trgm`` and one table of names to search (plan 2026: AD-I01; IA-078)

WHY THIS EXISTS
---------------
The search of today (``GET /api/v1/search``) is three ``ILIKE '%q%'`` over competitions, teams and matches: no players, coaches,
referees or stadiums, no accents folded (``atletico`` does not find ``Atlético``) and no typo tolerated. PostgreSQL 16.15 in
production has ``unaccent`` 1.1 and ``pg_trgm`` 1.6 available and not installed; both are *trusted* extensions, so the owner of
the database (the role that runs the migrations) may create them (production, 16-nov-2026).

WHAT IS ADDED (nothing existing is changed)
-------------------------------------------
``unaccent`` and ``pg_trgm``           in schema ``public`` (as ``btree_gin`` and ``pgcrypto`` are), if they are not there.
``core.search_key(text)``              the one normalisation of a name: lower case, accents of Latin letters folded
    (``unaccent``), punctuation and spaces collapsed to one space. IMMUTABLE so that it can be stored and indexed: if the
    ``unaccent`` rules or the database's locale ever change, refresh the index (``scripts.search_index refresh``).
``core.search_entries``                a MATERIALIZED VIEW, one row per (kind, entity, name key): every name of every team,
    national team, player, competition, coach, referee and stadium - its own names (``name``, ``short_name``, first + last
    name), the old alias tables (``core.team_aliases``, ``core.referee_aliases``) and the names in force of IA-071
    (``core.entity_aliases_live``) - with what a hit shows (label, sublabel) and a popularity (matches in tracked
    competitions, 400 days back and 60 ahead). Created WITH NO DATA: this migration builds nothing and reads no big table.
    The first ``scripts.search_index refresh`` fills it (outside ``fixtures_sync`` and never 03:50-05:00 UTC), and then it is
    refreshed CONCURRENTLY (readers keep the old rows until the new ones are ready).
Four indexes on it: the unique key (needed by CONCURRENTLY), a btree on ``name_key text_pattern_ops`` (pass 1, prefix), a
GIN on ``to_tsvector('simple', name_key)`` (pass 2, words with prefix, no stemming) and a GIN ``gin_trgm_ops`` (pass 3,
trigrams).

Nothing here is read by a model, a forecast, a pick or a settlement. The only reader is ``GET /api/v1/search/v2`` (C-10) and
its private projection; ``GET /api/v1/search`` is not changed. News are not indexed: ``news.items`` (AD-G01) does not exist
yet, and the body of other people's articles is never indexed.

Downgrade drops the view and the function, and the two extensions only when nothing else uses them.

Revision ID: 0145
Revises: 0141 (IA-071, under review: it still revises 0137 beside 0139 of main; once it is re-chained on the head of main,
this one follows it unchanged)
"""

from __future__ import annotations

from alembic import op

revision = "0145"
down_revision = "0144"
branch_labels = None
depends_on = None

SEARCH_KEY_SQL = r"""
CREATE OR REPLACE FUNCTION core.search_key(raw TEXT) RETURNS TEXT
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $fn$
SELECT nullif(btrim(regexp_replace(lower(public.unaccent('public.unaccent'::regdictionary, raw)),
                                   '[[:space:][:punct:]]+', ' ', 'g')), '')
$fn$"""

ENTRIES_SQL = """
CREATE MATERIALIZED VIEW core.search_entries AS
WITH tracked_fx AS (
    SELECT f.id, f.home_team_id, f.away_team_id, f.venue_id
      FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND f.kickoff_at > now() - interval '400 days' AND f.kickoff_at < now() + interval '60 days'
), team_pop AS (
    SELECT team_id, count(*)::real AS n
      FROM (SELECT home_team_id AS team_id FROM tracked_fx UNION ALL SELECT away_team_id FROM tracked_fx) x
     GROUP BY team_id
), squad AS (
    SELECT DISTINCT ON (p.id) p.id AS player_id, t.name AS team, coalesce(tp.n, 0) AS pop
      FROM core.squad_members s
      JOIN core.players p ON p.provider_player_id = s.provider_player_id
      JOIN core.teams t ON t.id = s.team_id
      LEFT JOIN team_pop tp ON tp.team_id = t.id
     WHERE s.last_seen_at > now() - interval '180 days'
     ORDER BY p.id, t.is_national, coalesce(tp.n, 0) DESC, s.last_seen_at DESC
), coach_now AS (
    SELECT DISTINCT ON (cc.coach_id) cc.coach_id, t.name AS team, coalesce(tp.n, 0) AS pop
      FROM core.coach_careers cc
      JOIN core.teams t ON t.id = cc.team_id
      LEFT JOIN team_pop tp ON tp.team_id = t.id
     WHERE cc.coach_id IS NOT NULL AND cc.end_date IS NULL
     ORDER BY cc.coach_id, cc.observed_at DESC, cc.start_date DESC NULLS LAST
), ref_pop AS (
    SELECT fr.referee_id, count(DISTINCT fr.fixture_id)::real AS n
      FROM core.fixture_referees fr JOIN tracked_fx f ON f.id = fr.fixture_id
     WHERE fr.referee_id IS NOT NULL
     GROUP BY fr.referee_id
), venue_pop AS (
    SELECT venue_id, count(*)::real AS n FROM tracked_fx WHERE venue_id IS NOT NULL GROUP BY venue_id
), entities AS (
    SELECT 'team'::text AS entity_type, CASE WHEN t.is_national THEN 'national_team' ELSE 'team' END AS kind, t.id,
           t.name AS label, coalesce(t.country, '') AS sublabel, coalesce(tp.n, 0) AS popularity
      FROM core.teams t LEFT JOIN team_pop tp ON tp.team_id = t.id
    UNION ALL
    SELECT 'player', 'player', p.id, p.name, coalesce(sq.team, p.nationality, ''), coalesce(sq.pop, 0)
      FROM core.players p LEFT JOIN squad sq ON sq.player_id = p.id
    UNION ALL
    SELECT 'competition', 'competition', c.id, c.name, coalesce(c.country, ''),
           CASE WHEN c.is_tracked THEN 1000 ELSE 0 END::real
      FROM core.competitions c
    UNION ALL
    SELECT 'coach', 'coach', k.id, k.name, coalesce(cn.team, k.nationality, ''), coalesce(cn.pop, 0)
      FROM core.coaches k LEFT JOIN coach_now cn ON cn.coach_id = k.id
    UNION ALL
    SELECT 'referee', 'referee', r.id, r.name, '', coalesce(rp.n, 0)
      FROM core.referees r LEFT JOIN ref_pop rp ON rp.referee_id = r.id
     WHERE r.status = 'active'
    UNION ALL
    SELECT 'venue', 'venue', v.id, v.name, concat_ws(', ', nullif(v.city, ''), nullif(v.country, '')), coalesce(vp.n, 0)
      FROM core.venues v LEFT JOIN venue_pop vp ON vp.venue_id = v.id
     WHERE v.name IS NOT NULL
), names AS (
    SELECT 'team'::text AS entity_type, t.id AS entity_id, t.name AS name, 'official'::text AS alias_type
      FROM core.teams t
    UNION ALL SELECT 'team', t.id, t.short_name, 'short' FROM core.teams t WHERE t.short_name IS NOT NULL
    UNION ALL SELECT 'team', a.team_id, a.alias, 'alternative' FROM core.team_aliases a
    UNION ALL SELECT 'player', p.id, p.name, 'official' FROM core.players p
    UNION ALL SELECT 'player', p.id, concat_ws(' ', p.firstname, p.lastname), 'full'
      FROM core.players p WHERE p.firstname IS NOT NULL OR p.lastname IS NOT NULL
    UNION ALL SELECT 'competition', c.id, c.name, 'official' FROM core.competitions c
    UNION ALL SELECT 'coach', k.id, k.name, 'official' FROM core.coaches k
    UNION ALL SELECT 'coach', k.id, concat_ws(' ', k.firstname, k.lastname), 'full'
      FROM core.coaches k WHERE k.firstname IS NOT NULL OR k.lastname IS NOT NULL
    UNION ALL SELECT 'referee', r.id, r.name, 'official' FROM core.referees r
    UNION ALL SELECT 'referee', a.referee_id, a.display, 'alternative' FROM core.referee_aliases a
    UNION ALL SELECT 'venue', v.id, v.name, 'official' FROM core.venues v
    UNION ALL SELECT a.entity_type, a.entity_id, a.alias, a.alias_type FROM core.entity_aliases_live a
)
SELECT DISTINCT ON (e.kind, e.id, k.key)
       e.kind, e.id AS entity_id, e.label, e.sublabel, e.popularity, n.name AS matched_name, k.key AS name_key,
       n.alias_type,
       CASE n.alias_type WHEN 'official' THEN 0 WHEN 'full' THEN 1 WHEN 'short' THEN 1 WHEN 'code' THEN 2
                         WHEN 'nickname' THEN 2 WHEN 'transliteration' THEN 3 WHEN 'localized' THEN 3 ELSE 4 END
           ::smallint AS alias_rank,
       now() AS indexed_at
  FROM names n
  JOIN entities e ON e.entity_type = n.entity_type AND e.id = n.entity_id
 CROSS JOIN LATERAL (SELECT core.search_key(n.name) AS key) k
 WHERE k.key IS NOT NULL
 ORDER BY e.kind, e.id, k.key,
          CASE n.alias_type WHEN 'official' THEN 0 WHEN 'full' THEN 1 WHEN 'short' THEN 1 WHEN 'code' THEN 2
                            WHEN 'nickname' THEN 2 WHEN 'transliteration' THEN 3 WHEN 'localized' THEN 3 ELSE 4 END,
          n.name
WITH NO DATA"""

INDEXES = (
    "CREATE UNIQUE INDEX search_entries_key ON core.search_entries (kind, entity_id, name_key)",
    "CREATE INDEX search_entries_prefix ON core.search_entries (name_key text_pattern_ops)",
    "CREATE INDEX search_entries_words ON core.search_entries USING gin (to_tsvector('simple'::regconfig, name_key))",
    "CREATE INDEX search_entries_trgm ON core.search_entries USING gin (name_key public.gin_trgm_ops)",
)


def upgrade() -> None:
    # A live database: never wait for a lock while holding others (see revision 0076). Nothing existing is locked beyond
    # the catalogue: the view is created empty (WITH NO DATA) and its indexes are built on nothing.
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    # [:punct:] in the database's UTF-8 locale (en_US.utf8 in production) is every punctuation mark and symbol, not only
    # ASCII: a curly apostrophe, «Kanté», a dash or an acute accent all become a space (checked on PostgreSQL 16, 17-nov-2026).
    op.execute(SEARCH_KEY_SQL)
    op.execute("""
        COMMENT ON FUNCTION core.search_key(TEXT) IS
        'AD-I01 (IA-078): the one normalisation of a name for the search - lower case, accents of Latin letters folded
         (unaccent), punctuation and spaces collapsed to one space; NULL when nothing is left. Other alphabets keep their
         letters (unaccent does not transliterate: Cyrillic, Arabic or Korean names are found through their aliases).
         IMMUTABLE so that it can be stored: refresh core.search_entries if the unaccent rules or the locale change.'""")
    op.execute(ENTRIES_SQL)
    for index in INDEXES:
        op.execute(index)
    op.execute("""
        COMMENT ON MATERIALIZED VIEW core.search_entries IS
        'AD-I01 (IA-078): one row per (kind, entity, name key) - every name of every team (kind team or national_team),
         player, competition, coach, referee (active) and stadium: own names, core.team_aliases, core.referee_aliases and
         core.entity_aliases_live (IA-071). label/sublabel are what a hit shows; popularity = matches in tracked
         competitions (400 days back, 60 ahead) of the entity, of the current team of a player or coach, or 1000 for a
         tracked competition; alias_rank orders official < full/short < code/nickname < transliteration/localized < rest;
         indexed_at = when it was refreshed. Created empty; filled and refreshed by python -m scripts.search_index refresh
         (CONCURRENTLY after the first time). Read only by GET /api/v1/search/v2 (C-10).'""")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS core.search_entries")
    op.execute("DROP FUNCTION IF EXISTS core.search_key(TEXT)")
    # The extensions go only when nothing else uses them (RESTRICT is the default: a dependent object keeps them).
    for extension in ("pg_trgm", "unaccent"):
        op.execute(f"""
            DO $do$ BEGIN
                DROP EXTENSION IF EXISTS {extension};
            EXCEPTION WHEN dependent_objects_still_exist THEN
                RAISE NOTICE '{extension} kept: other objects use it';
            END $do$""")
