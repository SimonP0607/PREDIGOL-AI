"""Plan F14.3: the owner's guide to the server's disk says what the code and the kit do, and offers only the deletions it describes.

``docs/owner/DISCO_F14.md`` explains what fills the server's disk and what the owner may remove, with the exact commands. What it says about the disk
itself is a reading taken on one morning (sizes, a daily history) and no test can hold that. What a test can hold is every number the guide quotes FROM
the code and the kit - the refusal limits of the price clock, the watchdog's thresholds and cadence, the sizing rule of the restore test, how many dumps
the rotation keeps, the journal messages that say no copy leaves the server - and the part that must not drift: the five orphan volumes are named once
each, every ``docker`` command the guide offers is on a short list, a prune always carries an age filter, and the files it names exist. A guide that
sends the owner to delete things on the production server has to be exact about the one deletion it recommends."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fbi.odds.quote_extract import DEFAULT_MAX_TABLE_GB, DEFAULT_MIN_FREE_GB

BACKEND = Path(__file__).resolve().parents[2]
GUIDE = BACKEND / "docs" / "owner" / "DISCO_F14.md"
CHECKLIST = BACKEND / "docs" / "owner" / "CHECKLIST_POR_FASE_F14.md"
KIT = BACKEND / "deploy" / "vps"

if not GUIDE.is_file():
    pytest.skip(f"no {GUIDE.name} next to the code", allow_module_level=True)

TEXT = GUIDE.read_text(encoding="utf-8")
VOLUME = re.compile(r"\b[0-9a-f]{64}\b")
COMMANDS = frozenset(
    {"docker volume ls", "docker volume rm", "docker system df", "docker builder prune", "docker image prune"}
)
FORBIDDEN = ("system prune", "volume prune", "--volumes", "rm -rf", "docker rmi", "--force")


def script(name: str) -> str:
    return (KIT / "bin" / name).read_text(encoding="utf-8")


def section(number: int, text: str = TEXT) -> str:
    """The body of ``## number. ...`` up to the next ``## `` heading."""
    found = re.search(rf"^## {number}\. .*?(?=^## |\Z)", text, flags=re.M | re.S)
    assert found, f"the guide has no section {number}"
    return found.group(0)


def flat(text: str) -> str:
    """The text on one line: the guide wraps its lines, the messages and rules it quotes do not."""
    return re.sub(r"\s+", " ", text)


def bullet(body: str, start: str) -> str:
    """The bullet of ``body`` that begins ``* start`` (its continuation lines included), on one line."""
    found = re.search(rf"^\* {re.escape(start)}.*?(?=^\* |\n\n|\Z)", body, flags=re.M | re.S)
    assert found, f"no bullet begins {start!r}"
    return flat(found.group(0))


def fenced_blocks(text: str = TEXT) -> list[str]:
    return re.findall(r"^```[a-z]*\n(.*?)^```", text, flags=re.M | re.S)


def docker_commands(text: str) -> list[str]:
    """Every ``docker ...`` command written in backticks or in a block, one string each (a block's continuation lines joined)."""
    inline = re.findall(r"`(docker [^`]+)`", text)
    in_blocks = [
        line
        for block in fenced_blocks(text)
        for line in re.sub(r"\\\n\s*", " ", block).splitlines()
        if line.startswith("docker ")
    ]
    return [flat(command) for command in inline + in_blocks]


def test_the_price_clock_limits_are_the_ones_the_code_refuses_at() -> None:
    clock = bullet(section(7), "El reloj de precios")
    assert f"menos de {DEFAULT_MIN_FREE_GB:g} GB libres" in clock
    assert f"su tabla pasa de {DEFAULT_MAX_TABLE_GB:g} GB" in clock


def test_the_watchdog_numbers_are_the_ones_in_its_script_and_its_timer() -> None:
    source = script("healthcheck.sh")
    problem = re.search(r"\(\( used >= (\d+) \)\); then problem", source)
    warning = re.search(r"elif \(\( used >= (\d+) \)\); then warning", source)
    target = re.search(r"size_kb \* (\d+) / (\d+) - used_kb", source)
    horizon = re.search(r"days_left < (\d+)", source)
    timer = re.search(r"OnUnitActiveSec=(\d+)min", (KIT / "systemd" / "predigol-health.timer").read_text(encoding="utf-8"))
    assert problem and warning and target and horizon and timer, "healthcheck.sh or its timer no longer have the shape this test reads"
    percent = 100 * int(target[1]) // int(target[2])
    watchdog = bullet(section(7), "El vigilante")
    assert f"(cada {timer[1]} minutos)" in watchdog
    assert f"pasa del {warning[1]} %" in watchdog
    assert f"al {problem[1]} %" in watchdog
    assert f"el {percent} % queda a menos de {horizon[1]} días" in watchdog


def test_the_restore_test_sizing_rule_is_the_one_in_its_script() -> None:
    rule = re.search(r"pg_database_size\('fbi'\)\"\) \* (\d+) / (\d+) / 1024 \+ (\d+) \* 1024 \* 1024", script("restore-test.sh"))
    assert rule, "restore-test.sh no longer sizes the restored copy the way this test reads"
    extra_percent = 100 * int(rule[1]) // int(rule[2]) - 100
    restore = bullet(section(7), "La prueba de restauración semanal")
    assert f"la base más un {extra_percent} % y {rule[3]} GB" in restore


def test_the_rotation_defaults_are_the_ones_in_the_backup_script() -> None:
    source = script("backup.sh")
    daily = re.search(r"BACKUP_KEEP_DAILY:-(\d+)", source)
    weekly = re.search(r"BACKUP_KEEP_WEEKLY:-(\d+)", source)
    assert daily and weekly, "backup.sh no longer passes the rotation defaults this test reads"
    assert f"por defecto {daily[1]} días y {weekly[1]} semanas" in bullet(section(7), "La rotación de volcados")


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("backup.sh", "no off-server copy configured"),
        ("backup.sh", "this dump exists only here"),
        ("raw-sync.sh", "RAW_RCLONE_REMOTE is not set"),
        ("pitr.sh", "not configured (PITR_S3_BUCKET is empty)"),
    ],
)
def test_the_journal_messages_it_quotes_are_the_ones_the_scripts_write(name: str, message: str) -> None:
    assert message in script(name), f"{name} no longer writes {message!r}"
    assert message in flat(section(6)), f"the guide no longer quotes {message!r}"


def test_the_five_orphan_volumes_are_named_once_each_in_the_one_removal() -> None:
    removals = [block for block in fenced_blocks() if "docker volume rm" in block]
    assert len(removals) == 1, "the guide must have exactly one block that removes volumes"
    names = VOLUME.findall(removals[0])
    assert len(names) == 5 and len(set(names)) == 5, names
    assert set(VOLUME.findall(TEXT)) == set(names), "the guide names a volume that the removal does not"
    assert "cinco copias viejas" in section(1)


def test_every_docker_command_it_offers_is_on_the_short_list_and_a_prune_always_has_an_age() -> None:
    history = section(3)  # the old restore test is quoted there with its `docker rm -f`: that was the bug, not an offer
    offered = TEXT.replace(history, "")
    assert "docker rm" in history and "docker rm" not in offered
    commands = docker_commands(offered)
    assert len(commands) >= 5, commands
    for command in commands:
        assert " ".join(command.split()[:3]) in COMMANDS or " ".join(command.split()[:2]) in COMMANDS, command
        assert not any(word in command for word in FORBIDDEN), command
        if " prune" in command:
            assert re.search(r"--filter until=\d+h\b", command), f"a prune without an age filter: {command}"
    assert not any(word in offered for word in FORBIDDEN)


def test_every_file_it_names_exists() -> None:
    names = set(re.findall(r"`([A-Za-z0-9_./-]+\.(?:sh|md|py))`", TEXT))
    assert {"restore-test.sh", "r2-setup.sh", "pitr.sh", "r2-restore-drill.sh", "test_vps_restore_test.py"} <= {Path(n).name for n in names}
    for name in sorted(names):
        if "/" in name:
            assert (BACKEND / name).is_file(), f"the guide names {name}, which is not in the repository"
        else:
            found = any(next((BACKEND / folder).rglob(name), None) is not None for folder in ("deploy", "tests", "scripts", "docs"))
            assert found, f"the guide names {name}, which is not in the repository"


def test_the_phase_checklist_points_to_this_guide() -> None:
    if not CHECKLIST.is_file():
        pytest.skip(f"no {CHECKLIST.name} next to the code")
    disk = re.search(r"^\* \*\*Disco del servidor:\*\*.*?(?=^\* |\n\n|\Z)", CHECKLIST.read_text(encoding="utf-8"), flags=re.M | re.S)
    assert disk, "the checklist no longer has its «Disco del servidor» line"
    assert GUIDE.name in disk.group(0)
