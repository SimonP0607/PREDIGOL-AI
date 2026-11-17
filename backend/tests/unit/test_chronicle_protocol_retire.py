"""The protocol of the human review (IA-118, ``chronicle-protocol-v1``) and the retirement of the duplicated texts (IA-119, AD-F05,
``retire-compare-v1``): both PREREGISTERED and UNSIGNED. n = 50 with 0 failures says «below 6 %»; the sample is deterministic; the
comparison is on the same matches and needs enough of them; no retirement is signed, nothing is turned off, no row is deleted; the
retirement of the readers' chronicle uses the switch the code really reads; and no screen is ever left without a text."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.api.services import reading
from fbi.chronicle import plan as cp
from fbi.chronicle import protocol, repetition, retire, verify
from tests.unit.test_chronicle_plan import inp
from tests.unit.test_chronicle_verify import CLAIMS, FIG, GOOD, chronicle

KICKOFF = datetime(2026, 11, 20, 20, tzinfo=UTC)
BEFORE = KICKOFF - timedelta(hours=3)


# ── the protocol ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_fifty_chronicles_without_a_failure_say_below_six_percent_and_no_more() -> None:
    bound = protocol.upper_bound(0, 50)
    assert bound is not None and 0.057 < bound < 0.06
    one = protocol.upper_bound(1, 50)
    assert one is not None and bound < one < 0.10
    assert protocol.upper_bound(0, 0) is None and protocol.upper_bound(5, 5) == 1.0


def test_the_protocol_is_preregistered_and_unsigned() -> None:
    s = protocol.status()
    assert s["signed"] is False and s["signature"] is None and protocol.SIGNED is False
    assert s["thresholds"]["sample"] == 50 and s["thresholds"]["unsupported_sentences_max"] == 0
    assert s["thresholds"]["stock_share_max"] == repetition.SHARE_MAX


def test_the_sample_is_deterministic_and_the_double_reading_is_inside_it() -> None:
    a, d = protocol.sample(range(1, 400))
    b, _ = protocol.sample(reversed(range(1, 400)))
    assert a == b and len(a) == protocol.SAMPLE and set(d) <= set(a) and len(d) == protocol.DOUBLE
    assert protocol.sample(range(1, 400), seed="otra")[0] != a


def test_the_sheet_never_shows_the_codes_verdict_and_the_score_counts_what_people_said() -> None:
    reviews = [{"id": 1, "chronicle_id": 10, "fixture_id": 7001, "facts": {"P:form.home": {"kind": "form", "params": {"n": 5}}},
                "items": [{"part": "chronicle", "section": "como_llega", "index": 0, "text": "x", "facts": ["P:form.home"],
                           "verdict": "not_evaluable"}]}]
    rows = protocol.sheet(reviews, double=[1])
    assert rows[0]["cited"] == [{"id": "P:form.home", "kind": "form", "params": {"n": 5}}] and "verdict" not in rows[0]
    filled = [{**rows[0], "label": "SUPPORTED", "label_second": "SUPPORTED"},
              {**rows[0], "review_id": 2, "label": "NOT_IN_SOURCES", "label_second": "SUPPORTED"},
              {**rows[0], "review_id": 3, "label": "UNCLEAR"}]
    s = protocol.score(filled)
    assert s["judged"] == 2 and s["unsupported"] == 1 and s["undecided"] == 1 and s["agreement"] == 0.5
    assert s["disagreements"][0]["review_id"] == 2 and s["meets"] == {"sample": False, "unsupported": False, "agreement": False}


# ── the steps of the retirement ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_readers_chronicle_retires_with_the_switch_the_code_reads_and_the_others_have_none() -> None:
    steps = {s.text: s for s in retire.STEPS}
    assert steps["user-narrative-v3"].switch == reading.NARRATIVE_SWITCH == "FBI_USER_NARRATIVE" and steps["user-narrative-v3"].off == "off"
    assert steps["brief-v8"].switch is None and steps["match-analysis-v1"].switch is None
    assert [s.order for s in retire.STEPS] == [1, 2, 3] and all(s.back and s.table for s in retire.STEPS)
    assert retire.step_state(steps["brief-v8"], "CUMPLE") == "sin_interruptor"
    assert retire.step_state(steps["user-narrative-v3"], "CUMPLE") == "lista_para_firma"
    assert retire.step_state(steps["user-narrative-v3"], "INSUFICIENTE") == "esperando_comparacion"
    assert retire.step_state(steps["user-narrative-v3"], "NO_CUMPLE") == "no_cumple"
    assert retire.SIGNATURES == {}, "no retirement is signed by the code"


def test_no_screen_is_ever_left_without_a_text() -> None:
    rows: list[dict[str, Any] | None] = [None, {"status": "ok", "content": {"es": {}}, "version": "chronicle-v4"},
                                         {"status": "abstained", "abstention": "SIN_DATOS"}, {"status": "rejected", "abstention": "VERIFICACION_VACIA"},
                                         {"status": "failed", "abstention": None}]
    for row, retired, legacy in itertools.product(rows, ([], ["user-narrative-v3"]), (True, False)):
        s = retire.shown(row, retired=retired, legacy_ok=legacy)
        assert s.kind in ("chronicle", "legacy", "abstention") and s.version, (row, retired, legacy)
        if s.kind == "legacy":
            assert "user-narrative-v3" not in retired
        if s.kind == "abstention":
            assert s.version in ("SIN_PLAN", "SIN_DATOS", "VERIFICACION_VACIA")


# ── the comparison ──────────────────────────────────────────────────────────────────────────────────────────────────────────

PLAIN = cp.build(inp(figures=(FIG,)))
"""A match where the engine proved nothing: «nada en juego» is authorised by no fact of its plan."""
V4 = verify.verify(chronicle({k: v for k, v in GOOD.items() if k not in ("que_se_juega", "que_falta")}), PLAIN, CLAIMS).content
LIES = [{"key": "stakes", "sentences": [{"text": "Al Getafe ya no le queda nada en juego en la liga."}]}]


def world(n: int, *, v3_ok: float, v4_ok: float = 1.0) -> tuple[dict[int, datetime], dict[str, list[dict[str, Any]]]]:
    matches = dict.fromkeys(range(n), KICKOFF)
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in (retire.CHRONICLE, *retire.TEXTS)}
    plan = PLAIN.as_json()
    for i in range(n):
        ok4 = i < round(n * v4_ok)
        rows[retire.CHRONICLE].append({"fixture_id": i, "created_at": BEFORE, "status": "partial" if ok4 else "rejected",
                                       "content": V4 if ok4 else None, "plan": plan, "cost_usd": Decimal("0.004")})
        ok3 = i < round(n * v3_ok)
        rows["user-narrative-v3"].append({"fixture_id": i, "created_at": BEFORE, "status": "ok" if ok3 else "rejected",
                                          "content": {"es": LIES} if ok3 else None, "cost_usd": Decimal("0.01")})
        rows["brief-v8"].append({"fixture_id": i, "created_at": BEFORE, "status": "ok", "engine": "llm", "cost_usd": Decimal("0.02"),
                                 "narrative": {"conclusion": "Partido igualado. Sin datos suficientes."}})
        rows["match-analysis-v1"].append({"fixture_id": i, "created_at": BEFORE, "cost_usd": 0})
    return matches, rows


def test_the_comparison_needs_enough_of_the_same_matches() -> None:
    m, r = world(40, v3_ok=0.37)
    out = retire.report(m, r, since=KICKOFF - timedelta(days=14), until=KICKOFF)
    assert all(a["verdict"] == "INSUFICIENTE" for a in out["against"].values())
    assert out["deleted_rows"] == 0 and out["decides"] is False and out["rule"]["signed"] is False


def test_a_better_single_chronicle_meets_the_rule_and_is_only_ready_for_the_owners_signature() -> None:
    m, r = world(150, v3_ok=0.37)
    out = retire.report(m, r, since=KICKOFF - timedelta(days=14), until=KICKOFF)
    v3 = out["against"]["user-narrative-v3"]
    assert v3["metrics"]["support"]["verdict"] == "MEJOR" and v3["metrics"]["unsupported"]["verdict"] in ("MEJOR", "NO_PEOR")
    assert v3["verdict"] == "CUMPLE" and v3["step"]["state"] == "lista_para_firma" and v3["step"]["switch"] == "FBI_USER_NARRATIVE"
    assert out["texts"]["user-narrative-v3"]["unsupported"]["k"] == round(150 * 0.37), "«nada en juego» without the engine"
    assert out["texts"][retire.CHRONICLE]["unsupported"]["k"] == 0
    assert out["against"]["brief-v8"]["step"]["state"] == "sin_interruptor"
    assert out["against"]["match-analysis-v1"]["metrics"]["support"]["verdict"] == "NO_APLICA"


def test_a_worse_single_chronicle_does_not_meet_the_rule() -> None:
    m, r = world(150, v3_ok=0.9, v4_ok=0.5)
    out = retire.report(m, r, since=KICKOFF - timedelta(days=14), until=KICKOFF)
    assert out["against"]["user-narrative-v3"]["verdict"] == "NO_CUMPLE"
    assert out["against"]["user-narrative-v3"]["step"]["state"] == "no_cumple"


def test_a_text_written_after_kick_off_is_not_counted() -> None:
    m, r = world(120, v3_ok=1.0)
    for row in r["user-narrative-v3"]:
        row["created_at"] = KICKOFF + timedelta(minutes=1)
    t = retire.tally(m, r)
    assert t["user-narrative-v3"].attempts == 0 and t["user-narrative-v3"].covered == 0


def test_the_command_line_reads_the_protocol_and_scores_a_sheet_without_a_database(tmp_path: Any, capsys: Any) -> None:
    from pathlib import Path

    from scripts import ia_chronicle_eval as cli

    assert cli.main(["protocol"]) == 0 and '"signed": false' in capsys.readouterr().out
    rows = protocol.sheet([{"id": 4, "chronicle_id": 1, "fixture_id": 2, "facts": {},
                            "items": [{"part": "chronicle", "section": "como_llega", "index": 0, "text": "x", "facts": []}]}], double=[4])
    sheet = Path(tmp_path) / "hoja.csv"
    cli.write_sheet([{**rows[0], "label": "SUPPORTED", "label_second": "SUPPORTED"}], sheet)
    assert cli.main(["score", str(sheet)]) == 0
    out = capsys.readouterr().out
    assert '"unsupported": 0' in out and '"agreement": 1.0' in out
    assert cli.main(["sample"]) == cli.CANNOT and cli.main(["score"]) == cli.CANNOT
