"""PM-05-03: compare, by hand and by machine, the corners of each half the settlement view gives with the answer the provider sent.

    python -m scripts.corners_halves_check --n 100            # 100 finished matches with known halves, newest first, at random
    python -m scripts.corners_halves_check --n 100 --seed 7   # the same sample again

Read only. For each match drawn it prints the four figures of ``market.fixture_outcomes`` (first and second half, home and away) beside the same
four read again from the RAW answer the figures were kept from (``fbi.providers.api_football.period_stats``), and how many matches agree. The
ficha asks 100 matches compared by hand before the switch ``FBI_CORNERS_BY_HALF`` is turned on: the printed table is that comparison, and
any row that does not agree is a reason not to turn it on. Memory: one answer at a time.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

SAMPLE_SQL = """
SELECT o.fixture_id, f.provider_fixture_id, th.provider_team_id, ta.provider_team_id, o.corners_1h_home, o.corners_1h_away,
       o.corners_2h_home, o.corners_2h_away, a.payload_hash, p.file_path
  FROM market.fixture_outcomes o
  JOIN core.fixtures f ON f.id = o.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.fixture_period_asks a ON a.fixture_id = o.fixture_id
  JOIN raw.ingestion_payloads p ON p.hash = a.payload_hash
 WHERE o.corners_1h_home IS NOT NULL AND o.corners_2h_home IS NOT NULL
 ORDER BY md5(o.fixture_id::text || %(seed)s) LIMIT %(n)s
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n", type=int, default=100)
    parser.add_argument("--seed", default="0")
    args = parser.parse_args(argv)

    import psycopg

    from fbi.core.config import settings
    from fbi.providers.api_football.period_stats import parse_period_answer
    from fbi.storage.payload_store import PayloadStore

    store = PayloadStore(settings.runtime.raw_store_dir)
    agree = disagree = unreadable = 0
    with psycopg.connect(settings.database.psycopg_url, connect_timeout=10, application_name="corners_halves_check") as conn:
        conn.execute("SET default_transaction_read_only = on")
        rows = conn.execute(SAMPLE_SQL, {"n": args.n, "seed": args.seed}).fetchall()
    print("fixture  provider_id   view 1H (h-a)  view 2H (h-a)   RAW 1H (h-a)   RAW 2H (h-a)   agree")
    for fid, provider_fixture, home_id, away_id, v1h, v1a, v2h, v2a, _hash, path in rows:
        try:
            body = (store.load(str(path)) or {}).get("body") or {}
        except (OSError, ValueError):
            unreadable += 1
            continue
        answer = parse_period_answer(body, int(provider_fixture))
        by_team = {t.provider_team_id: t for t in answer.teams}
        h, a = by_team.get(int(home_id)), by_team.get(int(away_id))

        def value(team: object, half: str) -> int | None:
            block = getattr(team, half, None)
            found = None if block is None else block.get("corners")
            return None if found is None else int(found)

        raw = (value(h, "first"), value(a, "first"), value(h, "second"), value(a, "second"))
        view = (v1h, v1a, v2h, v2a)
        same = all(r is not None and r == int(v) for r, v in zip(raw, view, strict=True))
        agree += same
        disagree += not same
        print(f"{fid:<8} {provider_fixture:<12} {v1h:>5}-{v1a:<5}     {v2h:>5}-{v2a:<5}     {raw[0]!s:>5}-{raw[1]!s:<5}    {raw[2]!s:>5}-{raw[3]!s:<5}    "
              f"{'yes' if same else 'NO'}")
    print(f"compared {agree + disagree}: {agree} agree, {disagree} differ; {unreadable} RAW files unreadable")
    return 1 if disagree or unreadable else 0


if __name__ == "__main__":
    sys.exit(main())
