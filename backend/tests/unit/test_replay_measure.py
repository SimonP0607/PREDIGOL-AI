"""The rule of reproducibility of the replay bank (IA-047, ``replay-measure-v1``): written before the data, pure, and every
verdict recomputable from its evidence. No database, no model, no clock."""

from __future__ import annotations

import random

import pytest

from fbi.ai.replay import measure
from fbi.ai.replay.measure import Answers, Unit

STANCES = ("SUPPORT", "NEUTRAL", "CONCERN", "REJECT_SIGNAL")


def units(n: int, *, matches: int, stored: str = "NEUTRAL", first: str = "NEUTRAL", second: str = "NEUTRAL") -> list[Unit]:
    return [Unit(item=i, fixture=i % matches, key="c1", stored=stored, first=first, second=second) for i in range(n)]


def ok(n: int) -> Answers:
    return Answers(stored=n, stored_invalid=0, replays=2 * n, replays_invalid=0)


def test_a_replay_that_says_what_was_stored_passes_with_enough_units_of_enough_matches() -> None:
    got = measure.assess(units(240, matches=40), ok(240))
    assert got["verdict"] == measure.PASS and got["passed"] is True and got["reasons"] == []
    assert got["complete_units"] == 240 and got["matches"] == 40 and got["changed_stored"] == got["changed_repeat"] == 0
    assert got["all_three_agree"] == 1.0 and got["difference"] == 0.0 and got["difference_ci95"] == [0.0, 0.0]


@pytest.mark.parametrize("n, matches", [(199, 40), (240, 29), (0, 1)])
def test_fewer_units_or_fewer_matches_than_the_rule_asks_is_insufficient_never_a_pass(n: int, matches: int) -> None:
    got = measure.assess(units(n, matches=matches), ok(n))
    assert got["verdict"] == measure.INSUFFICIENT and got["passed"] is False
    assert any(r.startswith("insufficient") for r in got["reasons"])


def test_a_replay_that_moves_more_of_what_was_stored_than_repeating_the_call_moves_does_not_pass() -> None:
    same = units(200, matches=40)
    moved = [Unit(1000 + i, i % 40, "c1", "SUPPORT", "NEUTRAL", "NEUTRAL") for i in range(30)]
    got = measure.assess(same + moved, ok(230))
    assert got["verdict"] == measure.FAIL and got["changed_stored"] == 30 and got["changed_repeat"] == 0
    assert got["moves"]["stored_to_first"] == {"SUPPORT>NEUTRAL": 30} and got["moves"]["first_to_second"] == {}
    assert got["toward_restriction"] == {"stored": 0, "repeat": 0} and got["toward_favouring"] == {"stored": 0, "repeat": 0}
    assert got["difference_ci95"][0] > 0, "thirty moves of 230 over forty matches are no luck"


def test_a_change_no_larger_than_the_one_of_repeating_the_call_passes() -> None:
    base = units(200, matches=40)
    noisy = [Unit(2000 + i, i % 40, "c1", "APPROVE", "APPROVE", "ABSTAIN") for i in range(20)]
    moved = [Unit(3000 + i, i % 40, "c1", "ABSTAIN", "APPROVE", "APPROVE") for i in range(20)]
    got = measure.assess(base + noisy + moved, ok(240))
    assert got["changed_stored"] == 20 and got["changed_repeat"] == 20 and got["verdict"] == measure.PASS
    assert got["toward_favouring"] == {"stored": 20, "repeat": 0} and got["toward_restriction"] == {"stored": 0, "repeat": 20}
    assert got["change_stored_both"] == round(60 / 480, 4), "the stored answer against BOTH replays is reported"


@pytest.mark.parametrize("replays_invalid, stored_invalid, passes", [(5, 0, True), (6, 0, False), (14, 10, True), (15, 30, True),
                                                                    (16, 30, False)])
def test_the_replays_that_do_not_stand_are_at_most_three_percent_and_one_point_above_the_stored(replays_invalid: int, stored_invalid: int,
                                                                                                 passes: bool) -> None:
    answers = Answers(stored=250, stored_invalid=stored_invalid, replays=500, replays_invalid=replays_invalid)
    got = measure.assess(units(240, matches=40), answers)
    assert got["passed"] is passes
    assert ("the replays do not stand more often than allowed" in got["reasons"]) is not passes


def test_nothing_is_decided_while_an_ask_is_on_its_way() -> None:
    got = measure.assess(units(240, matches=40), Answers(240, 0, 470, 0, open=10))
    assert got["verdict"] == measure.INSUFFICIENT and "10 ask(s) still on their way" in got["reasons"]


def test_the_units_of_a_run_are_the_stored_answers_and_a_reading_that_does_not_exist_is_none() -> None:
    got = measure.units_of(7, 3, {"c1": "SUPPORT", "c2": "NEUTRAL"}, {"c1": "SUPPORT", "c2": "CONCERN"}, None)
    assert got == [Unit(7, 3, "c1", "SUPPORT", "SUPPORT", None), Unit(7, 3, "c2", "NEUTRAL", "CONCERN", None)]
    assert not any(u.complete for u in got)
    assert measure.units_of(8, 3, None, {"c2": "APPROVE"}, {"c1": "REJECT"}) == [Unit(8, 3, "c1", None, None, "REJECT"),
                                                                                 Unit(8, 3, "c2", None, "APPROVE", None)]
    assert measure.units_of(9, 3, None, None, None) == []


def test_the_interval_is_drawn_by_matches_and_is_the_same_every_time() -> None:
    rng = random.Random(4)
    data = [Unit(i, i % 35, "c1", rng.choice(STANCES[:2]), rng.choice(STANCES[:2]), rng.choice(STANCES[:2])) for i in range(300)]
    a = measure.bootstrap_difference(data)
    assert a is not None and a == measure.bootstrap_difference(data) and a[0] <= a[1]
    point = (sum(u.stored != u.first for u in data) - sum(u.second != u.first for u in data)) / len(data)
    assert a[0] <= point <= a[1]
    assert measure.bootstrap_difference([Unit(1, 1, "c1", "A", "A", "A")]) is None


def test_the_council_confidence_is_reported_beside_the_verdicts_and_decides_nothing() -> None:
    conf = {f"{i}:c1": ("HIGH", "HIGH" if i % 2 else "LOW", "HIGH") for i in range(240)}
    got = measure.assess(units(240, matches=40, stored="APPROVE", first="APPROVE", second="APPROVE"), ok(240), confidence=conf)
    assert got["verdict"] == measure.PASS and got["confidence_agree_stored"] == 0.5 and got["confidence_agree_repeat"] == 0.5


def test_the_evidence_holds_every_reading_and_its_hash_is_stable() -> None:
    data = [Unit(2, 1, "c2", "NEUTRAL", None, "SUPPORT"), Unit(1, 1, "signals", "FORM:HOME", "FORM:HOME", "FORM:HOME")]
    assert measure.letters(data) == {"1:signals": "FORM:HOME|FORM:HOME|FORM:HOME", "2:c2": "NEUTRAL|-|SUPPORT"}
    evidence = {"letters": measure.letters(data), "rule": measure.METHOD}
    assert measure.evidence_hash(evidence) == measure.evidence_hash(dict(reversed(list(evidence.items()))))


def test_with_a_perfect_reproduction_the_rule_of_gate_a_passes_about_half_the_time_as_the_guide_says() -> None:
    """The property the owner's guide states: when the stored answer and the two replays are three draws of the same model on the
    same request, ``changed(S vs R1)`` and ``changed(R2 vs R1)`` have the same expectation, so the rule passes a little more than
    half the time - a NO PASA with an interval that covers 0 is the sample not telling, not a replay that does not reproduce."""
    rng = random.Random(measure.SEED)
    weights = (0.2, 0.6, 0.15, 0.05)
    passes = 0
    trials = 300
    for _ in range(trials):
        data = [Unit(i, i % 50, "c1", *rng.choices(STANCES, weights, k=3)) for i in range(250)]
        passes += measure.assess(data, ok(250), draws=1)["passed"]
    assert 0.45 <= passes / trials <= 0.65


def test_the_rule_is_written_down_in_its_own_words() -> None:
    got = measure.assess([], ok(0))
    assert got["method"] == measure.METHOD == "replay-measure-v1"
    assert got["rule"] == ("changed(S vs R1) <= changed(R2 vs R1) over >= 200 complete units of >= 30 matches; invalid replays <= 3% "
                           "and <= stored + 1%")
    assert (measure.MIN_UNITS, measure.MIN_MATCHES, measure.MAX_INVALID, measure.INVALID_MARGIN) == (200, 30, 0.03, 0.01)


def test_the_protocol_once_registered_is_the_rule_of_this_code() -> None:
    """``proto-int-c02-v1`` is registered by its own PR before the first run with spend (``harness.submit`` refuses without it):
    from then on its version, its seed and the figures of its rule must be this module's."""
    from fbi.ai.replay import PROTOCOL_KEY
    from fbi.research import protocol

    registered = protocol.PROTOCOLS.get(PROTOCOL_KEY)
    if registered is None:
        with pytest.raises(LookupError):
            protocol.require(PROTOCOL_KEY)
        return
    assert registered.version == "proto-int-c02-v1" and registered.seed == measure.SEED
    for figure in ("200", "30", "3 %", "1 punto"):
        assert figure in registered.pass_rule
