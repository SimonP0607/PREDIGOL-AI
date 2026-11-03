"""The arms of the shadow of phase 3 (``fbi.ai.arms``): who is in which arm, decided by arithmetic and written down once.

Pure: no database (the table and the concurrency are held by ``tests/integration/test_arms_assignment.py``). What matters here is that the
decision is STABLE - the same match is in the same bucket on every worker, platform and run, whatever Python's own hash is doing - UNIFORM,
NESTED (a larger sample only adds matches), and shaped the way the plan says: 30 % in the sample, COUNCIL SOLO half of it (15 % of all).
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.ai import arms, config, idempotency
from fbi.ai.arms import OUTSIDE, SALT, Assignment

D = Decimal
SRC = Path(arms.__file__).resolve().parents[2]
IDS = range(1, 20_001)
"""Twenty thousand consecutive ids: the shape of the ids a provider hands out, and the hardest input for a bad hash (a weak one shows its pattern)."""

# What ``sha256("<salt>:<id>")`` and ``sha256("<salt>:cs:<id>")`` give, computed by hand-written code that shares nothing with the module. If one of
# these moves, every match of a running experiment would change group: it is a new experiment (a new salt and a new ARMS_VERSION), never an edit.
GOLDEN = {  # id: (bucket, solo_bucket)
    1: (2855, 8643), 2: (3261, 7693), 3: (1882, 6327), 7: (9655, 1167), 42: (4790, 5971), 100: (4222, 2617), 1001: (825, 4769),
    12345: (3684, 1802), 999999: (1670, 9810), 2**31: (1937, 7649), 2**40 + 5: (6560, 1789)}
GOLDEN_V2 = {1: (9598, 7457), 2: (3492, 2911), 3: (7003, 9655), 7: (9376, 8795), 42: (854, 1499), 100: (4703, 1512)}


def reference(text: str) -> int:
    """The definition in the words of the module's text, written again: the first eight bytes of the SHA-256, big endian, modulo 10,000."""
    return int(hashlib.sha256(text.encode()).hexdigest()[:16], 16) % 10_000


# ── the hash ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_constants_say_what_the_plan_says() -> None:
    assert arms.ARMS_VERSION == "arms-v1" and arms.SALT == "ma-shadow-v1" and arms.BUCKETS == 10_000
    assert (arms.MULTIAGENT, arms.MULTIAGENT_HAIKU, arms.COUNCIL_SOLO) == ("ma-v1", "ma-v1-h", "cs-v1")
    assert arms.SAMPLE_ENGINES == ("ma-v1", "ma-v1-h")
    assert D("0.5") == arms.SOLO_SHARE, "COUNCIL SOLO is half of the sample: 15 % of all the matches when the sample is 30 %"
    assert D("0.15") == arms.SOLO_SHARE * D("0.3")


def test_the_engines_of_the_arms_are_the_shadow_engines_of_the_configuration() -> None:
    assert (*arms.SAMPLE_ENGINES, arms.COUNCIL_SOLO) == config.SHADOW_ENGINES
    assert (*config.BASELINE_ENGINES, *config.SHADOW_ENGINES) == config.KNOWN_ENGINES, "the canonical order the assignment lists them in"


def test_the_name_of_an_experiment_is_named_like_a_version_of_an_agent() -> None:
    assert arms.EXPERIMENT.pattern == idempotency.NAME.pattern
    assert arms.EXPERIMENT.fullmatch(SALT)


@pytest.mark.parametrize(("fixture_id", "expected"), sorted(GOLDEN.items()))
def test_the_buckets_of_the_experiment_never_move(fixture_id: int, expected: tuple[int, int]) -> None:
    assert (arms.bucket(fixture_id), arms.solo_bucket(fixture_id)) == expected
    assert (arms.bucket(fixture_id, SALT), arms.solo_bucket(fixture_id, SALT)) == expected


@pytest.mark.parametrize(("fixture_id", "expected"), sorted(GOLDEN_V2.items()))
def test_another_salt_is_another_experiment_with_its_own_groups(fixture_id: int, expected: tuple[int, int]) -> None:
    assert (arms.bucket(fixture_id, "ma-shadow-v2"), arms.solo_bucket(fixture_id, "ma-shadow-v2")) == expected
    assert expected != GOLDEN.get(fixture_id)


def test_the_hash_is_the_one_the_module_says_it_is() -> None:
    for fixture_id in (*range(1, 300), 10**6, 10**9, 2**40, 2**62):
        assert arms.bucket(fixture_id) == reference(f"ma-shadow-v1:{fixture_id}"), fixture_id
        assert arms.solo_bucket(fixture_id) == reference(f"ma-shadow-v1:cs:{fixture_id}"), fixture_id
        assert arms.bucket(fixture_id, "x.y_z-1") == reference(f"x.y_z-1:{fixture_id}")


def test_the_two_hashes_are_two_texts_so_a_match_is_not_the_same_bucket_twice() -> None:
    assert sum(arms.bucket(i) == arms.solo_bucket(i) for i in IDS) < 20_000 * 0.0006, "independent hashes agree about once in ten thousand"


def test_a_bucket_is_always_in_range_and_always_the_same() -> None:
    buckets = [arms.bucket(i) for i in IDS]
    assert min(buckets) < 5 and 9995 < max(buckets) <= 9999, "the whole range is used"
    assert all(0 <= b < 10_000 for b in buckets) and all(0 <= arms.solo_bucket(i) < 10_000 for i in range(1, 2000))
    assert buckets == [arms.bucket(i) for i in IDS], "no state, no clock, no randomness"
    assert all(isinstance(b, int) and not isinstance(b, bool) for b in buckets[:50])


def test_the_buckets_do_not_depend_on_the_hash_seed_of_the_interpreter() -> None:
    """``hash()`` of a text changes at every start of Python; the buckets of a running experiment must not."""
    code = "from fbi.ai import arms; print([arms.bucket(i) for i in (1, 2, 3, 12345)], [arms.solo_bucket(i) for i in (1, 2, 3, 12345)])"
    seen = set()
    for seed in ("0", "1", "12345", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(SRC)}
        done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120, check=True)
        seen.add(done.stdout.strip())
    assert seen == {"[2855, 3261, 1882, 3684] [8643, 7693, 6327, 1802]"}


def test_the_module_is_pure_it_never_calls_hash_or_a_clock_or_a_generator() -> None:
    tree = ast.parse(Path(arms.__file__).read_text(encoding="utf-8"))
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "hash" not in called and "id" not in called and "random" not in called
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= {"__future__", "hashlib", "re", "collections", "dataclasses", "datetime", "decimal", "fractions", "typing", "psycopg"}, imported
    assert not ({"random", "time", "uuid", "secrets", "os", "sys"} & imported)


@pytest.mark.parametrize("bad", [0, -1, -2**40, True, False, 1.0, 2.5, "7", None, b"7", (7,)])
def test_a_fixture_that_is_not_a_whole_number_from_one_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="fixture id"):
        arms.bucket(bad)
    with pytest.raises(ValueError, match="fixture id"):
        arms.solo_bucket(bad)
    with pytest.raises(ValueError, match="fixture id"):
        arms.arms_of(bad, D("0.3"))


@pytest.mark.parametrize("bad", ["", " ", "a b", "a:cs", "a/b", "-a", ".a", "x" * 65, "ñ", "a\n", None, 7])
def test_a_salt_that_cannot_name_an_experiment_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="experiment"):
        arms.bucket(5, bad)
    with pytest.raises(ValueError, match="experiment"):
        arms.solo_bucket(5, bad)


def test_the_first_and_the_second_text_cannot_be_confused_whatever_the_salt() -> None:
    """A salt cannot contain ':' so ``<salt>:cs:<id>`` is never ``<other salt>:<id>``: the two hashes of a match never read the same text."""
    for salt in ("a", "cs", "ma-shadow-v1", "x.y"):
        assert f"{salt}:cs:7" != f"{salt}:7"
    assert arms.bucket(7, "cs") == reference("cs:7") and arms.solo_bucket(7, "cs") == reference("cs:cs:7")


# ── the arms ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_match_is_sampled_exactly_when_its_bucket_is_below_the_share_of_ten_thousand() -> None:
    share = D("0.3")
    for b in (0, 1, 1499, 2998, 2999):
        assert arms.arms_for(b, share).sampled, b
    for b in (3000, 3001, 5000, 9999):
        assert not arms.arms_for(b, share).sampled, b


@pytest.mark.parametrize(("share", "last"), [("0.0001", 0), ("0.0002", 1), ("0.1", 999), ("0.15", 1499), ("0.3", 2999), ("0.5", 4999),
                                               ("0.9999", 9998), ("1", 9999), ("1.0", 9999), ("0.30", 2999), ("3E-1", 2999)])
def test_the_edge_of_the_sample_is_where_the_share_puts_it(share: str, last: int) -> None:
    assert arms.arms_for(last, D(share)).sampled
    if last < 9999:
        assert not arms.arms_for(last + 1, D(share)).sampled


def test_a_share_is_compared_exactly_not_rounded() -> None:
    assert arms.arms_for(3000, D("0.30000000000000000000000000001")).sampled, "a hair over 3000 is over 3000"
    assert not arms.arms_for(3000, D("0.29999999999999999999999999999")).sampled
    assert not arms.arms_for(2999, D("0.2999")).sampled and arms.arms_for(2998, D("0.2999")).sampled
    assert arms.arms_for(0, D("1E-30")).sampled, "any share above zero samples the bucket 0: bucket < share * 10000"


def test_a_share_of_zero_samples_nobody_and_a_share_of_one_samples_everybody() -> None:
    assert all(arms.arms_for(b, D(0)) == OUTSIDE for b in (0, 1, 5000, 9999))
    assert all(arms.arms_for(b, D(0), 0) == OUTSIDE for b in (0, 5000, 9999)), "not even COUNCIL SOLO: it needs the sample"
    assert all(arms.arms_for(b, D(1)).sampled for b in (0, 1, 5000, 9999))
    assert all(arms.arms_for(b, D("-0")) == OUTSIDE for b in (0, 9999)), "a negative zero is zero"


def test_a_sampled_match_runs_both_multi_agent_engines_and_a_match_outside_runs_none() -> None:
    inside = arms.arms_for(10, D("0.3"))
    assert inside == Assignment(sampled=True, council_solo=False, engines=("ma-v1", "ma-v1-h"))
    assert arms.arms_for(5000, D("0.3")) == OUTSIDE == Assignment(sampled=False, council_solo=False, engines=())


@pytest.mark.parametrize(("second", "solo"), [(0, True), (1, True), (2499, True), (4999, True), (5000, False), (5001, False), (9999, False)])
def test_council_solo_is_the_half_of_the_sample_whose_second_hash_is_in_the_first_half(second: int, solo: bool) -> None:
    got = arms.arms_for(10, D("0.3"), second)
    assert got.council_solo is solo and got.sampled
    assert got.engines == (("ma-v1", "ma-v1-h", "cs-v1") if solo else ("ma-v1", "ma-v1-h"))


def test_council_solo_needs_the_sample_and_a_second_hash() -> None:
    assert arms.arms_for(5000, D("0.3"), 0) == OUTSIDE, "a match outside the sample is in no arm, however its second hash falls"
    assert arms.arms_for(10, D("0.3")).council_solo is False, "without a second hash nobody is in COUNCIL SOLO"
    assert arms.arms_for(10, D("0.3"), None) == arms.arms_for(10, D("0.3"))


def test_the_arms_of_a_match_are_its_two_hashes_and_the_share() -> None:
    for i in (1, 2, 3, 42, 12345):
        assert arms.arms_of(i, D("0.3")) == arms.arms_for(arms.bucket(i), D("0.3"), arms.solo_bucket(i))
        assert arms.arms_of(i, D("0.5"), "other") == arms.arms_for(arms.bucket(i, "other"), D("0.5"), arms.solo_bucket(i, "other"))
    # the golden matches: 1 (2855, 8643) is in the sample and out of COUNCIL SOLO; 1001 (825, 4769) is in both; 7 (9655, 1167) is out of the sample
    assert arms.arms_of(1, D("0.3")).engines == ("ma-v1", "ma-v1-h")
    assert arms.arms_of(1001, D("0.3")).engines == ("ma-v1", "ma-v1-h", "cs-v1")
    assert arms.arms_of(7, D("0.3")) == OUTSIDE


@pytest.mark.parametrize("bad", [D(-1), D("-0.0001"), D("1.0001"), D(2), D("NaN"), D("Infinity"), D("-Infinity"), 0.3, 1, "0.3", None])
def test_a_share_that_is_not_a_number_from_zero_to_one_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="share"):
        arms.arms_for(10, bad)
    with pytest.raises(ValueError, match="share"):
        arms.arms_of(10, bad)


@pytest.mark.parametrize("bad", [-1, 10_000, 10**9, True, 1.5, "7", None])
def test_a_bucket_outside_the_range_is_refused(bad: Any) -> None:
    with pytest.raises(ValueError, match="bucket"):
        arms.arms_for(bad, D("0.3"))
    if bad is not None:  # no second bucket at all is allowed: nobody is then in COUNCIL SOLO
        with pytest.raises(ValueError, match="second bucket"):
            arms.arms_for(10, D("0.3"), bad)


# ── the shape of the experiment ──────────────────────────────────────────────────────────────────────────────────────────────────

def counts(share: str, ids: range = IDS) -> tuple[int, int]:
    got = [arms.arms_of(i, D(share)) for i in ids]
    return sum(a.sampled for a in got), sum(a.council_solo for a in got)


def test_the_plans_numbers_30_percent_in_the_sample_and_15_percent_in_council_solo() -> None:
    sampled, solo = counts("0.3")
    assert abs(sampled / len(IDS) - 0.30) < 0.01, sampled
    assert abs(solo / len(IDS) - 0.15) < 0.01, solo
    assert abs(solo / sampled - 0.5) < 0.02, "COUNCIL SOLO is half of the sample"
    assert (sampled, solo) == (6025, 3009), "and these are the counts of these ids: a different hash would move them"


@pytest.mark.parametrize("share", ["0.05", "0.1", "0.3", "0.5", "0.8", "1"])
def test_the_sample_is_the_share_of_the_matches_whatever_the_share(share: str) -> None:
    sampled, solo = counts(share)
    assert abs(sampled / len(IDS) - float(share)) < 0.01, (share, sampled)
    assert abs(solo / len(IDS) - float(share) / 2) < 0.01, (share, solo)


def test_the_buckets_are_spread_evenly_over_the_range() -> None:
    for hash_of in (arms.bucket, arms.solo_bucket):
        deciles = [0] * 10
        for i in IDS:
            deciles[hash_of(i) // 1000] += 1
        assert all(abs(n - 2000) < 160 for n in deciles), deciles  # +-8 %: the worst of these ids is 6 %
        assert len({hash_of(i) for i in IDS}) > 8000, "most of the 10,000 buckets are used"


def test_the_second_hash_does_not_depend_on_the_first() -> None:
    """COUNCIL SOLO is a half of the sample taken at random inside it, not the low half or the high half: the share of the second hash is the
    same inside the sample and outside it."""
    inside = [arms.solo_bucket(i) < 5000 for i in IDS if arms.bucket(i) < 3000]
    outside = [arms.solo_bucket(i) < 5000 for i in IDS if arms.bucket(i) >= 3000]
    assert abs(sum(inside) / len(inside) - 0.5) < 0.03 and abs(sum(outside) / len(outside) - 0.5) < 0.03
    assert abs(sum(inside) / len(inside) - sum(outside) / len(outside)) < 0.03
    for low in (0, 2500, 5000, 7500):  # and the same in every quarter of the first bucket
        quarter = [arms.solo_bucket(i) < 5000 for i in IDS if low <= arms.bucket(i) < low + 2500]
        assert abs(sum(quarter) / len(quarter) - 0.5) < 0.04, low


def test_sampled_matches_are_not_clustered_by_id() -> None:
    """A weak hash of consecutive ids puts neighbours in the same group; this one does not: the runs of sampled matches are as long as chance makes them."""
    flags = [arms.arms_of(i, D("0.3")).sampled for i in IDS]
    longest = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    assert longest < 20, longest  # the chance of 20 in a row at 30 % is 3.5e-11 per start
    block = [sum(flags[k:k + 1000]) for k in range(0, 20_000, 1000)]
    assert all(abs(n - 300) < 60 for n in block), block


def test_the_samples_are_nested_a_larger_share_only_adds_matches() -> None:
    shares = [D("0.05"), D("0.1"), D("0.15"), D("0.3"), D("0.3001"), D("0.5"), D("0.75"), D("1")]
    ids = range(1, 5001)
    sampled = [{i for i in ids if arms.arms_of(i, s).sampled} for s in shares]
    solo = [{i for i in ids if arms.arms_of(i, s).council_solo} for s in shares]
    for small, large in zip(range(len(shares) - 1), range(1, len(shares)), strict=True):
        assert sampled[small] <= sampled[large], f"a match left the sample when the share went from {shares[small]} to {shares[large]}"
        assert solo[small] <= solo[large], f"a match left COUNCIL SOLO when the share went from {shares[small]} to {shares[large]}"
        assert len(sampled[small]) < len(sampled[large])
    assert sampled[-1] == set(ids), "at 100 % everybody is in"
    assert all(s <= sm for s, sm in zip(solo, sampled, strict=True)), "COUNCIL SOLO is always inside the sample"
    assert solo[-1] and all(arms.arms_of(i, D(1)).engines[:2] == ("ma-v1", "ma-v1-h") for i in list(ids)[:200])


def test_what_a_match_runs_only_grows_with_the_share() -> None:
    for i in range(1, 400):
        previous: tuple[str, ...] = ()
        for share in ("0", "0.1", "0.3", "0.6", "1"):
            engines = arms.arms_of(i, D(share)).engines
            assert set(previous) <= set(engines), (i, share)
            previous = engines


def test_every_arm_has_matches_and_none_is_empty_at_the_plans_share() -> None:
    kinds = {arms.arms_of(i, D("0.3")).engines for i in IDS}
    assert kinds == {(), ("ma-v1", "ma-v1-h"), ("ma-v1", "ma-v1-h", "cs-v1")}


# ── what runs today ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_engines_that_run_are_the_assigned_ones_the_owner_has_switched_on() -> None:
    both = Assignment(sampled=True, council_solo=True, engines=("ma-v1", "ma-v1-h", "cs-v1"))
    sample_only = arms.arms_for(10, D("0.3"))
    activation = ("rules", "llm", "ma-v1", "ma-v1-h")  # the plan's activation: COUNCIL SOLO is not named
    assert arms.runnable(both, activation) == ("ma-v1", "ma-v1-h")
    assert arms.runnable(both, (*activation, "cs-v1")) == ("ma-v1", "ma-v1-h", "cs-v1")
    assert arms.runnable(both, ["cs-v1"]) == ("cs-v1",) and arms.runnable(both, iter(["cs-v1", "ma-v1"])) == ("ma-v1", "cs-v1"), "in the order of the assignment"
    assert arms.runnable(sample_only, (*activation, "cs-v1")) == ("ma-v1", "ma-v1-h"), "an engine the match is not assigned to does not run"
    assert arms.runnable(both, ("rules", "llm")) == () == arms.runnable(both, ()), "the rollback: FBI_AI_ENGINES=rules,llm"
    assert arms.runnable(OUTSIDE, (*activation, "cs-v1")) == ()
    assert arms.runnable(both, ("combined", "rules", "bogus")) == ()


def test_an_assignment_is_a_value_that_cannot_be_changed() -> None:
    a = arms.arms_for(10, D("0.3"))
    with pytest.raises(AttributeError):
        a.sampled = False  # type: ignore[misc]
    assert hash(a) == hash(Assignment(True, False, ("ma-v1", "ma-v1-h"))) and a == Assignment(True, False, ("ma-v1", "ma-v1-h"))
    assert not hasattr(a, "__dict__"), "slots"


# ── the SQL, without a database ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_statements_never_change_a_row_that_exists() -> None:
    insert = " ".join(arms.INSERT_SQL.split())
    assert "ON CONFLICT (experiment, fixture_id) DO NOTHING" in insert and "DO UPDATE" not in insert, "the first row of a match is its group for good"
    assert "ORDER BY a.fixture_id" in insert, "keys taken in the same order by every worker: no deadlock"
    for sql in (arms.STORED_SQL, arms.INSERT_SQL):
        assert "UPDATE ai." not in sql and "DELETE" not in sql.upper()
    assert arms.STORED_SQL.lstrip().upper().startswith("SELECT")


class Recorder:
    """A connection that keeps what it was asked and answers with the rows it was given: ``assign`` and ``stored`` without a database."""

    def __init__(self, rows: list[tuple[Any, ...]] | None = None) -> None:
        self.statements: list[tuple[str, dict[str, Any]]] = []
        self.rows = rows or []

    @contextmanager
    def cursor(self, **_: Any) -> Iterator[Recorder]:
        yield self

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.statements.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


NOON = datetime(2026, 11, 3, 12, tzinfo=UTC)


def test_a_share_of_zero_writes_nothing_and_a_match_with_no_row_is_outside() -> None:
    conn = Recorder(rows=[(2, True, False)])
    assert arms.assign(conn, [1, 2, 3], at=NOON, share=D(0)) == {  # type: ignore[arg-type]
        1: OUTSIDE, 2: Assignment(True, False, ("ma-v1", "ma-v1-h")), 3: OUTSIDE}
    assert [sql for sql, _ in conn.statements] == [arms.STORED_SQL], "only a read"


def test_a_share_above_zero_writes_the_arms_of_every_match_in_one_statement_and_answers_with_what_is_stored() -> None:
    conn = Recorder(rows=[(1001, True, True), (1, True, False), (7, False, False)])
    got = arms.assign(conn, [1001, 1, 7, 1], at=NOON, share=D("0.3"))  # type: ignore[arg-type]
    assert list(got) == [1001, 1, 7], "each match once, in the order asked"
    assert got[1001].engines == ("ma-v1", "ma-v1-h", "cs-v1") and got[1].engines == ("ma-v1", "ma-v1-h") and got[7] == OUTSIDE
    (insert, params), (read, _) = conn.statements
    assert insert == arms.INSERT_SQL and read == arms.STORED_SQL
    assert params["experiment"] == SALT and params["share"] == D("0.3") and params["at"] == NOON
    assert params["ids"] == [1001, 1, 7] and params["buckets"] == [825, 2855, 9655]
    assert params["sampled"] == [True, True, False] and params["solo"] == [True, False, False]


def test_the_answer_is_what_the_table_says_not_what_this_call_computed() -> None:
    """Match 1 would be sampled at this share; the table says an earlier call put it outside, and the table wins."""
    conn = Recorder(rows=[(1, False, False)])
    assert arms.assign(conn, [1], at=NOON, share=D(1))[1] == OUTSIDE  # type: ignore[arg-type]
    assert conn.statements[0][1]["sampled"] == [True], "it tried to write the new draw, and the table's DO NOTHING kept the old one"


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"share": D("1.5")}, "share"), ({"share": D(-1)}, "share"), ({"share": D("NaN")}, "share"), ({"share": 0.3}, "share"),
    ({"at": NOON.replace(tzinfo=None)}, "timezone"), ({"experiment": "a b"}, "experiment"), ({"experiment": ""}, "experiment"),
])
def test_a_bad_call_is_refused_before_the_database_is_touched(kwargs: dict[str, Any], message: str) -> None:
    """A statement that fails inside the caller's transaction aborts it: so nothing that can be known to be wrong is sent."""
    conn = Recorder()
    call: dict[str, Any] = {"at": NOON, "share": D("0.3")} | kwargs
    with pytest.raises(ValueError, match=message):
        arms.assign(conn, [1, 2], **call)  # type: ignore[arg-type]
    assert conn.statements == []


@pytest.mark.parametrize("ids", [[0], [1, -3], [True], [1.5], ["7"], [None]])
def test_a_match_that_is_not_one_is_refused_before_the_database_is_touched(ids: list[Any]) -> None:
    conn = Recorder()
    with pytest.raises(ValueError, match="fixture id"):
        arms.assign(conn, ids, at=NOON, share=D("0.3"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="fixture id"):
        arms.stored(conn, ids)  # type: ignore[arg-type]
    assert conn.statements == []


def test_no_match_asked_is_no_statement_at_all() -> None:
    conn = Recorder()
    assert arms.assign(conn, [], at=NOON, share=D("0.3")) == {} and arms.assign(conn, iter(()), at=NOON, share=D(0)) == {}  # type: ignore[arg-type]
    assert arms.stored(conn, []) == {}  # type: ignore[arg-type]
    assert conn.statements == []


def test_the_experiment_is_its_salt_in_the_hash_and_in_the_table() -> None:
    conn = Recorder(rows=[])
    arms.assign(conn, [1, 2, 3], at=NOON, share=D("0.3"), experiment="ma-shadow-v2")  # type: ignore[arg-type]
    params = conn.statements[0][1]
    assert params["experiment"] == "ma-shadow-v2"
    assert params["buckets"] == [arms.bucket(i, "ma-shadow-v2") for i in (1, 2, 3)] == [9598, 3492, 7003]
    assert conn.statements[1][1] == {"experiment": "ma-shadow-v2", "ids": [1, 2, 3]}
