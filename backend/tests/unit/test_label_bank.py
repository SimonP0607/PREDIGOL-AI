"""The labelled bank (IA-030): a deterministic, stratified sample with a blind second share, and a score whose reference is the human label."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from fbi.ai import label_bank as lb

AT = datetime(2026, 11, 8, 12, tzinfo=UTC)


def claim_row(i: int, version: str = "extract-v3", **kw: object) -> dict[str, object]:
    base: dict[str, object] = {"id": i, "kind": "injury", "assertion": "out", "claim_type": "OUT", "subject_type": "PLAYER", "subject_id": 7,
                               "provider_player_id": 7, "team_id": 3, "fixture_id": 9, "claim": "Juan Pérez se perdió el partido por lesión",
                               "source_url": f"https://x.example/{i}", "source_domain": "x.example", "published_at": AT, "retrieved_at": AT,
                               "status": "PROBABLE", "extract_version": version, "applies_to": "THIS_MATCH", "player_name": "Juan Pérez",
                               "result_title": "Parte médico", "instruction_like": False, "team_name": "Casa", "home_name": "Casa",
                               "away_name": "Fuera", "kickoff_at": AT}
    base.update(kw)
    return base


def test_a_claim_is_stratified_by_its_extractor_and_the_type_it_says() -> None:
    c = lb.claim_candidate(claim_row(5))
    assert (c.bank, c.id, c.stratum, c.system_class) == ("claims", "ev:5", "extract-v3|OUT", "OUT")
    assert c.fields["subject"] == "PLAYER: Juan Pérez (Casa)" and c.fields["match"].startswith("Casa - Fuera")
    v1 = lb.claim_candidate(claim_row(6, "extract-v1", claim_type=None, kind="doubtful", assertion="doubtful", subject_type=None))
    assert (v1.stratum, v1.system_class) == ("extract-v1|DOUBT", "DOUBT"), "v1 wrote no type: its kind and assertion say it"
    assert lb.type_of("news", "info", None) == "OTHER" and lb.type_of("weird", "x", None) == "OTHER" and lb.type_of("injury", "out", "SUSPENSION") == "SUSPENSION"


def test_the_quota_is_shared_equally_and_a_small_stratum_gives_its_rest_to_the_others() -> None:
    assert lb.allocate({"a": 100, "b": 100, "c": 3}, 30) == {"a": 14, "b": 13, "c": 3}
    assert lb.allocate({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}, "never more than a stratum has"
    assert lb.allocate({"a": 5, "b": 0}, 4) == {"a": 4, "b": 0} and lb.allocate({}, 10) == {}
    assert sum(lb.allocate({str(i): 50 for i in range(7)}, 150).values()) == 150


def test_the_sample_is_the_same_for_the_same_seed_and_another_for_another() -> None:
    pool = [lb.claim_candidate(claim_row(i, v, claim_type=t)) for i, (v, t) in enumerate(
        [(v, t) for v in ("extract-v1", "extract-v2", "extract-v3") for t in ("OUT", "DOUBT", "SUSPENSION", "OTHER") for _ in range(40)])]
    one = lb.sample(pool, quota=150)
    assert [r["id"] for r in one] == [r["id"] for r in lb.sample(list(reversed(pool)), quota=150)], "the order of the input does not matter"
    assert len(one) == 150 and len({r["id"] for r in one}) == 150
    assert {r["stratum"] for r in one} == {c.stratum for c in pool} and max(
        sum(1 for r in one if r["stratum"] == s) for s in {c.stratum for c in pool}) == 13, "150 over 12 strata: 12 or 13 each"
    other = lb.sample(pool, quota=150, seed="another")
    assert {r["id"] for r in other} != {r["id"] for r in one}
    assert all(r[k] == "" for r in one for k in lb.LABEL_COLUMNS["claims"]), "the sheet comes with its label columns empty"


def test_at_least_a_quarter_of_every_stratum_is_marked_for_the_blind_second_labeller() -> None:
    pool = [lb.claim_candidate(claim_row(i, "extract-v2", claim_type=("OUT", "DOUBT", "COACH")[i % 3])) for i in range(90)]
    rows = lb.sample(pool, quota=31)
    for s in {r["stratum"] for r in rows}:
        mine = [r for r in rows if r["stratum"] == s]
        assert sum(1 for r in mine if r["double"]) == math.ceil(0.25 * len(mine)), s
    assert sum(1 for r in rows if r["double"]) / len(rows) >= 0.25
    assert lb.sample([], quota=10) == []
    with pytest.raises(ValueError, match="one bank per sheet"):
        lb.sample([pool[0], lb.Candidate("sentences", "cr:1:summary:0", "held", "HELD")], quota=5)


def test_a_sentence_is_stratified_by_the_reviews_verdict_and_takes_its_class() -> None:
    row = {"review_id": 4, "fixture_id": 9, "narrative_id": 12, "version": "chronicle-review-v1", "outcome": {"home_goals": 2, "away_goals": 1},
           "item": {"section": "home", "index": 1, "text": "Llega sin  Pérez.", "refs": ["P:absences.home.0"], "verdict": "did_not_play",
                    "checks": [{"ref": "P:absences.home.0", "code": "absence", "verdict": "did_not_play", "detail": "did not play"}]},
           "packet_id": 3, "home_name": "Casa", "away_name": "Fuera", "kickoff_at": AT}
    c = lb.sentence_candidate(row)
    assert (c.id, c.stratum, c.system_class, c.fields["score"], c.fields["text"]) == ("cr:4:home:1", "did_not_play", "NOT_EVALUABLE", "2-1", "Llega sin Pérez.")
    assert lb.REVIEW_CLASS["held"] == "HELD" and lb.REVIEW_CLASS["pending"] == "NOT_CHECKABLE"
    assert set(lb.REVIEW_CLASS.values()) <= set(lb.SENTENCE_LABELS)


def test_the_csv_and_the_json_carry_the_same_rows() -> None:
    rows = lb.sample([lb.claim_candidate(claim_row(i)) for i in range(8)], quota=8)
    back = lb.read_sheet(lb.to_csv(rows, bank="claims"))
    assert [r["id"] for r in back] == [r["id"] for r in rows] and list(back[0]) == list(lb.SHEET_COLUMNS["claims"])
    doc = lb.sheet(rows, bank="claims", seed=lb.SEED, window={"since": "a", "until": "b"})
    assert doc["decides"] is False and doc["labels"]["label"] == lb.CLAIM_LABELS and "NONE" in doc["labels"]["type"]
    import json

    assert [r["id"] for r in lb.read_sheet(json.dumps(doc, default=str))] == [r["id"] for r in rows]


def filled_claims() -> list[dict[str, object]]:
    def r(i: int, system: str, a: str, b: str = "", ta: str = "", tb: str = "", double: bool = False) -> dict[str, object]:
        return {"bank": "claims", "id": f"ev:{i}", "stratum": f"extract-v3|{system}", "system_class": system, "double": double,
                "label_a": a, "label_b": b, "type_a": ta, "type_b": tb, "notes": ""}
    return [r(1, "OUT", "CORRECT", "correct", double=True), r(2, "OUT", "WRONG_FACT", "WRONG_FACT", "DOUBT", "DOUBT", True),
            r(3, "OUT", "CORRECT", "NOT_IN_SOURCE", double=True), r(4, "DOUBT", "CORRECT"), r(5, "DOUBT", "WRONG_SUBJECT"),
            r(6, "OUT", "UNCLEAR"), r(7, "OUT", ""), r(8, "OUT", "MAYBE"), r(9, "OUT", "WRONG_FACT")]


def test_the_score_takes_the_human_label_and_never_resolves_a_dispute() -> None:
    rep = lb.score(filled_claims())
    assert rep["decides"] is False and "human" in rep["reference"]
    b = rep["banks"]["claims"]
    assert b["labelled"] == {"both_alike": 2, "single": 4, "disputed": 1, "none": 2}
    assert b["invalid_labels"] == [{"id": "ev:8", "column": "label_a", "value": "MAYBE"}], "a word out of the set is listed, and is no label"
    assert b["disputed"] == [{"id": "ev:3", "a": "CORRECT", "b": "NOT_IN_SOURCE"}]
    ag = b["agreement"]
    assert ag["both_labelled"] == 3 and ag["agree"]["counted"] == 2 and ag["disagreements"] == [{"id": "ev:3", "a": "CORRECT", "b": "NOT_IN_SOURCE"}]
    # decided references: ev:1 CORRECT, ev:2 WRONG_FACT, ev:4 CORRECT, ev:5 WRONG_SUBJECT, ev:9 WRONG_FACT (UNCLEAR and the dispute are out)
    assert b["undecided"] == 1 and (b["correct"]["counted"], b["correct"]["cases"]) == (2, 5)
    t = b["types"]
    assert t["matrix"] == {"DOUBT|DOUBT": 1, "DOUBT|NONE": 1, "OUT|DOUBT": 1, "OUT|OUT": 1}, "ev:9 is WRONG_FACT with no type: not in the matrix"
    assert b["wrong_fact_without_type"] == 1
    assert (t["precision"]["OUT"]["counted"], t["precision"]["OUT"]["cases"]) == (1, 2)
    assert (t["recall"]["DOUBT"]["counted"], t["recall"]["DOUBT"]["cases"]) == (1, 2)
    assert t["precision"]["OUT"]["ci95_wilson_pct"] is not None and t["precision"]["OUT"]["decides"] is False


def test_cohens_kappa() -> None:
    assert lb.cohen_kappa([]) is None and lb.cohen_kappa([("A", "A"), ("A", "A")]) is None, "one label for all: chance explains it"
    assert lb.cohen_kappa([("A", "A"), ("B", "B"), ("A", "A"), ("B", "B")]) == 1.0
    assert lb.cohen_kappa([("A", "B"), ("B", "A")]) == -1.0
    # 20 rows: 15 alike; marginals A 10/10 for a, 11/9 for b -> p_o .75, p_e .5 -> kappa .5
    pairs = [("A", "A")] * 8 + [("B", "B")] * 7 + [("A", "B")] * 2 + [("B", "A")] * 3
    assert lb.cohen_kappa(pairs) == 0.5


def test_a_sheet_with_one_labeller_or_none_still_scores() -> None:
    empty = lb.score([{"bank": "sentences", "id": "cr:1:summary:0", "stratum": "held", "system_class": "HELD", "double": "false",
                       "label_a": "", "label_b": "", "support_a": "", "support_b": ""}])
    s = empty["banks"]["sentences"]
    assert s["labelled"]["none"] == 1 and s["review"]["pairs"] == 0 and s["agreement"]["kappa"] is None and s["support"]["supported"]["cases"] == 0
    one = lb.score([{"bank": "sentences", "id": f"cr:{i}:home:0", "stratum": v, "system_class": lb.REVIEW_CLASS[v], "double": "false",
                     "label_a": h, "label_b": "", "support_a": sup, "support_b": ""}
                    for i, (v, h, sup) in enumerate([("held", "HELD", "SUPPORTED"), ("contradicted", "HELD", "SUPPORTED"),
                                                     ("not_evaluable", "NOT_EVALUABLE", "NOT_IN_SOURCES"), ("pending", "UNCLEAR", "UNCLEAR")])])
    s = one["banks"]["sentences"]
    assert s["labelled"]["single"] == 4 and s["agreement"]["both_labelled"] == 0
    assert s["review"]["matrix"] == {"CONTRADICTED|HELD": 1, "HELD|HELD": 1, "NOT_EVALUABLE|NOT_EVALUABLE": 1}
    assert (s["review"]["recall"]["HELD"]["counted"], s["review"]["recall"]["HELD"]["cases"]) == (1, 2)
    assert (s["support"]["not_in_sources"]["counted"], s["support"]["not_in_sources"]["cases"]) == (1, 3)
    text = "\n".join(lb.lines(one))
    assert "informa, no decide" in text and "exhaustividad HELD" in text and lb.score([])["banks"] == {}
