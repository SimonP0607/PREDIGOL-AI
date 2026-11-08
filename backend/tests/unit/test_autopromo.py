"""Bounded automatic promotion (``fbi.governance.autopromo``, autopromo-v1) without a database: the closed classes, the owner's signature, the
metric, sample, band and change-limit rules, the switch, and that nothing in it ever writes."""

from __future__ import annotations

import ast
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from scripts import ia_autopromo

from fbi.council import weights as council_weights
from fbi.governance import promotions as registry
from fbi.governance.autopromo import evaluate as ev
from fbi.governance.autopromo import policy as pol
from fbi.governance.autopromo import sources
from fbi.intel import calibration

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src/fbi/governance/autopromo"
T0 = datetime(2026, 11, 1, 12, tzinfo=UTC)
AT = T0 + timedelta(days=3)
REFIT = pol.ChangeClass.CALIBRATOR_REFIT

TERMS: dict[str, Any] = {"version": pol.VERSION, "margin": 0.002, "min_sample": 1500, "max_changes": 1, "period_days": 7, "notify": "email"}
BAND_TERMS: dict[str, Any] = TERMS | {"min_sample": 300, "band": 0.1}


def policy_row(n: int, change_class: str, *, role: str = "VALIDATED", by: str = "owner", criteria: dict[str, Any] | None = None,
               at: datetime = T0) -> dict[str, Any]:
    return {"id": n, "at": at, "entity": pol.POLICY_ENTITY, "market_key": change_class, "to_role": role,
            "criteria": TERMS if criteria is None else criteria, "reason": "the owner authorises this class", "decided_by": by}


def book(*rows: dict[str, Any]) -> pol.PolicyBook:
    return pol.book_from_rows(rows)


SIGNED = book(policy_row(1, REFIT.value))


def refit(**over: Any) -> ev.Candidate:
    base: dict[str, Any] = {"change_class": REFIT.value, "key": "OU/dixon_coles", "version": "12", "at": AT, "champion_version": "7",
                            "candidate_metric": 0.660, "champion_metric": 0.665, "n": 2000, "metric": "wf_logloss_cal",
                            "method": "logit2", "champion_method": "logit2"}
    return ev.Candidate(**(base | over))


def weight(**over: Any) -> ev.Candidate:
    base: dict[str, Any] = {"change_class": pol.ChangeClass.COUNCIL_WEIGHTS.value, "key": "1X2/match", "version": "w2", "at": AT,
                            "champion_version": "w1", "candidate_metric": 0.60, "champion_metric": 0.61, "n": 400, "current_value": 1.0,
                            "proposed_value": 1.08}
    return ev.Candidate(**(base | over))


def auto_promotion(n: int, at: datetime, change_class: str = REFIT.value) -> registry.Promotion:
    return registry.from_intel_promotion({"id": n, "at": at, "entity": "calibrator", "market_key": "OU", "model_name": "dixon_coles",
                                          "entity_id": 100 + n, "from_role": "CHALLENGER", "to_role": "CHAMPION", "gate_version": pol.VERSION,
                                          "criteria": {"change_class": change_class}, "reason": "automatic refit", "decided_by": "system"})


# ── the classes ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_classes_are_exactly_the_four_routine_changes() -> None:
    assert {c.value for c in pol.ChangeClass} == {"calibrator_refit", "council_weights", "source_credibility", "cache_windows"}
    assert not pol.NEVER_AUTOMATIC & {c.value for c in pol.ChangeClass}


@pytest.mark.parametrize("word", sorted(pol.NEVER_AUTOMATIC))
def test_a_change_that_is_never_automatic_is_refused_by_name_even_with_a_policy_and_the_switch_on(word: str) -> None:
    signed = book(policy_row(1, word))
    assert pol.class_of(word) is None and pol.refusal_of(word) == "forbidden_class"
    assert [(r.raw_class, r.reason) for r in signed.refused] == [(word, "forbidden_class")] and not signed.by_class
    a = ev.evaluate(refit(change_class=word), signed, switch_on=True)
    assert (a.verdict, a.reasons) == ("NOT_ELIGIBLE", ("forbidden_class",))


@pytest.mark.parametrize("word", ["", "CALIBRATOR_REFIT", "calibrator", "prompt", "threshold"])
def test_anything_outside_the_enum_is_refused(word: str) -> None:
    assert pol.refusal_of(word) == "unknown_class"
    assert ev.evaluate(refit(change_class=word), SIGNED, switch_on=True).reasons == ("unknown_class",)


# ── the signature ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_everything_holds_and_the_candidate_is_eligible() -> None:
    a = ev.evaluate(refit(), SIGNED, switch_on=True)
    assert (a.verdict, a.reasons, a.policy_source) == ("ELIGIBLE", (), "intel.promotions#1")


def test_without_a_signature_nothing_is_eligible() -> None:
    a = ev.evaluate(refit(), book(), switch_on=True)
    assert (a.verdict, a.reasons) == ("NOT_ELIGIBLE", ("no_signed_policy",))


def test_a_policy_signed_by_the_system_is_not_a_signature() -> None:
    b = book(policy_row(1, REFIT.value, by="system"))
    assert b.of(REFIT) is None and [r.reason for r in b.refused] == ["not_signed_by_owner"]
    assert ev.evaluate(refit(), b, switch_on=True).reasons == ("no_signed_policy",)


def test_a_policy_signed_after_the_candidate_does_not_cover_it() -> None:
    late = book(policy_row(1, REFIT.value, at=AT + timedelta(hours=1)))
    assert "no_signed_policy" in ev.evaluate(refit(), late, switch_on=True).reasons
    assert book(policy_row(1, REFIT.value, at=AT + timedelta(hours=1))).of(REFIT) is not None
    assert pol.book_from_rows([policy_row(1, REFIT.value, at=AT + timedelta(hours=1))], at=AT).of(REFIT) is None


def test_the_newest_owner_row_decides_and_a_revocation_ends_the_policy() -> None:
    b = book(policy_row(1, REFIT.value), policy_row(2, REFIT.value, role="RETIRED", criteria={}, at=T0 + timedelta(days=1)))
    assert b.of(REFIT) is not None and b.of(REFIT).status == "REVOKED"  # type: ignore[union-attr]
    assert ev.evaluate(refit(), b, switch_on=True).reasons == ("policy_revoked",)
    again = book(policy_row(1, REFIT.value), policy_row(2, REFIT.value, role="RETIRED", criteria={}, at=T0 + timedelta(days=1)),
                 policy_row(3, REFIT.value, at=T0 + timedelta(days=2)))
    assert ev.evaluate(refit(), again, switch_on=True).verdict == "ELIGIBLE"


@pytest.mark.parametrize(("change", "problem"), [
    ({"version": "autopromo-v0"}, "terms_version"),
    ({"margin": -0.001}, "terms_margin"),  # a signature cannot accept a worse candidate
    ({"margin": True}, "terms_margin"),
    ({"min_sample": 1499}, "terms_min_sample"),  # never under the class's floor
    ({"max_changes": 0}, "terms_max_changes"),
    ({"max_changes": pol.MAX_CHANGES + 1}, "terms_max_changes"),
    ({"period_days": 6}, "terms_period_days"),
    ({"band": 0.1}, "terms_band"),  # a refit has no band
    ({"notify": "sms"}, "terms_notify"),
    ({"notify": None}, "terms_notify"),
])
def test_terms_a_signature_cannot_loosen_make_the_policy_invalid(change: dict[str, Any], problem: str) -> None:
    b = book(policy_row(1, REFIT.value, criteria=TERMS | change))
    p = b.of(REFIT)
    assert p is not None and p.status == "INVALID" and problem in p.problems and p.terms is None
    assert "policy_invalid" in ev.evaluate(refit(), b, switch_on=True).reasons


@pytest.mark.parametrize(("change_class", "band"), [("council_weights", 0.26), ("source_credibility", 0.11), ("cache_windows", 0.51),
                                                    ("council_weights", 0), ("council_weights", None)])
def test_a_band_wider_than_the_class_allows_is_invalid(change_class: str, band: float | None) -> None:
    p = book(policy_row(1, change_class, criteria=BAND_TERMS | {"band": band})).of(pol.ChangeClass(change_class))
    assert p is not None and p.status == "INVALID" and "terms_band" in p.problems


def test_terms_that_are_not_an_object_or_a_role_that_is_not_a_decision() -> None:
    assert book(policy_row(1, REFIT.value, criteria=[])).of(REFIT).problems == ("terms_not_an_object",)  # type: ignore[arg-type,union-attr]
    assert book(policy_row(1, REFIT.value, role="CHAMPION")).of(REFIT).status == "INVALID"  # type: ignore[union-attr]


# ── the switch ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("env", "on"), [({}, False), ({"FBI_AUTOPROMO": ""}, False), ({"FBI_AUTOPROMO": "off"}, False),
                                         ({"FBI_AUTOPROMO": "auto"}, False), ({"FBI_AUTOPROMO": "dry"}, False),
                                         ({"FBI_AUTOPROMO": "on"}, True), ({"FBI_AUTOPROMO": " ON "}, True), ({"FBI_AUTOPROMO": "1"}, True)])
def test_the_switch_is_off_unless_it_says_on(env: dict[str, str], on: bool) -> None:
    assert pol.switch_on(env) is on


def test_the_switch_off_alone_makes_a_perfect_candidate_not_eligible() -> None:
    assert ev.evaluate(refit(), SIGNED, switch_on=False).reasons == ("switch_off",)


# ── the champion, the metric and the sample ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_first_champion_is_never_automatic_and_not_reversible() -> None:
    a = ev.evaluate(refit(champion_version=None, champion_metric=None, champion_method=None), SIGNED, switch_on=True)
    assert a.verdict == "NOT_ELIGIBLE" and {"no_champion", "not_reversible", "metric_missing"} <= set(a.reasons)


def test_a_refit_with_another_method_is_not_routine() -> None:
    assert ev.evaluate(refit(method="platt"), SIGNED, switch_on=True).reasons == ("method_changed",)


def test_the_champion_itself_is_no_candidate() -> None:
    a = ev.evaluate(refit(version="7"), SIGNED, switch_on=True)
    assert {"same_version", "not_reversible"} <= set(a.reasons)


@pytest.mark.parametrize(("candidate", "eligible"), [(0.663, True), (0.6631, False), (0.665, False), (0.70, False), (0.50, True)])
def test_the_candidate_must_beat_the_champion_by_the_margin(candidate: float, eligible: bool) -> None:
    a = ev.evaluate(refit(candidate_metric=candidate), SIGNED, switch_on=True)
    assert (a.verdict == "ELIGIBLE") is eligible
    assert eligible or a.reasons == ("not_better_than_champion",)


@pytest.mark.parametrize("metrics", [{"candidate_metric": None}, {"champion_metric": None}, {"candidate_metric": float("nan")},
                                     {"champion_metric": float("inf")}])
def test_a_missing_metric_is_not_eligible(metrics: dict[str, Any]) -> None:
    assert "metric_missing" in ev.evaluate(refit(**metrics), SIGNED, switch_on=True).reasons


def test_the_sample_is_the_policy_minimum_and_never_under_the_code_floor() -> None:
    assert ev.evaluate(refit(n=1499), SIGNED, switch_on=True).reasons == ("sample_below_minimum",)
    assert ev.evaluate(refit(n=1500), SIGNED, switch_on=True).verdict == "ELIGIBLE"
    strict = book(policy_row(1, REFIT.value, criteria=TERMS | {"min_sample": 3000}))
    assert ev.evaluate(refit(n=2999), strict, switch_on=True).reasons == ("sample_below_minimum",)
    assert ev.evaluate(refit(n=10), book(), switch_on=True).reasons == ("no_signed_policy", "sample_below_minimum")


def test_the_floors_match_the_code_they_stand_for() -> None:
    assert pol.SAMPLE_FLOOR[REFIT] == calibration.MIN_OOS_N
    assert (float(council_weights.MIN_WEIGHT), float(council_weights.MAX_WEIGHT)) == ev.WEIGHT_BOUNDS


# ── the bands ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_council_weight_within_its_band_is_eligible_and_outside_it_is_not() -> None:
    b = book(policy_row(1, "council_weights", criteria=BAND_TERMS))
    assert ev.evaluate(weight(), b, switch_on=True).verdict == "ELIGIBLE"
    assert ev.evaluate(weight(proposed_value=1.11), b, switch_on=True).reasons == ("outside_band",)
    assert ev.evaluate(weight(current_value=1.45, proposed_value=1.52), b, switch_on=True).reasons == ("outside_bounds",)
    assert "value_missing" in ev.evaluate(weight(proposed_value=None), b, switch_on=True).reasons


def test_an_agent_that_does_not_count_yet_cannot_start_counting_by_itself() -> None:
    b = book(policy_row(1, "council_weights", criteria=BAND_TERMS))
    assert "agent_not_counting" in ev.evaluate(weight(current_value=0.0, proposed_value=0.05), b, switch_on=True).reasons


def test_source_credibility_and_cache_windows_have_their_own_band() -> None:
    cred = book(policy_row(1, "source_credibility", criteria=BAND_TERMS))
    c = weight(change_class="source_credibility", key="exa:example.org", current_value=0.6, proposed_value=0.68)
    assert ev.evaluate(c, cred, switch_on=True).verdict == "ELIGIBLE"
    assert ev.evaluate(weight(change_class="source_credibility", current_value=0.95, proposed_value=1.02), cred,
                       switch_on=True).reasons == ("outside_bounds",)
    cache = book(policy_row(1, "cache_windows", criteria=BAND_TERMS | {"band": 0.5}))
    assert ev.evaluate(weight(change_class="cache_windows", current_value=3600, proposed_value=5400), cache, switch_on=True).verdict == "ELIGIBLE"
    assert ev.evaluate(weight(change_class="cache_windows", current_value=3600, proposed_value=5401), cache,
                       switch_on=True).reasons == ("outside_band",)


# ── the change limit ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_one_change_per_period_and_the_window_moves() -> None:
    inside = [auto_promotion(1, AT - timedelta(days=6))]
    assert ev.evaluate(refit(), SIGNED, switch_on=True, history=inside).reasons == ("change_limit_reached",)
    outside = [auto_promotion(1, AT - timedelta(days=7))]
    assert ev.evaluate(refit(), SIGNED, switch_on=True, history=outside).verdict == "ELIGIBLE"
    other_class = [auto_promotion(1, AT - timedelta(days=1), "council_weights")]
    assert ev.evaluate(refit(), SIGNED, switch_on=True, history=other_class).verdict == "ELIGIBLE"


def test_an_owner_promotion_is_not_counted_against_the_automatic_limit() -> None:
    owner = registry.from_intel_promotion({"id": 9, "at": AT - timedelta(days=1), "entity": "calibrator", "market_key": "OU",
                                           "model_name": "dixon_coles", "entity_id": 7, "from_role": None, "to_role": "CHAMPION",
                                           "gate_version": "calib-gate-v1", "criteria": {}, "reason": "owner", "decided_by": "owner"})
    assert ev.evaluate(refit(), SIGNED, switch_on=True, history=[owner]).verdict == "ELIGIBLE"


def test_a_bigger_limit_allows_more_changes() -> None:
    b = book(policy_row(1, REFIT.value, criteria=TERMS | {"max_changes": 2}))
    one = [auto_promotion(1, AT - timedelta(days=1))]
    assert ev.evaluate(refit(), b, switch_on=True, history=one).verdict == "ELIGIBLE"
    assert ev.evaluate(refit(), b, switch_on=True, history=[*one, auto_promotion(2, AT - timedelta(hours=1))]).reasons == ("change_limit_reached",)


# ── the candidates of the calibrator ─────────────────────────────────────────────────────────────────────────────────────────────────

def fit(n: int, method: str, known_at: datetime, ll: float | None, size: int = 2000, market: str = "OU") -> dict[str, Any]:
    return {"id": n, "market_key": market, "model_name": "dixon_coles", "method": method, "known_at": known_at,
            "wf": {"logloss_cal": ll, "n": size}}


def test_the_candidates_are_the_fits_newer_than_the_champion() -> None:
    champ = fit(7, "logit2", T0, 0.665)
    fits = [fit(7, "logit2", T0, 0.665), fit(12, "logit2", AT, 0.660), fit(13, "platt", AT, 0.650), fit(20, "logit2", AT, 0.6, market="BTTS")]
    got = sources.calibrator_candidates(fits, {"OU/dixon_coles": champ})
    assert [(c.key, c.version, c.champion_version, c.method, c.champion_method, c.candidate_metric) for c in got] == [
        ("BTTS/dixon_coles", "20", None, "logit2", None, 0.6),
        ("OU/dixon_coles", "12", "7", "logit2", "logit2", 0.66),
        ("OU/dixon_coles", "13", "7", "platt", "logit2", 0.65)]
    verdicts = {c.version: ev.evaluate(c, SIGNED, switch_on=True) for c in got}
    assert verdicts["12"].verdict == "ELIGIBLE"
    assert verdicts["13"].reasons == ("method_changed",)
    assert "no_champion" in verdicts["20"].reasons


# ── nothing writes ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

class RecordingCursor:
    def __init__(self, log: list[str], rows: dict[str, list[dict[str, Any]]]) -> None:
        self.log, self.rows, self.last = log, rows, ""

    def __enter__(self) -> RecordingCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.log.append(sql)
        self.last = sql

    def fetchall(self) -> list[dict[str, Any]]:
        for marker, rows in self.rows.items():
            if marker in self.last:
                return rows
        return []


class RecordingConnection:
    def __init__(self, rows: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.log: list[str] = []
        self.rows = rows or {}
        self.commits = 0

    def cursor(self, **_: Any) -> RecordingCursor:
        return RecordingCursor(self.log, self.rows)

    def execute(self, sql: str, params: Any = None) -> RecordingCursor:
        self.log.append(sql)
        return RecordingCursor(self.log, self.rows)

    def commit(self) -> None:
        self.commits += 1


def _intel(n: int, entity: str, to_role: str, *, entity_id: int | None = None, market: str = "OU", by: str = "system",
           criteria: dict[str, Any] | None = None, at: datetime = T0) -> dict[str, Any]:
    return {"id": n, "at": at, "entity": entity, "market_key": market, "model_name": "dixon_coles", "entity_id": entity_id, "from_role": None,
            "to_role": to_role, "gate_version": "calib-gate-v1", "criteria": criteria or {}, "reason": "reason of the row", "decided_by": by}


WORLD: dict[str, list[dict[str, Any]]] = {
    "FROM intel.promotions WHERE entity": [policy_row(50, REFIT.value), policy_row(51, "stake_policy")],
    "FROM intel.promotions ORDER BY": [_intel(1, "calibrator", "CHAMPION", entity_id=7)],
    "DISTINCT ON (c.market_key, c.model_name, c.method)": [fit(7, "logit2", T0, 0.665), fit(12, "logit2", AT, 0.660),
                                                           fit(13, "platt", AT, 0.650)],
    "WHERE id = ANY": [fit(7, "logit2", T0, 0.665)],
}


@pytest.mark.parametrize("env", [{}, {"FBI_AUTOPROMO": "on"}])
def test_the_dry_run_only_selects_and_never_commits_even_with_the_switch_on(env: dict[str, str]) -> None:
    conn = RecordingConnection(WORLD)
    out, code = ia_autopromo.run(ia_autopromo.build_parser().parse_args(["check", "--json"]), conn, env)  # type: ignore[arg-type]
    assert code == ia_autopromo.OK and isinstance(out, dict)
    assert conn.log and all(re.match(r"\s*SELECT\b", sql) for sql in conn.log), conn.log
    assert conn.commits == 0 and out["writes"] is False
    assert out["switch"] == ("on" if env else "off")
    assert out["policies"]["calibrator_refit"]["status"] == "AUTHORISED"
    assert out["refused_policies"] == [{"source": "intel.promotions#51", "class": "stake_policy", "reason": "forbidden_class"}]
    by_version = {c["candidate"]["version"]: c for c in out["candidates"]}
    assert by_version["13"]["reasons"][-1] == "method_changed"
    assert by_version["12"]["verdict"] == ("ELIGIBLE" if env else "NOT_ELIGIBLE")
    assert out["eligible"] == (1 if env else 0)


def test_the_text_report_says_it_writes_nothing() -> None:
    out, code = ia_autopromo.run(ia_autopromo.build_parser().parse_args(["check"]), RecordingConnection(WORLD), {})  # type: ignore[arg-type]
    assert code == ia_autopromo.OK and isinstance(out, str)
    assert "switch off - dry run, writes nothing" in out and "switch_off" in out


@pytest.mark.parametrize("argv", [["check", "--at", "yesterday"], ["check", "--at", "2026-11-01T00:00:00"]])
def test_the_command_refuses_what_it_cannot_answer(argv: list[str]) -> None:
    out, code = ia_autopromo.run(ia_autopromo.build_parser().parse_args(argv), conn=None)  # type: ignore[arg-type]
    assert code == ia_autopromo.CANNOT and isinstance(out, dict) and "error" in out


WRITE = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE|GRANT|COPY|MERGE)\b", re.IGNORECASE)


def test_no_statement_of_the_package_writes_and_no_code_commits_or_promotes() -> None:
    for sql in (pol.POLICY_SQL, sources.FITS_SQL, sources.BY_ID_SQL):
        assert sql.lstrip().upper().startswith("SELECT") and not WRITE.search(sql), sql
    files = [*sorted(PACKAGE.glob("*.py")), ROOT / "scripts/ia_autopromo.py"]
    assert len(files) == 5
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                assert name not in {"commit", "promote", "store_fit", "executemany", "copy", "record_switches"}, (path, name)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in {"fbi.intel.calibration", "fbi.ai.gates"}, (path, node.module)
            if isinstance(node, ast.FunctionDef):
                assert not re.match(r"(write|insert|promote|sign|store|record)", node.name), (path, node.name)
        code = "\n".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                         and re.match(r"\s*(SELECT|WITH|INSERT|UPDATE|DELETE)\b", n.value, re.IGNORECASE))
        assert not WRITE.search(code), path


def test_the_registry_reads_an_owner_policy_row_as_what_it_is() -> None:
    p = registry.from_intel_promotion(policy_row(1, REFIT.value) | {"model_name": None, "entity_id": None, "from_role": None,
                                                                     "gate_version": pol.VERSION})
    assert (p.entity_type, p.entity_key, p.decision, p.decided_by) == (pol.POLICY_ENTITY, "calibrator_refit/*", "VALIDATED", "owner")
