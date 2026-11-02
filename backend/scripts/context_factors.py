"""The registry of context factors: what each is today, and the decision to validate one or take a validation back (plan F6).

    python -m scripts.context_factors list                      # every factor: its version in force, its status, the decision behind it
    python -m scripts.context_factors history [FACTOR]          # every decision taken, oldest first (of one factor, or of all)
    python -m scripts.context_factors promote FACTOR --experiment NAME --result FILE.json --reason "why"
                                                                # dry run: what validating it changes
    python -m scripts.context_factors promote FACTOR --experiment NAME --result FILE.json --reason "why" --by NAME --confirm
                                                                # a person's decision: validate it
    python -m scripts.context_factors retire FACTOR --reason "why" [--by NAME --confirm]
                                                                # take a validation back (DESCRIPTIVE again)

A context factor (the weighted head-to-head, the scenarios of a table or a tie, the observable tactics, rest and congestion) is
DESCRIPTIVE until a person validates it: the brief may describe it, no model reads it, and nothing the system decides changes. VALIDATED
is a decision about ONE version of the factor's code, with the name of the experiment that tested it and that experiment's result (a JSON
file); it lets the brief treat the factor as a signal and it is the record a later phase needs before putting the factor into a model.
Rolling back is ``retire``. Every command that writes is a dry run until ``--by NAME --confirm``; nothing here touches a model, a
forecast or a pick.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from fbi.core.clock import now
from fbi.core.config import settings
from fbi.intel import factors

MAX_FILE_BYTES = 4_000_000
"""A result file larger than this is not read: the registry keeps a summary and the file's name (``factors.MAX_RESULT_BYTES``)."""


def _when(x: datetime) -> str:
    return f"{x:%Y-%m-%d %H:%M} UTC"


def _decision_line(d: factors.Decision) -> str:
    what = (f"experiment {d.experiment}" if d.status == factors.VALIDATED else
            f"taken back (decision #{d.evidence.get('retired_decision')})" if "retired_decision" in d.evidence else "recorded")
    return f"#{d.id} {_when(d.decided_at)} {d.status:<11} {what}, by {d.who or d.decided_by}: {d.reason}"


# ------------------------------------------------------------------------------------------------------------------ list


def show(conn: psycopg.Connection[Any], *, at: datetime | None = None) -> list[str]:
    """Every factor of the catalogue as it stands (``at``: as it stood), then the decisions that are about older versions of the code."""
    stands = factors.standings(conn, at=at or now())
    out = ["CONTEXT FACTORS (no model reads any of them; a factor with no decision is DESCRIPTIVE):", ""]
    for f in factors.CATALOGUE:
        s = stands[f.key]
        d = s.decision
        out.append(f"{f.key:<17} {f.version:<24} {s.status:<11} {f.label}")
        if d is None:
            out.append("    never decided: born DESCRIPTIVE")
        else:
            out.append(f"    {_decision_line(d)}")
        out.append(f"    carried in the packet by: {f.where}. An experiment would have to show {f.claim}.")
    older = [d for d in factors.history(conn) if (d.factor, d.version) not in {(f.key, f.version) for f in factors.CATALOGUE}]
    if older:
        out += ["", "DECISIONS ABOUT OTHER VERSIONS OF THE CODE (they say nothing about the version in force now):"]
        out += [f"  {d.factor} {d.version}: {_decision_line(d)}" for d in older]
    return out


def history_lines(conn: psycopg.Connection[Any], factor: str | None) -> list[str]:
    if factor is not None:
        factors.known(factor)
    rows = factors.history(conn, factor)
    if not rows:
        return ["No decision has been taken" + ("." if factor is None else f" about {factor}.") + " Every factor is DESCRIPTIVE."]
    return [f"{d.factor} {d.version}: {_decision_line(d)}" for d in rows]


# ----------------------------------------------------------------------------------------------------- promote and retire


def read_result(path: Path) -> dict[str, Any]:
    """The experiment's result: a JSON file holding one non-empty object."""
    if not path.is_file():
        raise ValueError(f"{path}: no such file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path} is larger than {MAX_FILE_BYTES} bytes: put its summary and its name in a smaller file")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} is not readable JSON: {exc}") from exc
    if not isinstance(doc, dict) or not doc:
        raise ValueError(f"{path} must hold one JSON object with the result of the experiment")
    return doc


EFFECT = [
    "What it changes: the status the packet states for the factor and for its block, and with it what the brief may do with it (treat it as "
    "a signal, not only as a description).",
    "What it does not change: any model, probability, forecast, pick or price, and anything a user sees.",
]


def promote_command(conn: psycopg.Connection[Any], *, factor: str, experiment: str, result_file: Path, reason: str, by: str | None,
                    confirm: bool, at: datetime | None = None) -> tuple[int, list[str]]:
    """(exit code, lines). Without ``confirm`` nothing is written. The caller owns the transaction (``main`` commits when the code is
    0 and rolls back otherwise)."""
    try:
        f = factors.known(factor)
        factors.check_reason(reason)
        result = read_result(result_file)
        factors.check_evidence(experiment, result)
        if not confirm:
            current = factors.newest(conn, f.key, f.version)
            lines = [f"DRY RUN - validating {f.key} ({f.version}, {f.label}) on the strength of experiment {experiment!r}; its result "
                     f"({result_file.name}) holds: {', '.join(sorted(result)[:12])}.",
                     f"The experiment would have to show {f.claim}."]
            if current is not None and current.status == factors.VALIDATED and current.experiment == experiment.strip():
                lines.append("It is already validated by that experiment: nothing would change.")
                return 0, lines
            lines += EFFECT
            lines.append("Nothing was written. Add --by NAME --confirm to record the decision.")
            return 0, lines
        if not by:
            return 2, ["--confirm needs --by NAME: validating a factor is a person's decision"]
        change = factors.promote(conn, f.key, experiment=experiment, result=result, reason=reason, who=by, at=at)
    except (LookupError, PermissionError, ValueError) as exc:
        return 3, [f"refused: {exc}"]
    if not change.changed:
        return 0, [f"{f.key} is already validated by that experiment: nothing written."]
    return 0, [f"{f.key} ({f.version}) is VALIDATED (decision #{change.decision.id}, by {by}).", *EFFECT]


def retire_command(conn: psycopg.Connection[Any], *, factor: str, reason: str, by: str | None, confirm: bool,
                   at: datetime | None = None) -> tuple[int, list[str]]:
    try:
        f = factors.known(factor)
        factors.check_reason(reason)
        if not confirm:
            current = factors.newest(conn, f.key, f.version)
            if current is None or current.status != factors.VALIDATED:
                raise PermissionError(f"{f.key} ({f.version}) is not validated: there is nothing to take back")
            return 0, [f"DRY RUN - taking back the validation of {f.key} ({f.version}, by experiment {current.experiment}) makes it "
                       "DESCRIPTIVE again. Decisions already stored and packets already built are records and stay as they were.",
                       "Nothing was written. Add --by NAME --confirm to record the decision."]
        if not by:
            return 2, ["--confirm needs --by NAME: taking a validation back is a person's decision"]
        change = factors.retire(conn, f.key, reason=reason, who=by, at=at)
    except (LookupError, PermissionError, ValueError) as exc:
        return 3, [f"refused: {exc}"]
    return 0, [f"{f.key} is DESCRIPTIVE again (decision #{change.decision.id}, by {by})."]


# ------------------------------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("list", "history", "promote", "retire"))
    ap.add_argument("factor", nargs="?", help="history / promote / retire: the key of the factor (see `list`)")
    ap.add_argument("--experiment", help="promote: the name of the experiment that tested this version of the factor")
    ap.add_argument("--result", type=Path, help="promote: a JSON file with the result of the experiment")
    ap.add_argument("--reason", help="promote / retire: why, in a sentence a person can look back on")
    ap.add_argument("--by", help="promote / retire --confirm: who decides")
    ap.add_argument("--confirm", action="store_true", help="promote / retire: write the decision; without it, a dry run")
    args = ap.parse_args(argv)

    if args.command in ("promote", "retire") and (not args.factor or not args.reason):
        print("promote and retire need the FACTOR and --reason TEXT", file=sys.stderr)
        return 2
    if args.command == "promote" and (not args.experiment or args.result is None):
        print("promote needs --experiment NAME and --result FILE.json", file=sys.stderr)
        return 2

    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "list":
            code, lines = 0, show(conn)
        elif args.command == "history":
            try:
                code, lines = 0, history_lines(conn, args.factor)
            except LookupError as exc:
                code, lines = 3, [f"refused: {exc}"]
        elif args.command == "promote":
            code, lines = promote_command(conn, factor=args.factor, experiment=args.experiment, result_file=args.result,
                                          reason=args.reason, by=args.by, confirm=args.confirm)
        else:
            code, lines = retire_command(conn, factor=args.factor, reason=args.reason, by=args.by, confirm=args.confirm)
        if code == 0:
            conn.commit()  # what the command wrote, if anything (a dry run wrote nothing)
        else:
            conn.rollback()  # a refusal leaves no trace, and the advisory lock goes with the transaction
    print("\n".join(lines), file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
