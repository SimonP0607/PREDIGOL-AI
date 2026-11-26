"""The download of the published picks (plan PM, PM-14-08): what a third party can check of what PrediGol published.

Every pick PrediGol published - the ``qualified`` set, the only one a reader is shown; no query here names the ``evaluation`` set -
as it was frozen when it was chosen (the price taken, the probability said) and how it ended, ONE ROW PER PICK, exactly the rows and
the order of the table of «Cómo le va a PrediGol» (the same ``PICKS_SQL`` and the same cut at the end of the reader's today: a test
holds the file to the table page by page). Beside the picks, the calibration of the probabilities said - the ranges
``transparency.picks_calibration`` draws - each with the 95 % interval of what happened (Wilson), and the overall hit rate with its
interval once the sample allows (``MIN_SAMPLE``): the download shows how sure a figure is, never only the figure.

What it never holds: a pick that was not published, a return on investment, a yield, a "profit so far" or any total of units
(the table has no such figure: only each pick's own flat unit), the forecast of an evaluation model, a cookie or a user. Reading
only: nothing here computes a probability, prices a selection or changes a pick.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from math import sqrt
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

from fbi.api.contracts.transparency import PublishedPick
from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import transparency, transparency_picks
from fbi.api.services.mypicks import _csv, language_of, number_cell, text_cell, time_cell, word
from fbi.core.clock import now
from fbi.userdata.records import period_bounds

Part = Literal["picks", "calibration"]
MAX_ROWS: Final = 50_000
"""Far above the history (a handful of picks a day since 4 Oct 2026); a guard against an unbounded read, not a cut: a history that
reached it would be refused, never truncated."""
Z95: Final = 1.959964
"""The two-sided 95 % normal quantile."""

HEADINGS: Final[dict[str, dict[Part, tuple[str, ...]]]] = {
    "es": {
        "picks": ("dia", "inicio", "publicado", "liga", "pais", "local", "visitante", "mercado", "seleccion", "linea",
                  "cuota_publicada", "prob_dicha", "prob_mercado", "resultado", "unidades", "goles_local", "goles_visitante"),
        "calibration": ("rango_desde", "rango_hasta", "prob_dicha_media", "frecuencia_observada", "intervalo_95_desde",
                        "intervalo_95_hasta", "picks"),
    },
    "en": {
        "picks": ("day", "kickoff", "published_at", "league", "country", "home", "away", "market", "selection", "line",
                  "published_odds", "p_said", "p_market", "result", "units", "home_goals", "away_goals"),
        "calibration": ("range_from", "range_to", "mean_p_said", "observed_share", "interval_95_from", "interval_95_to",
                        "picks"),
    },
}


def wilson(hits: int, n: int) -> tuple[Decimal, Decimal] | None:
    """The 95 % Wilson interval of ``hits`` in ``n`` (None for no sample): well behaved at small n and at 0 % or 100 %."""
    if n <= 0:
        return None
    p = hits / n
    z2 = Z95 * Z95
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = Z95 * sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / (1 + z2 / n)
    q = Decimal("0.0001")
    return (Decimal(max(0.0, centre - half)).quantize(q), Decimal(min(1.0, centre + half)).quantize(q))


def all_picks(conn: Conn, *, tz: str, at: datetime | None = None) -> list[PublishedPick]:
    """Every published pick, newest kick-off first: the table's own rows, unpaged. A history over MAX_ROWS is an error."""
    _, until = period_bounds("all", at=at or now(), tz=tz)
    rows = fetch_all(conn, transparency_picks.PICKS_SQL,
                     {"until": until, "after_at": None, "after_id": None, "limit": MAX_ROWS + 1})
    if len(rows) > MAX_ROWS:
        raise RuntimeError("the published history is larger than the download allows")
    return [transparency_picks.pick_of(r) for r in rows]


def calibration(conn: Conn, *, tz: str, at: datetime | None = None) -> dict[str, Any]:
    """«¿Estima bien?» of the published picks with its uncertainty: the ranges of ``picks_calibration`` (ten points wide, at least
    ``MIN_BIN`` picks each, none below ``MIN_SAMPLE`` won or lost picks), each with the Wilson 95 % interval of what happened."""
    _, until = period_bounds("all", at=at or now(), tz=tz)
    rows = fetch_all(conn, transparency.PUBLISHED_SQL, {"until": until})
    cal = transparency.picks_calibration(rows)
    decided = [r for r in rows if r["status"] in ("WIN", "LOSS") and r["p_model"] is not None]
    won = sum(1 for r in decided if r["status"] == "WIN")
    enough = len(decided) >= transparency.MIN_SAMPLE
    overall = wilson(won, len(decided)) if enough else None
    hits_in: dict[int, int] = {}
    for r in decided:
        if r["status"] == "WIN":
            k = min(int(Decimal(r["p_model"]) * 10), 9)
            hits_in[k] = hits_in.get(k, 0) + 1
    bins = []
    for b in cal.bins:
        hits = hits_in.get(int(b.low * 10), 0)
        interval = wilson(hits, b.n)
        bins.append({"from": b.low, "to": b.high, "mean_said": b.predicted, "observed": b.observed, "n": b.n,
                     "interval_95": None if interval is None else {"from": interval[0], "to": interval[1]}})
    return {
        "picks_won_or_lost": len(decided), "min_sample": transparency.MIN_SAMPLE, "min_bin": transparency.MIN_BIN,
        "hit_rate": None if not enough else {
            "observed": (Decimal(won) / Decimal(len(decided))).quantize(Decimal("0.0001")), "n": len(decided),
            "interval_95": None if overall is None else {"from": overall[0], "to": overall[1]}},
        "bins": bins, "omitted": cal.omitted,
        "method": "Wilson score interval, 95 %. Only won or lost picks count; the probability is the one stored when the pick was "
                  "published, never recomputed. Ranges with fewer than min_bin picks are left out, and none is drawn below "
                  "min_sample picks.",
    }


def picks_csv(picks: Sequence[PublishedPick], *, tz: str, language: str | None) -> str:
    """The picks as the table shows them: one line each, the times in the reader's time zone, headings in their language."""
    lang = language_of(language)
    zone = ZoneInfo(tz)
    lines = [(
        str(p.day), time_cell(p.kickoff_at, zone), time_cell(p.published_at, zone), text_cell(p.competition),
        text_cell(p.country), text_cell(p.home), text_cell(p.away), text_cell(p.market), text_cell(p.selection),
        number_cell(p.line), number_cell(p.odds), number_cell(p.p_model), number_cell(p.p_market), word(lang, p.result),
        number_cell(p.units), number_cell(p.score_home), number_cell(p.score_away)) for p in picks]
    return _csv(HEADINGS[lang]["picks"], lines)


def calibration_csv(cal: dict[str, Any], *, language: str | None) -> str:
    lang = language_of(language)
    lines = []
    for b in cal["bins"]:
        interval = b["interval_95"]
        lines.append((number_cell(b["from"]), number_cell(b["to"]), number_cell(b["mean_said"]), number_cell(b["observed"]),
                      number_cell(interval["from"]) if interval else "", number_cell(interval["to"]) if interval else "",
                      str(b["n"])))
    return _csv(HEADINGS[lang]["calibration"], lines)


def picks_json(picks: Sequence[PublishedPick], cal: dict[str, Any], *, tz: str, at: datetime | None = None) -> str:
    """Picks and calibration in one document, with what a reader needs to read them (never an ROI)."""
    body = {
        "source": "PrediGol - published picks (qualified set only)", "timezone": tz,
        "generated_at": (at or now()).isoformat(timespec="seconds"), "count": len(picks),
        "notes": ["Each pick is as it was frozen when it was published: the price taken and the probability said are never recomputed.",
                  "units is the profit of a flat stake of one unit on that pick once settled (null while pending); no return "
                  "on investment is given, and past results do not say what will happen.",
                  "calibration compares the probability said with what happened, with its 95 % interval; a figure with a small "
                  "sample is not a conclusion."],
        "picks": [p.model_dump(mode="json") for p in picks], "calibration": cal,
    }
    return json.dumps(body, ensure_ascii=False, default=str, indent=1)


def filename(kind: str, ext: str, at: datetime | None = None) -> str:
    """predigol-picks-publicados-2026-12-08.csv / predigol-calibracion-2026-12-08.csv / .json."""
    return f"predigol-{kind}-{(at or now()):%Y-%m-%d}.{ext}"


