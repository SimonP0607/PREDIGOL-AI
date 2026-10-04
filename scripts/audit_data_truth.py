"""The data truth audit V2 - repeatable checks of what PrediGol holds against the provider.

    python -m scripts.audit_data_truth baseline    # counts, spans, latest stamps of every table (read only)
    python -m scripts.audit_data_truth leagues     # /leagues vs every tracked competition (1 request)
    python -m scripts.audit_data_truth fixtures    # every current season's list + a sample per status
    python -m scripts.audit_data_truth identity    # duplicates, collisions, flags, squads + provider samples
    python -m scripts.audit_data_truth fields      # what the normalizers drop (RAW on disk, 0 requests)
    python -m scripts.audit_data_truth golden      # golden dataset: 7 competitions x 3 seasons, three ways
    python -m scripts.audit_data_truth golden --decisions FILE.json   # + official decisions off the pitch
    python -m scripts.audit_data_truth ledger      # the evidence ledger, open entries first (read only)

The provider-facing audits of the three priorities have their own commands:
``scripts.audit_standings``, ``scripts.audit_team_stats``, ``scripts.audit_player_stats``.
Every report lands under ``data/truth/<stamp>-<kind>/`` (JSON + Markdown); provider answers are
stored as NEW raw payloads; nothing in core, market or features is written.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.truth.baseline import baseline, markdown
from fbi.truth.findings import Tally
from fbi.truth.v2 import fields as fl
from fbi.truth.v2 import fixtures as fx
from fbi.truth.v2 import identity as idn
from fbi.truth.v2 import leagues as lg
from fbi.truth.v2.ledger import clear_unseen, record_all
from fbi.truth.v2.runner import V2Run, write_report

REPORTS = Path("data/truth")
REPO = Path(__file__).resolve().parents[1]


def _connect(*, read_only: bool = False) -> psycopg.Connection[Any]:
    opts = "-c statement_timeout=600000 -c TimeZone=UTC"
    if read_only:
        opts += " -c default_transaction_read_only=on"
    return psycopg.connect(settings.database.psycopg_url, options=opts, autocommit=True)


def cmd_baseline(_: argparse.Namespace) -> int:
    at = now()
    with _connect(read_only=True) as conn:
        b = baseline(conn, at=at)
    md = markdown(b)
    folder = write_report(REPORTS, "baseline", at, b, md)
    print(md)
    print(json.dumps(b["extra"], default=str, indent=1))
    print(f"report: {folder}")
    return 0


async def _with_client(kind: str, body: Any, max_requests: int) -> int:
    from fbi.providers.api_football.build import build_client

    client = build_client(max_requests=max_requests) if max_requests else None
    try:
        with _connect() as conn:
            run = V2Run(conn, client, kind, now())
            try:
                summary, evidence, md = await body(run, conn)
            except BaseException:
                run.finish({"error": "interrupted or failed"}, failed=True)
                raise
            codes = record_all(conn, evidence, at=run.at, run_id=run.run_id)
            if not run.stopped and not run.failures:
                clear_unseen(conn, area=kind if kind != "fields" else "normalization",
                             scope_prefix=f"{kind if kind != 'fields' else 'normalization'}:", seen=codes.keys(),
                             at=run.at)
            summary = {**summary, "requests": run.requests, "stopped": run.stopped, "failures": run.failures[:20],
                       "evidence": codes}
            folder = write_report(REPORTS, kind, run.at, summary, md + ("\nEvidence: " + " ".join(sorted(
                codes.values())) + "\n" if codes else ""))
            status = run.finish({k: v for k, v in summary.items() if k != "rows"}, report_dir=folder)
    finally:
        if client is not None:
            await client.aclose()
    print(json.dumps({"status": status, "requests": run.requests, "evidence": len(codes), "report": str(folder),
                      **{k: v for k, v in summary.items() if k in ("labels", "totals", "strata", "classes")}},
                     indent=1, default=str))
    return 0 if status == "completed" else 1


async def _leagues(run: V2Run, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Any], str]:
    answer = await run.get("/leagues", {})
    items = {int(i["league"]["id"]): i for i in (answer.items if answer else [])
             if isinstance(i.get("league"), dict) and isinstance(i["league"].get("id"), int)}
    comps, seasons = lg.ours(conn)
    verdicts = [lg.judge(c, items.get(int(c["provider_league_id"])), seasons.get(int(c["provider_league_id"]), []))
                for c in comps]
    dups = lg.duplicates(comps)
    labels: dict[str, int] = {}
    for v in verdicts:
        for label in v.labels:
            labels[label] = labels.get(label, 0) + 1
    md = [f"# Leagues and seasons - {len(comps)} tracked competitions, {len(items):,} listed by the provider", "",
          f"Labels: {labels or 'none'}; duplicate groups: {len(dups)}", "", "| League | Labels | Notes |",
          "|---|---|---|"]
    md += [f"| {v.name} ({v.league}) | {', '.join(v.labels)} | {'; '.join(v.notes)} |" for v in verdicts if v.labels]
    summary = {"tracked": len(comps), "listed": len(items), "labels": labels, "duplicates": dups,
               "rows": [v.__dict__ for v in verdicts]}
    return summary, lg.evidence(verdicts, dups, answer.ref() if answer else None), "\n".join(md) + "\n"


async def _fixtures(run: V2Run, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Any], str]:
    fixtures, results = Tally("fixtures"), Tally("results")
    seasons = fx.current_seasons(conn)
    totals = await fx.run_lists(run, conn, seasons, fixtures, results)
    strata = fx.sample_ids(conn, at=run.at)
    per = await fx.run_sample(run, conn, strata, fixtures, results)
    md = [f"# Fixtures and results - {totals['seasons']} current seasons, {totals['api']:,} fixtures listed, "
          f"{totals['db']:,} held", "",
          f"Fixtures: checked {fixtures.checked:,}, matched {fixtures.matched:,}, findings {fixtures.total_findings}",
          f"Results: checked {results.checked:,}, matched {results.matched:,}, findings {results.total_findings}", "",
          "| Stratum | Fixtures | Findings |", "|---|---:|---:|"]
    md += [f"| {k} | {v['fixtures']} | {v['findings']} |" for k, v in per.items()]
    summary = {"totals": totals, "strata": per,
               "fixtures": {"checked": fixtures.checked, "matched": fixtures.matched,
                            "by_kind": fixtures.by_kind()},
               "results": {"checked": results.checked, "matched": results.matched, "by_kind": results.by_kind()},
               "rows": [f.as_dict() for f in fixtures.findings[:500] + results.findings[:500]]}
    return summary, fx.evidence(fixtures, results, {"endpoint": "/fixtures", "seasons": totals["seasons"]}), \
        "\n".join(md) + "\n"


async def _identity(run: V2Run, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Any], str]:
    checks = idn.db_checks(conn)
    tallies = await idn.provider_samples(run, conn, idn.sample(conn))
    md = ["# Entity identity", ""]
    for name, rows in checks.items():
        md.append(f"* **{name}**: " + (json.dumps(rows[:3], default=str) if rows else "none"))
    md += ["", "Provider samples: " + ", ".join(f"{k} {t.matched}/{t.checked} match" for k, t in tallies.items())]
    summary = {"checks": checks, "samples": {k: {"checked": t.checked, "matched": t.matched,
                                                 "findings": [f.as_dict() for f in t.findings], "notes": t.notes}
                                             for k, t in tallies.items()}}
    return summary, idn.evidence(checks, tallies, run.at), "\n".join(md) + "\n"


async def _fields(run: V2Run, conn: psycopg.Connection[Any]) -> tuple[dict[str, Any], list[Any], str]:
    raw_root = Path(settings.runtime.raw_store_dir)
    raw_root = raw_root if raw_root.is_absolute() else REPO / raw_root
    used = fl.used_columns(REPO / "src" / "fbi")
    rows: list[fl.FieldRow] = []
    for endpoint, ids_only in (("/fixtures", True), ("/standings", None), ("/injuries", None)):
        rows += fl.inventory(endpoint, fl.load_bodies(conn, raw_root, endpoint, ids_only=ids_only), used_columns=used)
    classes: dict[str, int] = {}
    for r in rows:
        classes[r.klass] = classes.get(r.klass, 0) + 1
    md = ["# Fields: provider -> normalizer -> database -> use", "",
          "| Endpoint | Field | API present | Normalized / stored | Used | Class |", "|---|---|---|---|---|---|"]
    md += [f"| {r.endpoint} | `{r.path}` | {r.present}/{r.seen} | {r.rule} | "
           f"{'-' if r.used is None else 'yes' if r.used else 'no'} | {r.klass} |" for r in rows]
    summary = {"classes": classes, "rows": [r.__dict__ | {"klass": r.klass} for r in rows]}
    return summary, fl.evidence(rows), "\n".join(md) + "\n"


async def _golden(run: V2Run, conn: psycopg.Connection[Any], decisions: str | None = None,
                  ) -> tuple[dict[str, Any], list[Any], str]:
    import httpx

    from fbi.ingestion.payload_store import PayloadStore
    from fbi.truth.v2 import golden as gd
    from fbi.truth.v2 import standings as st

    store = PayloadStore(settings.runtime.raw_store_dir, provider="football-data")
    official = st.load_decisions(decisions)
    seasons = []
    with httpx.Client(timeout=30, headers={"user-agent": gd.USER_AGENT}, follow_redirects=True) as http:
        for league in gd.GOLDEN:
            for season in gd.SEASONS:
                seasons.append(await gd.validate(run, conn, league, season, http=http, store=store,
                                                 decisions=official))
    rows = gd.summary_rows(seasons)
    verdicts: dict[str, int] = {}
    for g in seasons:
        verdicts[g.verdict] = verdicts.get(g.verdict, 0) + 1
    md = [f"# Golden validation dataset - {len(seasons)} competition-seasons", "",
          "| Competition | Season | Verdict | Score | Fixtures (matched/checked) | Results | Final table | "
          "Football-Data (matched / rows / score disagree / other) |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        f, res, tb, ex = r["fixtures"], r["results"], r["table"], r["external"]
        md.append(f"| {r['name']} ({r['league']}) | {r['season']} | **{r['verdict']}** | {r['score']} | {f[2]}/{f[3]} "
                  f"(API {f[0]}, DB {f[1]}) | {res[0]}/{res[1]} | {tb[0]}/{tb[1]} {tb[2]} | "
                  f"{'-' if ex[1] is None else f'{ex[0]} / {ex[1]} / {ex[2]} / {ex[3]}'} |")
    decided = [(r, o) for r in rows for o in r["official"]]
    if decided:
        md += ["", "Results decided off the pitch, counted at their official score (our fixtures keep the played one):",
               ""] + [f"* {r['name']} {r['season']} - {o}" for r, o in decided]
    return {"verdicts": verdicts, "labels": verdicts, "rows": rows}, gd.evidence(seasons), "\n".join(md) + "\n"


def cmd_ledger(_: argparse.Namespace) -> int:
    with _connect(read_only=True) as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT code, status, severity, at_fault, area, issue_type, claim FROM audit.evidence_ledger "
                    "ORDER BY status <> 'OPEN', array_position(ARRAY['critical','high','medium','low','info'], "
                    "severity), id")
        for r in cur.fetchall():
            print(f"{r['code']} {r['status']:<8} {r['severity']:<8} {r['at_fault']:<12} {r['area']:<13} "
                  f"{r['issue_type']:<26} {r['claim'][:140]}")
    return 0


ASYNC = {"leagues": (_leagues, 5), "fixtures": (_fixtures, 400), "identity": (_identity, 60), "fields": (_fields, 0),
         "golden": (_golden, 60)}


def main() -> int:
    parser = argparse.ArgumentParser(prog="audit_data_truth", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=sorted(["baseline", "ledger", *ASYNC]))
    parser.add_argument("--max-requests", type=int, default=None)
    parser.add_argument("--decisions", help="golden: official results decided off the pitch (JSON)")
    args = parser.parse_args()
    if args.command == "baseline":
        return cmd_baseline(args)
    if args.command == "ledger":
        return cmd_ledger(args)
    body, cap = ASYNC[args.command]
    if args.command == "golden":
        body = functools.partial(_golden, decisions=args.decisions)
    return asyncio.run(_with_client(args.command, body, args.max_requests if args.max_requests is not None else cap))


if __name__ == "__main__":
    sys.exit(main())
