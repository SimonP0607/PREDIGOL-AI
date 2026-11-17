"""The tracking of loose selections (IA-109, plan piece AD-E05): En juego -> Liquidada -> Evaluada on ``settle-v4``, in SHADOW.

WHY. A parlay of PrediGol is followed to the end (BUILDING -> READY -> ACTIVE -> WON / LOST, ``fbi.picks.product_settlement``); a loose
selection of the shadow was not. decision-v2's kept shadow (IA-093) takes its chains of the cycle of states (IA-068, AD-D02) up to
``en_juego`` at kick-off, and no layer of it settles anything: its chains stopped there. This pass settles them with the SAME rule the
picks are settled with (``fbi.picks.settlement.settle``, ``settle-v4``: the regulation score, a cancelled match void, no official result
72 h after the kick-off the selection was taken for void) and keeps each settlement as a row of its own.

WHAT ONE PASS DOES (``run_pass``, every ``EVERY`` minutes from the worker while ``FBI_SELECTION_SETTLE=shadow``; ``off`` by default:
the job is not even scheduled), for the chains of ``WRITERS`` whose match kicked off in the last ``BACK`` and whose newest state is
``en_juego``, ``liquidada`` or ``evaluada`` - and the legs of ``parlay-v6`` (IA-110), whatever their chain did since (``LEGS_SQL``):

1. the match as the settlement reads it (status, regulation score, extra time, the 90-minute score, the kick-off the selection was taken
   for: ``fbi.picks.engine.TAKEN_KICKOFF`` from the chain's first sight);
2. ``settle-v4``'s verdict, and against the settlements already kept (``plan``, pure):
       none kept and the verdict is final ............ ``primera``    (the result, its basis, the score it was read on)
       kept, and the provider corrected the score .... ``correccion`` (a NEW row naming the one it supersedes: nothing is rewritten;
                                                       what the re-settlement of the picks holds for a person is held here too)
       kept, and ``FIRM_AFTER`` has passed ........... ``firme``      (the result stands; the price taken, the last de-vigged price
                                                                       before kick-off and the value against it - the evaluation)
       not final yet ................................. nothing        (counted as pending, with settle-v4's reason)
3. the chain's moves after kick-off (``fbi.lifecycle.derive.after_kickoff``), appended through the cycle's API (``store.append``):
   ``en_juego`` -> ``liquidada`` on the first settlement, ``liquidada`` -> ``evaluada`` on the firm one. A correction does not move the
   chain (the cycle has no move from ``liquidada`` to itself): its trail is the settlement row.

It writes ``intel.selection_settlements`` and, through the cycle's API, ``intel.selection_lifecycle``; nothing else
(``tests/unit/test_tracking_ia109.py`` scans every statement). ``settle-v4`` is not touched: it still settles the picks as today.
Two passes cannot write at once (an advisory lock); the same database gives the same rows (a row exists once: the table's
unique index refuses a second successor of the same row).

``how_it_settles`` says in plain words how a selection is settled (C-02, «Cómo se liquida»); ``tracking`` is the owner's private reading
of one chain (its states, its settlements with their trail and that sentence). Nothing here is read by a decision, a pick, a parlay of
``parlay-v5`` or a page a reader can open.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.lifecycle import derive, machine
from fbi.lifecycle import store as lifecycle
from fbi.picks import settlement
from fbi.picks.engine import TAKEN_KICKOFF

SWITCH: Final = "FBI_SELECTION_SETTLE"
VERSION: Final = "selection-settle-v1"
WRITERS: Final[tuple[str, ...]] = ("decision-v2-shadow-v1",)
"""The chains the tracking settles: those of a layer that has no settlement of its own (decision-v2's kept shadow, IA-093). The chains of
``lifecycle-shadow-v1`` are settled off ``intel.decision_outcomes`` by the cycle's own writer and are never touched here."""
KINDS: Final[tuple[str, ...]] = ("primera", "correccion", "firme")
EVERY: Final = int(os.environ.get("FBI_SELECTION_SETTLE_MINUTES", "15"))
BACK: Final = timedelta(days=10)
"""How long after kick-off a chain is still followed: settle-v4's 72 h, the window of corrections and the firm evaluation."""
FIRM_AFTER: Final = timedelta(days=7)
"""When a settlement is firm: the window in which the routine re-settlement still reads the provider's corrections
(``fbi.picks.resettlement.RECHECK_WINDOW``, held equal by a test)."""
FIRM_HOLD: Final = timedelta(hours=24)
"""A correction is firm only a day after it was kept (a provider that corrects twice usually does it the same day)."""
STAKE: Final = Decimal("1")
LOCK: Final = 0x1A109
TIMEOUT_MS: Final = 60_000
CHUNK: Final = 200


def mode(env: Mapping[str, str] | None = None) -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    e = os.environ if env is None else env
    return "shadow" if e.get(SWITCH, "off").strip().lower() == "shadow" else "off"


# -- plain words (C-02, «Cómo se liquida») --------------------------------------------------------------------------------------------

_BASIS = "con el resultado de los 90 minutos más el añadido; la prórroga y los penaltis no cuentan"
_VOID = ("Si el partido se cancela, o si 72 horas después del saque previsto no hay resultado oficial (aplazado, suspendido, "
         "interrumpido o abandonado), la selección se anula y se devuelve lo apostado.")


def _num(x: Decimal) -> str:
    text = f"{x.normalize():f}" if x != x.to_integral_value() else str(int(x))
    return text.replace(".", ",")


def _goals(n: Decimal) -> str:
    return "1 gol" if n == 1 else f"{_num(n)} goles"


def how_it_settles(market_key: str, selection: str, line: Decimal | float | str) -> str:
    """How ``settle-v4`` settles this selection, in plain Spanish (one paragraph, the same words for every selection of a market). Pure;
    a market ``settle-v4`` has no rule for says so instead of guessing."""
    ln = Decimal(str(line))
    quarter = abs(ln * 4) % 2 == 1
    tail = f" Se liquida {_BASIS}. {_VOID}"
    if market_key == "1X2":
        what = {"Home": "Gana si el local gana el partido", "Draw": "Gana si el partido acaba en empate",
                "Away": "Gana si el visitante gana el partido"}.get(selection)
        return f"{what}; en otro caso pierde.{tail}" if what else _unknown(market_key, selection)
    if market_key == "DC":
        what = {"1X": "Gana si el local gana o empata", "12": "Gana si alguno de los dos gana (no hay empate)",
                "X2": "Gana si el visitante gana o empata"}.get(selection)
        return f"{what}; en otro caso pierde.{tail}" if what else _unknown(market_key, selection)
    if market_key == "BTTS":
        what = {"Yes": "Gana si los dos equipos marcan al menos un gol", "No": "Gana si al menos uno de los dos equipos no marca"}.get(
            selection)
        return f"{what}; en otro caso pierde.{tail}" if what else _unknown(market_key, selection)
    if market_key == "OU" and selection in ("Over", "Under"):
        side = "más" if selection == "Over" else "menos"
        if quarter:
            low, high = ln - Decimal("0.25"), ln + Decimal("0.25")
            return (f"Línea partida ({_num(ln)}): la mitad de lo apostado va a {side} de {_num(low)} y la otra mitad a {side} de "
                    f"{_num(high)} goles; cada mitad gana, pierde o se devuelve por su cuenta, y el conjunto puede ganar o perder a "
                    f"medias.{tail}")
        if ln == ln.to_integral_value():
            return (f"Gana si hay {side} de {_goals(ln)} en total; con exactamente {_goals(ln)} se devuelve lo apostado (nulo); en otro "
                    f"caso pierde.{tail}")
        return f"Gana si hay {side} de {_num(ln)} goles en total (sin devolución posible); en otro caso pierde.{tail}"
    if market_key == "AH" and selection in ("Home", "Away"):
        team = "el local" if selection == "Home" else "el visitante"
        of_team = "del local" if selection == "Home" else "del visitante"
        sign = "+" if ln > 0 else ""
        if quarter:
            return (f"Hándicap asiático partido ({sign}{_num(ln)}) para {team}: la mitad de lo apostado va a cada una de las dos líneas "
                    f"vecinas; cada mitad gana, pierde o se devuelve, y el conjunto puede ganar o perder a medias.{tail}")
        push = " Si quedan empatados, se devuelve lo apostado." if ln == ln.to_integral_value() else ""
        amount = _goals(abs(ln)) if ln == ln.to_integral_value() else f"{_num(abs(ln))} goles"
        verb = ("Se suma" if ln > 0 else "Se resta") + ("" if abs(ln) == 1 else "n")
        if ln == 0:
            return f"Gana si {team} gana el partido; pierde si lo pierde. Si empatan, se devuelve lo apostado.{tail}"
        return (f"{verb} {amount} al resultado {of_team} (hándicap {sign}{_num(ln)}): gana si así queda por delante; pierde si queda "
                f"por detrás.{push}{tail}")
    return _unknown(market_key, selection)


def _unknown(market_key: str, selection: str) -> str:
    return (f"settle-v4 no tiene regla de liquidación para {market_key} {selection}: esta selección no se liquida automáticamente "
            "y queda pendiente con su motivo.")


# -- what to keep (pure) --------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Kept:
    """A settlement already kept for a chain (a row of ``intel.selection_settlements``)."""

    id: int
    kind: str
    result: str
    basis: str | None
    known_at: datetime


@dataclass(frozen=True, slots=True)
class NewRow:
    kind: str
    result: str
    basis: str | None
    supersedes_id: int | None


def plan(kept: Sequence[Kept], verdict: settlement.Settlement, *, now: datetime, kickoff_at: datetime) -> list[NewRow]:
    """The settlement rows to add to a chain's trail (``kept``, oldest first). Pure.

    * nothing kept: the first settlement once the verdict is final;
    * the newest result was read on a SCORE and the current score settles it differently: a correction naming the newest row;
    * otherwise, once ``FIRM_AFTER`` from kick-off has passed (and ``FIRM_HOLD`` from the newest result), the firm evaluation - once.
    What the re-settlement of the picks holds for a person, this holds too (``held``; ``fbi.picks.resettlement.judge``, held equal by a
    test): a void by rule (cancelled, no official result 72 h after kick-off) stands when a result arrives later; a result read on a score
    is not changed by a match that now settles by rule or no longer settles at all."""
    results = [k for k in kept if k.kind in ("primera", "correccion")]
    newest = kept[-1] if kept else None
    if not results:
        if verdict.is_final:
            return [NewRow("primera", verdict.status.value, verdict.basis, None)]
        return []
    last = results[-1]
    assert newest is not None
    if held(kept, verdict) is None and (verdict.status.value, verdict.basis) != (last.result, last.basis):
        return [NewRow("correccion", verdict.status.value, verdict.basis, newest.id)]
    if newest.kind != "firme" and now >= kickoff_at + FIRM_AFTER and now >= last.known_at + FIRM_HOLD:
        return [NewRow("firme", last.result, last.basis, newest.id)]
    return []


def held(kept: Sequence[Kept], verdict: settlement.Settlement) -> str | None:
    """Why the current verdict does not correct the kept result (the codes of ``fbi.picks.resettlement.judge``), or None. Pure."""
    results = [k for k in kept if k.kind in ("primera", "correccion")]
    if not results:
        return None
    last = results[-1]
    if (verdict.status.value, verdict.basis) == (last.result, last.basis):
        return None
    if not verdict.is_final:
        return "no_longer_settles"
    if verdict.basis != settlement.BASIS:
        return "settles_by_rule_now"
    if last.basis != settlement.BASIS:
        return "void_by_rule_stands"
    return None


def line_value(odds_taken: Decimal | None, close_p_fair: Decimal | None) -> Decimal | None:
    """The value of the price taken against the last de-vigged price before kick-off: odds x p_fair - 1 (``lv_devigged`` of
    ``fbi.picks.fast_settlement``). None without either. Pure."""
    if odds_taken is None or close_p_fair is None:
        return None
    return (odds_taken * close_p_fair - 1).quantize(Decimal("0.000001"))


# -- the pass -------------------------------------------------------------------------------------------------------------------------

TIPS_SQL: Final = """
SELECT DISTINCT ON (s.chain_key) s.id, s.chain_key, s.writer, s.fixture_id, s.market_key, s.selection, s.line, s.layer, s.state,
       s.known_at, f.kickoff_at
  FROM intel.selection_lifecycle s JOIN core.fixtures f ON f.id = s.fixture_id
 WHERE s.writer = ANY(%(writers)s) AND f.kickoff_at >= %(start)s AND f.kickoff_at <= %(now)s
 ORDER BY s.chain_key, s.id DESC
"""
FOLLOWED: Final = frozenset({"en_juego", "liquidada", "evaluada"})
"""The chains the tracking settles and moves: in play at kick-off, or already settled (a correction, the firm evaluation)."""
LEGS_SQL: Final = "SELECT DISTINCT chain_key FROM intel.parlay_v6_legs WHERE kickoff_at >= %(start)s"
"""The legs of ``parlay-v6`` (IA-110): settled too whatever their chain did after the parlay was built (a parlay is frozen when built,
as ``parlay-v5``'s; a leg whose selection was withdrawn before kick-off still settles the parlay). Their chain is moved only if it is in
play: a withdrawn or discarded chain stays as it is, the settlement is a row of its own."""
TAKEN_SQL: Final = """
SELECT DISTINCT ON (s.chain_key) s.chain_key, s.source, s.source_id, s.known_at,
       (SELECT min(d.known_at) FROM intel.selection_lifecycle d WHERE d.chain_key = s.chain_key) AS first_at
  FROM intel.selection_lifecycle s
 WHERE s.chain_key = ANY(%(keys)s) AND s.state = 'confirmada_sombra'
 ORDER BY s.chain_key, s.id DESC
"""
"""The last confirmation of each chain before kick-off: where its price was taken (the decision it was read from), and its first sight."""
MATCH_SQL: Final = """
SELECT w.chain_key, f.id AS fixture_id, f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away,
       r.ft_goals_home, r.ft_goals_away, r.source_payload_hash,
       """ + TAKEN_KICKOFF.format(since="w.since") + """ AS taken_kickoff
  FROM unnest(%(keys)s::text[], %(fixtures)s::bigint[], %(since)s::timestamptz[]) AS w(chain_key, fixture_id, since)
  JOIN core.fixtures f ON f.id = w.fixture_id
  LEFT JOIN core.fixture_results r ON r.fixture_id = f.id
"""
KEPT_SQL: Final = """
SELECT id, chain_key, kind, result, basis, known_at
  FROM intel.selection_settlements
 WHERE chain_key = ANY(%(keys)s)
 ORDER BY chain_key, known_at, id
"""
PRICE_SQL: Final = {
    "intel.decisions_v2": "SELECT id, odds, p_market FROM intel.decisions_v2 WHERE id = ANY(%(ids)s)",
    "intel.decisions": "SELECT id, odds, p_market FROM intel.decisions WHERE id = ANY(%(ids)s)",
}
"""The price a confirmed selection was taken at, by the table its confirmation was read from (both keep ``odds`` and ``p_market``)."""
CLOSE_SQL: Final = """
SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line) m.fixture_id, m.market_key, m.selection, m.line, m.p_fair,
       m.best_odds, m.as_of
  FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.fixture_id = ANY(%(fixtures)s) AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
 ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
"""
INSERT_SQL: Final = """
INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, supersedes_id, result,
    profit_units, basis, review_reason, rule_version, status_short, reg_goals_home, reg_goals_away, taken_kickoff, result_payload_hash,
    odds_taken, price_source, price_source_id, close_p_fair, close_odds, close_at, line_value, known_at, tracker_version)
VALUES (%(chain_key)s, %(writer)s, %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(kind)s, %(supersedes_id)s, %(result)s,
    %(profit_units)s, %(basis)s, %(review_reason)s, %(rule_version)s, %(status_short)s, %(reg_goals_home)s, %(reg_goals_away)s,
    %(taken_kickoff)s, %(result_payload_hash)s, %(odds_taken)s, %(price_source)s, %(price_source_id)s, %(close_p_fair)s,
    %(close_odds)s, %(close_at)s, %(line_value)s, %(known_at)s, %(tracker_version)s)
RETURNING id
"""


@dataclass
class PassReport:
    chains: int = 0
    settled: int = 0
    corrected: int = 0
    firm: int = 0
    pending: int = 0
    needs_review: int = 0
    held: int = 0
    """Kept results the current verdict would change but the re-settlement's rule holds for a person (``held``)."""
    appended: int = 0
    raced: int = 0
    by_result: Counter[str] = field(default_factory=Counter)
    by_state: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"chains": self.chains, "settled": self.settled, "corrected": self.corrected, "firm": self.firm, "pending": self.pending,
                "needs_review": self.needs_review, "held": self.held, "appended": self.appended, "raced": self.raced,
                "by_result": dict(sorted(self.by_result.items())), "by_state": dict(sorted(self.by_state.items())),
                "errors": self.errors[:20]}


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _tables_exist(conn: psycopg.Connection[Any]) -> bool:
    row = conn.execute("SELECT to_regclass('intel.selection_settlements') IS NOT NULL AND "
                       "to_regclass('intel.parlay_v6_legs') IS NOT NULL AND "
                       "to_regclass('intel.selection_lifecycle') IS NOT NULL").fetchone()
    return bool(row and row[0])


def match_state(r: Mapping[str, Any]) -> settlement.MatchState:
    return settlement.MatchState(str(r["status_short"] or ""), r["reg_goals_home"], r["reg_goals_away"], r["et_goals_home"],
                                 r["et_goals_away"], r["ft_goals_home"], r["ft_goals_away"], r["taken_kickoff"])


def _chunks(xs: Sequence[Any], n: int) -> Iterable[list[Any]]:
    for i in range(0, len(xs), n):
        yield list(xs[i:i + n])


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, writers: Sequence[str] = WRITERS, dry_run: bool = False,
             back: timedelta = BACK) -> PassReport:
    """One pass of the tracking. ``dry_run`` reads the same and writes nothing. Commits once per chunk of chains; a chunk that fails is
    rolled back, counted and the pass goes on."""
    rep = PassReport()
    if lifecycle.WRITER in writers:
        raise ValueError(f"{lifecycle.WRITER} settles its own chains off intel.decision_outcomes")
    if not _tables_exist(conn):
        rep.errors.append("intel.selection_settlements or intel.selection_lifecycle does not exist: apply revisions 0142 and 0157")
        conn.rollback()
        return rep
    if not dry_run:
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
        if not got or not got[0]:
            rep.errors.append("another pass holds the lock")
            conn.rollback()
            return rep
    try:
        conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        legs = {str(r["chain_key"]) for r in _fetch(conn, LEGS_SQL, {"start": now - back})}
        tips = [t for t in _fetch(conn, TIPS_SQL, {"writers": list(writers), "start": now - back, "now": now})
                if t["state"] in FOLLOWED or str(t["chain_key"]) in legs]
        rep.chains = len(tips)
        conn.commit()
        for part in _chunks(tips, CHUNK):
            try:
                _one_chunk(conn, part, now=now, dry_run=dry_run, rep=rep)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
            except psycopg.errors.UniqueViolation as exc:
                conn.rollback()
                rep.raced += 1
                rep.errors.append(f"raced: {type(exc).__name__}"[:300])
            except psycopg.Error as exc:
                conn.rollback()
                rep.errors.append(f"{part[0]['chain_key']}..: {type(exc).__name__}: {exc}"[:300])
    finally:
        if not dry_run:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            conn.commit()
    return rep


def _one_chunk(conn: psycopg.Connection[Any], tips: Sequence[Mapping[str, Any]], *, now: datetime, dry_run: bool,
               rep: PassReport) -> None:
    keys = [str(t["chain_key"]) for t in tips]
    taken = {str(r["chain_key"]): r for r in _fetch(conn, TAKEN_SQL, {"keys": keys})}
    since = [taken[k]["first_at"] if k in taken else t["known_at"] for k, t in zip(keys, tips, strict=True)]
    matches = {str(r["chain_key"]): r for r in _fetch(conn, MATCH_SQL, {
        "keys": keys, "fixtures": [int(t["fixture_id"]) for t in tips], "since": since})}
    kept: dict[str, list[Kept]] = {}
    for r in _fetch(conn, KEPT_SQL, {"keys": keys}):
        kept.setdefault(str(r["chain_key"]), []).append(Kept(int(r["id"]), str(r["kind"]), str(r["result"]), r["basis"], r["known_at"]))
    prices: dict[tuple[str, int], dict[str, Any]] = {}
    for source, sql in PRICE_SQL.items():
        ids = sorted({int(t["source_id"]) for t in taken.values() if t["source"] == source and t["source_id"] is not None})
        if ids:
            prices.update({(source, int(r["id"])): r for r in _fetch(conn, sql, {"ids": ids})})
    closes = {(int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(r["line"])): r
              for r in _fetch(conn, CLOSE_SQL, {"fixtures": sorted({int(t["fixture_id"]) for t in tips})})}
    for t in tips:
        key = str(t["chain_key"])
        m = matches.get(key)
        if m is None:
            continue
        line = Decimal(t["line"])
        conf = taken.get(key)
        price = None if conf is None or conf["source_id"] is None else prices.get((str(conf["source"]), int(conf["source_id"])))
        odds = None if price is None or price["odds"] is None else Decimal(price["odds"])
        verdict = settlement.settle(str(t["market_key"]), str(t["selection"]), line, odds or Decimal(2), STAKE, match_state(m), at=now)
        if not verdict.is_final:
            rep.pending += 1
            rep.needs_review += int(verdict.review_reason is not None)
        trail = kept.get(key, [])
        rep.held += int(held(trail, verdict) is not None)
        for new in plan(trail, verdict, now=now, kickoff_at=t["kickoff_at"]):
            close = closes.get((int(t["fixture_id"]), str(t["market_key"]), str(t["selection"]), line))
            row_id = _keep(conn, t, m, new, verdict, odds=odds, conf=conf, close=close, now=now, dry_run=dry_run)
            trail.append(Kept(row_id, new.kind, new.result, new.basis, now))
            rep.settled += int(new.kind == "primera")
            rep.corrected += int(new.kind == "correccion")
            rep.firm += int(new.kind == "firme")
            if new.kind != "firme":
                rep.by_result[new.result] += 1
        rows = [derive.Row(step, at, src, sid, str(t["layer"])) for step, at, src, sid in derive.after_kickoff(
            str(t["state"]), [derive.Settled(k.id, k.kind, k.known_at, k.result) for k in trail], now=now)]
        rows = [derive.Row(r.step, max(r.known_at, t["known_at"]), r.source, r.source_id, r.layer) for r in rows]
        if rows:
            rep.appended += len(rows) if dry_run else lifecycle.append(
                conn, writer=str(t["writer"]), key=derive.Key.of(t["fixture_id"], t["market_key"], t["selection"], line), rows=rows,
                previous_id=int(t["id"]), from_state=str(t["state"]))
        rep.by_state[rows[-1].step.state if rows else str(t["state"])] += 1


def _keep(conn: psycopg.Connection[Any], t: Mapping[str, Any], m: Mapping[str, Any], new: NewRow, verdict: settlement.Settlement, *,
          odds: Decimal | None, conf: Mapping[str, Any] | None, close: Mapping[str, Any] | None, now: datetime, dry_run: bool) -> int:
    firm = new.kind == "firme"
    status = settlement.Status(new.result)
    p_fair = None if close is None or close["p_fair"] is None else Decimal(close["p_fair"])
    params = {
        "chain_key": t["chain_key"], "writer": t["writer"], "fixture_id": t["fixture_id"], "market_key": t["market_key"],
        "selection": t["selection"], "line": t["line"], "kind": new.kind, "supersedes_id": new.supersedes_id, "result": new.result,
        "profit_units": None if odds is None else settlement.profit(status, odds, STAKE), "basis": new.basis,
        "review_reason": None, "rule_version": settlement.RULE_VERSION, "status_short": m["status_short"],
        "reg_goals_home": m["reg_goals_home"], "reg_goals_away": m["reg_goals_away"], "taken_kickoff": m["taken_kickoff"],
        "result_payload_hash": m["source_payload_hash"], "odds_taken": odds,
        "price_source": None if conf is None else conf["source"], "price_source_id": None if conf is None else conf["source_id"],
        "close_p_fair": p_fair if firm else None, "close_odds": None if not firm or close is None else close["best_odds"],
        "close_at": None if not firm or close is None else close["as_of"],
        "line_value": line_value(odds, p_fair) if firm else None, "known_at": now, "tracker_version": VERSION}
    if dry_run:
        return -1
    got = conn.execute(INSERT_SQL, params).fetchone()
    assert got is not None
    return int(got[0])


# -- the owner's reading (private) ----------------------------------------------------------------------------------------------------

CHAIN_SQL: Final = """
SELECT id, state, reason, actor, settlement_result, known_at, source, source_id
  FROM intel.selection_lifecycle WHERE chain_key = %(key)s ORDER BY id
"""
TRAIL_SQL: Final = """
SELECT id, kind, supersedes_id, result, basis, rule_version, status_short, reg_goals_home, reg_goals_away, odds_taken, close_p_fair,
       line_value, known_at
  FROM intel.selection_settlements WHERE chain_key = %(key)s ORDER BY known_at, id
"""


def tracking(conn: psycopg.Connection[Any], *, writer: str, fixture_id: int, market_key: str, selection: str,
             line: Decimal | float | str) -> dict[str, Any]:
    """One selection as the owner follows it (C-03, «Seguimiento privado»; C-02, «Cómo se liquida»): its moves, its settlements with their
    trail and how it is settled. Read-only, under a statement timeout; for an admin route (``require_admin``), never a reader's page."""
    key = lifecycle.chain_key(writer, derive.Key.of(fixture_id, market_key, selection, line))
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SET LOCAL statement_timeout = 30000")
        cur.execute(CHAIN_SQL, {"key": key})
        chain = [dict(r) for r in cur.fetchall()]
        cur.execute(TRAIL_SQL, {"key": key})
        trail = [dict(r) for r in cur.fetchall()]
    results = [r for r in trail if r["kind"] in ("primera", "correccion")]
    return {
        "chain_key": key, "machine_version": machine.VERSION, "tracker_version": VERSION,
        "state": chain[-1]["state"] if chain else None,
        "moves": [{"state": r["state"], "reason": r["reason"], "actor": r["actor"], "known_at": r["known_at"].isoformat(),
                   "source": r["source"], "source_id": r["source_id"], "result": r["settlement_result"]} for r in chain],
        "result": results[-1]["result"] if results else None,
        "corrected": len(results) > 1,
        "settlements": [{"id": int(r["id"]), "kind": r["kind"], "supersedes_id": r["supersedes_id"], "result": r["result"],
                         "basis": r["basis"], "rule_version": r["rule_version"], "status": r["status_short"],
                         "score": None if r["reg_goals_home"] is None else [r["reg_goals_home"], r["reg_goals_away"]],
                         "odds_taken": None if r["odds_taken"] is None else float(r["odds_taken"]),
                         "close_p_fair": None if r["close_p_fair"] is None else float(r["close_p_fair"]),
                         "line_value": None if r["line_value"] is None else float(r["line_value"]),
                         "known_at": r["known_at"].isoformat()} for r in trail],
        "how_it_settles": how_it_settles(market_key, selection, line),
    }


PARITY_SQL: Final = """
WITH s AS (
    SELECT DISTINCT ON (chain_key) chain_key, fixture_id, market_key, selection, line, result
      FROM intel.selection_settlements
     WHERE writer = ANY(%(writers)s) AND kind IN ('primera', 'correccion') AND known_at >= %(start)s AND known_at < %(end)s
     ORDER BY chain_key, known_at DESC, id DESC
)
SELECT s.chain_key, s.result,
       (SELECT array_agg(DISTINCT pr.result_status) FROM picks.picks p JOIN picks.pick_results pr ON pr.pick_id = p.id
         WHERE p.fixture_id = s.fixture_id AND p.market_key = s.market_key AND p.selection = s.selection AND p.line = s.line
           AND pr.result_status <> 'pending') AS picks_results
  FROM s
"""


def parity(conn: psycopg.Connection[Any], *, start: datetime, end: datetime, writers: Sequence[str] = WRITERS) -> dict[str, Any]:
    """AD-E05's criterion over the selections settled in ``[start, end)``: the tracking's newest result against ``settle-v4``'s stored
    result of the shadow picks of the same selection (every pick of a selection settles the same bet). Read-only."""
    rows = _fetch(conn, PARITY_SQL, {"writers": list(writers), "start": start, "end": end})
    same = differ = without = 0
    examples: list[dict[str, Any]] = []
    for r in rows:
        theirs = set(r["picks_results"] or ())
        if not theirs:
            without += 1
        elif theirs == {r["result"]}:
            same += 1
        else:
            differ += 1
            if len(examples) < 20:
                examples.append({"chain_key": r["chain_key"], "tracking": r["result"], "settle_v4": sorted(theirs)})
    return {"settled": len(rows), "same_as_settle_v4": same, "different": differ, "without_pick": without, "examples": examples}
