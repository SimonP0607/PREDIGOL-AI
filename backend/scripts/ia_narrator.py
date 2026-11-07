"""The Narrator of a pick (``narrator-v1``, IA-017), from the command line.

    python -m scripts.ia_narrator preview --pick 123            # the pick's facts from its trace and the prompt: no call, no cost
    python -m scripts.ia_narrator preview --pick 123 --json
    python -m scripts.ia_narrator preview --pick 123 --call     # and ONE call with the LAB workspace's key, then the verifier

``preview`` reads the pick's trace (``fbi.observability.trace``: SELECTs only) and prints the closed list of facts, their hash and
the prompt ``pick-why-v1`` the model would be sent. It calls nothing. ``--call`` makes one call - only with the LAB workspace's own
key for the Narrator's tier (``FBI_AI_KEY_ANTHROPIC_LAB``) and only while the LAB's envelope allows it (``fbi.ai.usage.call_json``,
``lab=True``; recorded in the LAB's ledger) - and prints what the verifier kept and dropped. Nothing is stored. Exit 0 when the
facts (and the call's verified text) are there, 1 when the pick has no facts or no sentence stood, 2 when it cannot run.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

import psycopg

from fbi.ai.config import AiSettings
from fbi.core.clock import now
from fbi.narrator import VERSION, job
from fbi.narrator.facts import PickFacts
from fbi.narrator.prompt import PROMPT_VERSION, SYSTEM, body

OK, NO, CANNOT = 0, 1, 2


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_narrator", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("preview",))
    ap.add_argument("--pick", type=int, required=True, help="the pick (picks.picks.id)")
    ap.add_argument("--call", action="store_true", help="make ONE call with the LAB key (never the production key)")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the result as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def render(pf: PickFacts) -> str:
    lines = [f"{VERSION} pick {pf.pick_id}  decision {pf.decision_id} ({pf.decision_at})  trace {pf.trace_id}",
             f"  {pf.market} {pf.selection} {pf.line}  status {pf.pick_status}  input {pf.hash[:16]}  prompt {PROMPT_VERSION}"]
    for f in pf.facts:
        params = ", ".join(f"{k}={v}" for k, v in f.params.items())
        lines.append(f"  {f.id:<24} {f.role:<8} {params}"[:220])
    return "\n".join(lines)


def preview(args: argparse.Namespace, conn: psycopg.Connection[Any], settings: AiSettings) -> tuple[dict[str, Any] | str, int]:
    pf = job.build(conn, args.pick)
    if isinstance(pf, str):
        return {"pick_id": args.pick, "status": pf}, NO
    doc: dict[str, Any] = pf.as_json() | {"prompt": {"version": PROMPT_VERSION, "system_chars": len(SYSTEM), "user": body(pf)}}
    if not args.call:
        return (doc if args.as_json else render(pf) + "\n  (no call: add --call to ask the LAB once)"), OK
    tier = job.narrator_tier()
    if settings.tier(tier, lab=True) is None:
        return {"error": f"--call needs the LAB workspace's key for the tier {tier!r}: nothing was called"}, CANNOT
    outcome = job.narrate(pf, call=job.caller(conn, settings, at=now(), tier=tier, lab=True))
    doc["outcome"] = outcome.as_json()
    if args.as_json:
        return doc, OK if outcome.content is not None else NO
    out = [render(pf), f"  call: {outcome.status} {outcome.provider}:{outcome.model} US$ {outcome.cost}"]
    for lang in ("es", "en"):
        for section, sentences in (outcome.content or {}).get(lang, {}).items():
            out += [f"  {lang}.{section}: {s['text']}  [{', '.join(s['facts'])}]" for s in sentences]
    out += [f"  dropped {d.where}: {d.why} ({d.text[:100]!r})" for d in outcome.dropped]
    return "\n".join(out), OK if outcome.content is not None else NO


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from fbi.core.config import settings as platform

    settings = AiSettings.from_env()
    with psycopg.connect(args.dsn or platform.database.psycopg_url, options="-c TimeZone=UTC") as conn:
        conn.read_only = not args.call
        out, code = preview(args, conn, settings)
        if args.call:
            conn.commit()  # only what call_json itself records (a spend limit hit); the narrative is never stored
        else:
            conn.rollback()
    if isinstance(out, str):
        sys.stdout.write(out + "\n")
    else:
        sys.stdout.write(json.dumps(out, indent=1, default=str, ensure_ascii=False) + "\n")
        if code == CANNOT and "error" in out:
            sys.stderr.write(f"{out['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
