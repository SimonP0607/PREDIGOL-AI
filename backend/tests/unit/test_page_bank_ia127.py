"""IA-127 (AD-C09): the bank of pages labelled by people, the score of the four arms against it and the gate of its own - row 17 untouched."""

from __future__ import annotations

import ast
import json
import math
from pathlib import Path

import pytest

from fbi.ai import extract_protocol, gates, page_bank
from fbi.ai.page_bank import Fact, Page
from fbi.research import protocol

BACKEND = Path(__file__).resolve().parents[2]


def pages(n: int, strata: tuple[str, ...] = ("club|es|availability", "seleccion|en|preview")) -> list[Page]:
    return [Page(f"pg:{i:04d}", strata[i % len(strata)], {"url": f"https://x.example/{i}", "text": "t"}) for i in range(n)]


def test_the_sample_is_deterministic_stratified_and_a_quarter_is_double() -> None:
    a = page_bank.sample(pages(400))
    b = page_bank.sample(list(reversed(pages(400))))
    assert [r["id"] for r in a] == [r["id"] for r in b], "same pages in, same sheet out"
    assert len(a) == page_bank.QUOTA
    for stratum in {r["stratum"] for r in a}:
        rows = [r for r in a if r["stratum"] == stratum]
        assert sum(1 for r in rows if r["double"]) == math.ceil(0.25 * len(rows))
    other = page_bank.sample(pages(400), seed="otra-semilla")
    assert {r["id"] for r in other} != {r["id"] for r in a}
    assert page_bank.sample(pages(3), quota=150) and len(page_bank.sample(pages(3))) == 3


def test_the_sheet_is_untrusted_never_published_and_carries_the_protocol() -> None:
    doc = page_bank.sheet(page_bank.sample(pages(10)), window={"kickoff_from": "a", "kickoff_to": "b"})
    assert doc["untrusted"] is True and doc["publish"] is False and doc["decides"] is False
    assert doc["protocol"]["fingerprint"] == protocol.fingerprint(protocol.require("AD-C09"))
    template = page_bank.labels_template(page_bank.sample(pages(10)))
    assert template.splitlines()[0] == ",".join(page_bank.LABEL_COLUMNS)


def test_a_page_without_a_label_is_left_out_never_guessed() -> None:
    text = ("page_id,labeller,subject,provider_id,claim_type,quote,notes\n"
            "pg:1,a,Juan Pérez,10,OUT,no jugará,\n"
            "pg:2,a,,,NONE,,\n"
            "pg:3,a,,,,,\n"                      # an unfilled line of the template: labels nothing
            "pg:4,a,Luis,,BANNED,,\n"            # a word out of the list: listed, does not count
            "pg:5,c,Luis,,OUT,,\n")              # an unknown labeller
    labels, invalid = page_bank.read_labels(text)
    assert labels[("pg:1", "a")][0].provider_id == 10 and labels[("pg:2", "a")] == []
    assert ("pg:3", "a") not in labels and ("pg:4", "a") not in labels and ("pg:5", "c") not in labels
    assert {i["why"] for i in invalid} == {"claim_type", "page_or_labeller"}
    ref = page_bank.reference([{"id": f"pg:{i}"} for i in range(1, 6)], labels)
    assert set(ref.pages) == {"pg:1", "pg:2"} and ref.pages["pg:2"] == []


def test_a_double_page_keeps_what_both_wrote_and_sets_apart_what_one_wrote() -> None:
    a = [Fact("p", "Juan Pérez", "OUT"), Fact("p", "Luis Díaz", "STARTER")]
    b = [Fact("p", "J. Pérez", "OUT"), Fact("p", "Carlos", "DOUBT")]
    ref = page_bank.reference([{"id": "p"}], {("p", "a"): a, ("p", "b"): b})
    assert [f.subject for f in ref.pages["p"]] == ["Juan Pérez"]
    assert {f.subject for f in ref.disputed["p"]} == {"Luis Díaz", "Carlos"}
    assert ref.agreement == 0.5


def test_matching_is_by_type_and_compatible_subject_and_a_list_counts_per_player() -> None:
    assert Fact("p", "Juan Pérez", "OUT").compatible(Fact("p", "Pérez", "OUT"))
    assert not Fact("p", "Juan Pérez", "OUT").compatible(Fact("p", "Juan Pérez", "DOUBT"))
    assert not Fact("p", "x", "OUT", 1).compatible(Fact("p", "x", "OUT", 2)), "two provider ids decide"
    assert Fact("p", "", "SCHEDULE").compatible(Fact("p", "", "SCHEDULE"))
    arms, invalid = page_bank.read_arms(json.dumps({"arms": {"v4": {"p": [
        {"claim_type": "LIST_OUT", "players": [{"subject": "A Uno"}, {"subject": "B Dos"}]}, {"claim_type": "WHAT"}]},
        "otro": {}}}))
    assert [f.claim_type for f in arms["v4"]["p"]] == ["OUT", "OUT"]
    assert {i["why"] for i in invalid} == {"claim_type", "arm"}


def test_an_arm_scores_precision_recall_and_a_disputed_claim_counts_neither_way() -> None:
    rows = [{"id": "p", "stratum": "club|es|availability"}]
    labels = {("p", "a"): [Fact("p", "Juan Pérez", "OUT"), Fact("p", "Luis Díaz", "STARTER")],
              ("p", "b"): [Fact("p", "Juan Pérez", "OUT"), Fact("p", "Luis Díaz", "STARTER"), Fact("p", "Carlos Ruiz", "DOUBT")]}
    system = {"p": [Fact("p", "Pérez", "OUT"), Fact("p", "Carlos Ruiz", "DOUBT"), Fact("p", "Otro Nombre", "OUT")], "q": [Fact("q", "x", "OUT")]}
    s = page_bank.score_arm("v4", page_bank.reference(rows, labels), system, {"p": "club|es|availability"})
    assert (s["true"], s["false"], s["disputed_neutral"], s["outside_bank"]) == (1, 1, 1, 1)
    assert s["recall"]["counted"] == 1 and s["recall"]["cases"] == 2
    assert s["precision"]["counted"] == 1 and s["precision"]["cases"] == 2
    assert s["recall"]["level_corrected"] == 0.9875 and s["review"]["checked"] == 2


def world(n_pages: int, *, recall_hits: int, wrong: int = 0, disagree: bool = False) -> tuple[list[dict[str, object]], dict, dict]:
    rows = [{"id": f"p{i}", "stratum": "club|es|availability", "double": i % 4 == 0} for i in range(n_pages)]
    labels: dict[tuple[str, str], list[Fact]] = {}
    system: dict[str, list[Fact]] = {}
    for i in range(n_pages):
        truth = [Fact(f"p{i}", f"Jugador Numero{i}a", "OUT"), Fact(f"p{i}", f"Jugador Numero{i}b", "STARTER")]
        labels[(f"p{i}", "a")] = truth
        if i % 4 == 0:
            labels[(f"p{i}", "b")] = [Fact(f"p{i}", "Nadie Igual", "COACH")] if disagree else list(truth)
        system[f"p{i}"] = list(truth[:1]) if i < recall_hits else []
        if i < wrong:
            system[f"p{i}"].append(Fact(f"p{i}", "Inventado Total", "SUSPENSION"))
    return rows, labels, {"ventanas": system}


def test_the_verdicts_of_the_protocol() -> None:
    rows, labels, arms = world(60, recall_hits=60)
    rep = page_bank.score(rows, labels, arms)
    assert rep["arms"]["ventanas"]["verdict"] == "INSUFICIENTE" and rep["arms"]["v4"]["verdict"] == "INSUFICIENTE"
    rows, labels, arms = world(160, recall_hits=160)  # half of the reference found: recall 0.5 < 0.60
    rep = page_bank.score(rows, labels, arms)
    assert rep["arms"]["ventanas"]["verdict"] == "NO_PASA" and rep["agreement"] == 1.0
    rows, labels, arms = world(160, recall_hits=160, disagree=True)
    assert page_bank.score(rows, labels, arms)["arms"]["ventanas"]["verdict"] == "NO_EVALUABLE"
    arm = {"review": {"checked": 50, "correct": 47}, "recall": {"ci_corrected": [0.61, 0.8]}}
    assert page_bank.verdict(arm, pages=150, double=38, agreement=0.9) == ("PASA", [])
    assert page_bank.verdict(arm | {"review": {"checked": 50, "correct": 46}}, pages=150, double=38, agreement=0.9)[0] == "NO_PASA"
    assert page_bank.verdict(arm, pages=150, double=10, agreement=0.9)[0] == "INSUFICIENTE"


def test_the_code_keeps_the_thresholds_the_protocol_registered() -> None:
    p = protocol.require("AD-C09")
    assert "al menos 47 de sus 50" in p.pass_rule and page_bank.REVIEW_MIN == 47 and page_bank.REVIEW == 50
    assert "≥ 0,60" in p.pass_rule and page_bank.RECALL_MIN == 0.60
    assert "≥ 0,80" in p.pass_rule and page_bank.AGREEMENT_MIN == 0.80
    assert "150 páginas" in p.min_sample and page_bank.QUOTA == 150 and page_bank.DOUBLE_SHARE == 0.25
    assert "1 - 0,05/4" in p.primary_metric and pytest.approx(2.498, abs=1e-3) == page_bank.Z_CORRECTED
    assert "«ventanas»" in p.pass_rule and page_bank.CANDIDATE_ARM == "ventanas" and len(page_bank.ARMS) == 4
    assert f"proto-ad-c09-v1:{p.seed}" == page_bank.SEED
    assert extract_protocol.THRESHOLDS["recall_min"] == page_bank.RECALL_MIN


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.ImportFrom) and n.module:
            out |= {f"{n.module}.{a.name}" for a in n.names} | {n.module}
        elif isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
    return out


def test_no_gate_threshold_agent_or_learner_reads_the_bank_but_its_own_gate() -> None:
    sources = [*(BACKEND / "src").rglob("*.py"), *(BACKEND / "scripts").glob("*.py"), *(BACKEND / "apps").rglob("*.py")]
    readers = sorted(str(p.relative_to(BACKEND)) for p in sources
                     if any(m in ("fbi.ai.page_bank", "fbi.ai.page_bank_readers", "fbi.ai.extract_protocol") or m.startswith("fbi.ai.page_bank.")
                            for m in _imports(p)) or "fbi.ai.page_bank" in {m.rsplit(".", 1)[0] for m in _imports(p)})
    assert readers == ["scripts/ia_page_bank.py", "src/fbi/ai/extract_protocol.py", "src/fbi/ai/page_bank_readers.py"], readers
    named = sorted(str(p.relative_to(BACKEND)) for p in sources if "'extract_protocol'" in p.read_text(encoding="utf-8"))
    assert named == ["src/fbi/ai/extract_protocol.py"], "nothing switches on a row of the gate"


def test_row_17_stays_the_research_gate_is_untouched() -> None:
    text = (BACKEND / "src/fbi/ai/extract_protocol.py").read_text(encoding="utf-8")
    code = text.split('"""', 2)[2]
    assert "research_v2" not in code.replace('"row_17": "research_v2 se conserva tal cual (NO PASA, 12-nov)"', "")
    assert "extract_protocol" not in gates.GATES and "research_v2" in gates.GATES
    assert "extract_protocol" not in (BACKEND / "src/fbi/ai/gates.py").read_text(encoding="utf-8")
    assert "page_bank" not in (BACKEND / "src/fbi/ai/gate_research.py").read_text(encoding="utf-8")


def test_the_migration_admits_the_gate_and_keeps_every_other() -> None:
    mig = (BACKEND / "migrations/versions/0162_source_credibility_extract_gate.py").read_text(encoding="utf-8")
    assert '"extract_protocol"' in mig and 'down_revision = "0161"' in mig
    for g in ("batch", "native_schema", "cache_layout", "gate_a", "battery", "research_v2", "switches", "gate_b", "lab_plan"):
        assert f'"{g}"' in mig


def test_the_owners_signature_is_a_preview_without_confirmation() -> None:
    class NoDb:
        def cursor(self, *a: object, **k: object) -> object:
            raise AssertionError("a preview writes nothing")

    out = extract_protocol.sign(NoDb(), reason="", confirm_owner=False, at=None)  # type: ignore[arg-type]
    assert out["written"] is False and out["lines"][0].startswith("VISTA PREVIA")
