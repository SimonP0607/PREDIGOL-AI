"""Dataset versions: what a model may learn from (``audit.dataset_versions``).

``PRE_DATA_TRUTH_AUDIT`` (LEGACY) is the data as normalized before the data-truth audits; it is never
changed - its known defects are in the evidence ledger and ``audit.data_repairs``. ``DATASET_V2`` is the
data after them: the same core tables corrected by repairs that kept the old rows, plus everything rebuilt
from RAW into new tables (phases, fixture facts, player extras, reference feeds, season aggregates).

A build records the version's counts and its gates - each a check against the newest audit run or the
ledger, with the run it read - and sets its status:

* ``CANDIDATE``  - at least one gate fails;
* ``VALIDATED``  - every gate passes (a ``note`` is not a failure: it is something a person should read);
* ``MODEL_READY`` - only by ``promote``: a person, every gate passing, research not frozen. Never automatic.

Every model entry point calls ``require_model_ready`` and refuses when no version is MODEL_READY: models
learn only from a dataset someone declared fit for it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.core.version import code_version

GateStatus = Literal["pass", "fail", "note"]
CURRENT = "DATASET_V2"


class DatasetNotModelReadyError(RuntimeError):
    """No dataset version is MODEL_READY: a model may not be trained or stored."""


@dataclass
class Gate:
    key: str
    status: GateStatus
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _latest_run(conn: psycopg.Connection[Any], kind: str, *, where: str = "") -> dict[str, Any] | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT id, started_at, status, summary, report_dir FROM audit.truth_v2_runs "
                    f"WHERE kind = %s AND status IN ('completed', 'partial') {where} "
                    f"ORDER BY started_at DESC LIMIT 1", (kind,))
        return cur.fetchone()


def _run_ref(run: dict[str, Any]) -> dict[str, Any]:
    return {"run": run["id"], "at": str(run["started_at"]), "status": run["status"], "report": run["report_dir"]}


def gate_phases(conn: psycopg.Connection[Any]) -> list[Gate]:
    out: list[Gate] = []
    current = _latest_run(conn, "phases", where="AND (summary->>'seasons')::int > 20")
    golden = _latest_run(conn, "phases", where="AND (summary->'golden'->>'checked')::int > 0")
    if current is None:
        out.append(Gate("phases", "fail", "no phases audit over the current seasons has run"))
    else:
        s = current["summary"]
        wrong = int(s.get("now_wrong") or 0)
        out.append(Gate("phases", "pass" if wrong == 0 else "fail",
                        f"{s.get('seasons')} seasons, {s.get('tables')} tables: {wrong} matches shown a wrong table; "
                        f"{s.get('stage_without_table', 0)} stages without a provider table", _run_ref(current)))
    if golden is None:
        out.append(Gate("phases_golden", "fail", "the golden phase cases have never been checked"))
    else:
        g = golden["summary"].get("golden") or {}
        failed = int(g.get("failed") or 0)
        out.append(Gate("phases_golden", "pass" if failed == 0 else "fail",
                        f"{g.get('seasons')} golden seasons, {g.get('checked')} checks, {failed} failed",
                        _run_ref(golden)))
    return out


PREDIGOL_FAULT_VERDICTS = ("predigol_behind", "mismatch", "fixtures_missing")


def gate_standings(conn: psycopg.Connection[Any]) -> list[Gate]:
    run = _latest_run(conn, "standings", where="AND (summary->>'seasons')::int > 20")
    if run is None:
        return [Gate("standings", "fail", "no standings audit over the current seasons has run")]
    verdicts = run["summary"].get("verdicts") or {}
    ours = {k: v for k, v in verdicts.items() if k in PREDIGOL_FAULT_VERDICTS and v}
    return [Gate("standings", "fail" if ours else "pass",
                 ", ".join(f"{k} {v}" for k, v in sorted(verdicts.items())) or "no verdicts", _run_ref(run))]


def gate_official(conn: psycopg.Connection[Any]) -> list[Gate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) FILTER (WHERE status = 'OPEN') AS open, count(*) AS n FROM audit.evidence_ledger "
                    "WHERE key LIKE 'standings:%%:official:%%' AND at_fault IN ('predigol', 'provider')")
        row = cur.fetchone() or {"open": 0, "n": 0}
    return [Gate("official_tables", "pass" if not row["open"] else "fail",
                 f"{row['open']} open differences against an official table ({row['n']} ever recorded); tolerance 0",
                 {"open": row["open"]})]


def gate_fields(conn: psycopg.Connection[Any]) -> list[Gate]:
    run = _latest_run(conn, "field_coverage")
    if run is None:
        return [Gate("field_coverage", "fail", "the field coverage audit has never run")]
    s = run["summary"]
    dropped = list(s.get("bug_dropped") or [])
    classes = s.get("classes") or {}
    return [Gate("field_coverage", "fail" if dropped else "pass",
                 f"{s.get('fields')} fields of {s.get('endpoints')} endpoints: "
                 + ", ".join(f"{k} {v}" for k, v in sorted(classes.items()))
                 + (f"; dropped by a bug: {', '.join(dropped[:6])}" if dropped else ""), _run_ref(run))]


def gate_raw(conn: psycopg.Connection[Any]) -> list[Gate]:
    run = _latest_run(conn, "raw_integrity", where="AND (params->>'since') IS NULL")
    if run is None:
        return [Gate("raw_integrity", "fail", "RAW integrity has never been checked")]
    s = run["summary"]
    damaged = int(s.get("damaged") or 0)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM audit.evidence_ledger WHERE area = 'raw_integrity' AND status <> 'CLEARED'")
        row = cur.fetchone()
    recorded = int(row[0]) if row else 0
    status: GateStatus = "pass" if damaged == 0 else ("note" if recorded >= damaged else "fail")
    return [Gate("raw_integrity", status,
                 f"{s.get('payloads')} payloads checked (hash: {s.get('hash_checked')}): {damaged} damaged, "
                 f"{recorded} recorded in the evidence ledger; RAW is never repaired", _run_ref(run))]


def gate_ledger(conn: psycopg.Connection[Any]) -> list[Gate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT area, issue_type, count(*) AS n FROM audit.evidence_ledger WHERE status = 'OPEN' "
                    "AND at_fault = 'predigol' AND severity IN ('critical', 'high') GROUP BY 1, 2 ORDER BY 3 DESC")
        rows = cur.fetchall()
    n = sum(int(r["n"]) for r in rows)
    return [Gate("ledger", "fail" if n else "pass",
                 f"{n} open critical/high entries at PrediGol's fault"
                 + (": " + ", ".join(f"{r['area']}/{r['issue_type']} {r['n']}" for r in rows[:8]) if rows else ""),
                 {"open": [dict(r) for r in rows]})]


def gate_history(conn: psycopg.Connection[Any]) -> list[Gate]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT class, count(*) AS n FROM analytics.competition_data_scores GROUP BY 1")
        rows = {str(r["class"]): int(r["n"]) for r in cur.fetchall()}
    ready = rows.get("MODEL_READY", 0)
    return [Gate("historical_validation", "pass" if ready else "fail",
                 "competition seasons by class: " + ", ".join(f"{k} {v}" for k, v in sorted(rows.items())),
                 {"classes": rows})]


def gate_contract() -> list[Gate]:
    from fbi.providers.api_football.integration import USES

    missing = [k for k, u in USES.items() if u.status == "MISSING"]
    wrong = [k for k, u in USES.items() if u.status == "WRONG"]
    partial = [k for k, u in USES.items() if u.status == "PARTIAL"]
    status: GateStatus = "fail" if (missing or wrong) else ("note" if partial else "pass")
    return [Gate("api_contract", status, f"{len(USES)} documented endpoints: {len(missing)} missing, {len(wrong)} "
                                         f"misread, partial: {', '.join(partial) or 'none'}",
                 {"missing": missing, "wrong": wrong, "partial": partial})]


def gate_frozen() -> list[Gate]:
    from fbi.research.loop import frozen

    why = frozen()
    return [Gate("research_frozen", "note" if why else "pass",
                 f"research is frozen: {why}" if why else "research is not frozen")]


def all_gates(conn: psycopg.Connection[Any]) -> list[Gate]:
    return [*gate_phases(conn), *gate_standings(conn), *gate_official(conn), *gate_fields(conn), *gate_raw(conn),
            *gate_ledger(conn), *gate_history(conn), *gate_contract(), *gate_frozen()]


COUNTS = {
    "fixtures": "SELECT count(*) FROM core.fixtures",
    "results": "SELECT count(*) FROM core.fixture_results",
    "odds_snapshots": "SELECT count(*) FROM market.odds_snapshots",
    "player_match_stats": "SELECT count(*) FROM core.fixture_player_stats",
    "events": "SELECT count(*) FROM core.fixture_events",
    "standings_rows": "SELECT count(*) FROM core.standings",
    "fixture_facts": "SELECT count(*) FROM core.fixture_facts",
    "player_extras": "SELECT count(*) FROM core.fixture_player_extras",
    "player_season_stats": "SELECT count(*) FROM core.player_season_stats",
    "team_season_stats": "SELECT count(*) FROM core.team_season_stats",
    "provider_predictions": "SELECT count(*) FROM core.provider_predictions",
    "season_rounds": "SELECT count(*) FROM core.season_rounds",
    "season_leaders": "SELECT count(*) FROM core.season_leaders",
    "coach_profiles": "SELECT count(*) FROM core.coach_profiles",
    "coach_careers": "SELECT count(*) FROM core.coach_careers",
    "person_sidelined": "SELECT count(*) FROM core.person_sidelined",
    "person_trophies": "SELECT count(*) FROM core.person_trophies",
    "player_transfers": "SELECT count(*) FROM core.player_transfers",
    "reference_checks": "SELECT count(*) FROM core.reference_checks",
    "raw_payloads": "SELECT count(*) FROM raw.ingestion_payloads",
    "model_ready_competition_seasons": "SELECT count(*) FROM analytics.competition_data_scores "
                                       "WHERE class = 'MODEL_READY'",
}


def counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    out = {}
    with conn.cursor() as cur:
        for k, sql in COUNTS.items():
            cur.execute(sql)
            row = cur.fetchone()
            out[k] = int(row[0]) if row else 0
    return out


@dataclass
class Build:
    name: str
    status: str
    gates: list[Gate]
    counts: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "counts": self.counts,
                "gates": [asdict(g) for g in self.gates]}


BUILT_FROM = ("core.*, market.* and analytics.* after the data-truth audits of 4 Oct 2026: repairs that kept the old "
              "rows (audit.data_repairs) and new tables rebuilt from RAW - competition phases (fbi.competitions), "
              "fixture facts and player extras, the reference feeds, the provider's season aggregates")


def build(conn: psycopg.Connection[Any], *, name: str = CURRENT, at: datetime) -> Build:
    """Record the version's counts and gates. CANDIDATE or VALIDATED - never MODEL_READY."""
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM audit.dataset_versions WHERE name = %s", (name,))
        held = cur.fetchone()
    if held is not None and held[0] in ("LEGACY", "MODEL_READY", "REJECTED"):
        raise ValueError(f"{name} is {held[0]}: it is not rebuilt (a new version gets a new name)")
    gates = all_gates(conn)
    status = "CANDIDATE" if any(g.status == "fail" for g in gates) else "VALIDATED"
    result = Build(name, status, gates, counts(conn))
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit.dataset_versions (name, status, model_ready, built_from, code_version, counts, gates, "
            "notes) VALUES (%(n)s, %(s)s, false, %(b)s, %(v)s, %(c)s, %(g)s, %(notes)s) "
            "ON CONFLICT (name) DO UPDATE SET status = EXCLUDED.status, code_version = EXCLUDED.code_version, "
            "counts = EXCLUDED.counts, gates = EXCLUDED.gates, notes = EXCLUDED.notes",
            {"n": name, "s": status, "b": BUILT_FROM, "v": code_version(), "c": Jsonb(result.counts),
             "g": Jsonb({"at": at.isoformat(), "gates": [asdict(g) for g in gates]}),
             "notes": f"built {at:%Y-%m-%d %H:%M} UTC: " + ", ".join(f"{g.key} {g.status}" for g in gates)})
    return result


def promote(conn: psycopg.Connection[Any], name: str, *, by: str, at: datetime) -> None:
    """A person declares a VALIDATED version fit for models. Refused while research is frozen or a gate fails."""
    from fbi.research.loop import frozen

    if why := frozen():
        raise ValueError(f"research is frozen ({why}): unfreeze it first, deliberately")
    with conn.cursor() as cur:
        cur.execute("SELECT status, gates FROM audit.dataset_versions WHERE name = %s", (name,))
        row = cur.fetchone()
        if row is None or row[0] != "VALIDATED":
            raise ValueError(f"{name} is {row[0] if row else 'unknown'}: only a VALIDATED version can be promoted")
        cur.execute("UPDATE audit.dataset_versions SET status = 'MODEL_READY', model_ready = true, promoted_at = %s, "
                    "notes = notes || %s WHERE name = %s",
                    (at, f" | promoted to MODEL_READY by {by} at {at:%Y-%m-%d %H:%M} UTC", name))


def require_model_ready(conn: psycopg.Connection[Any]) -> str:
    """The newest MODEL_READY dataset version, or DatasetNotModelReadyError - every training entry point asks."""
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM audit.dataset_versions WHERE status = 'MODEL_READY' ORDER BY promoted_at DESC "
                    "LIMIT 1")
        row = cur.fetchone()
        if row is not None:
            return str(row[0])
        cur.execute("SELECT name, status FROM audit.dataset_versions ORDER BY created_at")
        held = ", ".join(f"{n} {s}" for n, s in cur.fetchall()) or "none"
    raise DatasetNotModelReadyError(f"no dataset version is MODEL_READY ({held}): models may not be trained or "
                                    "stored until a person promotes a VALIDATED version (scripts.dataset_version)")
