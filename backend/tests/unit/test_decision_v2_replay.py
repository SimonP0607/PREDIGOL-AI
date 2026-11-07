"""The replay of decision-v2 against decision-v1 and decision-fam-v1 (``fbi.decision.replay``) without a database: the comparison of rows
with decisions, the stage a disagreement is put down to, determinism, the command's output - and that none of it can write.

The replay against a real database is in tests/integration/test_decision_v2_replay.py."""

from __future__ import annotations

import ast
import json
import random
import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from scripts import ia_decision_v2 as cli

from fbi.decision import engine, replay
from fbi.decision.families import CORE, FAMILIES
from fbi.intel import decision

from .test_decision_v2_engine import AT, KEY, MODEL, as_row, core, pick, v1, world

PACKAGE = Path(engine.__file__).parent


def pair(w: decision.World, p: dict[str, Any], ident: int, *, known_at: Any = AT) -> replay.Pair:
    _, r = v1(w, {MODEL: p})
    r = dict(r) | {"id": ident, "known_at": known_at, "model_name": MODEL, "decision_version": "x"}
    return r, "core", engine.decide(w, core({MODEL: p}))


def before_ia017(p: replay.Pair, **fields: Any) -> replay.Pair:
    """The pair with its row as decision-v1 recorded it before IA-017 (``decision.RULES``): those rows stay in ``intel.decisions`` under
    ``decision-v1``, and the replay still reads them."""
    r, family, d = p
    return dict(r) | fields, family, d


def lifted_row(ident: int) -> replay.Pair:
    """A review DOWNGRADE on a market with no validated edge: decision-v1 recorded CAUTELA before IA-017 (the context raised the state),
    decision-v2 says ABSTAIN - and so does decision-v1 since."""
    p = pair(world(edge=False, review="DOWNGRADE"), pick(), ident)
    assert (p[0]["state"], p[2] and p[2].state) == ("INVESTIGACION", "ABSTAIN"), "the two agree today"
    return before_ia017(p, state="CAUTELA", reasons=["ai_downgrade"])


def test_an_agreement_counts_and_a_disagreement_is_put_down_to_its_stage() -> None:
    agree = pair(world(), pick(), 1)
    stale = pair(world(), pick(price_age=timedelta(hours=4)), 2)
    lifted = lifted_row(3)  # decision-v1 CAUTELA (before IA-017), decision-v2 ABSTAIN
    gone = (dict(agree[0]) | {"id": 4}, "core", None)
    out = replay.compare([lifted, gone, stale, agree], families=[f.name for f in FAMILIES])
    assert out["agreement"] == {"n": 4, "agree": 2, "rate": 0.5, "unmatched": 1, "correlation_ties": 0}
    assert out["families"]["core"]["confusion"] == {"CAUTION": {"ABSTAIN": 1}, "RECOMMENDED": {"(none)": 1, "RECOMMENDED": 1}, "WATCH": {"WATCH": 1}}
    assert out["families"]["CORNERS"]["n"] == 0 and out["families"]["CORNERS"]["rate"] is None, "every family is reported"
    [d] = out["disagreements"]
    assert (d["decision_id"], d["v1_state"], d["v1_state2"], d["v2_state"], d["stage"]) == (3, "CAUTELA", "CAUTION", "ABSTAIN", "final")
    assert d["v1_codes"] == ["ai_downgrade"] and set(d["v2_codes"]) == {"ai_downgrade", "edge_not_validated"}
    assert d["v2_why"] and d["line"] == "0.00"
    [u] = out["unmatched"]
    assert u["decision_id"] == 4 and u["stage"] == replay.NOT_FOUND
    assert out["families"]["core"]["labels"] == {"n": 1, "agree": 1} and out["families"]["core"]["checkpoints"] == {"n": 3, "agree": 3}
    assert out["families"]["core"]["by_market"] == {"1X2": {"n": 4, "agree": 2, "rate": 0.5}}


def test_a_disagreement_of_correlation_on_a_tie_of_scores_says_so() -> None:
    """Before IA-017 decision-v1 broke a tie of scores on the order the database returned its candidates in; decision-v2 breaks it on the
    selection, and decision-v1 now does too. On its old rows, where the two chose differently, the replay says it was a tie."""
    k2: decision.Key = (77, "1X2", "Away", Decimal("0.00"))
    w = world()
    a, b = pick(), pick(selection="Away")
    [da, db_] = engine.decide_all(w, [core({MODEL: a}), core({MODEL: b}, k2)])
    assert da.score == db_.score and da.verdict("correlation").data["tie"] is True
    assert (da.state, db_.state) == ("CAUTION", "RECOMMENDED"), "on a tie, the selection decides: Away before Home"
    for order in ((0, 1), (1, 0)):
        ea, eb = decision.evaluate(w, KEY, {MODEL: a}), decision.evaluate(w, k2, {MODEL: b})
        decision.correlate([(ea, eb)[i] for i in order])
        rows = [as_row(e) | {"id": i, "known_at": AT, "model_name": MODEL} for i, e in enumerate((ea, eb), 1)]
        now = replay.compare([(rows[0], "core", da), (rows[1], "core", db_)], families=["core"])
        assert now["agreement"]["agree"] == 2 and not now["disagreements"], ("decision-v1 keeps Away whatever the order", order)
    # the rows decision-v1 wrote before IA-017 when it kept the first it was given (Home)
    assert (ea.state, eb.state) == ("CAUTELA", "CANDIDATO_PARLAY")
    rows = [as_row(ea) | {"id": 1, "known_at": AT, "model_name": MODEL, "state": eb.state, "reasons": []},
            as_row(eb) | {"id": 2, "known_at": AT, "model_name": MODEL, "state": "CAUTELA", "reasons": ["correlated_same_match"]}]
    out = replay.compare([(rows[0], "core", da), (rows[1], "core", db_)], families=["core"])
    assert out["agreement"]["correlation_ties"] == 2 and {d["tie"] for d in out["disagreements"]} == {True}
    assert {d["stage"] for d in out["disagreements"]} == {"correlation"}


def test_the_comparison_is_deterministic_whatever_the_order_of_its_input() -> None:
    pairs = [pair(world(edge=e, review=r), pick(odds=o, price_age=a), i, known_at=AT + timedelta(minutes=i % 3))
             for i, (e, r, o, a) in enumerate([(True, None, 2.0, timedelta(minutes=5)), (False, "REJECT", 2.0, timedelta(minutes=5)),
                                                (True, None, 3.4, timedelta(hours=4)), (False, None, 1.6, timedelta(minutes=5)),
                                                (True, "DOWNGRADE", 2.2, timedelta(minutes=50))])]
    first = json.dumps(replay.compare(pairs, families=["core"]), default=str, sort_keys=True)
    for seed in range(5):
        shuffled = pairs[:]
        random.Random(seed).shuffle(shuffled)
        assert json.dumps(replay.compare(shuffled, families=["core"]), default=str, sort_keys=True) == first


def test_the_stage_of_a_disagreement_is_the_first_whose_codes_differ() -> None:
    w = world()
    d = engine.decide(w, core({MODEL: pick(price_age=timedelta(hours=4), width=0.3)}))
    assert replay.cause({"reasons": ["risk", "price_stale"]}, d) == "final", "the same codes: the final stage"
    assert replay.cause({"reasons": ["risk"]}, d) == "market"
    assert replay.cause({"reasons": ["risk", "price_stale", "ev_cal_below", "family_research"]}, d) == "value", "the request for research is not a code"


def test_the_ai_mode_is_the_one_the_rows_recorded() -> None:
    assert replay.recorded_ai_mode([{"context_status": "AI_OFF"}, {"context_status": "AI_OFF"}]) == "off"
    assert replay.recorded_ai_mode([{"context_status": "LIMITED"}]) != "off"


def test_the_key_of_a_row_is_the_layers_key() -> None:
    assert replay.key_of({"fixture_id": 77, "market_key": "1X2", "selection": "Home", "line": Decimal("0")}) == KEY


# -- read-only, by construction ------------------------------------------------------------------------------------------------------

WRITES = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\.\w+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE)\b", re.IGNORECASE)


def test_nothing_in_the_package_or_its_command_writes_or_commits() -> None:
    for path in [*sorted(PACKAGE.glob("*.py")), Path(cli.__file__)]:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not [s for s in literals if WRITES.search(s)], f"{path.name} holds a statement that writes"
        calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        assert not calls & {"commit", "store", "select_day", "decide_families", "run_step", "stake_for"}, f"{path.name}: {calls}"
    assert "default_transaction_read_only=on" in Path(cli.__file__).read_text(encoding="utf-8"), "the command opens a read-only connection"


def test_the_sql_of_the_replay_names_the_layer_it_reads() -> None:
    for sql in (replay.DAY_SQL, replay.PREVIOUS_BEFORE_SQL):
        assert "decision_version = ANY" in sql or "decision_version = %(version)s" in sql
    assert "known_at < %(at)s" in replay.PREVIOUS_BEFORE_SQL, "the history of a row is what was written before it"


# -- the command ----------------------------------------------------------------------------------------------------------------------

def doc() -> dict[str, Any]:
    out = replay.compare([pair(world(), pick(), 1), lifted_row(2)], families=[f.name for f in FAMILIES])
    return {"version": engine.VERSION, "replay": replay.VERSION, "day": "2026-11-05", "versions": ["decision-fam-v1", "decision-v1"],
            "inputs": {"council": None, "signals": False}, "rows": 2, "moments": 1, "skipped": {"selection_copies": 0, "unclaimed": 0},
            "unclaimed_rows": []} | out


def test_the_command_renders_the_agreement_the_confusion_and_each_disagreement() -> None:
    text = cli.render(doc())
    assert "agreement: 1/2 (50.00%)" in text and "core" in text and "CORNERS" in text
    assert "stage final" in text and "CAUTION      ABSTAIN 1" in text


def test_the_command_parses_its_options() -> None:
    args = cli.build_parser().parse_args(["replay", "--day", "2026-11-05", "--json", "--council", "ma-v1", "--signals"])
    assert (args.command, args.day, args.as_json, args.council, args.signals) == ("replay", "2026-11-05", True, "ma-v1", True)
    assert cli.parse_day("2026-11-05").isoformat() == "2026-11-05"


def test_the_core_family_is_the_first_one_the_replay_tries() -> None:
    assert FAMILIES[0] is CORE
