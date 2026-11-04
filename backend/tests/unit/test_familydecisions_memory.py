"""What the families remember (plan F11, ``memory-fam-v1``): the post-mortems of their decisions added up by family, market, competition and referee.

The pure part, with every number worked out by hand: the record of a set of post-mortems (hits against what the family said, the closing-line value, the
return at flat stakes, the verdicts), the recent window, the confidence, the change between the recent record and the one over everything, which entities
exist and which do not, and when a snapshot is new. The database is in tests/integration/test_familydecisions_memory.py."""

from __future__ import annotations

import json
import math
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.core import decision_versions as dv
from fbi.familydecisions import decide as fd
from fbi.familydecisions import memory as mem
from fbi.familydecisions import postmortem as pm
from fbi.intel import postmortem as pipeline
from fbi.intel.outcomes import profit_per_unit

DAY = date(2026, 10, 25)
"""The day the snapshots are as of."""
KICKOFF = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
"""2 p.m. in Bogotá on the 24th: one day before ``DAY``."""


def row(id: int = 1, *, result: str = "win", clv: float | None = 0.05, p: float = 0.5, odds: str = "2.000", family: str = "CORNERS",
        model: str = "family-corners_ft", key: str = "CORNERS_OU", competition: int | None = None, referee: int | None = None,
        kickoff: datetime = KICKOFF, decision: int | None = None, quality: str | None = None, verdict: str | None = None) -> mem.Row:
    """A post-mortem of ``pm-fam-v1``: its quality, verdict and profit follow from the result, the closing value and the price, as the constraints demand."""
    q = quality or pipeline.quality_of(clv)
    return mem.Row(id, id + 1000 if decision is None else decision, kickoff + timedelta(hours=4), kickoff, family, model, key, competition, referee,
                   result, q, verdict or pipeline.verdict_of(result, q), p, clv, profit_per_unit(result, Decimal(odds)).quantize(Decimal("0.0001")))


def aged(days: int, **kw: Any) -> mem.Row:
    """A post-mortem of a match played exactly ``days`` Bogotá days before ``DAY`` (at 2 p.m.): ``aged(0)`` is today's."""
    return row(kickoff=KICKOFF - timedelta(days=days - 1), **kw)


# ── the record ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_record_of_nothing_has_every_key_and_no_number() -> None:
    r = mem.record([])
    assert r == {
        "n": 0, "decided": 0, "wins": 0, "hit": None, "claimed": None, "gap": None, "z": None, "clv_n": 0, "clv_mean": None,
        "quality": {"GOOD": 0, "NEUTRAL": 0, "BAD": 0, "UNKNOWN": 0}, "staked": 0, "profit": 0.0, "roi": None,
        "verdicts": dict.fromkeys(("MERECIDO", "VARIANZA", "SUERTE", "ERROR", "NULO", "SIN_DATOS"), 0),
        "results": dict.fromkeys(("win", "loss", "push", "void", "half_win", "half_loss"), 0)}, "a reader never has to ask whether a key is there"


def test_the_record_of_six_decisions_worked_out_by_hand() -> None:
    rows = [
        row(1, result="win", clv=0.05, p=0.6, odds="2.000"),  # +1.0, GOOD, MERECIDO
        row(2, result="loss", clv=-0.05, p=0.5, odds="2.000"),  # -1.0, BAD, ERROR
        row(3, result="win", clv=0.0, p=0.4, odds="2.500"),  # +1.5, NEUTRAL, MERECIDO
        row(4, result="push", clv=None, p=0.5),  # 0, no close, NULO
        row(5, result="half_win", clv=0.02, p=0.5, odds="2.200"),  # +0.6, GOOD, MERECIDO
        row(6, result="void", clv=None, p=0.5),  # 0, no close, NULO
    ]
    r = mem.record(rows)
    assert (r["n"], r["decided"], r["wins"]) == (6, 3, 2), "decided: the three that were won or lost outright"
    assert r["hit"] == pytest.approx(2 / 3, abs=1e-4) and r["claimed"] == pytest.approx((0.6 + 0.5 + 0.4) / 3, abs=1e-4)
    assert r["gap"] == pytest.approx(2 / 3 - 0.5, abs=1e-4)
    variance = 0.6 * 0.4 + 0.5 * 0.5 + 0.4 * 0.6
    assert r["z"] == pytest.approx((2 - 1.5) / math.sqrt(variance), abs=1e-3) and r["z"] == pytest.approx(0.585, abs=1e-3)
    assert r["clv_n"] == 4 and r["clv_mean"] == pytest.approx((0.05 - 0.05 + 0.0 + 0.02) / 4, abs=1e-6), "the means are over the decisions that had a close"
    assert r["quality"] == {"GOOD": 2, "NEUTRAL": 1, "BAD": 1, "UNKNOWN": 2}
    assert r["staked"] == 4, "a push and a void give the stake back: nothing was risked"
    assert r["profit"] == pytest.approx(1.0 - 1.0 + 1.5 + 0.0 + 0.6 + 0.0) and r["roi"] == pytest.approx(2.1 / 4, abs=1e-4)
    assert r["verdicts"] == {"MERECIDO": 3, "VARIANZA": 0, "SUERTE": 0, "ERROR": 1, "NULO": 2, "SIN_DATOS": 0}
    assert r["results"] == {"win": 2, "loss": 1, "push": 1, "void": 1, "half_win": 1, "half_loss": 0}


def test_a_half_result_is_in_the_return_and_not_in_the_hits() -> None:
    r = mem.record([row(1, result="half_win", odds="2.200"), row(2, result="half_loss", odds="2.000")])
    assert (r["decided"], r["wins"], r["hit"], r["claimed"], r["gap"], r["z"]) == (0, 0, None, None, None, None)
    assert r["staked"] == 2 and r["profit"] == pytest.approx(0.6 - 0.5) and r["roi"] == pytest.approx(0.05)


def test_four_wins_of_four_at_even_odds_are_two_standard_errors_better_than_chance() -> None:
    r = mem.record([row(i, result="win", p=0.5) for i in range(1, 5)])
    assert (r["hit"], r["claimed"], r["gap"]) == (1.0, 0.5, 0.5)
    assert r["z"] == pytest.approx((4 - 2) / math.sqrt(4 * 0.25)) == pytest.approx(2.0)
    assert mem.record([row(i, result="loss", p=0.5) for i in range(1, 5)])["z"] == pytest.approx(-2.0)


def test_the_closing_value_is_averaged_over_the_decisions_that_had_a_close_only() -> None:
    r = mem.record([row(1, clv=0.04), row(2, clv=None), row(3, clv=0.02)])
    assert r["clv_n"] == 2 and r["clv_mean"] == pytest.approx(0.03) and r["quality"]["UNKNOWN"] == 1
    r = mem.record([row(1, clv=None)])
    assert r["clv_n"] == 0 and r["clv_mean"] is None


def test_the_return_is_per_unit_staked_and_a_decision_that_gave_the_stake_back_is_not_a_unit() -> None:
    r = mem.record([row(1, result="win", odds="3.000"), row(2, result="loss"), row(3, result="loss"), row(4, result="push", clv=None)])
    assert (r["staked"], r["profit"], r["roi"]) == (3, 0.0, 0.0), "+2 -1 -1 over three units; the push is not one of them"
    only_pushes = mem.record([row(1, result="push", clv=None), row(2, result="void", clv=None)])
    assert (only_pushes["staked"], only_pushes["profit"], only_pushes["roi"]) == (0, 0.0, None)


def test_the_record_does_not_depend_on_the_order_of_the_rows() -> None:
    rows = [row(i, result=("win", "loss", "push")[i % 3], clv=(0.05, -0.05, None, 0.0)[i % 4], p=0.3 + i / 100) for i in range(1, 25)]
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    assert mem.record(rows) == mem.record(shuffled)


def test_what_the_record_holds_is_json() -> None:
    entity = mem.snapshot("family", "CORNERS", "córners", [row(1, p=0.55), row(2, result="loss", clv=None)], DAY)
    for part in (entity.stats, entity.delta, entity.evidence):
        assert json.loads(json.dumps(part)) == part


# ── the vocabulary ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_words_the_record_counts_are_the_ones_the_post_mortem_can_say() -> None:
    results = {"win", "loss", "push", "void", "half_win", "half_loss"}
    assert set(mem.RESULTS) == results
    assert set(mem.QUALITIES) == {pipeline.quality_of(c) for c in (None, 0.5, 0.0, -0.5)}
    assert set(mem.VERDICTS) == {pipeline.verdict_of(x, q) for x in results for q in mem.QUALITIES}, (
        "every verdict the rule can give is counted, and no word the rule cannot give")
    assert len(mem.RESULTS) == len(set(mem.RESULTS)) and len(mem.VERDICTS) == len(set(mem.VERDICTS))


def test_the_versions_are_the_ones_of_the_decision_versions_and_the_post_mortem() -> None:
    assert mem.VERSION == dv.MEMORY_FAMILIES == "memory-fam-v1"
    assert mem.SOURCE == pm.VERSION == dv.POSTMORTEM_FAMILIES == "pm-fam-v1"
    assert (mem.RECENT_DAYS, mem.HALF_LIFE_DAYS, mem.PRIOR) == (28, 60.0, 30.0), (
        "the numbers of the memory are written in its rows: another number is another version")
    assert set(mem.NEEDS) == set(mem.ENTITY_TYPES) and mem.NEEDS == {"family": 1, "market": 1, "competition": 3, "referee": 3}


# ── age, recent and confidence ───────────────────────────────────────────────────────────────────────────────────────

def test_the_age_of_a_match_is_in_days_of_bogota_and_never_negative() -> None:
    late_night = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)  # 22:00 of the 24th in Bogotá
    assert mem.age_in_days(row(kickoff=late_night), DAY) == 1, "the day of the match is Bogotá's, not UTC's"
    assert mem.age_in_days(row(kickoff=late_night + timedelta(hours=6)), DAY) == 0
    assert mem.age_in_days(row(kickoff=late_night + timedelta(days=3)), DAY) == 0, "a match after the day of the snapshot counts as today"
    assert mem.age_in_days(row(kickoff=late_night - timedelta(days=59)), DAY) == 60


def test_a_decision_loses_half_its_weight_every_sixty_days() -> None:
    assert mem.effective_sample([aged(0)], DAY) == pytest.approx(1.0)
    assert mem.effective_sample([aged(60)], DAY) == pytest.approx(0.5)
    assert mem.effective_sample([aged(120)], DAY) == pytest.approx(0.25)
    assert mem.effective_sample([aged(0), aged(60), aged(120)], DAY) == pytest.approx(1.75)
    assert mem.effective_sample([aged(30)], DAY) == pytest.approx(math.sqrt(0.5)), "a month is a half of a half-life"
    assert mem.effective_sample([], DAY) == 0.0


def test_the_confidence_is_the_effective_sample_over_itself_plus_thirty() -> None:
    assert mem.confidence_of(0.0) == 0.0
    assert mem.confidence_of(30.0) == 0.5
    assert mem.confidence_of(90.0) == pytest.approx(0.75)
    assert 0 < mem.confidence_of(1e9) <= 1
    assert [mem.confidence_of(n) for n in (1, 5, 20, 100)] == sorted(mem.confidence_of(n) for n in (1, 5, 20, 100)), "more evidence, more confidence"
    snap = mem.snapshot("family", "CORNERS", None, [aged(0, id=1), aged(60, id=2)], DAY)
    assert snap.confidence == round(1.5 / 31.5, 4) == 0.0476 and snap.evidence["n_eff"] == 1.5


def test_the_same_evidence_is_worth_less_the_older_it_is() -> None:
    new = mem.snapshot("family", "CORNERS", None, [aged(10, id=i) for i in range(1, 21)], DAY)
    old = mem.snapshot("family", "CORNERS", None, [aged(200, id=i) for i in range(1, 21)], DAY)
    assert new.stats["all"]["n"] == old.stats["all"]["n"] == 20, "the same number of decisions"
    assert new.confidence > old.confidence, "but the ones from last month say more about the family today than the ones from last spring"


def test_the_recent_record_is_the_matches_of_the_last_twenty_eight_days() -> None:
    rows = [aged(0, id=1), aged(1, id=2), aged(27, id=3), aged(28, id=4), aged(29, id=5), aged(90, id=6)]
    snap = mem.snapshot("family", "CORNERS", None, rows, DAY)
    assert [mem.age_in_days(r, DAY) for r in rows] == [0, 1, 27, 28, 29, 90]
    assert snap.stats["all"]["n"] == 6
    assert snap.stats["recent"]["n"] == 3, "today's, yesterday's and the one of 27 days ago are recent; the one of 28 days ago is not"
    assert snap.stats["recent"] == mem.record(rows[:3])
    assert snap.stats["recent_days"] == 28


# ── the change ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_delta_is_the_recent_record_minus_the_one_over_everything() -> None:
    rows = [aged(1, id=1, result="win", p=0.5, clv=0.04), aged(2, id=2, result="win", p=0.5, clv=0.02),  # recent: 2 of 2, clv +0.03
            aged(60, id=3, result="loss", p=0.5, clv=-0.06), aged(61, id=4, result="loss", p=0.5, clv=-0.04)]  # older: 0 of 2, clv -0.05
    snap = mem.snapshot("family", "CORNERS", None, rows, DAY)
    assert snap.stats["all"]["hit"] == 0.5 and snap.stats["recent"]["hit"] == 1.0
    assert snap.delta["hit"] == 0.5 and snap.delta["gap"] == 0.5 and snap.delta["claimed"] == 0.0
    assert snap.delta["clv_mean"] == pytest.approx(0.03 - (0.04 + 0.02 - 0.06 - 0.04) / 4) == pytest.approx(0.04)
    assert snap.delta["roi"] == pytest.approx(1.0 - 0.0), "+1 +1 -1 -1 over four units is zero; the recent two made +1 per unit"


def test_without_a_recent_record_there_is_no_delta() -> None:
    snap = mem.snapshot("family", "CORNERS", None, [aged(60, id=1), aged(90, id=2)], DAY)
    assert snap.stats["recent"]["n"] == 0 and snap.delta == {}, "nothing recent to compare: no difference, not a difference of None"


def test_a_number_that_one_of_the_two_records_lacks_is_not_in_the_delta() -> None:
    rows = [aged(1, id=1, result="win", clv=None), aged(60, id=2, result="loss", clv=0.04)]  # the recent one has no close
    snap = mem.snapshot("family", "CORNERS", None, rows, DAY)
    assert snap.stats["recent"]["clv_mean"] is None and snap.stats["all"]["clv_mean"] == 0.04
    assert snap.delta == {"hit": 0.5, "claimed": 0.0, "gap": 0.5, "roi": 1.0}, "only what both records have: no closing value to compare"
    only_pushes = mem.snapshot("family", "CORNERS", None, [aged(1, id=1, result="push", clv=None), aged(60, id=2, result="win")], DAY)
    assert only_pushes.stats["recent"]["hit"] is None and only_pushes.stats["recent"]["roi"] is None
    assert only_pushes.delta == {}, "a push has no hit and stakes nothing: nothing to compare with the record over everything"


# ── what a snapshot rests on ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_snapshot_names_the_post_mortems_it_rests_on_and_the_newest_of_them() -> None:
    rows = [row(i, decision=500 + i, kickoff=KICKOFF - timedelta(days=i)) for i in (3, 9, 1, 7, 5, 8, 2)]
    evidence = mem.snapshot("market", "CORNERS_OU", None, rows, DAY).evidence
    assert evidence["source_version"] == "pm-fam-v1" and evidence["postmortems"] == 7
    assert evidence["through"] == {"id": 9, "created_at": (KICKOFF - timedelta(days=9) + timedelta(hours=4)).isoformat()}, "the newest is the largest id"
    assert evidence["sample"] == [{"postmortem": i, "decision": 500 + i} for i in (9, 8, 7, 5, 3)], "the newest five, newest first"
    assert evidence["from_kickoff"] == (KICKOFF - timedelta(days=9)).isoformat() and evidence["to_kickoff"] == (KICKOFF - timedelta(days=1)).isoformat()
    assert (evidence["half_life_days"], evidence["prior"]) == (60.0, 30.0)


def test_a_snapshot_is_new_when_the_entity_has_post_mortems_the_last_one_did_not_rest_on() -> None:
    entity = mem.snapshot("family", "CORNERS", None, [row(1), row(2), row(3)], DAY)
    assert (entity.n, entity.through) == (3, 3)
    assert mem.is_new(entity, None), "an entity never remembered is new"
    assert not mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 3, 3)), "the same post-mortems: nothing to write"
    assert mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 2, 2)), "one more"
    assert mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 3, 2)), "as many, but the newest is another"
    assert mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 3, 4)), "a snapshot that rests on a different newest one is not this one"
    assert mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 2, 3)), (
        "one more, though the newest is the same: the ids of two rows follow the order they were numbered in, not the order they were committed in, "
        "so a post-mortem can arrive late with a number below the newest one the last snapshot saw")
    assert mem.is_new(entity, mem.Previous(DAY - timedelta(days=1), 4, 3)), "and a snapshot that rested on more than there are now is not this one either"


# ── the entities ─────────────────────────────────────────────────────────────────────────────────────────────────────

def keys(entities: list[mem.Entity]) -> list[tuple[str, str]]:
    return [(e.type, e.key) for e in entities]


def test_every_post_mortem_belongs_to_its_family_and_its_market_and_to_its_competition_and_referee_when_the_match_has_them() -> None:
    assert mem.entities_of(row(1)) == [("family", "CORNERS"), ("market", "CORNERS_OU")]
    assert mem.entities_of(row(1, competition=7)) == [("family", "CORNERS"), ("market", "CORNERS_OU"), ("competition", "7")]
    assert mem.entities_of(row(1, competition=7, referee=9)) == [
        ("family", "CORNERS"), ("market", "CORNERS_OU"), ("competition", "7"), ("referee", "9")]
    assert mem.entities_of(row(1, referee=9))[-1] == ("referee", "9")


def test_a_competition_or_a_referee_with_fewer_than_three_decisions_is_not_remembered() -> None:
    rows = [row(1, competition=7, referee=9), row(2, competition=7, referee=9), row(3, competition=8, referee=9), row(4, competition=7, referee=10)]
    assert keys(mem.summarise(rows, as_of=DAY)) == [
        ("family", "CORNERS"), ("market", "CORNERS_OU"), ("competition", "7"), ("referee", "9")], "7 has three, 8 has one; 9 has three, 10 has one"
    assert keys(mem.summarise(rows[:2], as_of=DAY)) == [("family", "CORNERS"), ("market", "CORNERS_OU")], "two are an anecdote"
    assert keys(mem.summarise(rows[:1], as_of=DAY)) == [("family", "CORNERS"), ("market", "CORNERS_OU")], "a family and a market exist from the first"


def test_a_match_without_a_competition_or_a_referee_counts_for_the_family_and_the_market_only() -> None:
    rows = [row(i) for i in range(1, 6)]
    assert keys(mem.summarise(rows, as_of=DAY)) == [("family", "CORNERS"), ("market", "CORNERS_OU")]


def test_the_families_come_first_then_the_markets_the_competitions_and_the_referees_each_in_order_of_key() -> None:
    rows = [row(i, family=f, key=k, competition=c, referee=r) for i, (f, k, c, r) in enumerate([
        ("CARDS", "CARDS_OU", 12, 3), ("CORNERS", "CORNERS_OU", 4, 30), ("CARDS", "CARDS_OU", 12, 3), ("CORNERS", "CORNERS_1X2", 4, 30),
        ("CARDS", "CARDS_OU", 12, 3), ("CORNERS", "CORNERS_OU", 4, 30), ("CORNERS", "CORNERS_1X2", 4, 30), ("CARDS", "CARDS_OU", 12, 3),
        ("CORNERS", "CORNERS_OU", 4, 30), ("CORNERS", "CORNERS_1X2", 4, 30)], start=1)]
    assert keys(mem.summarise(rows, as_of=DAY)) == [
        ("family", "CARDS"), ("family", "CORNERS"), ("market", "CARDS_OU"), ("market", "CORNERS_1X2"), ("market", "CORNERS_OU"),
        ("competition", "12"), ("competition", "4"), ("referee", "3"), ("referee", "30")]


def test_the_entities_do_not_depend_on_the_order_of_the_rows() -> None:
    rows = [row(i, result=("win", "loss")[i % 2], family=("CORNERS", "CARDS")[i % 2], key=("CORNERS_OU", "CARDS_OU")[i % 2], competition=(4, 12)[i % 2],
               referee=(3, 30)[(i // 2) % 2], kickoff=KICKOFF - timedelta(days=i)) for i in range(1, 31)]
    shuffled = rows[:]
    random.Random(11).shuffle(shuffled)
    assert mem.summarise(rows, as_of=DAY) == mem.summarise(shuffled, as_of=DAY)


def test_each_entity_sums_only_its_own_post_mortems() -> None:
    rows = ([row(i, family="CORNERS", key="CORNERS_OU", result="win") for i in range(1, 4)]
            + [row(i, family="CARDS", key="CARDS_OU", result="loss") for i in range(4, 6)]
            + [row(6, family="CORNERS", key="CORNERS_1X2", result="loss")])
    by = {(e.type, e.key): e for e in mem.summarise(rows, as_of=DAY)}
    assert by["family", "CORNERS"].stats["all"]["n"] == 4 and by["family", "CORNERS"].stats["all"]["wins"] == 3
    assert by["family", "CARDS"].stats["all"]["n"] == 2 and by["family", "CARDS"].stats["all"]["wins"] == 0
    assert by["market", "CORNERS_OU"].stats["all"]["n"] == 3 and by["market", "CORNERS_1X2"].stats["all"]["n"] == 1
    assert sum(e.stats["all"]["n"] for e in by.values() if e.type == "family") == 6, "every post-mortem is in exactly one family"
    assert sum(e.stats["all"]["n"] for e in by.values() if e.type == "market") == 6, "and in exactly one market"


def test_a_family_is_named_the_way_the_owner_reads_it_and_the_others_by_what_is_known_of_them() -> None:
    rows = [row(1, family="CORNERS", key="CORNERS_OU", competition=7, referee=9), row(2, family="CORNERS", key="CORNERS_OU", competition=7, referee=9),
            row(3, family="CORNERS", key="CORNERS_OU", competition=7, referee=9), row(4, family="NEW_FAMILY", key="NEW_OU")]
    names = {("competition", "7"): "Premier League", ("referee", "9"): "A. Taylor"}
    by = {(e.type, e.key): e for e in mem.summarise(rows, as_of=DAY, names=names)}
    assert by["family", "CORNERS"].name == pm.FAMILY_ES["CORNERS"] == "córners"
    assert by["family", "NEW_FAMILY"].name == "NEW_FAMILY", "a family that has no Spanish name is written with its own"
    assert by["competition", "7"].name == "Premier League" and by["referee", "9"].name == "A. Taylor"
    assert by["market", "CORNERS_OU"].name is None
    nameless = {(e.type, e.key): e for e in mem.summarise(rows, as_of=DAY)}
    assert nameless["competition", "7"].name is None and nameless["referee", "9"].name is None, "a name nobody gave is no name"


def test_a_family_carries_its_record_by_model_and_the_others_do_not() -> None:
    rows = [row(1, model="family-corners_ft"), row(2, model="family-corners_ft", result="loss"), row(3, model="family-corners_ht"),
            row(4, competition=7), row(5, competition=7), row(6, competition=7)]
    by = {(e.type, e.key): e for e in mem.summarise(rows, as_of=DAY)}
    models = by["family", "CORNERS"].stats["models"]
    assert list(models) == ["family-corners_ft", "family-corners_ht"]
    assert models["family-corners_ft"]["n"] == 5 and models["family-corners_ht"]["n"] == 1
    assert models["family-corners_ft"] == mem.record([r for r in rows if r.model == "family-corners_ft"])
    assert "models" not in by["market", "CORNERS_OU"].stats and "models" not in by["competition", "7"].stats


def test_the_confidence_of_each_entity_is_that_of_its_own_evidence() -> None:
    few = [aged(0, id=1, key="CORNERS_1X2")]
    many = [aged(0, id=i, key="CORNERS_OU") for i in range(2, 32)]
    by = {(e.type, e.key): e for e in mem.summarise(few + many, as_of=DAY)}
    assert by["market", "CORNERS_1X2"].confidence == round(1 / 31, 4) == 0.0323
    assert by["market", "CORNERS_OU"].confidence == 0.5, "thirty decisions of today are an effective sample of thirty"
    assert by["family", "CORNERS"].confidence == round(31 / 61, 4) == 0.5082


# ── the step ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class Untouched:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the step used the connection ({name})")


@pytest.mark.parametrize("value", [None, "off", "", "OFF", "on", "true", "1", "live"])
def test_with_the_switch_off_the_step_does_nothing_and_touches_nothing(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(fd, "environment", lambda: {} if value is None else {fd.SWITCH: value})
    assert mem.run_step(Untouched(), at=datetime(2026, 10, 25, 5, 0, tzinfo=UTC)) == {"mode": "off"}  # type: ignore[arg-type]


def test_the_report_of_a_pass_is_what_the_night_writes_in_its_record() -> None:
    report = mem.MemoryReport(postmortems=10, entities=4, written=3, unchanged=1, waiting=0, failed=0, by_type={"family": 1, "market": 2},
                              errors=[str(i) for i in range(9)])
    out = report.as_dict()
    assert out == {"postmortems": 10, "entities": 4, "written": 3, "unchanged": 1, "waiting": 0, "failed": 0, "by_type": {"family": 1, "market": 2},
                   "errors": ["0", "1", "2", "3", "4"]}, "only the first few errors are kept in the record"
    assert json.loads(json.dumps(out)) == out
