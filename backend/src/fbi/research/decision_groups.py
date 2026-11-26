"""The weekly search over the pre-registered groups of decisions, and its report in three columns (plan RP-8.5, finding H27). Nothing here decides a model, a
probability, a pick or a threshold, and nothing here calls a provider or an AI: it reads settled decisions.

``fbi.research.pattern_search`` already asks, for 12 dimensions and 3 measures, whether a group differs from the rest by more than chance explains. RP-8.5 fixes,
BEFORE looking, the dimensions that say how a decision came about - the ones an owner would want to ask about - so that no one chooses them after the result:

    reject_reason     why the decision was rejected (the first reason the decision layer wrote; ``ninguno`` for one that was not)
    market            the market (1X2, double chance, ...)
    odds_band         the odds band of the price taken
    market_distance   how far the probability of the system is from the market's: under -5 points, -5 to -2, -2 to +2, +2 to +5, over +5
    competition_tier  the level of the competition (its tier in ``core.competitions``)
    searched          whether a web search was done before the decision
    lineups           whether the line-ups were confirmed when the decision was taken (the plan says "if the line-up changed": that needs two sheets of the
                      same match and is not read here; this is the state of the sheet, said as it is)
    news              whether a piece of news about the match was confirmed (evidence of any origin with the state CONFIRMED)

The search is the one of ``pattern_search`` (clustered by match, a minimum of matches, repeated in both halves, corrected for all the comparisons it makes); the
comparisons of this family are counted ON THEIR OWN, so the correction is for the questions of this list and not for the others. Only a group that is
significant after the correction, repeats in both halves and is not a description of how the price is built becomes a hypothesis for the owner. The report
puts every group of the week in one of three columns:

    se confirma       reached the bar, repeats in both halves and survives the correction for all the comparisons: proposed (at most ``MAX_PROPOSALS``)
    sin evidencia     cannot be told: too few matches to be tested, or it reached the bar and did not repeat, or did not survive the correction
    se descarta       tested with enough matches and the difference is below the bar: the data say there is nothing of the size the bar looks for

A world with no effect produces no entry in the first column (``tests/unit/test_decision_groups.py`` runs it on simulated data).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core.decision_versions import DECISION_CORE
from fbi.core.env import environment
from fbi.research import pattern_search as ps
from fbi.research.pattern_search import Obs

VERSION: Final = "decision-groups-v1"
SWITCH: Final = "FBI_DECISION_GROUPS"
MODES: Final = ("off", "report", "propose")
DIMENSIONS: Final = (
    "reject_reason",
    "market",
    "odds_band",
    "market_distance",
    "competition_tier",
    "searched",
    "lineups",
    "news",
)
"""The dimensions fixed by the plan, in the order of the report. They are written here once and a test holds them: a week's search cannot add one."""

DISTANCE_BANDS: Final = (
    (-0.05, "bajo -5 puntos"),
    (-0.02, "-5 a -2 puntos"),
    (0.02, "-2 a +2 puntos"),
    (0.05, "+2 a +5 puntos"),
)
LAST_DISTANCE: Final = "sobre +5 puntos"
NONE_REASON: Final = "ninguno"
VALUE_ES: Final = {
    ("searched", "yes"): "con búsqueda web",
    ("searched", "no"): "sin búsqueda web",
    ("lineups", "yes"): "alineación confirmada",
    ("lineups", "no"): "alineación sin confirmar",
    ("news", "yes"): "con noticia confirmada",
    ("news", "no"): "sin noticia confirmada",
    ("reject_reason", NONE_REASON): "ninguno (no rechazada)",
}
"""How the values that do not read as what they are are written for the owner; the key of a hypothesis keeps the value."""


def distance_band(distance: float) -> str:
    """The probability of the system minus the market's, as a band (the lower edge belongs to the band above it)."""
    for edge, name in DISTANCE_BANDS:
        if distance < edge:
            return name
    return LAST_DISTANCE


def confirmed_news(evidence: Mapping[str, Any] | None) -> bool:
    """Whether any evidence of the match, of any origin, is CONFIRMED (the keys of the decision's context are ``origin:STATUS``)."""
    return any(
        str(key).endswith(":CONFIRMED") and int(value or 0) > 0
        for key, value in (evidence or {}).items()
    )


def group_tags(
    *,
    reasons: Sequence[str],
    p: float,
    p_market: float | None,
    tier: int | None,
    context: Mapping[str, Any] | None,
) -> dict[str, tuple[str, ...]]:
    """The groups of one decision in the dimensions of this module; one the row cannot say (no market probability, no tier, a context without the key) is left out."""
    tags: dict[str, tuple[str, ...]] = {"reject_reason": (reasons[0] if reasons else NONE_REASON,)}
    if p_market is not None:
        tags["market_distance"] = (distance_band(p - p_market),)
    if tier is not None:
        tags["competition_tier"] = (f"nivel {tier}",)
    ctx = context or {}
    if "web_searched" in ctx:
        tags["searched"] = ("yes" if ctx["web_searched"] else "no",)
    if "lineups_at" in ctx:
        tags["lineups"] = ("yes" if ctx["lineups_at"] else "no",)
    if "evidence" in ctx:
        tags["news"] = ("yes" if confirmed_news(ctx["evidence"]) else "no",)
    return tags


DECISIONS_SQL = ps.DECISIONS_SQL.replace(
    "rf.name AS referee_name",
    "rf.name AS referee_name, l.reasons, l.p_market::float8 AS p_market, c.tier AS tier, l.context AS context",
)
"""The decisions of ``pattern_search`` with, for each, the reasons it was rejected for, the market's probability, the tier of its competition and the context
it was taken in. Everything else (the last decision of each selection before the kick-off, a voided one left out) is the same text."""


def read(
    conn: psycopg.Connection[Any], *, start: datetime, end: datetime
) -> tuple[list[Obs], dict[tuple[str, str], str]]:
    """The settled decisions with kick-off in ``[start, end)`` as rows of the search with the groups of this module added to the 12 of ``pattern_search``, and the
    names of the groups. Reads only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            DECISIONS_SQL.format(extra=""),
            {"start": start, "end": end, "decision_version": DECISION_CORE},
        )
        decisions = cur.fetchall()
    rows: list[Obs] = []
    labels: dict[tuple[str, str], str] = dict(VALUE_ES)
    for r in decisions:
        line = Decimal(r["line"])
        tags = ps.tags_of(
            market=r["market_key"],
            line=line,
            selection=r["selection"],
            model=r["model_name"],
            calibrator_role=r["calibrator_role"],
            odds=r["odds"],
            context=r["context_status"],
            competition_type=r["competition_type"],
            stage_role=r["stage_role"],
            competition_id=int(r["competition_id"]),
            home_team=int(r["home_team_id"]),
            away_team=int(r["away_team_id"]),
            home_coach=None,
            away_coach=None,
            referee_id=None,
        )
        tags.update(
            group_tags(
                reasons=list(r["reasons"] or ()),
                p=float(r["p"]),
                p_market=r["p_market"],
                tier=r["tier"],
                context=r["context"],
            )
        )
        won = (
            (1 if r["result_status"] == "win" else 0)
            if ps.readable(r["result_status"], float(r["p_push"]), line)
            else None
        )
        rows.append(
            Obs(
                int(r["fixture_id"]),
                r["kickoff_at"],
                float(r["p"]),
                won,
                r["p_close"],
                r["clv"],
                tags,
                r["lead_hours"],
            )
        )
    for dimension, value in {
        (d, v) for row in rows for d, vs in row.tags.items() if d in DIMENSIONS for v in vs
    }:
        labels.setdefault((dimension, value), value)
    return rows, labels


def run(
    conn: psycopg.Connection[Any], *, at: datetime, days: int = ps.WINDOW_DAYS
) -> dict[str, Any]:
    """The search over the fixed dimensions for the decisions with kick-off in the ``days`` before ``at``, with the window written in the report. Reads only."""
    start = at - timedelta(days=days)
    rows, labels = read(conn, start=start, end=at)
    report = ps.search(rows, labels=labels, dimensions=DIMENSIONS)
    report["window"] = {
        "start": start.isoformat(),
        "end": at.isoformat(),
        "days": days,
        "selected_only": False,
    }
    report["groups_version"] = VERSION
    return report


def columns(report: Mapping[str, Any]) -> dict[str, Any]:
    """Every group of the report in one of the three columns, by dimension (see the head of the module). ``se confirma`` lists the groups; the other two are
    counted (the report's ``found`` and ``nearest`` hold what is worth reading of them)."""
    chosen, _ = ps.triage(report, only_surviving=True)
    confirmed_ids = {id(f) for f in chosen}
    found = report["found"]
    reached = len(found)
    groups = sum(v["groups"] for per in report["coverage"].values() for v in per.values())
    tested_total = report["tests"]
    by_dimension: dict[str, dict[str, int]] = {}
    for metric_cov in report["coverage"].values():
        for dimension, v in metric_cov.items():
            cell = by_dimension.setdefault(dimension, {"groups": 0, "tested": 0, "same": 0})
            for k in cell:
                cell[k] += v[k]
    confirmed = [f for f in found if id(f) in confirmed_ids]
    unclear_found = reached - len(confirmed)
    untested = groups - tested_total - sum(c["same"] for c in by_dimension.values())
    return {
        "version": VERSION,
        "confirmed": [
            {
                "measure": f["metric"],
                "dimension": f["dimension"],
                "group": f["label"][: ps.LABEL_CHARS],
                "z": round(f["z"], 2),
                "matches": f["matches"],
                "delta": round(f["delta"], 4),
            }
            for f in confirmed
        ],
        "no_evidence": {
            "not_tested": max(untested, 0),
            "reached_the_bar_but_not_confirmed": unclear_found,
        },
        "discarded": max(tested_total - reached, 0),
        "tests": tested_total,
        "expected_by_chance": round(float(report["expected_by_chance"]), 1),
        "by_dimension": by_dimension,
    }


def mode() -> str:
    """What the weekly job does, by ``FBI_DECISION_GROUPS``: ``off`` (the default, and what anything unknown means), ``report`` (the three columns in the run's
    record, nothing written anywhere else) or ``propose`` (...and what is confirmed is proposed to the owner in Evolución, once each)."""
    value = environment().get(SWITCH, "off").strip().lower()
    return value if value in MODES else "off"


def weekly(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The weekly step: nothing when the switch is ``off``; otherwise the report in three columns and, in ``propose``, the confirmed groups written as
    hypotheses (``pattern_search.register``, keyed: a group and direction is proposed once). The caller commits."""
    chosen = mode()
    if chosen == "off":
        return {"mode": chosen}
    report = run(conn, at=at)
    out: dict[str, Any] = {"mode": chosen, **columns(report)}
    if chosen == "propose":
        out["proposed"] = len(ps.register(conn, ps.proposals(report, only_surviving=True), at=at))
    return out


def render(columns_: Mapping[str, Any]) -> str:
    """The three columns as text for the owner."""
    c = columns_
    lines = [
        f"Grupos de decisión ({c['version']}): {c['tests']} comparaciones; por azar se esperarían {c['expected_by_chance']} sobre la barra",
        f"SE CONFIRMA ({len(c['confirmed'])}):",
    ]
    lines.extend(
        f"  {f['measure']:<11} {ps.DIMENSION_ES[f['dimension']]}: {f['group']}  z {f['z']:+.1f}  en {f['matches']} partidos"
        for f in c["confirmed"]
    )
    n = c["no_evidence"]
    lines.append(
        f"SIN EVIDENCIA: {n['not_tested']} grupos sin muestra para probarse y {n['reached_the_bar_but_not_confirmed']} que llegaron a la barra sin repetirse "
        "o sin sobrevivir a la corrección"
    )
    lines.append(
        f"SE DESCARTA: {c['discarded']} comparaciones con muestra suficiente y diferencia por debajo de la barra"
    )
    return "\n".join(lines)


__all__ = [
    "DIMENSIONS",
    "VERSION",
    "columns",
    "confirmed_news",
    "distance_band",
    "group_tags",
    "mode",
    "read",
    "render",
    "run",
    "weekly",
]
