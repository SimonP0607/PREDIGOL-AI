from __future__ import annotations

from fbi.api.repositories import Conn, Row, fetch_all


def search(conn: Conn, q: str, limit: int) -> list[Row]:
    pattern = f"%{q}%"
    return fetch_all(conn, """
        (SELECT 'competition' AS type, c.id, c.name AS label, COALESCE(c.country, '') AS sublabel, 0 AS rank
           FROM core.competitions c WHERE c.name ILIKE %(p)s ORDER BY c.is_tracked DESC, c.name LIMIT %(l)s)
        UNION ALL
        (SELECT 'team', t.id, t.name, COALESCE(t.country, ''), 1
           FROM core.teams t WHERE t.name ILIKE %(p)s ORDER BY t.name LIMIT %(l)s)
        UNION ALL
        (SELECT 'fixture', f.id, th.name || ' v ' || ta.name,
                to_char(f.kickoff_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') || ' UTC', 2
           FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
           WHERE th.name ILIKE %(p)s OR ta.name ILIKE %(p)s
           ORDER BY abs(extract(epoch FROM f.kickoff_at - now())) LIMIT %(l)s)
    """, {"p": pattern, "l": limit})
