"""The neutral-venue rule: its verdicts, its before/after backtest and its switch (plan F0, defect 1; rule neutral-v1).

    python -m scripts.neutral_rule show                          # the switch, its history, the verdicts, the newest runs
    python -m scripts.neutral_rule classify [--all] [--since D] [--until D] [--apply]
                                                                 # decide the fixtures that have no verdict (dry run by default)
    python -m scripts.neutral_rule backtest [--apply] [--allow-dirty] [--out FILE]
                                                                 # before/after backtest of the stored verdicts (--apply stores it)
    python -m scripts.neutral_rule promote --run ID --reason "why"
                                                                 # dry run: what putting that run's rule in force changes
    python -m scripts.neutral_rule promote --run ID --reason "why" --by NAME --confirm
                                                                 # a person's decision: put it in force
    python -m scripts.neutral_rule retire --reason "why" [--by NAME --confirm]
                                                                 # switch it off again (the verdicts stay)

The ingestion writes a verdict for every non-league fixture it stores (``core.fixture_venue_class``); that changes nothing
a model reads. The models read a verdict only for the rule the switch (``analytics.neutral_rule_promotion``) names, and
the switch is OFF until a person promotes a rule whose before/after backtest (``analytics.neutral_rule_runs``) came out
"justified" on the very verdicts that are stored now. Rolling back is ``retire``. Nothing here touches production by
itself: every command that writes is a dry run until ``--apply`` / ``--confirm``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.backtesting.neutral_ab import PROTOCOL, run_ab
from fbi.catalog.neutral import RULE_VERSION
from fbi.catalog.neutral_store import (
    CHUNK,
    Counts,
    Run,
    check_reason,
    classify_fixtures,
    get_run,
    history,
    label_state,
    labels_through,
    load_reference,
    non_league_ids,
    promote,
    promoted,
    record_run,
    retire,
    runs,
    unclassified_ids,
)
from fbi.core.config import settings
from fbi.core.version import code_version
from scripts.run_backtest import dirty_tree

NEWEST = 5
Say = Callable[[str], None]


def _day(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text).replace(tzinfo=UTC)


# ------------------------------------------------------------------------------------------------------------- show


def show(conn: psycopg.Connection[Any]) -> list[str]:
    out: list[str] = []
    current = promoted(conn)
    if current is None or current.rule_version is None:
        out.append("The switch is OFF: no model reads a neutral-venue verdict." if current is None else
                   f"The switch is OFF since {current.promoted_at:%Y-%m-%d %H:%M} UTC (retired by {current.promoted_by}): "
                   f"{current.reason}")
    else:
        out.append(f"The switch is ON since {current.promoted_at:%Y-%m-%d %H:%M} UTC: rule {current.rule_version}, "
                   f"backtest run #{current.run_id}, put in force by {current.evidence.get('who', current.promoted_by)}")
        out.append(f"  why: {current.reason}")
    older = history(conn)[1:]
    if older:
        out.append("")
        out.append("EARLIER:")
        for p in older:
            what = f"rule {p.rule_version} (run #{p.run_id})" if p.rule_version else "retired"
            out.append(f"  #{p.id} {p.promoted_at:%Y-%m-%d %H:%M} {p.action:<7} {what}, by {p.evidence.get('who', p.promoted_by)}: "
                       f"{p.reason}")
    out.append("")
    out.extend(_verdict_lines(conn))
    stored = runs(conn, limit=NEWEST)
    out.append("")
    out.append(f"BEFORE/AFTER BACKTESTS (the {NEWEST} newest; only a justified run can be promoted):")
    if not stored:
        out.append("  none yet: python -m scripts.neutral_rule backtest --apply")
    for r in stored:
        fresh = label_state(conn, r.rule_version, through=labels_through(r.labels)) == r.labels
        mark = "*" if current is not None and current.run_id == r.id else " "
        out.append(f" {mark} run #{r.id} {r.created_at:%Y-%m-%d %H:%M} {r.rule_version} {r.verdict.upper()} "
                   f"({'labels unchanged' if fresh else 'LABELS CHANGED since: not promotable'}, code {r.code_version})")
        out.append(f"      {r.result.get('headline', '')}")
    return out


def _verdict_lines(conn: psycopg.Connection[Any]) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT rule_version, count(*), count(*) FILTER (WHERE neutral) FROM core.fixture_venue_class "
                    "GROUP BY 1 ORDER BY 1")
        rules = cur.fetchall()
        cur.execute("SELECT basis, neutral, count(*) FROM core.fixture_venue_class WHERE rule_version = %s "
                    "GROUP BY 1, 2 ORDER BY 3 DESC", (RULE_VERSION,))
        bases = cur.fetchall()
    missing = len(unclassified_ids(conn))
    out = ["VERDICTS (core.fixture_venue_class; domestic league matches have none: they are never neutral):"]
    if not rules:
        out.append("  none stored yet")
    for rule, total, neutral in rules:
        out.append(f"  {rule}: {total} fixtures, {neutral} neutral")
    for basis, neutral, n in bases:
        out.append(f"    {'NEUTRAL' if neutral else 'not neutral':<12} {basis:<22} {n:>7}")
    out.append(f"  without a verdict of {RULE_VERSION}: {missing}" + ("" if not missing else
               "  -> python -m scripts.neutral_rule classify --apply"))
    return out


# --------------------------------------------------------------------------------------------------------- classify


def classify_command(conn: psycopg.Connection[Any], *, everything: bool, since: datetime | None,
                     until: datetime | None, apply: bool, say: Say = print) -> tuple[int, list[str]]:
    """Classify the fixtures that have no verdict yet (``everything``: all of them again, writing only what changed).
    A dry run does the whole computation and rolls it back, so what it reports is exactly what ``--apply`` would write.
    With ``apply`` each chunk is committed, so an interruption loses nothing and a rerun continues."""
    ids = non_league_ids(conn, since=since, until=until) if everything else unclassified_ids(conn, since=since, until=until)
    if not ids:
        return 0, [f"Every non-league fixture in range already has a verdict of {RULE_VERSION}: nothing to do."]
    ref = load_reference(conn)
    total = Counts()
    for start in range(0, len(ids), CHUNK):
        total.add(classify_fixtures(conn, ids[start:start + CHUNK], ref=ref))
        if apply:
            conn.commit()
        say(f"  {min(start + CHUNK, len(ids))}/{len(ids)} fixtures decided")
    if not apply:
        conn.rollback()
    lines = [f"{'APPLIED' if apply else 'DRY RUN'} - rule {RULE_VERSION} over {len(ids)} non-league fixtures: "
             f"{total.neutral} neutral, {total.written} verdicts {'written' if apply else 'would be written'} "
             f"(new or changed)."]
    for basis, n in total.by_basis.most_common():
        lines.append(f"  {basis:<22} {n:>7}")
    if not apply:
        lines.append("Nothing was written. Add --apply to write the verdicts.")
    return 0, lines


# ---------------------------------------------------------------------------------------------------------- backtest


def _layer(label: str, d: Mapping[str, Any] | None) -> str:
    if d is None:
        return f"  {label}: nothing could be priced by both arms"
    return (f"  {label}: {d['n']} matches. Log loss {d['loss_a']:.4f} -> {d['loss_b']:.4f} (after - before "
            f"{d['diff']:+.4f}, 95% {d['lo']:+.4f}..{d['hi']:+.4f}); Brier {d['brier_a']:.4f} -> {d['brier_b']:.4f}; "
            f"ECE {d['ece_a']:.4f} -> {d['ece_b']:.4f}; home side over-rated by {d['home_bias_a']:+.3f} -> "
            f"{d['home_bias_b']:+.3f}")


def summary_lines(doc: Mapping[str, Any]) -> list[str]:
    """The result of a backtest (fresh or stored) in words: log loss, Brier and the calibration error before and after."""
    counts = doc["counts"]
    out = [f"VERDICT: {str(doc['verdict']).upper()}   (protocol {doc['protocol']}, rule {doc['rule_version']})",
           f"window {doc['window']['from'][:10]} .. {doc['window']['through'][:10]}; labelled matches in it: "
           f"{counts['labelled_in_window']}, priced by both arms: {counts['labelled_priced_by_both']}; the others "
           f"priced as a control: {counts['control_priced']}",
           "(negative 'after - before' = the rule helps; the interval resamples whole match days)", "",
           "LAYERS:", _layer("labelled matches, pooled Elo + ordered logit", doc.get("primary"))]
    for kind, g in sorted(doc.get("guards", {}).items()):
        out.append(_layer(f"labelled matches, production {kind} goal model", g))
    out.append(_layer("every other match (control)", doc.get("control")))
    for basis, b in sorted(doc.get("bases", {}).items()):
        out.append(_layer(f"labelled matches decided by '{basis}'", b))
    out += ["", "WHY:"] + [f"  - {r}" for r in doc["reasons"]]
    if doc.get("notes"):
        out += ["", "TOO SMALL TO COUNT:"] + [f"  - {n}" for n in doc["notes"]]
    return out


def backtest_command(conn: psycopg.Connection[Any], *, apply: bool, allow_dirty: bool, out: Path | None,
                     say: Say = print) -> tuple[int, list[str]]:
    """Run the before/after backtest of the stored verdicts. Nothing is written unless ``apply``, and then only the run
    (the verdicts and the switch are untouched). The caller commits."""
    missing = len(unclassified_ids(conn))
    if missing:
        return 3, [f"refused: {missing} non-league fixtures have no verdict of {RULE_VERSION} yet. A backtest over part of "
                   "the labels says nothing about the rule: python -m scripts.neutral_rule classify --apply"]
    dirty = dirty_tree()
    if apply and dirty and not allow_dirty:
        return 3, ["refused: the code has uncommitted changes, so the run could not be reproduced from its code_version. "
                   "Commit first (or pass --allow-dirty).", *dirty[:10]]
    result = run_ab(conn, rule=RULE_VERSION, progress=say)
    doc = result.as_dict()
    lines = summary_lines(doc)
    lines.append(f"Took {result.seconds:.0f} s.")
    if out is not None:
        out.write_text(json.dumps(doc, indent=2, sort_keys=True))
        lines.append(f"The whole result is in {out}.")
    if apply:
        run = record_run(conn, rule_version=RULE_VERSION, protocol=PROTOCOL, verdict=result.decision.verdict,
                         labels=result.labels, params=result.protocol.as_dict(), result=doc,
                         code_version=code_version(), dataset_hash=result.dataset_hash)
        lines.append(f"Stored as run #{run.id} (code {run.code_version}).")
        if run.verdict == "justified":
            lines.append(f"To put the rule in force: python -m scripts.neutral_rule promote --run {run.id} --reason \"...\"")
        else:
            lines.append("Not justified: it cannot be promoted, and nothing changes.")
    else:
        lines.append("Nothing was stored. Add --apply to keep this run.")
    return 0, lines


# ------------------------------------------------------------------------------------------------ promote and retire


AFTER_THE_SWITCH = [
    "After the switch changes, the stored Elo history and feature sets still hold the ratings of the old reading. Rebuild "
    "them so that what the models read agrees with what they will price:",
    "  python -m scripts.build_features --elo-only --apply",
    "  python -m scripts.build_features --apply",
    "Forecasts and AI packets read the switch on their next run; the forecasts already stored are records and are not "
    "rewritten.",
]


def _what_changes(conn: psycopg.Connection[Any], rule: str, *, switching_on: bool = True) -> list[str]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT count(*) AS neutral,
                   count(*) FILTER (WHERE f.status_group IN ('scheduled', 'live')) AS ahead,
                   count(*) FILTER (WHERE f.status_group = 'finished') AS played
              FROM core.fixture_venue_class k JOIN core.fixtures f ON f.id = k.fixture_id
             WHERE k.rule_version = %s AND k.neutral""", (rule,))
        row = cur.fetchone()
        cur.execute(
            """
            SELECT c.name, c.competition_type, count(*) AS n
              FROM core.fixture_venue_class k JOIN core.fixtures f ON f.id = k.fixture_id
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
             WHERE k.rule_version = %s AND k.neutral
             GROUP BY c.name, c.competition_type ORDER BY n DESC, c.name LIMIT 8""", (rule,))
        top = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) AS n
              FROM core.fixture_venue_class k JOIN core.fixtures f ON f.id = k.fixture_id
             WHERE k.rule_version = %s AND k.neutral AND f.status_group IN ('scheduled', 'live')
               AND EXISTS (SELECT 1 FROM models.predictions p
                             JOIN models.model_versions v ON v.id = p.model_version_id
                             JOIN models.model_registry m ON m.id = v.model_id
                            WHERE p.fixture_id = f.id AND p.backtest_session_id IS NULL AND m.name = 'elo_ologit')""",
            (rule,))
        logit = cur.fetchone()
    assert row is not None and logit is not None
    lines = [f"  {row['neutral']} fixtures are read as neutral from then on: {row['played']} played (their ratings and the "
             f"training of every model change), {row['ahead']} still to play (priced without a home advantage)."]
    lines += [f"    {t['n']:>5}  {t['name']} ({t['competition_type']})" for t in top]
    if switching_on and logit["n"]:
        lines.append(f"  {logit['n']} of the matches still to play already hold a forecast of the ordered logit, made with a "
                     "home advantage. A forecast is a record and stays; the logit cannot price a neutral match, so nothing "
                     "newer replaces it and it remains that model's newest forecast of the match until kick-off.")
    return lines


def _check_promotable(conn: psycopg.Connection[Any], run: Run) -> None:
    if run.verdict != "justified":
        raise PermissionError(f"run {run.id} says {run.verdict!r}: only a justified rule can be put in force")
    now_state = label_state(conn, run.rule_version, through=labels_through(run.labels))
    if now_state != run.labels:
        raise PermissionError(f"the stored verdicts changed since run {run.id} (then {run.labels}, now {now_state}): "
                              "run the backtest again")


def promote_command(conn: psycopg.Connection[Any], *, run_id: int, reason: str, by: str | None,
                    confirm: bool) -> tuple[int, list[str]]:
    """(exit code, lines). Without ``confirm`` nothing is written. The caller owns the transaction (``main`` commits when
    the code is 0 and rolls back otherwise)."""
    try:
        check_reason("owner", reason)
        run = get_run(conn, run_id)
        if not confirm:
            _check_promotable(conn, run)
            current = promoted(conn)
            lines = [f"DRY RUN - run #{run_id} ({run.created_at:%Y-%m-%d}, code {run.code_version}) justified "
                     f"{run.rule_version}: {run.result.get('headline', '')}"]
            if current is not None and current.rule_version == run.rule_version and current.run_id == run_id:
                lines.append("It is already in force: nothing would change.")
                return 0, lines
            lines.append("Putting it in force would change:")
            lines += _what_changes(conn, run.rule_version)
            lines += ["", *AFTER_THE_SWITCH, "Nothing was written. Add --by NAME --confirm to put it in force."]
            return 0, lines
        if not by:
            return 2, ["--confirm needs --by NAME: putting a rule in force is a person's decision"]
        result = promote(conn, run_id, by="owner", reason=reason, who=by)
    except (LookupError, PermissionError, ValueError) as exc:
        return 3, [f"refused: {exc}"]
    if not result.changed:
        return 0, [f"Run #{run_id} is already in force: nothing written."]
    return 0, [f"Rule {result.promotion.rule_version} is in force (decision #{result.promotion.id}, by {by}).",
               *AFTER_THE_SWITCH]


def retire_command(conn: psycopg.Connection[Any], *, reason: str, by: str | None, confirm: bool) -> tuple[int, list[str]]:
    try:
        check_reason("owner", reason)
        current = promoted(conn)
        if not confirm:
            if current is None or current.rule_version is None:
                raise PermissionError("no rule is in force: nothing to retire")
            return 0, [f"DRY RUN - retiring {current.rule_version} (in force since {current.promoted_at:%Y-%m-%d}) puts the "
                       "models back on the reading they had before it: no match is neutral.", *_what_changes(
                           conn, current.rule_version, switching_on=False), "", *AFTER_THE_SWITCH,
                       "The verdicts stay stored. Nothing was written. Add --by NAME --confirm to retire it."]
        if not by:
            return 2, ["--confirm needs --by NAME: switching the rule off is a person's decision"]
        result = retire(conn, by="owner", reason=reason, who=by)
    except (LookupError, PermissionError, ValueError) as exc:
        return 3, [f"refused: {exc}"]
    return 0, [f"The rule is retired (decision #{result.promotion.id}, by {by}); the verdicts stay stored.", *AFTER_THE_SWITCH]


# ------------------------------------------------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("show", "classify", "backtest", "promote", "retire"))
    ap.add_argument("--apply", action="store_true", help="classify / backtest: write (without it, a dry run / not stored)")
    ap.add_argument("--all", action="store_true", help="classify: decide every fixture again, not only those without a verdict")
    ap.add_argument("--since", help="classify: only fixtures kicking off from this date (YYYY-MM-DD, UTC)")
    ap.add_argument("--until", help="classify: only fixtures kicking off before this date (YYYY-MM-DD, UTC)")
    ap.add_argument("--allow-dirty", action="store_true", help="backtest --apply: store even with uncommitted code")
    ap.add_argument("--out", type=Path, help="backtest: also write the whole result as JSON to this file")
    ap.add_argument("--run", type=int, help="promote: the stored backtest run whose rule is put in force")
    ap.add_argument("--reason", help="promote / retire: why, in a sentence a person can look back on")
    ap.add_argument("--by", help="promote / retire --confirm: who decides")
    ap.add_argument("--confirm", action="store_true", help="promote / retire: write the decision; without it, a dry run")
    args = ap.parse_args(argv)

    def say(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    with psycopg.connect(settings.database.psycopg_url) as conn:
        if args.command == "show":
            print("\n".join(show(conn)))
            return 0
        if args.command == "classify":
            code, lines = classify_command(conn, everything=args.all, since=_day(args.since), until=_day(args.until),
                                           apply=args.apply, say=say)
        elif args.command == "backtest":
            code, lines = backtest_command(conn, apply=args.apply, allow_dirty=args.allow_dirty, out=args.out, say=say)
        else:
            if not args.reason or (args.command == "promote" and args.run is None):
                print("promote needs --run ID and --reason TEXT; retire needs --reason TEXT", file=sys.stderr)
                return 2
            if args.command == "promote":
                code, lines = promote_command(conn, run_id=args.run, reason=args.reason, by=args.by, confirm=args.confirm)
            else:
                code, lines = retire_command(conn, reason=args.reason, by=args.by, confirm=args.confirm)
        if code == 0:
            conn.commit()  # what the command wrote, if anything (a dry run wrote nothing)
        else:
            conn.rollback()  # a refusal leaves no trace, and the advisory lock goes with the transaction
    print("\n".join(lines), file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
