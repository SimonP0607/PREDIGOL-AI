"""When an absence reaches PrediGol, by each channel already in use (IA-150, plan PM, PM-06-03). Read only.

An ABSENCE here is one player of one match the provider's injury report listed ``Missing Fixture`` (a sporting fact: out
injured, suspended or for another reason). For each one, the first moment each channel brought it to PrediGol:

* ``proveedor_parte``     the provider's injury report (``/injuries``): the first ``LISTED`` row of
                          ``core.player_availability_obs`` (its ``observed_at`` is when WE asked, origin ``answer`` only: the
                          ``snapshot`` rows of 0078 are a copy, not an arrival);
* ``proveedor_periodos``  the provider's periods out of a player (``/sidelined``): the first ``core.person_sidelined`` row whose
                          period covers the match day;
* ``alineacion``          the first arrival of his side's official line-up (``core.fixture_lineup_arrivals``): the latest a
                          baja is confirmed, by omission.

Only channels PrediGol ALREADY reads are measured: nothing here fetches anything, and no new site is used. Official sites are
the owner's signature (DM-05, the levels of IA-147) and X is decision DM-07: both stay out until signed. A news feed item
(``news.items``) names no player yet (no player link on 20-nov-2026). The press facts the research keeps (``ai.evidence``) are
NOT read here: every reader of that table goes through Intelligence's typed-evidence guard (research v2 in shadow); their arrival
was measured once, read-only, for the guide (docs/owner/IA_150_TIEMPO_DE_LLEGADA_DE_BAJAS.md), and a reader of them is a
proposal for the Intelligence session.

What is NEVER read or returned: the provider's reason beyond telling a suspension from an injury (reduced to ``lesion``,
``sancion`` or ``otro`` in the query, as ``fbi.people.availability`` does), a name. The report is counts and
hours.

The figures: per channel, how many absences it brought, how many before kick-off and how many hours before kick-off (median,
p10, p90, with a bootstrap 95 % interval of the median); and against the provider's report, for the absences both brought
before kick-off, the median lead in hours (positive: the channel was earlier) with its interval and the share that was earlier
with a Wilson interval. The resolution is our own reading cadence (``cadence``: the provider's report is asked every few hours
per competition; the research runs at fixed hours), never the source's publication time, which no permitted source dates.

Pure but for ``load``/``report``, which read through a connection the caller keeps read-only.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "absence-timing-v1"

Channel = Literal["proveedor_parte", "proveedor_periodos", "alineacion"]
CHANNELS: Final[tuple[Channel, ...]] = ("proveedor_parte", "proveedor_periodos", "alineacion")
REFERENCE: Final[Channel] = "proveedor_parte"
Kind = Literal["lesion", "sancion", "otro"]

SMALL_SAMPLE: Final = 20
"""Below this many pairs a figure is given but marked ``muestra_pequena``."""
BOOT: Final = 2000
SEED: Final = 150
PENDING: Final = (
    "Sitios oficiales nuevos (DIMAYOR, FCF, clubes: niveles de IA-147) y su consulta legal: firma del dueño DM-05 y DM-08",
    "X (API de pago): decisión DM-07, que se toma con este informe",
    "Noticias de news.items: aún no enlazan jugadores (sin vínculo de jugador el 20-nov-2026)",
    "Prensa ya leída por la investigación (ai.evidence): medida una vez en la guía; un lector propio, propuesta a Intelligence",
)

SUSPENSION_RE: Final = "(red card|yellow cards?|suspend|suspension|banned|sanci|tarjeta)"
"""As ``fbi.people.availability._SUSPENSION``, in PostgreSQL's case-insensitive regex."""
NOT_HEALTH_RE: Final = ("^(inactive|coach.s decision|rest|off the roster|lacking match fitness|international duty|"
                        "personal reasons|national selection|loan|unknown)$")
"""Provider reasons that are neither a suspension nor about the player's body (they are ``otro``)."""

CASES_SQL: Final = """
WITH win AS (SELECT f.id, f.provider_fixture_id, f.kickoff_at, f.competition_season_id FROM core.fixtures f
              WHERE f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s AND f.status_short IN ('FT', 'AET', 'PEN')),
prov AS (SELECT o.fixture_id, o.provider_player_id, min(o.observed_at) AS first_at, max(o.provider_team_id) AS team,
                CASE WHEN bool_or(o.reason ~* %(susp)s) THEN 'sancion'
                     WHEN bool_and(o.reason ~* %(other)s) THEN 'otro' ELSE 'lesion' END AS kind
           FROM core.player_availability_obs o JOIN win ON win.id = o.fixture_id
          WHERE o.origin = 'answer' AND o.status = 'LISTED' AND o.absence_type = 'Missing Fixture' GROUP BY 1, 2),
keys AS (SELECT fixture_id, provider_player_id FROM prov)
SELECT w.provider_fixture_id AS fixture, k.provider_player_id AS player, w.kickoff_at, c.provider_league_id AS league,
       p.kind,
       p.first_at AS proveedor_parte,
       (SELECT min(s.observed_at) FROM core.person_sidelined s
         WHERE s.person_kind = 'player' AND s.provider_person_id = k.provider_player_id
           AND s.start_date <= w.kickoff_at::date AND (s.end_date IS NULL OR s.end_date >= w.kickoff_at::date)) AS proveedor_periodos,
       (SELECT min(a.observed_at) FROM core.fixture_lineup_arrivals a JOIN core.fixtures f2 ON f2.id = a.fixture_id
          JOIN core.teams t ON t.id = CASE a.team_side WHEN 'home' THEN f2.home_team_id ELSE f2.away_team_id END
         WHERE a.fixture_id = k.fixture_id AND t.provider_team_id = p.team) AS alineacion
  FROM keys k JOIN win w ON w.id = k.fixture_id
  JOIN core.competition_seasons cs ON cs.id = w.competition_season_id JOIN core.competitions c ON c.id = cs.competition_id
  JOIN prov p ON p.fixture_id = k.fixture_id AND p.provider_player_id = k.provider_player_id
 ORDER BY w.kickoff_at, k.fixture_id, k.provider_player_id
"""

CADENCE_SQL: Final = """
SELECT (params->>'league')::int AS league, count(*) AS reads,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY gap_h) AS median_gap_h
  FROM (SELECT params, extract(epoch FROM fetched_at - lag(fetched_at) OVER (PARTITION BY params->>'league', params->>'season'
                                                                               ORDER BY fetched_at)) / 3600 AS gap_h
          FROM raw.ingestion_payloads WHERE endpoint = '/injuries' AND fetched_at >= %(since)s AND fetched_at < %(until)s) x
 GROUP BY 1 ORDER BY 2 DESC
"""


@dataclass(frozen=True, slots=True)
class Case:
    fixture: int
    """The provider's fixture id."""
    player: int
    """The provider's player id."""
    kickoff_at: datetime
    league: int
    kind: Kind
    first: Mapping[Channel, datetime | None] = field(default_factory=dict)

    def hours_before(self, channel: Channel) -> float | None:
        """Hours between the channel's first arrival and the kick-off (negative: after it), or None when it never came."""
        at = self.first.get(channel)
        return None if at is None else (self.kickoff_at - at).total_seconds() / 3600


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (PostgreSQL's ``percentile_cont``)."""
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def bootstrap(values: Sequence[float], stat: Callable[[Sequence[float]], float] = statistics.median, *, n: int = BOOT,
              seed: int = SEED) -> tuple[float, float] | None:
    """The 95 % percentile interval of ``stat`` over ``n`` resamples (fixed seed: the same data give the same interval)."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    xs = list(values)
    stats = sorted(stat([rng.choice(xs) for _ in xs]) for _ in range(n))
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def _r(x: float | None, digits: int = 1) -> float | None:
    return None if x is None else round(x, digits)


def _ci(ci: tuple[float, float] | None, digits: int = 1) -> list[float] | None:
    return None if ci is None else [round(ci[0], digits), round(ci[1], digits)]


def channel_figures(cases: Sequence[Case], channel: Channel) -> dict[str, Any]:
    hours = [h for c in cases if (h := c.hours_before(channel)) is not None]
    before = [h for h in hours if h > 0]
    return {"channel": channel, "absences": len(hours), "before_kickoff": len(before), "after_kickoff": len(hours) - len(before),
            "median_h": _r(statistics.median(before)) if before else None, "p10_h": _r(quantile(before, 0.1)),
            "p90_h": _r(quantile(before, 0.9)), "median_ci95_h": _ci(bootstrap(before)),
            "small_sample": len(before) < SMALL_SAMPLE}


def against_reference(cases: Sequence[Case], channel: Channel) -> dict[str, Any]:
    """For the absences the channel and the provider's report both brought before kick-off: how many hours the channel was
    earlier (median, interval) and in what share of them."""
    leads: list[float] = []
    for c in cases:
        mine, ref = c.hours_before(channel), c.hours_before(REFERENCE)
        if mine is not None and ref is not None and mine > 0 and ref > 0:
            leads.append(mine - ref)
    earlier = sum(1 for x in leads if x > 0)
    only = sum(1 for c in cases if (h := c.hours_before(channel)) is not None and h > 0
               and not ((r := c.hours_before(REFERENCE)) is not None and r > 0))
    return {"channel": channel, "pairs": len(leads), "median_lead_h": _r(statistics.median(leads)) if leads else None,
            "median_lead_ci95_h": _ci(bootstrap(leads)), "earlier": earlier,
            "earlier_share": _r(earlier / len(leads), 3) if leads else None, "earlier_share_ci95": _ci(wilson(earlier, len(leads)), 3),
            "only_this_channel_before_kickoff": only, "small_sample": len(leads) < SMALL_SAMPLE}


def summarise(cases: Sequence[Case], *, cadence: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    kinds = Counter(c.kind for c in cases)
    leagues_with_report = sorted({c.league for c in cases if c.first.get(REFERENCE) is not None})
    return {
        "version": VERSION, "absences": len(cases), "kinds": dict(sorted(kinds.items())),
        "channels": [channel_figures(cases, ch) for ch in CHANNELS],
        "against_provider_report": [against_reference(cases, ch) for ch in CHANNELS if ch != REFERENCE],
        "leagues_with_provider_report": len(leagues_with_report),
        "cadence": [{"league": int(r["league"]), "reads": int(r["reads"]),
                     "median_gap_h": _r(None if r["median_gap_h"] is None else float(r["median_gap_h"]))} for r in cadence],
        "pending_signature": list(PENDING),
    }


def sample(cases: Sequence[Case], n: int, *, seed: int = SEED) -> list[dict[str, Any]]:
    """``n`` absences drawn with a fixed seed, with every channel's first arrival: the cases a person checks by hand against
    the stored rows (ids and times only)."""
    rng = random.Random(seed)
    picked = rng.sample(list(cases), min(n, len(cases)))
    return [{"fixture": c.fixture, "player": c.player, "kickoff_at": c.kickoff_at.isoformat(), "league": c.league, "kind": c.kind,
             **{ch: _iso(c.first.get(ch)) for ch in CHANNELS}}
            for c in sorted(picked, key=lambda c: (c.kickoff_at, c.fixture, c.player))]


def _iso(at: datetime | None) -> str | None:
    return None if at is None else at.isoformat()


KINDS: Final[Mapping[str, Kind]] = {"lesion": "lesion", "sancion": "sancion", "otro": "otro"}


def case_of(row: Mapping[str, Any]) -> Case:
    return Case(int(row["fixture"]), int(row["player"]), row["kickoff_at"], int(row["league"]),
                KINDS.get(str(row["kind"]), "otro"), {ch: row.get(ch) for ch in CHANNELS})


def load(conn: psycopg.Connection[Any], *, since: datetime, until: datetime) -> tuple[list[Case], list[dict[str, Any]]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CASES_SQL, {"since": since, "until": until, "susp": SUSPENSION_RE, "other": NOT_HEALTH_RE})
        cases = [case_of(r) for r in cur.fetchall()]
        cur.execute(CADENCE_SQL, {"since": since, "until": until})
        cadence = [dict(r) for r in cur.fetchall()]
    return cases, cadence


def report(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, measured_at: datetime,
           sample_size: int = 0) -> dict[str, Any]:
    cases, cadence = load(conn, since=since, until=until)
    out = {"window": {"since": since.isoformat(), "until": until.isoformat(), "measured_at": measured_at.isoformat()},
           **summarise(cases, cadence=cadence)}
    if sample_size:
        out["sample"] = sample(cases, sample_size)
    return out
