"""The research registry from the command line.

    python -m scripts.experiment list                 # every experiment, newest first
    python -m scripts.experiment show <id|uuid>       # config, metrics, gate, files (re-hashed)
    python -m scripts.experiment verify               # every experiment's files against its manifest
    python -m scripts.experiment reproduce <id|uuid>  # re-run its session from the registry row and compare
    python -m scripts.experiment promote <id>         # CANDIDATE -> PRODUCTION, only with a passed gate

``reproduce`` refuses unless the working tree is clean and at the recorded
code version: a reproduction of other code proves nothing. It re-runs the
whole backtest session the experiment belongs to (one run, all models),
records one new experiment per model with ``reproduced_from`` set, and marks
every original whose predictions came out identical as reproducible - the
one model-gate check a first run cannot pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg
from psycopg.rows import tuple_row

from fbi.backtesting.persist import config_from_json
from fbi.backtesting.session import hypers_for, run_session
from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.core.version import code_version
from fbi.research.experiments import (
    load_experiment,
    mark_reproduced,
    predictions_digest,
    promote,
    record_session,
    session_experiments,
    verify_manifest,
)
from scripts.run_backtest import dirty_tree


def _say(msg: str) -> None:
    print(msg, flush=True)


def cmd_list(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(
            "SELECT id, started_at, name, model_family, research_status, (gate->>'passed')::boolean, "
            "(metrics->'own_sample'->>'log_loss')::float, (metrics->'vs_primary'->'logloss_diff'->>'mean')::float, "
            "metrics->'vs_primary'->>'verdict', metrics->'vs_primary'->>'evidence', reproduced_from "
            "FROM analytics.experiments ORDER BY id DESC")
        rows = cur.fetchall()
    if not rows:
        _say("no experiments recorded")
        return 0
    _say(f"{'id':>4s}  {'started (UTC)':16s}  {'model':12s} {'status':10s} {'gate':5s} {'log loss':>9s} "
         f"{'vs market':>10s}  verdict")
    for i, at, _name, fam, status, passed, ll, d, verdict, evidence, origin in rows:
        vs = "" if d is None else f"{d:+.5f}"
        ll_s = "" if ll is None else f"{ll:.5f}"
        extra = f"  (reproduces {origin})" if origin else ""
        _say(f"{i:4d}  {at:%Y-%m-%d %H:%M}  {fam:12s} {status:10s} {'yes' if passed else 'no':5s} {ll_s:>9s} "
             f"{vs:>10s}  {verdict or '-'} ({evidence or '-'}){extra}")
    return 0


def cmd_show(conn: psycopg.Connection, ref: str) -> int:
    row = load_experiment(conn, ref)
    if row is None:
        _say(f"no experiment {ref}")
        return 1
    m = row.metrics
    _say(f"experiment {row.id} ({row.uuid})  {row.name}")
    _say(f"  status {row.research_status}; session {row.backtest_session_id}; code {row.code_version[:12]}; "
         f"dataset {str(row.dataset_hash)[:16]}")
    own = m.get("own_sample") or {}
    _say(f"  own sample: n={own.get('n')} log loss={own.get('log_loss')} brier={own.get('brier')} "
         f"ece={own.get('ece')}")
    vs = m.get("vs_primary") or {}
    if vs:
        d = vs.get("logloss_diff", {})
        _say(f"  vs {m.get('primary_baseline')}: n={vs.get('n_common')} dLL={d.get('mean')} "
             f"[{d.get('lo')}, {d.get('hi')}] -> {vs.get('verdict')} ({vs.get('evidence')})")
    _say(f"  model gate: {'PASSED' if row.gate.get('passed') else 'not passed'}")
    for name, check in row.gate.get("checks", {}).items():
        _say(f"    [{'x' if check.get('passed') else ' '}] {name}: {check.get('evidence')}")
    if row.artifact_path:
        problems = verify_manifest(Path(row.artifact_path), row.artifact_manifest)
        _say(f"  files: {row.artifact_path} - {len(row.artifact_manifest)} recorded, "
             + ("all match their sha256" if not problems else "; ".join(problems)))
    return 0


def cmd_verify(conn: psycopg.Connection) -> int:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT id, artifact_path, artifact_manifest FROM analytics.experiments ORDER BY id")
        rows = cur.fetchall()
    bad = 0
    for i, path, files in rows:
        problems = verify_manifest(Path(path), dict(files)) if path else ["no artifact path"]
        if problems:
            bad += 1
            _say(f"experiment {i}: " + "; ".join(problems))
    _say(f"{len(rows)} experiments checked, {bad} with problems")
    return 1 if bad else 0


def cmd_reproduce(conn: psycopg.Connection, ref: str) -> int:
    row = load_experiment(conn, ref)
    if row is None or row.backtest_session_id is None:
        _say(f"no stored backtest experiment {ref}")
        return 1
    version = code_version()
    if version != row.code_version or dirty_tree():
        _say(f"refusing: experiment {row.id} ran code {row.code_version[:12]}, the tree is at {version[:12]}"
             + (" with uncommitted changes" if dirty_tree() else "")
             + f". Check out {row.code_version[:12]} on a clean tree and run again.")
        return 2
    originals = {o.model_family: o for o in session_experiments(conn, row.backtest_session_id)}
    cfg = config_from_json(row.config["walk_forward"])
    comps = [(int(c["id"]), str(c["name"])) for c in row.config["competitions"]]
    _say(f"re-running session {row.backtest_session_id} ({len(originals)} experiments) at {version[:12]}")
    result = run_session(conn, cfg, comps, progress=_say)
    reproduction: dict[str, dict[str, object]] = {}
    differences: dict[str, list[str]] = {}
    for ev in result.evaluation.models:
        o = originals.get(ev.run.model)
        if o is None:
            continue
        diffs = []
        if result.evaluation.dataset_hash != o.dataset_hash:
            diffs.append("dataset hash differs: the data changed since the original run")
        if predictions_digest(ev) != o.metrics.get("predictions_digest"):
            diffs.append("predictions differ")
        old_ll = (o.metrics.get("own_sample") or {}).get("log_loss")
        if ev.own is None or old_ll is None or abs(ev.own.log_loss - float(old_ll)) > 1e-12:
            diffs.append(f"own-sample log loss {old_ll} -> {None if ev.own is None else ev.own.log_loss}")
        reproduction[ev.run.model] = {"of": o.id, "identical": not diffs, "differences": diffs}
        differences[ev.run.model] = diffs
    name = str(row.config.get("session_name", "session"))
    recorded = record_session(conn, result=result, session_id=None, name=f"reproduce-{name}",
                              question=f"Does backtest session {row.backtest_session_id} reproduce from its "
                                       "recorded code, configuration and data?",
                              code_version=version, hypers=hypers_for(result, version), reproduction=reproduction)
    for r in recorded:
        rep = reproduction.get(r.model, {})
        o = originals.get(r.model)
        if o is not None and rep.get("identical"):
            gate = mark_reproduced(conn, o, r.id)
            _say(f"  {r.model:12s} identical -> experiment {o.id} reproducible; gate "
                 f"{'PASSED' if gate['passed'] else 'not passed'}")
        else:
            _say(f"  {r.model:12s} NOT identical: {'; '.join(differences.get(r.model, []))}")
    conn.commit()
    return 0 if all(v["identical"] for v in reproduction.values()) else 3


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="experiment", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("verify")
    for name in ("show", "reproduce"):
        sub.add_parser(name).add_argument("ref")
    sub.add_parser("promote").add_argument("id", type=int)
    args = parser.parse_args()
    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.cmd == "list":
            return cmd_list(conn)
        if args.cmd == "show":
            return cmd_show(conn, args.ref)
        if args.cmd == "verify":
            return cmd_verify(conn)
        if args.cmd == "reproduce":
            return cmd_reproduce(conn, args.ref)
        try:
            promote(conn, args.id)
        except (LookupError, PermissionError) as exc:
            _say(f"refusing: {exc}")
            return 2
        conn.commit()
        _say(f"experiment {args.id} is PRODUCTION")
        return 0


if __name__ == "__main__":
    sys.exit(main())
