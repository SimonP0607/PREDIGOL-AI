"""The news pipeline in shadow (IA-099 to IA-102), by hand. See ``fbi.news.pipeline``.

    python -m scripts.ia_news_stories report              # what is in news.*: stories by category and level, texts, queue (read-only)
    python -m scripts.ia_news_stories replay --days 14    # the grouping of stories-v1 over the web evidence of ai.evidence (read-only)
    python -m scripts.ia_news_stories run                 # ONE pass in shadow (needs FBI_NEWS_STORIES=shadow): reads and writes

``report`` and ``replay`` connect read-only and write nothing; ``run`` is the worker's pass. ``replay`` treats each address of the web
evidence as an article (its title as the search gave it, its teams and players, its type of claim) and groups them from scratch: the rate of
duplicates and of grouping the plan's file asks to measure. Nothing calls a model unless ``FBI_NEWS_TEXT=shadow`` and ``run``.
Exit 0; 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.news import canonical, evidence_reads, grouping, pipeline

REPORT_SQL = {
    "items": "SELECT count(*) FROM news.items",
    "stories": "SELECT count(DISTINCT story_key) FROM news.stories",
    "texts": "SELECT outcome, count(*) FROM news.story_texts GROUP BY 1 ORDER BY 1",
    "categories": ("SELECT category, level, count(*) FROM (SELECT DISTINCT ON (story_key) category, level FROM news.stories "
                   "ORDER BY story_key, version DESC) s GROUP BY 1, 2 ORDER BY 1, 2"),
    "status": ("SELECT status, count(*) FROM (SELECT DISTINCT ON (story_key) status FROM news.stories ORDER BY story_key, version DESC) s "
               "GROUP BY 1 ORDER BY 1"),
    "moderation": "SELECT action, coalesce(rule, '-'), count(*) FROM news.moderation_log GROUP BY 1, 2 ORDER BY 1, 2",
    "methods": "SELECT method, count(*) FROM news.item_story GROUP BY 1 ORDER BY 1",
}
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_news_stories", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dsn")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("report", help="what the news store holds")
    r = sub.add_parser("replay", help="group the web evidence of the last days from scratch")
    r.add_argument("--days", type=int, default=14)
    sub.add_parser("run", help="one pass in shadow")
    return ap


def _connect(dsn: str | None, *, read_only: bool) -> Any:
    import psycopg

    from fbi.core.config import settings as platform

    options = "-c default_transaction_read_only=on -c statement_timeout=95000" if read_only else "-c statement_timeout=120000"
    return psycopg.connect(dsn or platform.database.psycopg_url, options=options)


def report(conn: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    with conn.cursor() as cur:
        for name, sql in REPORT_SQL.items():
            cur.execute(sql)
            rows = cur.fetchall()
            out[name] = rows[0][0] if len(rows) == 1 and len(rows[0]) == 1 else [list(r) for r in rows]
    return out


def items_of(rows: Sequence[dict[str, Any]]) -> list[grouping.ItemSignal]:
    out = []
    for n, r in enumerate(rows, 1):
        try:
            url = canonical.canonical_url(str(r["source_url"]))
        except canonical.NotAnArticleUrlError:
            continue
        title = r["title"] or None
        codes = Counter(evidence_reads.claim_word(c, None) for c in (r["codes"] or []))
        kinds = Counter(evidence_reads.claim_word(None, k) for k in (r["kinds"] or []))
        claim = (codes or kinds).most_common(1)[0][0] if (codes or kinds) else None
        text = title if title and canonical.folded(title) else url
        out.append(grouping.ItemSignal(n, canonical.sha256_hex(url), canonical.fingerprint(text), str(r["domain"] or ""), r["seen_at"],
                                       r["published_at"], title, None, claim, frozenset(int(t) for t in r["teams"] or []),
                                       frozenset(int(p) for p in r["players"] or [])))
    return out


def replay(conn: Any, *, days: int, at: datetime) -> dict[str, Any]:
    from fbi.ai import gates

    rows = evidence_reads.web_by_address(conn, since=at - timedelta(days=days), typed=gates.typed_visible(conn))
    items = items_of(rows)
    out = grouping.measure(items).as_json()
    out.update({"days": days, "addresses": len(rows), "canonical_urls": len({i.url_sha256 for i in items})})
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    at = datetime.now(UTC)
    try:
        conn = _connect(args.dsn, read_only=args.command != "run")
    except Exception as exc:  # the database is the one thing this script needs
        print(json.dumps({"error": f"database: {type(exc).__name__}"}))
        return 2
    with conn:
        if args.command == "report":
            print(json.dumps(report(conn), ensure_ascii=False, default=str, indent=1))
        elif args.command == "replay":
            print(json.dumps(replay(conn, days=args.days, at=at), ensure_ascii=False, default=str, indent=1))
        else:
            if pipeline.mode() != "shadow":
                print(json.dumps({"error": "FBI_NEWS_STORIES is not shadow"}))
                return 2
            r = pipeline.run_pass(conn, at=at)
            conn.commit()
            print(json.dumps(r.as_json(), ensure_ascii=False, default=str, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
