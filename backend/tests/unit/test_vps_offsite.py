"""The copies off the server (deploy/vps/bin): tiers, the order of the checks, the RAW sync, the proof of the bucket locks and
the first-time setup. The scripts run for real against stand-ins for rclone, docker, age and date (_vps_sandbox)."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit._vps_sandbox import BIN, Sandbox, tools_present

pytestmark = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)

LOCKS = "dumps/daily/,dumps/weekly/,dumps/monthly/,raw/"
SUNDAY = "2026-10-25 04:19:00 UTC"  # a Sunday, not the 1st
FIRST = "2026-12-01 04:19:00 UTC"  # a Tuesday, the 1st
SUNDAY_FIRST = "2026-11-01 04:19:00 UTC"  # both
MONDAY = "2026-10-26 04:19:00 UTC"


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _tiers(name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(BIN / "offsite-tiers.sh"), name], capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(
    ("name", "tiers"),
    [
        ("predigol-20261026T041939Z", ["daily"]),  # a Monday
        ("predigol-20261025T041939Z", ["daily", "weekly"]),  # a Sunday
        ("predigol-20261201T041939Z", ["daily", "monthly"]),  # the 1st, a Tuesday
        ("predigol-20261101T041939Z", ["daily", "weekly", "monthly"]),  # the 1st and a Sunday
        (
            "predigol-20261025T110007Z-pre-deploy-8ba309f4c7e4",
            ["daily"],
        ),  # a deploy's own dump, even on a Sunday
        ("predigol-20261101T110007Z-r2-first", ["daily"]),
    ],
)
def test_the_tiers_of_a_dump_come_from_its_name_alone(name: str, tiers: list[str]) -> None:
    result = _tiers(name)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == tiers


@pytest.mark.parametrize(
    "name", ["", "dump.sql", "predigol-2026102T041939Z", "predigol-20261025T041939Z.dump", "../x"]
)
def test_a_name_that_is_not_a_dump_is_refused(name: str) -> None:
    assert _tiers(name).returncode != 0


# ---- backup.sh ----------------------------------------------------------------------------------------------------


def _backup(sb: Sandbox, now: str, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return sb.run("backup.sh", *args, FAKE_NOW=now, **env)


def _manifest(sb: Sandbox, stamp: str) -> dict:
    return json.loads((sb.backups / f"predigol-{stamp}.json").read_text())


def test_a_dump_with_no_remote_stays_only_here(sb: Sandbox) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, BACKUP_AGE_RECIPIENT=None)
    result = _backup(sb, SUNDAY)
    assert result.returncode == 0, result.stderr
    assert "no off-server copy configured" in result.stdout
    assert "offsite" not in _manifest(sb, "20261025T041900Z")
    assert sb.rclone_calls() == []


def test_the_timer_dump_of_a_sunday_goes_to_the_daily_and_the_weekly_tier(sb: Sandbox) -> None:
    result = _backup(sb, SUNDAY, RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    name = "predigol-20261025T041900Z"
    for tier in ("daily", "weekly"):
        assert (sb.bucket / "dumps" / tier / f"{name}.dump.age").is_file(), tier
        assert (sb.bucket / "dumps" / tier / f"{name}.json").is_file(), tier
    assert not list((sb.bucket / "dumps" / "monthly").glob("predigol-*")), (
        "(only the locks check's canary is there)"
    )
    assert not (sb.backups / f"{name}.dump.age").exists(), (
        "the encrypted copy does not stay on the disk"
    )
    assert not list(sb.backups.glob("*.json.up")) and not list(sb.backups.glob("*.json.new"))


def test_the_first_of_the_month_and_a_sunday_make_three_copies(sb: Sandbox) -> None:
    result = _backup(sb, SUNDAY_FIRST, RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    for tier in ("daily", "weekly", "monthly"):
        assert (sb.bucket / "dumps" / tier / "predigol-20261101T041900Z.dump.age").is_file(), tier
    assert _manifest(sb, "20261101T041900Z")["offsite"]["tiers"] == ["daily", "weekly", "monthly"]


def test_a_deploys_own_dump_goes_to_the_daily_tier_only(sb: Sandbox) -> None:
    result = _backup(sb, SUNDAY, "--label", "pre-deploy-8ba309f4c7e4", RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    name = "predigol-20261025T041900Z-pre-deploy-8ba309f4c7e4"
    assert (sb.bucket / "dumps" / "daily" / f"{name}.dump.age").is_file()
    assert not (sb.bucket / "dumps" / "weekly").exists(), "a deploy does not add a weekly copy"
    assert _manifest(sb, "20261025T041900Z-pre-deploy-8ba309f4c7e4")["offsite"]["tiers"] == [
        "daily"
    ]


def test_the_manifest_is_marked_verified_only_after_every_tier_is_there(sb: Sandbox) -> None:
    _backup(sb, SUNDAY, RCLONE_STUB_LOCKED=LOCKS)
    name = "predigol-20261025T041900Z"
    local = _manifest(sb, "20261025T041900Z")["offsite"]
    assert (
        local["verified_at"].endswith("Z") and local["bytes"] > 0 and len(local["age_sha256"]) == 64
    )
    # What the bucket received: the hash of the encrypted file (so a download can be proven before it is decrypted), the tiers -
    # and no "verified" mark, which only the server's own record carries.
    there = json.loads((sb.bucket / "dumps" / "daily" / f"{name}.json").read_text())["offsite"]
    assert there["age_sha256"] == local["age_sha256"] and "verified_at" not in there
    order = [c[0] + ":" + c[-1].rsplit("/", 1)[-1] for c in sb.rclone_calls() if c[0] == "copyto"]
    assert order[:2] == [f"copyto:{name}.dump.age", f"copyto:{name}.json"], (
        "the dump first, its manifest second, per tier"
    )


def test_nothing_in_a_backup_ever_deletes_anything_off_the_server(sb: Sandbox) -> None:
    old = sb.bucket / "dumps" / "daily"
    old.mkdir(parents=True)
    (old / "predigol-20260101T041900Z.dump.age").write_bytes(b"old")  # far past any retention
    _backup(
        sb, MONDAY, RCLONE_STUB_LOCKED=LOCKS
    )  # (the Sunday copy also runs the locks check, which tries to delete ITS canary)
    verbs = {"deletefile", "delete", "purge", "sync", "move", "moveto"}
    assert sb.rclone_calls() and not [c for c in sb.rclone_calls() if verbs & set(c)]
    assert (old / "predigol-20260101T041900Z.dump.age").exists()


def test_a_copy_far_past_its_tiers_keep_is_reported_not_deleted(sb: Sandbox) -> None:
    old = sb.bucket / "dumps" / "daily" / "predigol-20260101T041900Z.dump.age"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    result = _backup(sb, SUNDAY, RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0
    assert "WARNING off-server: 1 copy(ies) in dumps/daily/ older than 18 days" in result.stdout
    assert old.exists()


def test_an_upload_that_arrives_short_fails_the_backup_and_leaves_no_verified_mark(
    sb: Sandbox,
) -> None:
    result = _backup(sb, SUNDAY, RCLONE_STUB_LOCKED=LOCKS, RCLONE_STUB_SHORT_UPLOAD="1")
    assert result.returncode != 0
    assert "NOT verified" in result.stdout
    name = "predigol-20261025T041900Z"
    assert (sb.backups / f"{name}.dump").exists(), "the dump itself is kept"
    assert "offsite" not in _manifest(sb, "20261025T041900Z"), (
        "its copy was never checked, so rotation keeps it"
    )
    assert not (sb.backups / f"{name}.dump.age").exists(), (
        "the encrypted copy is removed on failure too"
    )
    assert not list(sb.backups.glob("*.json.up"))


def test_the_sunday_copy_proves_the_locks_and_a_failing_proof_never_fails_the_backup(
    sb: Sandbox,
) -> None:
    ok = _backup(sb, SUNDAY, RCLONE_STUB_LOCKED=LOCKS)
    assert (
        ok.returncode == 0
        and json.loads((sb.state / "lock-check.json").read_text())["passed"] is True
    )
    bad = _backup(sb, "2026-11-08 04:19:00 UTC", RCLONE_STUB_LOCKED="")  # no lock at all
    assert bad.returncode == 0, "the backup itself succeeded"
    assert "the bucket-lock check FAILED" in bad.stdout
    assert json.loads((sb.state / "lock-check.json").read_text())["passed"] is False


def test_an_ordinary_day_does_not_touch_the_locks_check(sb: Sandbox) -> None:
    _backup(sb, MONDAY, RCLONE_STUB_LOCKED=LOCKS)
    assert not (sb.state / "lock-check.json").exists()


# ---- r2-lock-check.sh ---------------------------------------------------------------------------------------------


def _check(sb: Sandbox, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return sb.run("r2-lock-check.sh", *args, **env)


def test_locked_tiers_pass_and_their_canaries_stay(sb: Sandbox) -> None:
    result = _check(sb, RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    verdict = json.loads((sb.state / "lock-check.json").read_text())
    assert verdict["passed"] is True and [t["tier"] for t in verdict["tiers"]] == [
        "daily",
        "weekly",
        "monthly",
        "raw",
    ]
    for tier in ("daily", "weekly", "monthly"):
        assert len(list((sb.bucket / "dumps" / tier).glob("_lockcheck-*.txt"))) == 1, tier
    assert len(list((sb.bucket / "raw" / "_lockcheck").glob("_lockcheck-*.txt"))) == 1
    canary = next((sb.bucket / "dumps" / "daily").glob("_lockcheck-*.txt"))
    assert canary.read_text().startswith("lock check "), "unchanged: the overwrite was refused"


def test_a_tier_without_a_lock_fails_and_says_so(sb: Sandbox) -> None:
    result = _check(sb, RCLONE_STUB_LOCKED="dumps/daily/,dumps/monthly/,raw/")  # weekly forgotten
    assert result.returncode == 1
    assert "FAIL weekly" in result.stdout and "weekly is NOT LOCKED" in result.stdout
    verdict = json.loads((sb.state / "lock-check.json").read_text())
    assert verdict["passed"] is False
    assert {t["tier"]: t["passed"] for t in verdict["tiers"]} == {
        "daily": True,
        "weekly": False,
        "monthly": True,
        "raw": True,
    }
    assert not list((sb.bucket / "dumps" / "weekly").glob("_lockcheck-*.txt")), (
        "the canary it could delete is gone"
    )


def test_a_failed_delete_with_an_unknown_error_is_inconclusive_not_locked(sb: Sandbox) -> None:
    """The text R2 gives for a refused delete is not known in advance. An error that is not recognisably a lock refusal must
    never read as 'locked': the canary stayed, but the proof is missing."""
    result = _check(
        sb, "--tier", "daily", RCLONE_STUB_LOCKED=LOCKS, RCLONE_STUB_REFUSAL="the network went away"
    )
    assert result.returncode == 1
    assert "does not look like a lock refusal" in result.stdout
    assert (
        json.loads((sb.state / "lock-check.json").read_text())["tiers"][0]["delete"]
        == "inconclusive"
    )


def test_the_raw_tier_is_checked_under_its_own_prefix(sb: Sandbox) -> None:
    result = _check(sb, "--tier", "raw", RCLONE_STUB_LOCKED="raw/")
    assert result.returncode == 0, result.stdout
    assert list((sb.bucket / "raw" / "_lockcheck").glob("_lockcheck-*-raw.txt"))
    assert not (sb.bucket / "dumps").exists()


def test_the_remote_argument_wins_over_predigol_env(sb: Sandbox) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, RAW_RCLONE_REMOTE=None)
    assert _check(sb, "--tier", "daily").returncode == 2, "no remote anywhere: nothing to check"
    result = _check(sb, "--tier", "daily", "--remote", "r2:bucket", RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout


# ---- raw-sync.sh --------------------------------------------------------------------------------------------------

NOW = "2026-10-25 11:20:00 UTC"


def _day(sb: Sandbox, provider: str, day: str) -> Path:
    path = sb.data / "raw" / provider / day
    path.mkdir(parents=True, exist_ok=True)
    return path


def _raw_files(sb: Sandbox) -> Path:
    day = _day(sb, "api-football", "2026/10/25")
    (day / "fixtures__aaaaaaaaaaaa.json.gz").write_bytes(b"payload-a")
    (day / "odds__bbbbbbbbbbbb.json.gz").write_bytes(b"payload-b")
    (day / "odds__cccccccccccc.json.tmp").write_bytes(b"half-written")
    (day / "odds__dddddddddddd.json.gz").write_bytes(b"")
    return day


def _sync(
    sb: Sandbox, *args: str, now: str = NOW, **extra: str
) -> subprocess.CompletedProcess[str]:
    return sb.run("raw-sync.sh", *args, FAKE_NOW=now, RCLONE_STUB_LOCKED=LOCKS, **extra)


def _there(sb: Sandbox, rel: str) -> Path:
    return sb.bucket / "raw" / rel


def _state(sb: Sandbox) -> dict:
    return json.loads((sb.state / "raw-sync.json").read_text())


def _names(path: Path) -> list[str]:
    return sorted(p.name for p in path.iterdir())


def test_the_first_pass_is_a_full_one_and_lands_under_raw_not_under_raw_raw(sb: Sandbox) -> None:
    _raw_files(sb)
    result = _sync(sb)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _names(_there(sb, "api-football/2026/10/25")) == [
        "fixtures__aaaaaaaaaaaa.json.gz",
        "odds__bbbbbbbbbbbb.json.gz",
    ]
    assert not (sb.bucket / "raw" / "raw").exists(), (
        "the double raw/raw of the first version is gone"
    )
    state = _state(sb)
    assert state["mode"] == "full" and state["full_at"] == "2026-10-25T11:20:00Z"
    assert state["copied"] == 2 and state["empty_recent_files"] == 1, (
        "a half-written file and an empty one are not copied"
    )
    again = _sync(sb)
    assert again.returncode == 0 and _state(sb)["copied"] == 0
    assert _state(sb)["mode"] == "recent", "the next pass within the day is the hourly kind"


def test_the_raw_sync_only_adds_and_compares_by_size(sb: Sandbox) -> None:
    _raw_files(sb)
    _sync(sb)
    _sync(sb)
    copies = [c for c in sb.rclone_calls() if c[0] == "copy"]
    assert len(copies) >= 2
    for copy in copies:
        for flag in ("--immutable", "--size-only", "--min-size", "--exclude"):
            assert flag in copy, flag
    assert not [
        c
        for c in sb.rclone_calls()
        if {"sync", "move", "moveto", "deletefile", "delete", "purge"} & set(c)
    ]


def test_the_hourly_pass_looks_at_today_and_yesterday_only_and_the_full_pass_finds_the_rest(
    sb: Sandbox,
) -> None:
    _raw_files(sb)
    (_day(sb, "api-football", "2026/10/20") / "players__111111111111.json.gz").write_bytes(b"old")
    (_day(sb, "football-data", "2026/10/24") / "E0.csv__222222222222.json.gz").write_bytes(b"y")
    assert _sync(sb).returncode == 0
    # an older store is imported (a day nothing else writes to), and a new file lands in today's directory
    (_day(sb, "api-football", "2026/09/12") / "status__333333333333.json.gz").write_bytes(b"late")
    (_day(sb, "api-football", "2026/10/25") / "fixtures__444444444444.json.gz").write_bytes(b"new")
    before = len(sb.rclone_calls())
    hourly = _sync(sb, now="2026-10-25 12:20:00 UTC")
    assert hourly.returncode == 0, hourly.stdout + hourly.stderr
    state = _state(sb)
    assert state["mode"] == "recent" and state["copied"] == 1
    assert state["full_at"] == "2026-10-25T11:20:00Z", (
        "a recent pass leaves the date of the full one alone"
    )
    assert not _there(sb, "api-football/2026/09/12").exists()
    sources = [c[-2] for c in sb.rclone_calls()[before:] if c[0] == "copy"]
    assert sorted(s.split("/raw/", 1)[1] for s in sources) == [
        "api-football/2026/10/25",
        "football-data/2026/10/24",
    ], "day directories of today and yesterday, never the whole store"
    assert _sync(sb, "--full", now="2026-10-25 13:20:00 UTC").returncode == 0
    assert (_there(sb, "api-football/2026/09/12") / "status__333333333333.json.gz").exists()
    assert _state(sb)["mode"] == "full" and _state(sb)["full_at"] == "2026-10-25T13:20:00Z"


def test_just_after_midnight_utc_yesterdays_directory_is_still_looked_at(sb: Sandbox) -> None:
    last_night = _day(sb, "api-football", "2026/10/24")
    (last_night / "fixtures__000000000001.json.gz").write_bytes(b"23:50")
    assert _sync(sb, now="2026-10-24 23:55:00 UTC").returncode == 0
    (last_night / "fixtures__000000000002.json.gz").write_bytes(
        b"23:59"
    )  # renamed into place at 00:00:01
    (_day(sb, "api-football", "2026/10/23") / "fixtures__000000000003.json.gz").write_bytes(b"old")
    assert _sync(sb, now="2026-10-25 00:20:00 UTC").returncode == 0
    assert _state(sb)["mode"] == "recent"
    assert (_there(sb, "api-football/2026/10/24") / "fixtures__000000000002.json.gz").exists()
    assert not _there(sb, "api-football/2026/10/23").exists(), "two days back is the full pass's"


def test_a_full_pass_is_due_again_after_a_day(sb: Sandbox) -> None:
    _raw_files(sb)
    assert _sync(sb).returncode == 0
    assert _sync(sb, now="2026-10-26 10:20:00 UTC").returncode == 0  # 23 h later
    assert _state(sb)["mode"] == "recent"
    assert _sync(sb, now="2026-10-26 11:21:00 UTC").returncode == 0  # more than 24 h
    assert _state(sb)["mode"] == "full" and _state(sb)["full_at"] == "2026-10-26T11:21:00Z"


def test_a_provider_with_another_layout_is_found_by_the_full_pass(sb: Sandbox) -> None:
    _raw_files(sb)
    assert _sync(sb).returncode == 0
    odd = sb.data / "raw" / "other-provider"
    odd.mkdir()
    (odd / "export.json.gz").write_bytes(b"x")
    assert _sync(sb, now="2026-10-25 12:20:00 UTC").returncode == 0
    assert not _there(sb, "other-provider").exists()
    assert _sync(sb, "--full", now="2026-10-25 13:20:00 UTC").returncode == 0
    assert (_there(sb, "other-provider") / "export.json.gz").exists()


def test_a_file_that_differs_from_its_copy_fails_the_pass_loudly_and_the_others_still_go(
    sb: Sandbox,
) -> None:
    day = _raw_files(sb)
    there = _there(sb, "api-football/2026/10/25")
    there.mkdir(parents=True)
    (there / "fixtures__aaaaaaaaaaaa.json.gz").write_bytes(b"a different size entirely")
    result = _sync(sb)
    assert result.returncode != 0 and "raw-sync FAILED" in result.stdout
    assert (
        there / "fixtures__aaaaaaaaaaaa.json.gz"
    ).read_bytes() == b"a different size entirely", "never overwritten"
    assert (there / "odds__bbbbbbbbbbbb.json.gz").exists(), "the file after the bad one was copied"
    assert not (sb.state / "raw-sync.json").exists(), "no verdict of success"
    assert (sb.state / "raw-sync.last-failure.log").exists()
    assert day.exists()


def test_a_failing_full_pass_is_not_repeated_every_hour(sb: Sandbox) -> None:
    _raw_files(sb)
    assert _sync(sb).returncode == 0
    old = _day(sb, "api-football", "2026/10/10")
    (old / "players__555555555555.json.gz").write_bytes(b"12345")
    clash = _there(sb, "api-football/2026/10/10")
    clash.mkdir(parents=True)
    (clash / "players__555555555555.json.gz").write_bytes(b"a different size entirely")
    failed = _sync(sb, now="2026-10-26 11:30:00 UTC")  # the full pass is due, and finds the clash
    assert failed.returncode != 0 and "raw-sync FAILED" in failed.stdout
    hourly = _sync(sb, now="2026-10-26 12:30:00 UTC")
    assert hourly.returncode == 0, hourly.stdout
    assert _state(sb)["mode"] == "recent"
    assert _state(sb)["full_at"] == "2026-10-25T11:20:00Z", "the last full pass that SUCCEEDED"
    retried = _sync(sb, now="2026-10-27 11:31:00 UTC")  # a day after the failed attempt
    assert retried.returncode != 0, "tried again the next day, and said so"


def test_a_pass_that_is_still_running_makes_the_next_one_skip_itself_without_failing(
    sb: Sandbox,
) -> None:
    _raw_files(sb)
    sb.state.mkdir(parents=True, exist_ok=True)
    with open(sb.state / "raw-sync.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _sync(sb)
    assert result.returncode == 0 and "still running" in result.stdout
    assert sb.rclone_calls() == []


def test_only_empty_files_of_the_last_week_are_news(sb: Sandbox) -> None:
    day = _raw_files(sb)  # one empty file, written now
    long_ago = time.time() - 20 * 86400
    old_day = _day(sb, "api-football", "2026/10/04")
    in_old_dir = old_day / "players__000000000000.json.gz"
    in_old_dir.write_bytes(b"")
    in_new_dir = day / "players__000000000009.json.gz"
    in_new_dir.write_bytes(b"")
    os.utime(in_old_dir, (long_ago, long_ago))
    os.utime(in_new_dir, (long_ago, long_ago))
    os.utime(old_day, (long_ago, long_ago))
    assert _sync(sb).returncode == 0
    assert _state(sb)["empty_recent_files"] == 1, "the 4 October incident is history, not an alert"


def test_without_a_raw_remote_nothing_happens(sb: Sandbox) -> None:
    _raw_files(sb)
    sb.set_env(RAW_RCLONE_REMOTE=None)
    result = _sync(sb)
    assert result.returncode == 0 and "exists only on this server" in result.stdout
    assert sb.rclone_calls() == [] and not (sb.state / "raw-sync.json").exists()


def test_an_unknown_argument_is_refused(sb: Sandbox) -> None:
    result = _sync(sb, "--everything")
    assert result.returncode == 2 and sb.rclone_calls() == []


# ---- r2-setup.sh --------------------------------------------------------------------------------------------------

ENV = (
    "R2_ACCOUNT_ID=0123456789abcdef0123456789abcdef\nR2_ACCESS_KEY_ID=AKIDEXAMPLE000000000000000000AA\n"
    "R2_SECRET_ACCESS_KEY=sekrit0000000000000000000000000000000000000000000000000000000000\nR2_BUCKET=predigol-backups\n"
    "AGE_RECIPIENT=age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq\n"
)


def _r2_env(sb: Sandbox, text: str = ENV, mode: int = 0o600) -> Path:
    path = sb.root / "r2.env"
    path.write_bytes(text.encode())
    path.chmod(mode)
    return path


def test_setup_refuses_a_file_that_holds_the_private_key(sb: Sandbox) -> None:
    path = _r2_env(
        sb,
        ENV
        + "# "
        + "AGE-SECRET-"
        + "KEY-1"
        + "Q" * 58
        + "\n",  # (built here: a literal would trip the repository's own scanner)
    )
    result = sb.run("r2-setup.sh", str(path))
    assert result.returncode == 2 and "PRIVATE key" in result.stderr
    assert sb.rclone_calls() == []


def test_setup_wants_the_file_private_and_complete(sb: Sandbox) -> None:
    assert sb.run("r2-setup.sh", str(_r2_env(sb, mode=0o644))).returncode == 2
    assert (
        sb.run(
            "r2-setup.sh", str(_r2_env(sb, ENV.replace("R2_BUCKET=predigol-backups\n", "")))
        ).returncode
        == 2
    )
    assert sb.run("r2-setup.sh", str(_r2_env(sb, ENV.replace("age1qq", "age2qq")))).returncode == 2


def test_setup_stops_before_touching_predigol_env_when_the_bucket_is_not_locked(
    sb: Sandbox,
) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, BACKUP_AGE_RECIPIENT=None, RAW_RCLONE_REMOTE=None)
    before = sb.env_file.read_text()
    result = sb.run("r2-setup.sh", str(_r2_env(sb)), RCLONE_STUB_LOCKED="dumps/daily/")
    assert result.returncode == 1 and "not locked as it must be" in result.stdout
    assert sb.env_file.read_text() == before
    assert not list(sb.root.glob("predigol.env.before-r2-*"))
    assert not list(sb.backups.glob("*.dump")), (
        "no dump was taken for a bucket that would let the server erase it"
    )


def test_setup_end_to_end_writes_the_remote_takes_the_first_dump_and_checks_it(sb: Sandbox) -> None:
    sb.set_env(BACKUP_RCLONE_REMOTE=None, BACKUP_AGE_RECIPIENT=None, RAW_RCLONE_REMOTE=None)
    path = _r2_env(sb, ENV.replace("\n", "\r\n"))  # written on Windows
    result = sb.run("r2-setup.sh", str(path), RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "r2-setup PASSED" in result.stdout
    env_text = sb.env_file.read_text()
    assert (
        "BACKUP_RCLONE_REMOTE=r2:predigol-backups\n" in env_text
        and "RAW_RCLONE_REMOTE=r2:predigol-backups/raw\n" in env_text
    )
    assert "BACKUP_AGE_RECIPIENT=age1qqqq" in env_text and "\r" not in env_text
    assert list(sb.root.glob("predigol.env.before-r2-*")), "the file as it was is kept"
    assert oct((sb.root / "rclone.conf").stat().st_mode & 0o777) == "0o600"
    conf = (sb.root / "rclone.conf").read_text()
    assert "[r2]" in conf and "provider = Cloudflare" in conf and "no_check_bucket = true" in conf
    assert "no_head = true" in conf, "without it R2's 501 turns every upload into a failure"
    assert "sekrit" in conf, "the secret is where it belongs..."
    assert not any(
        "sekrit" in " ".join(c) or "AKIDEXAMPLE" in " ".join(c) for c in sb.rclone_calls()
    ), "...and never in an argv"
    (first,) = sb.backups.glob("predigol-*-r2-first.json")
    assert json.loads(first.read_text())["offsite"]["tiers"] == ["daily"]


def test_setup_keeps_the_other_remotes_of_the_rclone_config(sb: Sandbox) -> None:
    conf = sb.root / "rclone.conf"
    conf.write_text(
        "[other]\ntype = local\n\n[r2]\ntype = s3\naccess_key_id = OLD\n\n[last]\ntype = local\n"
    )
    result = sb.run("r2-setup.sh", str(_r2_env(sb)), "--check-only", RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    text = conf.read_text()
    assert "[other]" in text and "[last]" in text and "OLD" not in text and text.count("[r2]") == 1
    assert list(sb.root.glob("rclone.conf.before-r2-*")), "the previous config is kept"


def test_setup_writes_the_remote_with_no_head_because_the_real_r2_rejects_what_rclone_asks_after_an_upload(
    sb: Sandbox,
) -> None:
    # Seen on the real bucket (2026-10-26): rclone 1.60.1 (Ubuntu 24.04's) follows every upload with
    # HEAD <object>?versionId=..., R2 answers 501 NotImplemented, and rclone calls a stored object a failed upload.
    sb.root.joinpath("rclone.conf").unlink()
    result = sb.run("r2-setup.sh", str(_r2_env(sb)), "--check-only", RCLONE_STUB_LOCKED=LOCKS)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no_head = true" in (sb.root / "rclone.conf").read_text().splitlines()


def _stand_in(sb: Sandbox, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(sb.stubs / "rclone"), *args],
        env=sb.env(**env),
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_stand_in_rclone_fails_an_upload_to_a_remote_without_no_head_like_the_real_r2(
    sb: Sandbox,
) -> None:
    # The stand-in is only as good as what it imitates: this is the behaviour measured against the real bucket.
    src = sb.root / "x.txt"
    src.write_text("x")
    (sb.root / "rclone.conf").write_text("[r2]\ntype = s3\nno_check_bucket = true\n")
    failed = _stand_in(sb, "copyto", str(src), "r2:bucket/a.txt")
    assert failed.returncode != 0 and "NotImplemented" in failed.stderr and "501" in failed.stderr
    assert (sb.bucket / "a.txt").read_text() == "x", "...although the object is stored, as on R2"
    assert _stand_in(sb, "copyto", "--s3-no-head", str(src), "r2:bucket/b.txt").returncode == 0
    (sb.root / "rclone.conf").write_text("[other]\ntype = s3\n\n[r2]\ntype = s3\nno_head = true\n")
    assert _stand_in(sb, "copyto", str(src), "r2:bucket/c.txt").returncode == 0
    folder = sb.root / "folder"
    folder.mkdir()
    (folder / "f.txt").write_text("f")
    assert _stand_in(sb, "copy", str(folder), "r2:bucket/dir").returncode == 0
    # Reading is not uploading: nothing follows a download.
    assert _stand_in(sb, "copyto", "r2:bucket/c.txt", str(sb.root / "back.txt")).returncode == 0
