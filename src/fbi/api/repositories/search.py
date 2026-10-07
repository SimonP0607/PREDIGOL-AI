from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all


def search(conn: Conn, q: str, limit: int) -> list[Row]:
    # Fixtures: the matching teams first (8k rows), then their fixtures through the (team, kick-off) indexes. Joining
    # every fixture to both teams' names first scanned all 245k fixtures per keystroke: 0.25 s alone, 6-11 s under
    # the rehearsal's load (7 Oct 2026); this takes ~30 ms.
    pattern = f"%{q}%"
    return fetch_all(conn, """
        (SELECT 'competition' AS type, c.id, c.name AS label, COALESCE(c.country, '') AS sublabel, 0 AS rank
           FROM core.competitions c WHERE c.name ILIKE %(p)s ORDER BY c.is_tracked DESC, c.name LIMIT %(l)s)
        UNION ALL
        (SELECT 'team', t.id, t.name, COALESCE(t.country, ''), 1
           FROM core.teams t WHERE t.name ILIKE %(p)s ORDER BY t.name LIMIT %(l)s)
        UNION ALL
        (WITH tm AS (SELECT t.id FROM core.teams t WHERE t.name ILIKE %(p)s),
              fx AS (SELECT f.id FROM core.fixtures f WHERE f.home_team_id IN (SELECT id FROM tm)
                     UNION
                     SELECT f.id FROM core.fixtures f WHERE f.away_team_id IN (SELECT id FROM tm))
         SELECT 'fixture', f.id, th.name || ' v ' || ta.name,
                to_char(f.kickoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') || ' UTC', 2
           FROM fx JOIN core.fixtures f ON f.id = fx.id
           JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
          ORDER BY abs(extract(epoch FROM f.kickoff_at - now())), f.id LIMIT %(l)s)
    """, {"p": pattern, "l": limit})
