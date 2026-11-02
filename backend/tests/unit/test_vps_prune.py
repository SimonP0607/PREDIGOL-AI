"""Docker's disk use on the server (deploy/vps/bin/prune.sh): old images go, the ones a rollback needs never do, and a volume
goes only when it is named, unused, outside the compose project and the newest dump has a verified copy off the server."""

from __future__ import annotations

import fcntl
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.unit._vps_sandbox import Sandbox, tools_present

pytestmark = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)


def _images() -> dict[str, str]:
    """Six backend and six web images, one a day (a1 oldest), three database images."""
    day0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
    out: dict[str, str] = {}
    for i in range(1, 7):
        stamp = (day0 + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
        out[f"predigol-backend:a{i}"] = stamp
        out[f"predigol-web:w{i}"] = stamp
    for i in range(1, 4):
        out[f"predigol-postgres:p{i}"] = (day0 + timedelta(days=i * 3)).strftime(
            "%Y-%m-%dT%H:%M:%S.123456789Z"
        )
    out["caddy:2.11.7"] = "2026-09-01T00:00:00.1Z"  # a base image: never touched
    return out


def _server(
    sb: Sandbox,
    *,
    containers: list[str] | None = None,
    versions: tuple[str, str, str] = ("a5", "w5", "p3"),
    deploys: list[tuple[str, str, str, str]] | None = None,
    **docker: object,
) -> None:
    """The server as a deploy leaves it: what runs, what versions.env says, the last deploys.log lines."""
    sb.state.mkdir(parents=True, exist_ok=True)
    (sb.state / "versions.env").write_text(
        f"PREDIGOL_VERSION={versions[0]}\nPREDIGOL_WEB_VERSION={versions[1]}\nPREDIGOL_PG_VERSION={versions[2]}\n"
    )
    rows = deploys if deploys is not None else [("a6", "w6", "a5", "w5")]
    (sb.state / "deploys.log").write_text(
        "".join(
            f"2026-10-2{n}T20:00:00Z\t{be}\t{web}\t{obe}\t{oweb}\n"
            for n, (be, web, obe, oweb) in enumerate(rows)
        )
    )
    sb.set_docker(
        images=_images(),
        containers=containers
        if containers is not None
        else ["predigol-backend:a4", "predigol-web:w4", "predigol-postgres:p3", "caddy:2.11.7"],
        **docker,
    )


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def _removed(sb: Sandbox) -> set[str]:
    return set(sb.docker().get("removed", []))


def _df_shrinks(sb: Sandbox, *, from_gib: int = 100, to_gib: int = 95) -> dict[str, str]:
    """A `df -Pk` that says from_gib GiB used the first time and to_gib afterwards; returns the environment that points at it."""
    stub = sb.stubs / "df"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'f="$DF_STUB_COUNT"; n=$(cat "$f" 2> /dev/null || echo 0); echo $((n + 1)) > "$f"\n'
        f"if (( n == 0 )); then used=$(({from_gib} * 1048576)); pct=50; else used=$(({to_gib} * 1048576)); pct=47; fi\n"
        'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        'echo "/dev/stub 209715200 $used $((209715200 - used)) ${pct}% /srv"\n'
    )
    stub.chmod(0o755)
    return {"DF_STUB_COUNT": str(sb.root / "df.count")}


def _record(sb: Sandbox) -> dict:
    return json.loads((sb.state / "prune.json").read_text())


def test_the_newest_three_what_runs_and_the_rollback_target_are_kept(sb: Sandbox) -> None:
    _server(sb)
    result = sb.run("prune.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    # backend: newest three a6 a5 a4 (a4 also runs, a5 is versions.env and the previous deploy); web the same
    assert _removed(sb) == {
        "predigol-backend:a1",
        "predigol-backend:a2",
        "predigol-backend:a3",
        "predigol-web:w1",
        "predigol-web:w2",
        "predigol-web:w3",
        "predigol-postgres:p1",
    }
    record = _record(sb)
    assert record["images_removed"].count("predigol-web:w3") == 1
    assert "image predigol-web:w3" in record["items"] and len(record["items"]) == 7
    assert isinstance(record["freed_bytes"], int) and record["freed_bytes"] >= 0
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["at"])


def test_an_old_rollback_target_survives_even_when_it_is_not_among_the_newest(sb: Sandbox) -> None:
    """`predigolctl rollback` reads the last deploys.log line and starts those images: they must still be there."""
    _server(
        sb, deploys=[("a4", "w4", "a3", "w3"), ("a5", "w5", "a4", "w4"), ("a6", "w6", "a2", "w2")]
    )
    assert sb.run("prune.sh").returncode == 0
    assert {
        "predigol-backend:a2",
        "predigol-web:w2",
        "predigol-backend:a3",
        "predigol-web:w3",
    }.isdisjoint(_removed(sb))
    assert _removed(sb) >= {"predigol-backend:a1", "predigol-web:w1"}


def test_a_rollback_line_does_not_pin_a_dash_as_an_image(sb: Sandbox) -> None:
    _server(
        sb, deploys=[("a6", "w6", "a5", "w5"), ("a5", "w5", "-", "-")]
    )  # (the rollback line has "-" for the previous)
    result = sb.run("prune.sh")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "predigol-backend:a5" not in _removed(sb)


def test_base_images_and_unrelated_repositories_are_left_alone(sb: Sandbox) -> None:
    _server(sb)
    sb.run("prune.sh")
    assert "caddy:2.11.7" in sb.docker()["images"]


def test_a_dry_run_removes_nothing_and_prunes_nothing(sb: Sandbox) -> None:
    _server(sb)
    result = sb.run("prune.sh", "--dry-run")
    assert result.returncode == 0 and "would remove image predigol-backend:a1" in result.stdout
    state = sb.docker()
    assert not state.get("removed") and not state.get("calls")
    assert not (sb.state / "prune.json").exists(), "a dry run leaves no record"


def test_the_record_says_when_how_much_and_what(sb: Sandbox) -> None:
    """The storage report reads {at, freed_bytes, items} from state/prune.json; freed_bytes is the drop in used disk (df)."""
    _server(sb, reclaim=True)
    env = _df_shrinks(sb)
    result = sb.run("prune.sh", **env)
    assert result.returncode == 0, result.stdout + result.stderr
    record = _record(sb)
    assert record["freed_bytes"] == 5 * 1024**3
    assert record["items"] == [
        *(f"image {i}" for i in record["images_removed"]),
        "dangling images older than 24 h",
        "build cache beyond 4GB",
    ]
    assert record["disk_used_percent"] == {"before": 50, "after": 47}
    assert "docker_before" in record and "docker_after" in record


def test_nothing_reclaimed_by_docker_adds_no_item_and_the_disk_never_counts_as_negative(
    sb: Sandbox,
) -> None:
    _server(sb)  # Docker says "0B" for both prunes
    env = _df_shrinks(sb, from_gib=90, to_gib=95)  # something else wrote 5 GiB meanwhile
    assert sb.run("prune.sh", **env).returncode == 0
    record = _record(sb)
    assert record["freed_bytes"] == 0
    assert all(item.startswith("image ") for item in record["items"])


def test_the_record_is_replaced_whole_and_no_temporary_file_is_left(sb: Sandbox) -> None:
    _server(sb)
    (sb.state / "prune.json").write_text('{"at": "2020-01-01T00:00:00Z"}')
    assert sb.run("prune.sh").returncode == 0
    assert _record(sb)["at"] != "2020-01-01T00:00:00Z"
    assert sorted(p.name for p in sb.state.glob("prune.json*")) == ["prune.json"]


def test_a_record_that_cannot_be_written_is_said_so_fails_the_run_and_leaves_no_temporary_file(
    sb: Sandbox,
) -> None:
    """The images go all the same; what is missing is the constancia. A folder where the file should be stands for any place the new
    record cannot go: `mv -T` refuses, where a plain `mv` would put the new file INSIDE it and leave the old record in place."""
    _server(sb)
    (sb.state / "prune.json").mkdir()
    result = sb.run("prune.sh")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "could not write" in result.stdout + result.stderr
    assert _removed(sb), "the clean-up itself was done"
    assert sorted(p.name for p in sb.state.glob("prune.json*")) == ["prune.json"]
    assert list((sb.state / "prune.json").iterdir()) == []


def test_a_record_that_cannot_be_written_after_removing_volumes_is_said_so_and_fails_the_run(
    sb: Sandbox,
) -> None:
    _volumes(sb)
    (sb.state / "prune.json").mkdir()
    result = sb.run("prune.sh", "--volumes", "orphan1", "--confirm")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "could not write" in result.stdout + result.stderr
    assert sb.docker()["removed_volumes"] == ["orphan1"]
    assert sorted(p.name for p in sb.state.glob("prune.json*")) == ["prune.json"]


def test_dangling_images_and_the_build_cache_are_pruned_to_a_budget(sb: Sandbox) -> None:
    _server(sb)
    sb.run("prune.sh")
    calls = sb.docker()["calls"]
    assert "image prune" in calls
    assert "builder prune -f --reserved-space 4GB" in calls


def test_an_image_docker_refuses_to_remove_is_reported_and_the_rest_goes_on(sb: Sandbox) -> None:
    _server(sb, busy=["predigol-backend:a1"])
    result = sb.run("prune.sh")
    assert result.returncode == 0 and "kept predigol-backend:a1 (Docker refused" in result.stdout
    assert "predigol-backend:a2" in _removed(sb)


def test_while_a_deploy_holds_its_lock_nothing_is_pruned_unless_the_deploy_itself_asks(
    sb: Sandbox,
) -> None:
    _server(sb)
    sb.state.mkdir(parents=True, exist_ok=True)
    with open(sb.state / "deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        left = sb.run("prune.sh")
        assert left.returncode == 0 and "left for later" in left.stdout and not _removed(sb)
        mine = sb.run("prune.sh", PREDIGOL_PRUNE_AFTER_DEPLOY="1")
        assert mine.returncode == 0 and _removed(sb), "the deploy's own call goes ahead"


# ---- volumes --------------------------------------------------------------------------------------------------------


def _volumes(sb: Sandbox, *, verified_hours_ago: float | None = 2) -> None:
    _server(
        sb,
        volumes={
            "orphan1": {"project": ""},
            "orphan2": {"project": ""},
            "pgdata": {"project": "predigol"},
            "busy": {"project": ""},
        },
        containers=["predigol-backend:a4"],
        uses={"predigol-backend:a4": ["busy"]},
    )
    sb.backups.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"name": "predigol-20261025T041900Z"}
    if verified_hours_ago is not None:
        at = datetime.now(UTC) - timedelta(hours=verified_hours_ago)
        manifest["offsite"] = {"verified_at": at.strftime("%Y-%m-%dT%H:%M:%SZ")}
    (sb.backups / "predigol-20261025T041900Z.json").write_text(json.dumps(manifest))


def test_a_named_orphan_volume_is_removed_and_only_that_one(sb: Sandbox) -> None:
    _volumes(sb)
    result = sb.run("prune.sh", "--volumes", "orphan1", "--confirm")
    assert result.returncode == 0, result.stdout + result.stderr
    assert sb.docker()["removed_volumes"] == ["orphan1"] and "orphan2" in sb.docker()["volumes"]


@pytest.mark.parametrize("args", [["--volumes", "orphan1"], ["--confirm"]])
def test_volumes_need_both_a_name_and_the_confirmation(sb: Sandbox, args: list[str]) -> None:
    _volumes(sb)
    result = sb.run("prune.sh", *args)
    assert not sb.docker().get("removed_volumes")
    if args == ["--volumes", "orphan1"]:
        assert result.returncode == 1 and "needs --confirm" in result.stdout


@pytest.mark.parametrize(
    ("name", "why"),
    [
        ("busy", "used by a container"),
        ("pgdata", "belongs to the predigol compose project"),
        ("ghost", "no such volume"),
    ],
)
def test_a_volume_in_use_or_in_the_project_or_unknown_is_refused_and_nothing_else_goes(
    sb: Sandbox, name: str, why: str
) -> None:
    _volumes(sb)
    result = sb.run("prune.sh", "--volumes", f"orphan1,{name}", "--confirm")
    assert result.returncode == 1 and why in result.stdout
    assert not sb.docker().get("removed_volumes"), (
        "all or nothing: the valid one in the list stays too"
    )


@pytest.mark.parametrize("hours", [None, 40])
def test_without_a_fresh_verified_copy_off_the_server_no_volume_is_removed(
    sb: Sandbox, hours: float | None
) -> None:
    _volumes(sb, verified_hours_ago=hours)
    result = sb.run("prune.sh", "--volumes", "orphan1", "--confirm")
    assert (
        result.returncode == 1
        and "no verified copy off the server from the last 26 h" in result.stdout
    )
    assert not sb.docker().get("removed_volumes")


def test_removing_volumes_leaves_a_record_of_which_and_how_much(sb: Sandbox) -> None:
    _volumes(sb)
    env = _df_shrinks(sb, from_gib=120, to_gib=70)
    result = sb.run("prune.sh", "--volumes", "orphan1,orphan2", "--confirm", **env)
    assert result.returncode == 0, result.stdout + result.stderr
    record = _record(sb)
    assert record["items"] == ["volume orphan1", "volume orphan2"]
    assert record["volumes_removed"] == ["orphan1", "orphan2"] and record["images_removed"] == []
    assert record["freed_bytes"] == 50 * 1024**3
    assert "docker_before" not in record, (
        "`docker system df` walks every volume: it is not asked for here"
    )


def test_a_volume_docker_cannot_remove_is_said_so_fails_the_run_and_stays_out_of_the_record(
    sb: Sandbox,
) -> None:
    _volumes(sb)
    state = sb.docker()
    state["volume_rm_fails"] = ["orphan2"]
    sb.set_docker(**state)
    result = sb.run("prune.sh", "--volumes", "orphan1,orphan2", "--confirm")
    assert result.returncode == 1 and "could not remove volume orphan2" in result.stdout
    assert _record(sb)["volumes_removed"] == ["orphan1"]


def test_a_dry_run_of_volumes_removes_nothing_and_leaves_no_record(sb: Sandbox) -> None:
    _volumes(sb)
    result = sb.run("prune.sh", "--dry-run", "--volumes", "orphan1", "--confirm")
    assert result.returncode == 0 and "would remove volume orphan1" in result.stdout
    assert not sb.docker().get("removed_volumes") and not (sb.state / "prune.json").exists()
