"""The registry of sources (IA-062) and its policy (IA-063), from the command line.

    python -m scripts.ia_sources_load load                 # after a deploy: the pinned directory and exclusion list (idempotent)
    python -m scripts.ia_sources_load load --dry-run       # what it would load, without writing
    python -m scripts.ia_sources_load status               # versions in force, counts per state, signatures, switches
    python -m scripts.ia_sources_load check-url https://www.marca.com/futbol/...   # what the policy says of one page
    python -m scripts.ia_sources_load tiers                # the tier the directory implies vs ai.sources (tiers-v1): a report
    python -m scripts.ia_sources_load shadow --days 14     # what the policy blocked or would have blocked (ai.source_policy_log)
    python -m scripts.ia_sources_load sign --source bra-agencia-brasil-esportes --reason "..." --confirm-owner
    python -m scripts.ia_sources_load sign --revoke --source ... --reason "..." --confirm-owner
    python -m scripts.ia_sources_load sign-exclusion --reason "..." --confirm-owner

``load`` and the two ``sign`` commands are the only ones that write, and only to the append-only tables of migration 0139; ``sign`` refuses
without ``--confirm-owner`` (only the owner moves a source to authorised). Every other command opens the database read-only. Nothing here
calls a model, Exa or a web page. Exit 0; 1 when a check fails (a file that is not the pinned one, a source not in the registry); 2 when it
cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import tuple_row

from fbi.ai import source_policy as policy
from fbi.ai import source_registry as registry

OK, NO, CANNOT = 0, 1, 2
WRITES = ("load", "sign", "sign-exclusion")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_sources_load", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("load", "status", "check-url", "tiers", "shadow", "sign", "sign-exclusion"))
    ap.add_argument("url", nargs="?", help="check-url: the page")
    ap.add_argument("--dry-run", action="store_true", help="load: read and check the files, write nothing")
    ap.add_argument("--source", action="append", default=[], help="sign: a source id (repeatable)")
    ap.add_argument("--revoke", action="store_true", help="sign: take the authorisation back")
    ap.add_argument("--reason", default="", help="sign: why (3 to 500 characters)")
    ap.add_argument("--confirm-owner", action="store_true", help="sign: I am the owner and I sign it")
    ap.add_argument("--days", type=int, default=14, help="shadow: the window (default 14)")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def _code_version() -> str | None:
    import os

    return os.environ.get("FBI_CODE_VERSION")


def cmd_load(conn: psycopg.Connection[Any] | None, args: argparse.Namespace, at: datetime) -> tuple[dict[str, Any], int]:
    try:
        directory = registry.bundled_directory()
        rules = registry.bundled_exclusion()
    except (OSError, registry.RegistryError) as exc:
        return {"error": str(exc)}, NO
    planned = {"directory": {"version": registry.DIRECTORY.version, "file": registry.DIRECTORY.file, **directory.counts()},
               "exclusion": {"version": registry.EXCLUSION.version, "file": registry.EXCLUSION.file, **registry.exclusion_counts(rules)}}
    if args.dry_run or conn is None:
        return {"dry_run": True, "planned": planned}, OK
    done = [registry.load_directory(conn, directory, at=at, file_name=registry.DIRECTORY.file, code_version=_code_version()),
            registry.load_exclusion(conn, rules, version=registry.EXCLUSION.version, sha256=registry.EXCLUSION.sha256, at=at,
                                    file_name=registry.EXCLUSION.file, code_version=_code_version())]
    conn.commit()
    return {"loaded": [{"kind": d.kind, "version": d.version, "created": d.created, "rows": d.rows, "counts": d.counts} for d in done],
            "note": "a version already loaded writes nothing (created = false)"}, OK


def _state_counts(conn: psycopg.Connection[Any], version: str) -> dict[str, int]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT state, count(*) FROM ai.source_registry WHERE version = %s GROUP BY 1 ORDER BY 1", (version,))
        return {str(s): int(n) for s, n in cur.fetchall()}


def cmd_status(conn: psycopg.Connection[Any], _args: argparse.Namespace, _at: datetime) -> tuple[dict[str, Any], int]:
    dir_v, excl_v = registry.current_versions(conn)
    signed = sorted(registry.signed_sources(conn))
    loaded = policy.load(conn)
    pending_signature = sorted(s.source_id for s in (loaded.by_domain.values() if loaded else ())
                               if s.state == "verificada_autorizada" and s.source_id not in signed)
    out: dict[str, Any] = {
        "directory": {"version": dir_v, "states": _state_counts(conn, dir_v) if dir_v else None},
        "exclusion": {"version": excl_v},
        "policy": {"origin": None if loaded is None else loaded.origin, "version": None if loaded is None else loaded.version,
                   "FBI_SOURCE_POLICY": policy.policy_mode(), "FBI_SOURCE_EXCLUSION": policy.exclusion_mode()},
        "signed": signed, "authorised_without_signature": pending_signature,
        "pinned": {"directory": registry.DIRECTORY.version, "exclusion": registry.EXCLUSION.version},
    }
    if excl_v:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute("SELECT action, count(*) FROM ai.domain_rules WHERE version = %s GROUP BY 1 ORDER BY 1", (excl_v,))
            out["exclusion"]["actions"] = {str(a): int(n) for a, n in cur.fetchall()}
            cur.execute("SELECT count(*) FROM ai.source_signoffs WHERE decision = 'exclusion_list' AND registry_version = %s", (excl_v,))
            row = cur.fetchone()
            out["exclusion"]["signed_by_owner"] = bool(row and row[0])
    behind = [k for k, v, p in (("directory", dir_v, registry.DIRECTORY.version), ("exclusion", excl_v, registry.EXCLUSION.version))
              if v != p]
    out["load_needed"] = behind
    return out, OK


def cmd_check_url(conn: psycopg.Connection[Any] | None, args: argparse.Namespace, _at: datetime) -> tuple[dict[str, Any], int]:
    if not args.url:
        return {"error": "check-url needs a URL"}, CANNOT
    loaded = policy.load(conn)
    if loaded is None:
        return {"error": "no registry could be read: nothing would reach a model"}, NO
    st = loaded.standing(args.url)
    return {"url": args.url, "host": st.host, "domain": st.domain, "state": st.state, "source_id": st.source_id, "signed": st.signed,
            "ai_reserved": st.ai_reserved, "rule_class": st.rule_class, "rule_action": st.rule_action, "hard": st.hard_reason,
            "can_fetch": asdict(policy.can_fetch(st)), "can_extract": asdict(policy.can_extract(st)), "can_store": policy.can_store(st),
            "can_publish": {k: asdict(policy.can_publish(st, k)) for k in ("lesiones", "alineaciones", "sanciones", "rumores")},
            "strict_mode": policy.policy_mode(), "exclusion_mode": policy.exclusion_mode(),
            "registry": loaded.version}, OK


def cmd_tiers(conn: psycopg.Connection[Any], _args: argparse.Namespace, _at: datetime) -> tuple[dict[str, Any], int]:
    loaded = policy.load(conn)
    if loaded is None:
        return {"error": "no registry"}, NO
    dir_v, _ = registry.current_versions(conn)
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT domain, tier FROM ai.sources ORDER BY domain")
        tiers = {str(d): str(t) for d, t in cur.fetchall()}
        cur.execute("SELECT source_id, record FROM ai.source_registry WHERE version = %s", (dir_v,))
        records = {str(i): dict(r) for i, r in cur.fetchall()}
    full = {d: registry.source_of(records[s.source_id]) if s.source_id in records else s for d, s in loaded.by_domain.items()}
    rows = []
    for domain, tier in tiers.items():
        src = full.get(domain)
        rows.append((domain, tier, None if src is None else registry.derived_tier(src), None if src is None else src.state))
    in_dir = [r for r in rows if r[2] is not None]
    changes = [r for r in in_dir if r[1] != r[2]]
    return {"ai_sources": len(rows), "in_directory": len(in_dir), "not_in_directory": len(rows) - len(in_dir), "same_tier": len(in_dir) - len(changes),
            "changes": Counter(f"{a}->{b}" for _, a, b, _ in changes), "change_list": [list(r) for r in changes],
            "note": "a report only: ai.sources is not changed; a change of tier needs the owner's signed list (AD-C01)"}, OK


def cmd_shadow(conn: psycopg.Connection[Any], args: argparse.Namespace, at: datetime) -> tuple[dict[str, Any], int]:
    since = at - timedelta(days=max(1, args.days))
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT path, outcome, hard, split_part(reason, ':', 1), state, count(*), count(DISTINCT url) FROM ai.source_policy_log "
                    "WHERE at >= %s GROUP BY 1, 2, 3, 4, 5 ORDER BY 6 DESC", (since,))
        groups = [{"path": p, "outcome": o, "hard": h, "reason": r, "state": s, "rows": int(n), "urls": int(u)}
                  for p, o, h, r, s, n, u in cur.fetchall()]
        cur.execute("SELECT domain, count(*) FROM ai.source_policy_log WHERE at >= %s AND outcome = 'blocked' GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
                    (since,))
        top_blocked = [[d, int(n)] for d, n in cur.fetchall()]
    return {"since": since.isoformat(), "groups": groups, "top_blocked_domains": top_blocked}, OK


def cmd_sign(conn: psycopg.Connection[Any], args: argparse.Namespace, at: datetime) -> tuple[dict[str, Any], int]:
    if not args.confirm_owner:
        return {"error": "only the owner signs: add --confirm-owner"}, NO
    dir_v, excl_v = registry.current_versions(conn)
    try:
        if args.command == "sign-exclusion":
            if not excl_v:
                return {"error": "no exclusion list loaded"}, NO
            registry.sign_exclusion(conn, version=excl_v, at=at, reason=args.reason)
            conn.commit()
            return {"signed": "exclusion_list", "version": excl_v}, OK
        if not dir_v:
            return {"error": "no directory loaded"}, NO
        n = registry.sign(conn, source_ids=args.source, decision="revoke" if args.revoke else "authorize", version=dir_v, at=at,
                          reason=args.reason)
    except (registry.RegistryError, psycopg.errors.CheckViolation) as exc:
        conn.rollback()
        return {"error": str(exc).splitlines()[0]}, NO
    conn.commit()
    return {"signed": n, "decision": "revoke" if args.revoke else "authorize", "version": dir_v}, OK


COMMANDS = {"load": cmd_load, "status": cmd_status, "check-url": cmd_check_url, "tiers": cmd_tiers, "shadow": cmd_shadow,
            "sign": cmd_sign, "sign-exclusion": cmd_sign}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    at = datetime.now(UTC)
    from fbi.core.config import settings as platform

    try:
        conn = psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC -c statement_timeout=60000")
    except psycopg.Error as exc:
        if (args.command == "load" and args.dry_run) or args.command == "check-url":
            conn = None
        else:
            print(json.dumps({"error": f"database: {type(exc).__name__}"}))
            return CANNOT
    try:
        if conn is not None and args.command not in WRITES:
            conn.read_only = True
        result, code = COMMANDS[args.command](conn, args, at)  # type: ignore[arg-type]
    finally:
        if conn is not None:
            conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=None if args.as_json else 2, default=str))
    return code


if __name__ == "__main__":
    sys.exit(main())
