"""The grants of the database roles are applied from the checkout (deploy/vps/bin/lib.sh ``apply_grants``, used by ``predigolctl deploy``
and ``predigolctl grants``)."""

from __future__ import annotations

import subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parents[2] / "deploy" / "vps"
LIB = KIT / "bin" / "lib.sh"
FAKE_DOCKER = """#!/usr/bin/env bash
# records what `docker compose exec` was asked and what it was given on stdin
printf '%s\\n' "$@" > "$FAKE_DIR/args"
cat > "$FAKE_DIR/stdin"
"""


def _apply_grants(tmp_path: Path) -> tuple[list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    env_file = tmp_path / "predigol.env"
    env_file.write_text("", encoding="utf-8")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_DIR": str(tmp_path), "PREDIGOL_ENV_FILE": str(env_file),
           "PREDIGOL_APP_ENV_FILE": str(tmp_path / "none.env"), "PREDIGOL_DATA": str(tmp_path / "data"), "HOME": str(tmp_path)}
    subprocess.run(["bash", "-c", f"set -Eeuo pipefail; . '{LIB}'; apply_grants"], check=True, capture_output=True, text=True, env=env)
    return (tmp_path / "args").read_text(encoding="utf-8").splitlines(), (tmp_path / "stdin").read_text(encoding="utf-8")


def test_the_grants_come_from_the_file_of_the_checkout_through_stdin(tmp_path: Path) -> None:
    """Regression (22 Oct 2026, F3 deploy): the file was read from `/predigol/grants.sql`, a bind mount of ONE file in the postgres
    container. `git checkout` replaces the file with a new one and the mount kept showing the old inode, so the deploy applied the grants
    of the release before: the new tables had no grants for the API (the referee console answered 500) until the file was piped by hand."""
    args, stdin = _apply_grants(tmp_path)
    assert stdin == (KIT / "db" / "grants.sql").read_text(encoding="utf-8"), "the checkout's file, byte for byte"
    assert "/predigol/grants.sql" not in " ".join(args), "never the container's copy"
    assert args[len(args) - 1 - args[::-1].index("-f") + 1] == "-", "psql (the last -f; compose has its own) reads the script from stdin"
    assert {"exec", "postgres", "psql", "ON_ERROR_STOP=1"} <= set(args)
    assert args[args.index("-U") + 1] == "fbi" and args[args.index("-d") + 1] == "fbi", "as the owner of the database"
