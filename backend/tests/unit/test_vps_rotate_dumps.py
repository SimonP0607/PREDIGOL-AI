"""Which database dumps the server keeps (deploy/vps/bin/rotate-dumps.sh, called by backup.sh after every dump)."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin" / "rotate-dumps.sh"


def _dumps(folder: Path, names: list[str]) -> None:
    for n in names:
        (folder / f"predigol-{n}.dump").write_bytes(b"x")
        (folder / f"predigol-{n}.json").write_text("{}")


def _rotate(folder: Path, daily: int = 3, weekly: int = 2, offsite: int = 0, unverified: int | None = None) -> set[str]:
    extra = [] if unverified is None else [str(unverified)]
    subprocess.run(["bash", str(SCRIPT), str(folder), str(daily), str(weekly), str(offsite), *extra], check=True,
                   capture_output=True, text=True)
    return {p.name.removeprefix("predigol-").removesuffix(".dump") for p in folder.glob("predigol-*.dump")}


def _copied(folder: Path, *names: str) -> None:
    for n in names:
        (folder / f"predigol-{n}.json").write_text('{"offsite": {"verified_at": "2026-10-20T05:00:00Z"}}')


def test_a_morning_of_deploys_keeps_the_previous_days(tmp_path: Path) -> None:
    """Regression (13 Oct 2026): the newest three dumps were kept, whatever their day - three deploys in one morning
    rotated out the 12 Oct dumps and the 13 Oct daily one; only the 11 Oct dump (a weekly one) survived."""
    _dumps(tmp_path, ["20261011T164349Z-pre-deploy-a", "20261012T042026Z", "20261012T110007Z-pre-deploy-b",
                      "20261013T041939Z", "20261013T065428Z-pre-deploy-c", "20261013T071704Z-pre-deploy-d",
                      "20261013T081932Z-pre-deploy-e"])
    kept = _rotate(tmp_path)
    assert {"20261013T081932Z-pre-deploy-e", "20261013T071704Z-pre-deploy-d",
            "20261013T065428Z-pre-deploy-c"} <= kept, "the newest three: each deploy's own"
    assert "20261012T110007Z-pre-deploy-b" in kept, "the newest of 12 Oct"
    assert "20261011T164349Z-pre-deploy-a" in kept, "the newest of 11 Oct (and of last week)"
    assert "20261012T042026Z" not in kept and "20261013T041939Z" not in kept
    assert not (tmp_path / "predigol-20261012T042026Z.json").exists(), "its description goes with it"


def test_an_ordinary_week_keeps_three_days_and_two_weeks(tmp_path: Path) -> None:
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 16)])  # 12-15 Oct: ISO week 42; 5-11 Oct: week 41
    assert _rotate(tmp_path) == {"20261015T041939Z", "20261014T041939Z", "20261013T041939Z", "20261011T041939Z"}


def test_with_an_off_server_copy_an_unchecked_dump_is_kept(tmp_path: Path) -> None:
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 8)])
    (tmp_path / "predigol-20261001T041939Z.json").write_text('{"offsite": {"verified_at": "2026-10-01T05:00:00Z"}}')
    kept = _rotate(tmp_path, offsite=1)
    assert "20261001T041939Z" not in kept and "20261002T041939Z" in kept, "only a checked copy lets it go"


def test_an_unchecked_dump_goes_once_a_newer_one_has_been_copied(tmp_path: Path) -> None:
    """The local copy of a night whose upload failed is kept only while it may be the only one: when a LATER dump reached the
    bucket, it is superseded and rotates out like any other (otherwise it would stay for ever)."""
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 11)])
    _copied(tmp_path, "20261007T041939Z")
    kept = _rotate(tmp_path, offsite=1)
    assert kept == {"20261010T041939Z", "20261009T041939Z", "20261008T041939Z", "20261004T041939Z"}, (
        "the rules' own: the newest three and the newest of the last two weeks; nothing older is kept for being unchecked")


def test_an_unchecked_dump_is_kept_while_nothing_newer_was_copied(tmp_path: Path) -> None:
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 11)])
    _copied(tmp_path, "20261002T041939Z")  # older than the ones in doubt
    kept = _rotate(tmp_path, offsite=1)
    assert {"20261003T041939Z", "20261005T041939Z", "20261006T041939Z", "20261007T041939Z"} <= kept
    assert "20261002T041939Z" not in kept, "its own copy is checked: it goes"


def test_the_dumps_in_doubt_are_capped_so_that_a_bucket_down_for_weeks_cannot_fill_the_disk(tmp_path: Path) -> None:
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 15)])  # none ever copied
    kept = _rotate(tmp_path, offsite=1, unverified=3)
    # by the rules: 12, 13, 14 and the newest of the week before (11); in doubt, the newest three of the rest: 10, 9, 8
    assert kept == {f"202610{d:02d}T041939Z" for d in (14, 13, 12, 11, 10, 9, 8)}
    assert not (tmp_path / "predigol-20261007T041939Z.json").exists()


def test_without_an_off_server_copy_the_rules_alone_decide(tmp_path: Path) -> None:
    _dumps(tmp_path, [f"202610{d:02d}T041939Z" for d in range(1, 15)])
    assert _rotate(tmp_path, offsite=0, unverified=99) == {f"202610{d:02d}T041939Z" for d in (14, 13, 12, 11)}
