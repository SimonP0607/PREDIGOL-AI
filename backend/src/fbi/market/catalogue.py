"""The catalogue of markets by family (plan F9): the keys of the markets PrediGol will one day model, the rules that grade them, and the link
from every priced bet of the provider to both.

``market.markets`` has had five keys since the start (1X2, OU, BTTS, DC, AH) and every table a forecast, a price or a pick can sit in
points at it. Before a model of the goals of a half, of corners or of cards (F10) can write a forecast, those markets need a key. This
module DERIVES the keys from what the taxonomy already knows of a bet (``fbi.odds.quote_taxonomy``: family, period, subject, kind) and
from the rule that grades it (``fbi.market.rules``), so a key exists only for a bet that can be graded, and two bets that are the same
market (the provider lists "Corners. Double Chance" twice) share one::

    OU_1H            goals over/under, first half            CORNERS_OU        corners of the match over/under
    OU_HOME_2H       home goals over/under, second half      CARDS_OU_HOME     home cards over/under
    1X2_1H           result at half time                     YELLOW_OU_1H      yellow cards of the first half over/under
    HTFT             half-time / full-time                   SOT_1X2           shots on target, who has more

``sync`` makes the database say what the code says, and nothing more: it writes the rules that are missing, the keys that are missing
(``is_tracked`` and ``is_model_enabled`` false - a key in the catalogue is not a market that is captured or modelled, so the five-market
pipeline, the quality counters and the tests that count the catalogue see what they always saw) and the two links of every definition
(``market_key``, ``settle_rule``) that are empty. It never overwrites: a value the database already holds that differs from the code is
reported as DRIFT and left alone (the owner's lever of ``quote_taxonomy`` stays: a definition edited by hand survives), and a rule that
differs from the code is an ERROR - a rule is never edited, a new convention is a new version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.market.rules import RULES, Rule, rule_for
from fbi.odds.quote_taxonomy import PROVIDER, SCOPE, BetSpec, spec_for

# kind of selection -> (key abbreviation, number of outcomes)
KINDS: Final[dict[str, tuple[str, int]]] = {
    "over_under": ("OU", 2),
    "one_x_two": ("1X2", 3),
    "double_chance": ("DC", 3),
    "draw_no_bet": ("DNB", 2),
    "both_teams_score": ("BTTS", 2),
    "asian_handicap": ("AH", 2),
    "odd_even": ("OE", 2),
    "half_time_full_time": ("HTFT", 9),
    "highest_scoring_half": ("HSH", 3),
}
# measure -> prefix of the key ("" for the goals, whose keys are the plain ones)
_PREFIX: Final[dict[str, str]] = {
    "corners": "CORNERS", "cards_lines": "CARDS", "yellow": "YELLOW", "red": "RED", "cards_points": "POINTS",
    "shots_on_target": "SOT", "shots": "SHOTS", "fouls": "FOULS", "offsides": "OFFSIDES", "saves": "SAVES",
}
_SUBJECT: Final = {"home": "HOME", "away": "AWAY"}


class RuleChangedError(RuntimeError):
    """A rule stored in the database is not the rule in the code: it was edited without a new version."""


def _prefix(measure: str) -> str:
    stem = measure.rsplit("_", 1)[0] if measure.rsplit("_", 1)[-1] in ("ft", "1h", "2h") else measure
    return _PREFIX.get(stem, "")


def market_key_for(spec: BetSpec) -> str | None:
    """The catalogue key of a priced bet that can be graded, or None. The five markets the pipeline reads keep their keys."""
    if spec.market_key:
        return spec.market_key
    if not spec.extract or spec.kind not in KINDS:
        return None
    rule = rule_for(spec)
    if rule is None:
        return None
    parts = [p for p in (_prefix(rule.measure), KINDS[spec.kind][0], _SUBJECT.get(spec.subject, ""),
                         spec.period if spec.period in ("1H", "2H") else "") if p]
    return "_".join(parts)


@dataclass(frozen=True, slots=True)
class KeyDef:
    key: str
    name: str
    n_outcomes: int
    has_line: bool
    is_exclusive: bool
    provider_bet_id: int
    line_is_signed: bool


def key_defs(specs: list[BetSpec]) -> dict[str, KeyDef]:
    """The keys a set of definitions asks for (the five legacy keys are not new and are left out). Two bets under one key must be the
    same market - same kind, subject, period and rule - or the derivation is wrong and this raises."""
    out: dict[str, KeyDef] = {}
    seen: dict[str, tuple[str, str, str, str]] = {}
    for spec in sorted(specs, key=lambda s: s.bet_id):
        key = market_key_for(spec)
        if key is None or spec.market_key:
            continue
        rule = rule_for(spec)
        ident = (spec.kind, spec.subject, spec.period, rule.key if rule else "")
        if key in seen:
            if seen[key] != ident:
                raise RuntimeError(f"market key {key} is asked for by two different markets: {seen[key]} and {ident}")
            continue
        seen[key] = ident
        out[key] = KeyDef(key=key, name=spec.name, n_outcomes=KINDS[spec.kind][1], has_line=spec.has_line,
                          is_exclusive=spec.kind != "double_chance", provider_bet_id=spec.bet_id,
                          line_is_signed=spec.line_is_signed)
    return out


def spec_from_row(row: dict[str, Any]) -> BetSpec:
    """A definition as the database holds it (so an edit by hand is respected), except for ``market_key``: that field of a ``BetSpec`` is
    the LEGACY key the taxonomy gives one of the five markets of the pipeline, never a key this module derived and wrote - reading the
    stored one back would make a derived key look like a legacy one, and a hand-edited key could never be told from the code's."""
    bet_id, name = int(row["provider_bet_id"]), str(row["name"])
    return BetSpec(bet_id=bet_id, name=name, family=str(row["family"]), period=str(row["period"]),
                   subject=str(row["subject"]), kind=str(row["kind"]), schema=str(row["schema"]), has_line=bool(row["has_line"]),
                   line_is_signed=bool(row["line_is_signed"]), away_line_negated=bool(row["away_line_negated"]),
                   status=str(row["status"]), extract=bool(row["extract"]), market_key=spec_for(bet_id, name).market_key)


DEFINITIONS_SQL = """
SELECT id, provider_bet_id, name, family, period, subject, kind, schema, has_line, line_is_signed, away_line_negated, status,
       extract, market_key, settle_rule
  FROM market.market_definitions WHERE provider = %s AND scope = %s ORDER BY provider_bet_id
"""


@dataclass
class SyncReport:
    rules_written: int = 0
    keys_written: int = 0
    keys_total: int = 0
    markets_linked: int = 0
    rules_linked: int = 0
    definitions: int = 0
    with_rule: int = 0
    drift: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"rules_written": self.rules_written, "keys_written": self.keys_written, "keys_total": self.keys_total,
                "markets_linked": self.markets_linked, "rules_linked": self.rules_linked, "definitions": self.definitions,
                "with_rule": self.with_rule, "drift": self.drift}


def _rule_row(rule: Rule) -> tuple[Any, ...]:
    return (rule.key, rule.measure, rule.version, rule.family, rule.period, rule.convention, list(rule.columns), rule.liquidable,
            rule.reason, rule.note)


def sync(conn: psycopg.Connection[Any]) -> SyncReport:
    """Make the database say what the code says (see the module docstring). Idempotent; runs in the caller's transaction."""
    report = SyncReport()
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT rule_key, measure, version, family, period, convention, columns, liquidable, reason, note "
                    "FROM market.settlement_rules")
        stored = {str(r["rule_key"]): r for r in cur.fetchall()}
        for rule in RULES:
            row = stored.get(rule.key)
            if row is None:
                cur.execute("INSERT INTO market.settlement_rules (rule_key, measure, version, family, period, convention, columns, "
                            "liquidable, reason, note) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (rule_key) DO NOTHING",
                            _rule_row(rule))
                report.rules_written += cur.rowcount
            elif _rule_row(rule) != (row["rule_key"], row["measure"], row["version"], row["family"], row["period"],
                                     row["convention"], list(row["columns"]), row["liquidable"], row["reason"], row["note"]):
                raise RuleChangedError(f"rule {rule.key} differs from the one stored: a rule is never edited, write a new version")

        cur.execute(DEFINITIONS_SQL, (PROVIDER, SCOPE))
        rows = cur.fetchall()
        specs = {int(r["provider_bet_id"]): spec_from_row(r) for r in rows}
        report.definitions = len(rows)

        wanted = key_defs(list(specs.values()))
        cur.execute("SELECT key FROM market.markets")
        known = {str(r["key"]) for r in cur.fetchall()}
        for kd in wanted.values():
            if kd.key in known:
                continue
            cur.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive, provider_bet_id, is_tracked, "
                        "is_model_enabled, line_is_signed) VALUES (%s,%s,%s,%s,%s,%s,false,false,%s) ON CONFLICT (key) DO NOTHING",
                        (kd.key, kd.name, kd.n_outcomes, kd.has_line, kd.is_exclusive, kd.provider_bet_id, kd.line_is_signed))
            report.keys_written += cur.rowcount
        report.keys_total = len(wanted)

        for row in rows:
            spec = specs[int(row["provider_bet_id"])]
            want_key, want_rule = market_key_for(spec), rule_for(spec)
            sets: dict[str, str] = {}
            if want_key is not None:
                if row["market_key"] is None:
                    sets["market_key"] = want_key
                elif row["market_key"] != want_key:
                    report.drift.append(f"bet {spec.bet_id}: market_key {row['market_key']} (code says {want_key})")
            if want_rule is not None:
                if row["settle_rule"] is None:
                    sets["settle_rule"] = want_rule.key
                elif row["settle_rule"] != want_rule.key:
                    report.drift.append(f"bet {spec.bet_id}: settle_rule {row['settle_rule']} (code says {want_rule.key})")
            elif row["settle_rule"] is not None:
                report.drift.append(f"bet {spec.bet_id}: settle_rule {row['settle_rule']} (code says none can grade it)")
            if sets:
                cur.execute("UPDATE market.market_definitions SET " + ", ".join(f"{c} = %({c})s" for c in sets) +
                            " WHERE id = %(id)s", {**sets, "id": row["id"]})
                report.markets_linked += "market_key" in sets
                report.rules_linked += "settle_rule" in sets
            if want_rule is not None or row["settle_rule"] is not None:
                report.with_rule += 1
    return report
