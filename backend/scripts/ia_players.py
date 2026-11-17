"""The player engine in shadow (``player-engine-v1``, IA-017), from the command line: starts, minutes, per-90 rates and props.

    python -m scripts.ia_players evaluate --from 2026-01-01 --to 2026-07-01 [--competition 39 --competition 140] [--json]
    python -m scripts.ia_players show --fixture 123 [--at 2026-11-07T18:00:00Z] [--team-xg 1.6,1.1] [--json]

``evaluate`` walks forward over the played matches that kicked off in ``[--from, --to)`` (with a year of history before them): the
calibration of the start probability (Brier, log-loss) and, per prop family and line, the log-loss and Brier of the model against a
naive baseline, every sample size stated, and the verdict MODELABLE / NOT_MODELABLE with its reasons.

``lineups`` measures the estimated starters (``lineup-estimate-v1``, IA-094) over the played matches that kicked off in ``[--from, --to)``
with an official line-up: each side estimated 90 minutes before kick-off, against the official starters, Brier score and reliability
against «the same XI as the previous match», by competition with its sample (``fbi.players.lineup_estimate.measure``).

``show`` forecasts one match as of ``--at`` (default: now; never later than the kick-off): each side's candidates (the confirmed
line-up when it was fetched by then), their P(start), expected minutes, rates and props, and the verdict of each family on the 180 days
before the moment. ``--team-xg`` conditions the goal shares on the team's expected goals (home,away).

Read-only: the connection refuses writes, nothing is asked of a provider or a model, and nothing here is read by a decision, a pick, a
stake or a page (``fbi.players``). Exit 0 with a report, 2 when it cannot run (an unknown fixture, a bad argument).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import psycopg

from fbi.players import VERSION
from fbi.players import backtest as bt
from fbi.players import history as hist

COMMANDS = ("evaluate", "show", "lineups")
OK, CANNOT = 0, 2
CALIBRATION = timedelta(days=180)
"""``show``: the window before the moment whose matches the verdicts are measured on."""


def parse_at(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not an ISO instant") from exc
    if moment.tzinfo is None:
        raise ValueError(f"{text!r} has no time zone: say Z or an offset")
    return moment


def parse_day(text: str) -> datetime:
    return datetime.combine(date.fromisoformat(text), time(0), tzinfo=UTC)


def parse_xg(text: str) -> tuple[float, float]:
    try:
        home, away = (float(x) for x in text.split(","))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not HOME,AWAY expected goals") from exc
    if home < 0 or away < 0:
        raise ValueError("expected goals cannot be negative")
    return home, away


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ia_players", description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("--from", dest="start", help="evaluate: first kick-off day, YYYY-MM-DD (UTC)")
    ap.add_argument("--to", dest="end", help="evaluate: the day after the last, YYYY-MM-DD (UTC)")
    ap.add_argument("--competition", type=int, action="append", help="evaluate: only these competitions (repeatable)")
    ap.add_argument("--fixture", type=int, help="show: the fixture id")
    ap.add_argument("--at", help="show: the moment, ISO with a zone (default: now)")
    ap.add_argument("--team-xg", dest="team_xg", help="show: HOME,AWAY expected goals to condition the goal shares")
    ap.add_argument("--json", action="store_true", dest="as_json", help="print the report as JSON")
    ap.add_argument("--dsn", help="the database (default: the worker's own)")
    return ap


def evaluate(conn: psycopg.Connection[Any], start: datetime, end: datetime, competitions: Sequence[int] | None = None
             ) -> tuple[dict[str, Any], int]:
    if end <= start:
        return {"error": "--to must be after --from"}, CANNOT
    matches = hist.load_matches(conn, start - bt.WARMUP, end, competitions=competitions)
    trained = [m.fixture_id for m in matches if m.kickoff >= start - bt.TRAIN_LEAD]
    doc = bt.evaluate(matches, hist.absence_history(conn, trained), start=start, end=end)
    doc["competitions"] = list(competitions) if competitions else "all"
    return doc, OK


def show(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, team_xg: tuple[float, float] | None = None
         ) -> tuple[dict[str, Any], int]:
    fx = hist.read_fixture(conn, fixture_id)
    if fx is None:
        return {"error": f"fixture {fixture_id} is unknown"}, CANNOT
    moment = min(at, fx.kickoff)
    matches = [m for m in hist.load_matches(conn, moment - bt.WARMUP, moment, competitions=[fx.competition_id],
                                            teams=[fx.home_team_id, fx.away_team_id]) if m.fixture_id != fixture_id]
    trained = [m.fixture_id for m in matches if m.kickoff >= moment - CALIBRATION - bt.TRAIN_LEAD]
    engine = bt.Engine(matches, hist.absence_history(conn, trained))
    rec = engine.walk(moment, record_from=moment - CALIBRATION, train_from=moment - CALIBRATION - bt.TRAIN_LEAD)
    engine.prepare(moment)
    lineup = hist.confirmed_lineup(conn, fixture_id, moment)
    out = hist.absences_as_of(conn, fixture_id, moment)
    sides: dict[str, Any] = {}
    for side, team, opponent, xg in (("home", fx.home_team_id, fx.away_team_id, None if team_xg is None else team_xg[0]),
                                     ("away", fx.away_team_id, fx.home_team_id, None if team_xg is None else team_xg[1])):
        sheet = lineup.get(side)
        sides[side] = {"team_id": team, "name": fx.home_name if side == "home" else fx.away_name, "lineup_confirmed": sheet is not None,
                       **engine.forecast_side(at=moment, team_id=team, opponent_id=opponent, sheet=sheet, absences=out, team_xg=xg)}
    return {"version": VERSION, "shadow": True, "fixture_id": fixture_id, "kickoff": fx.kickoff.isoformat(),
            "at": moment.isoformat(), "clamped_to_kickoff": moment < at, "matches_in_history": engine.h.matches,
            "start_model": {"fitted": engine.model.coef is not None, "samples": engine.model.samples},
            "dispersion": {k: round(v, 4) for k, v in engine.phi.items()},
            "calibration_window": {"from": (moment - CALIBRATION).isoformat(), "to": moment.isoformat(),
                                   "fixtures": rec.fixtures, "families": bt.verdicts(rec)},
            "sides": sides}, OK


OFFICIAL_SQL = """
SELECT lp.fixture_id, lp.team_side, lp.provider_player_id
  FROM core.fixture_lineup_players lp JOIN core.fixtures f ON f.id = lp.fixture_id
 WHERE lp.is_starter AND lp.provider_player_id > 0 AND lp.source = 'api-football' AND f.status_group = 'finished'
   AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""
LINEUP_FACTS_SQL = """
SELECT e.id, e.fixture_id, COALESCE(e.provider_player_id, p.provider_player_id) AS provider_player_id, e.attributes->>'assertion' AS assertion,
       e.claim_type, e.origin, e.status, e.source_tier, e.subject_type, e.retrieved_at, e.published_at
  FROM ai.evidence e JOIN core.fixtures f ON f.id = e.fixture_id
  LEFT JOIN core.players p ON e.subject_type = 'PLAYER' AND p.id = e.subject_id
 WHERE e.kind = 'lineup' AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND (e.subject_type IS NULL OR %(typed)s)
"""
ABSENCE_FACTS_SQL = """
SELECT e.fixture_id, e.provider_player_id, e.kind, e.attributes->>'assertion' AS assertion, e.status, e.source_tier,
       e.source_domain AS source_name, e.retrieved_at AS known_at
  FROM ai.evidence e JOIN core.fixtures f ON f.id = e.fixture_id
 WHERE e.kind IN ('injury', 'suspension', 'doubtful') AND (e.subject_type IS NULL OR %(typed)s) AND e.status <> 'OUTDATED'
   AND e.provider_player_id IS NOT NULL AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s
"""
"""What ``lineups`` reads besides the matches: the official starters, the facts «titular» (research v2's claims only when the system reads
them, ``typed_visible``) and the facts about who is out (the same) - never the text of a claim."""


def lineups(conn: psycopg.Connection[Any], start: datetime, end: datetime) -> tuple[dict[str, Any], int]:
    from collections import defaultdict

    from psycopg.rows import dict_row

    from fbi.ai.gates import typed_visible
    from fbi.players import lineup_estimate as le

    if end <= start:
        return {"error": "--to must be after --from"}, CANNOT
    matches = hist.load_matches(conn, start - le.HISTORY, end, prefer_sheet=True)
    official: dict[tuple[int, str], set[int]] = defaultdict(set)
    facts: dict[int, list[dict[str, Any]]] = defaultdict(list)
    press: dict[int, list[dict[str, Any]]] = defaultdict(list)
    params = {"start": start, "end": end, "typed": typed_visible(conn)}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(OFFICIAL_SQL, params)
        for r in cur.fetchall():
            official[(int(r["fixture_id"]), str(r["team_side"]))].add(int(r["provider_player_id"]))
        cur.execute(LINEUP_FACTS_SQL, params)
        for r in cur.fetchall():
            facts[int(r["fixture_id"])].append(dict(r))
        cur.execute(ABSENCE_FACTS_SQL, params)
        for r in cur.fetchall():
            press[int(r["fixture_id"])].append(dict(r) | {"player_name": None})
    trained = [m.fixture_id for m in matches if m.kickoff >= start - le.TRAIN]
    doc = le.measure(matches, hist.absence_history(conn, trained), start=start, end=end,
                     official={k: frozenset(v) for k, v in official.items()}, facts=facts, press=press)
    return doc, OK


def _f(x: Any, fmt: str = ".3f") -> str:
    return "-" if x is None else format(x, fmt)


def render_families(families: Sequence[dict[str, Any]]) -> list[str]:
    lines = []
    for f in families:
        main = next(iter(f["lines"].values()), {"n": 0})
        tail = ""
        if main.get("n"):
            tail = (f"  logloss {_f(main['log_loss'], '.4f')} vs base {_f(main['log_loss_baseline'], '.4f')} "
                    f"(diff {main['log_loss_diff']:+.4f} +/- {main['log_loss_diff_se']:.4f}, n={main['n']}, events={main['events']})")
        lines.append(f"  {f['family']:<16} {f['verdict']:<14} starters={f['starters']} with count={f['player_matches']} "
                     f"coverage={f['coverage']:.0%}{tail}" + (f"  [{'; '.join(f['reasons'])}]" if f["reasons"] else ""))
    return lines


def render(command: str, doc: dict[str, Any]) -> str:
    if "error" in doc:
        return str(doc["error"])
    if command == "evaluate":
        a = doc["availability"]
        s = a["start"]
        head = [f"{doc['version']} (shadow) {doc['from']} -> {doc['to']}: {doc['fixtures_evaluated']} matches, "
                f"{doc['sides_evaluated']} sides ({doc['matches_loaded']} loaded with the warm-up)"]
        if s.get("n"):
            head.append(f"  P(start) n={s['n']} brier {s['brier']:.4f} (base {s['brier_baseline']:.4f}) logloss {s['log_loss']:.4f} "
                        f"(base {s['log_loss_baseline']:.4f}); ruled out {a['ruled_out']} (started anyway {a['ruled_out_but_started']}); "
                        f"minutes MAE {a['minutes_mae']} (naive {a['minutes_mae_naive']})")
        else:
            head.append("  P(start): no candidates evaluated")
        return "\n".join([*head, *render_families(doc["families"])])
    lines = [f"{doc['version']} (shadow) fixture {doc['fixture_id']} as of {doc['at']} (kick-off {doc['kickoff']}); "
             f"history {doc['matches_in_history']} matches; start model fitted: {doc['start_model']['fitted']}",
             f"verdicts on {doc['calibration_window']['fixtures']} matches of the 180 days before:",
             *render_families(doc["calibration_window"]["families"])]
    for side, s in doc["sides"].items():
        lines.append(f"{side}: {s['name']} (line-up {'confirmed' if s['lineup_confirmed'] else 'not confirmed'})"
                     + ("" if s["goal_scale"] is None else f", goal scale {s['goal_scale']} for xG {s['team_xg']}"))
        for p in s["players"]:
            a = p["availability"]
            main = ", ".join(f"{pp['family'].split('_', 1)[1]}>{next(iter(pp['p_over']))} {next(iter(pp['p_over'].values())):.2f}"
                             for pp in p["props"])
            lines.append(f"  {p['player_id']:>8} {p['name'] or '':<22.22} {p['position']} {a['basis']:<17} "
                         f"P(start) {a['p_start']:.2f} E[min] {a['expected_minutes']:5.1f}  {main}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.command in ("evaluate", "lineups"):
            if not args.start or not args.end:
                ap.error(f"{args.command} needs --from and --to")
            start, end = parse_day(args.start), parse_day(args.end)
        else:
            if args.fixture is None:
                ap.error("show needs --fixture")
            at = parse_at(args.at) if args.at else now
            xg = parse_xg(args.team_xg) if args.team_xg else None
    except ValueError as exc:
        ap.error(str(exc))
    from fbi.core.config import settings as platform

    with psycopg.connect(args.dsn or platform.database.psycopg_url,
                         options="-c TimeZone=UTC -c default_transaction_read_only=on") as conn:
        if args.command == "evaluate":
            doc, code = evaluate(conn, start, end, args.competition)
        elif args.command == "lineups":
            doc, code = lineups(conn, start, end)
        else:
            doc, code = show(conn, args.fixture, at=at, team_xg=xg)
    as_json = args.as_json or args.command == "lineups"
    out = json.dumps(doc, indent=1, default=str, ensure_ascii=False) if as_json else render(args.command, doc)
    sys.stdout.write(out + "\n")
    if code == CANNOT and "error" in doc:
        sys.stderr.write(f"{doc['error']}\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
