"""The agent evaluation bench (Plan Maestro IA, sections 22-25 and 32) - ``eval-bench-v1``: how each version of each agent behaves, day by day,
measured from what the shadow already stored. It READS ``ai.agent_runs``, ``ai.agent_tasks``, ``ai.shadow_assignments`` and
``intel.agent_attributions``; it writes nothing, calls nothing and changes nothing production decides or shows.

WHY. A gate says yes or no over a window; the bench says WHERE an agent stands and how it moves - the figures a reviewer looks at before
proposing a new version, and the ones an experiment of section 25 compares. Every figure below is computed from stored rows with one definition,
written here before any data; one that the rows cannot support is OMITTED and the report says so (``omitted``) - never filled with a guess.

THE RUNS. ``ai.agent_runs`` of the kinds in ``RUN_KINDS`` (``live`` and ``shadow``: the battery's synthetic scenarios and the replays are other
measurements), per agent, agent version and Bogotá day of ``started_at``, and summed over the window:

    runs                    every row, whatever came of it, with the count of each status
    valid_first_attempt     of the first attempts that reached the model (``attempt = 1`` and ``ok``, ``invalid``, ``abstain`` or ``timeout``), the
                            share that came back valid (``ok`` or ``abstain``: an abstention is a valid answer of the contract)
    invalid_by_code         the invalid runs by the code of their ``error`` (the part before the first colon, split on commas: a run with several
                            problems counts under each)
    retries                 the calls beyond the first that a task needed (``ai.agent_tasks.attempts - 1`` of the task whose last run is the run:
                            ``runtime.run_with_retries`` retries transport failures only); a run with no task counts none
    cost_usd, tokens        sums of ``cost_usd`` and of the input (all of it: fresh, read and written), output, cache-read, cache-write and thinking
                            tokens
    latency_ms              p50 and p95 (nearest rank) of ``latency_ms`` over the runs that have it (a paid run); a group with none has no latency
                            figure, and a report where no run has one omits the column

OVER THE WINDOW ONLY (per agent and version):

    coverage                of the matches assigned to the sample (``ai.shadow_assignments.sampled``) whose kick-off falls in the window, the share
                            with at least one valid run of that agent version. Per MATCH, not per selection: the runs name the selections by the
                            labels of their pass (``c1``, ``c2``...), which no other table joins, so «selections with a run / eligible selections»
                            is not derivable. The Statistics Agent runs only on matches with candidates of the counts families, so its share is
                            not a defect by itself. No assignment in the window: omitted
    stability               of the repeated identical inputs - two or more valid runs of the same agent version, prompt, schema and model over the
                            same ``ai.agent_tasks.input_hash`` - the share of the repeats whose output (md5 of the stored JSON) is the group's most
                            frequent one: sum(most frequent - 1) / sum(runs - 1). No repeated input: omitted (the idempotency key makes a repeat
                            rare by design: the same question is asked once)
    signal_precision        from ``intel.agent_attributions`` (``attr-v1``, the rows of the code) of the matches the version ran on in the window:
                            HIT / (HIT + MISS) of the SIGNAL rows (every code but ``VERDICT``), and the same for the ``VERDICT`` rows; ``VOID``
                            (no side taken, or a void selection) is in neither. A USEFUL SIGNAL is a signal row whose outcome is ``HIT``: the signal
                            pointed the way the result went
    cost_per_useful_signal  the version's cost over the window / its useful signals. No attribution: omitted

Nothing here reads a key, a prompt or a text a model wrote, other than the hash of the stored output."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row, tuple_row

from fbi.ai.agents.attribution import VERSION as ATTRIBUTION_VERSION
from fbi.ai.calendar import day_start, local_day
from fbi.ai.intervals import Proportion

METHOD: Final = "eval-bench-v1"
"""The definitions of this module. A change to any of them is a new version, never an edit."""
RUN_KINDS: Final = ("live", "shadow")
"""The runs that are the agent at work. ``battery`` (synthetic attacks, measured by their own rule) and ``replay`` are left out."""
CALLED: Final = ("ok", "invalid", "abstain", "timeout")
VALID: Final = ("ok", "abstain")
USEFUL_OUTCOME: Final = "HIT"


def _rate(num: int | Decimal, den: int | Decimal) -> Decimal | None:
    return None if not den else (Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else f"{value * 100:.2f}"


def percentile(values: Sequence[int], q: float) -> int | None:
    """The nearest-rank percentile (``q`` in (0, 1]) of the values; None for none."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def error_codes(head: str | None) -> list[str]:
    codes = [c.strip()[:64] for c in (head or "").split(",") if c.strip()]
    return codes or ["unknown"]


# ── one agent version, one day (or the window) ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Cell:
    """The runs of one agent version over one Bogotá day - or, summed (``combine``), over the window (``day`` None)."""

    agent: str
    version: str
    day: date | None
    runs: int = 0
    first_attempts: int = 0
    first_valid: int = 0
    retries: int = 0
    cost: Decimal = Decimal(0)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    thinking_tokens: int = 0
    latencies: tuple[int, ...] = ()
    by_status: Mapping[str, int] = field(default_factory=dict)
    invalid_by_code: Mapping[str, int] = field(default_factory=dict)

    @property
    def valid_first_attempt(self) -> Decimal | None:
        return _rate(self.first_valid, self.first_attempts)

    def as_json(self, *, latency: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "runs": self.runs, "by_status": dict(sorted(self.by_status.items())), "first_attempts": self.first_attempts,
            "valid_first_attempt_pct": _pct(self.valid_first_attempt), "invalid_by_code": dict(sorted(self.invalid_by_code.items())),
            "valid_first_attempt_interval": Proportion(self.first_valid, self.first_attempts).as_json(),
            "retries": self.retries, "cost_usd": str(self.cost.quantize(Decimal("0.000001"))),
            "tokens": {"input": self.input_tokens, "output": self.output_tokens, "cache_read": self.cached_tokens,
                       "cache_write": self.cache_write_tokens, "thinking": self.thinking_tokens}}
        if self.day is not None:
            out = {"day": self.day.isoformat(), **out}
        if latency:
            out["latency_ms"] = {"n": len(self.latencies), "p50": percentile(self.latencies, 0.5), "p95": percentile(self.latencies, 0.95)}
        return out


def _add(a: Mapping[str, int], b: Mapping[str, int]) -> dict[str, int]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0) + v
    return out


def combine(cells: Iterable[Cell], *, agent: str, version: str) -> Cell:
    """The window's totals of one agent version: every count summed and every latency kept (the percentiles are of the window's runs, not an
    average of the days')."""
    total = Cell(agent, version, None)
    for c in cells:
        total = replace(total, runs=total.runs + c.runs, first_attempts=total.first_attempts + c.first_attempts,
                        first_valid=total.first_valid + c.first_valid, retries=total.retries + c.retries, cost=total.cost + c.cost,
                        input_tokens=total.input_tokens + c.input_tokens, output_tokens=total.output_tokens + c.output_tokens,
                        cached_tokens=total.cached_tokens + c.cached_tokens, cache_write_tokens=total.cache_write_tokens + c.cache_write_tokens,
                        thinking_tokens=total.thinking_tokens + c.thinking_tokens, latencies=total.latencies + c.latencies,
                        by_status=_add(total.by_status, c.by_status), invalid_by_code=_add(total.invalid_by_code, c.invalid_by_code))
    return total


def with_statuses(cells: Iterable[Cell], rows: Iterable[tuple[str, str, date, str, str | None, int]]) -> list[Cell]:
    """The cells with their statuses and invalid codes, from (agent, version, day, status, error head, n) rows."""
    status: dict[tuple[str, str, date], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    codes: dict[tuple[str, str, date], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for agent, version, day, st, head, n in rows:
        status[(agent, version, day)][st] += n
        if st == "invalid":
            for code in error_codes(head):
                codes[(agent, version, day)][code] += n
    out: list[Cell] = []
    for c in cells:
        assert c.day is not None
        k = (c.agent, c.version, c.day)
        out.append(replace(c, by_status=dict(status.get(k, {})), invalid_by_code=dict(codes.get(k, {}))))
    return out


# ── over the window ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stability:
    inputs: int
    """Inputs asked at least twice with a valid answer."""
    repeats: int
    same: int

    @property
    def rate(self) -> Decimal | None:
        return _rate(self.same, self.repeats)

    def as_json(self) -> dict[str, Any]:
        return {"repeated_inputs": self.inputs, "repeats": self.repeats, "same_output": self.same, "rate_pct": _pct(self.rate)}


def stability(outputs: Mapping[Any, Mapping[str, int]]) -> Stability:
    """``outputs``: per identical input, how many valid runs gave each output hash. Of every input asked n >= 2 times, n - 1 repeats, of which
    (count of its most frequent output) - 1 gave the same output."""
    inputs = repeats = same = 0
    for by_hash in outputs.values():
        n = sum(by_hash.values())
        if n < 2:
            continue
        inputs += 1
        repeats += n - 1
        same += max(by_hash.values()) - 1
    return Stability(inputs, repeats, same)


@dataclass(frozen=True)
class Signals:
    hit: int = 0
    miss: int = 0
    void: int = 0
    verdict_hit: int = 0
    verdict_miss: int = 0
    verdict_void: int = 0

    @property
    def precision(self) -> Decimal | None:
        return _rate(self.hit, self.hit + self.miss)

    @property
    def verdict_precision(self) -> Decimal | None:
        return _rate(self.verdict_hit, self.verdict_hit + self.verdict_miss)

    @property
    def useful(self) -> int:
        return self.hit

    def cost_per_useful(self, cost: Decimal) -> Decimal | None:
        return None if not self.useful else (cost / self.useful).quantize(Decimal("0.000001"))

    def as_json(self, cost: Decimal) -> dict[str, Any]:
        per = self.cost_per_useful(cost)
        return {"signals": {"hit": self.hit, "miss": self.miss, "void": self.void, "precision_pct": _pct(self.precision),
                            "interval": Proportion(self.hit, self.hit + self.miss).as_json()},
                "verdict": {"hit": self.verdict_hit, "miss": self.verdict_miss, "void": self.verdict_void,
                            "precision_pct": _pct(self.verdict_precision),
                            "interval": Proportion(self.verdict_hit, self.verdict_hit + self.verdict_miss).as_json()},
                "useful_signals": self.useful, "cost_per_useful_signal_usd": None if per is None else str(per)}


def signals(rows: Iterable[tuple[bool, str, int]]) -> Signals:
    """(is the VERDICT row, outcome, n) rows into the counts of one agent version."""
    s = Signals()
    for verdict, outcome, n in rows:
        if verdict:
            s = replace(s, verdict_hit=s.verdict_hit + n * (outcome == "HIT"), verdict_miss=s.verdict_miss + n * (outcome == "MISS"),
                        verdict_void=s.verdict_void + n * (outcome == "VOID"))
        else:
            s = replace(s, hit=s.hit + n * (outcome == USEFUL_OUTCOME), miss=s.miss + n * (outcome == "MISS"), void=s.void + n * (outcome == "VOID"))
    return s


# ── the SQL ─────────────────────────────────────────────────────────────────────────────────────────────────────

_WHERE: Final = ("r.run_kind = ANY(%(kinds)s) AND r.started_at >= %(since)s AND r.started_at < %(until)s "
                 "AND (%(agent)s::text IS NULL OR r.agent = %(agent)s::text)")

CELLS_SQL: Final = f"""
SELECT r.agent, r.agent_version, (r.started_at AT TIME ZONE 'America/Bogota')::date AS day, count(*) AS runs,
       count(*) FILTER (WHERE r.attempt = 1 AND r.status = ANY(%(called)s)) AS first_attempts,
       count(*) FILTER (WHERE r.attempt = 1 AND r.status = ANY(%(valid)s)) AS first_valid,
       COALESCE(sum(GREATEST(t.attempts - 1, 0)), 0) AS retries, COALESCE(sum(r.cost_usd), 0) AS cost,
       COALESCE(sum(r.input_tokens), 0) AS input_tokens, COALESCE(sum(r.output_tokens), 0) AS output_tokens,
       COALESCE(sum(r.cached_tokens), 0) AS cached_tokens, COALESCE(sum(r.cache_write_tokens), 0) AS cache_write_tokens,
       COALESCE(sum(r.thinking_tokens), 0) AS thinking_tokens,
       COALESCE(array_agg(r.latency_ms) FILTER (WHERE r.latency_ms IS NOT NULL), '{{}}') AS latencies
  FROM ai.agent_runs r LEFT JOIN ai.agent_tasks t ON t.last_run_id = r.id
 WHERE {_WHERE}
 GROUP BY 1, 2, 3 ORDER BY 1, 2, 3
"""
STATUSES_SQL: Final = f"""
SELECT r.agent, r.agent_version, (r.started_at AT TIME ZONE 'America/Bogota')::date AS day, r.status,
       CASE WHEN r.status = 'invalid' THEN split_part(coalesce(r.error, ''), ':', 1) END AS head, count(*) AS n
  FROM ai.agent_runs r WHERE {_WHERE} GROUP BY 1, 2, 3, 4, 5
"""
ELIGIBLE_SQL: Final = """
SELECT DISTINCT a.fixture_id FROM ai.shadow_assignments a JOIN core.fixtures f ON f.id = a.fixture_id
 WHERE a.sampled AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
"""
COVERED_SQL: Final = """
SELECT r.agent, r.agent_version, count(DISTINCT r.fixture_id) AS covered
  FROM ai.agent_runs r
 WHERE r.run_kind = ANY(%(kinds)s) AND r.status = ANY(%(valid)s) AND r.fixture_id = ANY(%(fixtures)s)
   AND (%(agent)s::text IS NULL OR r.agent = %(agent)s::text)
 GROUP BY 1, 2
"""
"""The runs of the sampled matches of the window, whenever they ran (a first pass may be the day before the kick-off)."""
STABILITY_SQL: Final = f"""
SELECT r.agent, r.agent_version, r.prompt_version, r.schema_version, r.model, t.input_hash, md5(r.output::text) AS out, count(*) AS n
  FROM ai.agent_runs r JOIN ai.agent_tasks t ON t.idem_key = r.idem_key
 WHERE {_WHERE} AND r.status = ANY(%(valid)s) AND r.output IS NOT NULL
 GROUP BY 1, 2, 3, 4, 5, 6, 7
"""
SIGNALS_SQL: Final = f"""
SELECT a.agent, a.agent_version, a.signal = 'VERDICT' AS verdict, a.outcome, count(*) AS n
  FROM intel.agent_attributions a
 WHERE a.classified_by = 'code' AND a.attribution_version = %(attr)s
   AND EXISTS (SELECT 1 FROM ai.agent_runs r WHERE r.fixture_id = a.fixture_id AND r.agent = a.agent AND r.agent_version = a.agent_version
                 AND {_WHERE})
 GROUP BY 1, 2, 3, 4
"""


# ── the report ──────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AgentBench:
    agent: str
    version: str
    days: tuple[Cell, ...]
    totals: Cell
    coverage: tuple[int, int] | None = None
    """(matches covered, matches eligible), or None when eligibility cannot be read."""
    stability: Stability | None = None
    signals: Signals | None = None

    def as_json(self, *, latency: bool) -> dict[str, Any]:
        out: dict[str, Any] = {"agent": self.agent, "agent_version": self.version, "days": [c.as_json(latency=latency) for c in self.days],
                               "totals": self.totals.as_json(latency=latency)}
        if self.coverage is not None:
            covered, eligible = self.coverage
            out["coverage"] = {"matches_covered": covered, "matches_eligible": eligible, "rate_pct": _pct(_rate(covered, eligible)),
                               "interval": Proportion(covered, eligible).as_json()}
        if self.stability is not None and self.stability.repeats:
            out["stability"] = self.stability.as_json()
        if self.signals is not None:
            out["attribution"] = self.signals.as_json(self.totals.cost)
        return out


@dataclass(frozen=True)
class BenchReport:
    first: date
    last: date
    agent: str | None
    at: datetime
    agents: tuple[AgentBench, ...]
    eligible: int | None
    """Matches of the sample in the window; None when ``ai.shadow_assignments`` has none."""

    @property
    def has_latency(self) -> bool:
        return any(a.totals.latencies for a in self.agents)

    @property
    def omitted(self) -> list[str]:
        out: list[str] = []
        if not self.has_latency:
            out.append("latency: no run in the range has latency_ms")
        if self.eligible is None:
            out.append("coverage: no match of the range is in ai.shadow_assignments (the sample cannot be read)")
        if not any(a.stability is not None and a.stability.repeats for a in self.agents):
            out.append("stability: no input was asked twice with a valid answer")
        if not any(a.signals is not None for a in self.agents):
            out.append("attribution: no row of intel.agent_attributions for the matches of these runs")
        return out

    def as_json(self) -> dict[str, Any]:
        today = local_day(self.at)
        return {"method": METHOD, "from": self.first.isoformat(), "to": self.last.isoformat(), "agent": self.agent,
                "at": self.at.isoformat(), "run_kinds": list(RUN_KINDS), "complete_days_only": self.last < today,
                "agents": [a.as_json(latency=self.has_latency) for a in self.agents], "omitted": self.omitted,
                "definitions": {"useful_signal": f"a row of intel.agent_attributions ({ATTRIBUTION_VERSION}, classified_by code) whose signal is "
                                                 "not VERDICT and whose outcome is HIT",
                                "coverage": "matches of the sample (ai.shadow_assignments.sampled) with kick-off in the range that have a valid run "
                                            "of the agent version, over the matches of the sample",
                                "stability": "sum(most frequent output - 1) / sum(runs - 1) over the identical inputs asked at least twice",
                                "valid_first_attempt": "ok or abstain over the first attempts that reached the model"}}

    def lines(self) -> list[str]:
        out = [f"BANCO DE EVALUACIÓN · {METHOD} · {self.first} a {self.last} (días de Bogotá)"]
        for a in self.agents:
            t = a.totals
            lat = (f" · p50 {percentile(t.latencies, 0.5)} ms · p95 {percentile(t.latencies, 0.95)} ms" if t.latencies else "")
            out.append(f"{a.agent} {a.version}: {t.runs} ejecuciones · válidas al primer intento {_pct(t.valid_first_attempt) or '-'} % · "
                       f"inválidas {t.by_status.get('invalid', 0)} · reintentos {t.retries} · {t.cost.quantize(Decimal('0.0001'))} USD{lat}")
            out.append(f"  válidas al primer intento: {Proportion(t.first_valid, t.first_attempts).text()}")
            for c in a.days:
                out.append(f"  {c.day}: {c.runs} · válidas {_pct(c.valid_first_attempt) or '-'} % · inválidas {c.by_status.get('invalid', 0)}"
                           f" · {c.cost.quantize(Decimal('0.0001'))} USD")
        out += [f"Omitido: {o}" for o in self.omitted]
        return out


def report(conn: psycopg.Connection[Any], *, first: date, last: date, at: datetime, agent: str | None = None) -> BenchReport:
    """The bench over the Bogotá days ``first`` to ``last`` (both included), optionally for one agent. Reads only."""
    if last < first:
        raise ValueError(f"the range ends ({last}) before it starts ({first})")
    params: dict[str, Any] = {"kinds": list(RUN_KINDS), "since": day_start(first), "until": day_start(last + timedelta(days=1)),
                              "agent": agent, "called": list(CALLED), "valid": list(VALID), "attr": ATTRIBUTION_VERSION}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(CELLS_SQL, params)
        cells = [Cell(str(r["agent"]), str(r["agent_version"]), r["day"], int(r["runs"]), int(r["first_attempts"]), int(r["first_valid"]),
                      int(r["retries"]), Decimal(r["cost"]), int(r["input_tokens"]), int(r["output_tokens"]), int(r["cached_tokens"]),
                      int(r["cache_write_tokens"]), int(r["thinking_tokens"]), tuple(int(x) for x in r["latencies"] or []))
                 for r in cur.fetchall()]
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(STATUSES_SQL, params)
        cells = with_statuses(cells, [(str(a), str(v), d, str(s), h, int(n)) for a, v, d, s, h, n in cur.fetchall()])
        cur.execute(ELIGIBLE_SQL, params)
        eligible = [int(r[0]) for r in cur.fetchall()]
        covered: dict[tuple[str, str], int] = {}
        if eligible:
            cur.execute(COVERED_SQL, params | {"fixtures": eligible})
            covered = {(str(a), str(v)): int(n) for a, v, n in cur.fetchall()}
        cur.execute(STABILITY_SQL, params)
        outputs: dict[tuple[str, str], dict[tuple[Any, ...], dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
        for a, v, p, s, m, h, out, n in cur.fetchall():
            outputs[(str(a), str(v))][(p, s, m, h)][str(out)] = int(n)
        cur.execute(SIGNALS_SQL, params)
        sig_rows: dict[tuple[str, str], list[tuple[bool, str, int]]] = defaultdict(list)
        for a, v, verdict, outcome, n in cur.fetchall():
            sig_rows[(str(a), str(v))].append((bool(verdict), str(outcome), int(n)))
    by_version: dict[tuple[str, str], list[Cell]] = defaultdict(list)
    for c in cells:
        by_version[(c.agent, c.version)].append(c)
    agents = tuple(
        AgentBench(a, v, tuple(cs), combine(cs, agent=a, version=v),
                   coverage=(covered.get((a, v), 0), len(eligible)) if eligible else None,
                   stability=stability(outputs[(a, v)]) if (a, v) in outputs else None,
                   signals=signals(sig_rows[(a, v)]) if (a, v) in sig_rows else None)
        for (a, v), cs in sorted(by_version.items()))
    return BenchReport(first, last, agent, at, agents, len(eligible) if eligible else None)
