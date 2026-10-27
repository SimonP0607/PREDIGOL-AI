"""A sandbox for the server's shell scripts (deploy/vps/bin): stand-ins for rclone, docker, age and date on PATH, so that
backup.sh, raw-sync.sh, r2-lock-check.sh, r2-setup.sh and prune.sh run for real - their own code, not a copy of it -
against a folder that plays the bucket and a JSON file that plays Docker.

The stand-in rclone knows what the scripts ask of it (copyto, copy, lsjson, lsf, deletefile, cat, config file) and applies the
rules R2 will apply: bucket locks by key prefix (a delete or an overwrite under one is refused, a new object is accepted), and
`--immutable`. It records every call, so a test can also say what was NEVER asked of the bucket (a delete).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

BIN = Path(__file__).resolve().parents[2] / "deploy" / "vps" / "bin"
TOOLS = ("bash", "jq", "flock", "sha256sum")


def tools_present() -> bool:
    return all(shutil.which(t) for t in TOOLS)


RCLONE_STUB = """#!__PY__
import fnmatch, json, os, shutil, sys, time

ROOT = os.environ["RCLONE_STUB_ROOT"]
LOCKED = [p for p in os.environ.get("RCLONE_STUB_LOCKED", "").split(",") if p]
LOG = os.environ.get("RCLONE_STUB_LOG")
REFUSAL = os.environ.get("RCLONE_STUB_REFUSAL", "AccessDenied: the object is locked")
SHORT = bool(os.environ.get("RCLONE_STUB_SHORT_UPLOAD"))
VALUE_FLAGS = {"s3-chunk-size", "s3-upload-concurrency", "retries", "low-level-retries", "contimeout", "timeout", "count",
               "transfers", "checkers", "include", "exclude", "min-age", "min-size", "log-level", "stats", "log-file", "filter"}
flags, positional, args = {}, [], sys.argv[1:]
i = 0
while i < len(args):
    a = args[i]
    if a.startswith("--"):
        name = a[2:]
        if name in VALUE_FLAGS:
            flags.setdefault(name, []).append(args[i + 1])
            i += 2
        else:
            flags[name] = [True]
            i += 1
    else:
        positional.append(a)
        i += 1
if LOG:
    with open(LOG, "a") as fh:
        fh.write(json.dumps({"argv": sys.argv[1:]}) + "\\n")


def real(path):
    return os.path.join(ROOT, path[3:]) if path.startswith("r2:") else path


def key(path):
    return path[3:].split("/", 1)[1] if path.startswith("r2:") and "/" in path[3:] else ""


def locked(path):
    return path.startswith("r2:") and any(key(path).startswith(p) for p in LOCKED)


def die(msg, code=1):
    sys.stderr.write("ERROR : " + msg + "\\n")
    sys.exit(code)


def no_head():
    # What the real R2 does to rclone 1.60.x (Ubuntu 24.04 ships 1.60.1), seen on the real bucket on 2026-10-26: the answer to the PUT
    # carries a version id, rclone then asks HEAD <object>?versionId=..., R2 answers 501 NotImplemented, and rclone reports the
    # upload as failed although the object IS stored. `no_head` (in the [r2] section of the config file, as RCLONE_CONFIG_R2_NO_HEAD,
    # or --s3-no-head) makes rclone trust the 200 of the PUT instead.
    if "s3-no-head" in flags:
        return True
    env = os.environ.get("RCLONE_CONFIG_R2_NO_HEAD")
    if env is not None:
        return env.strip().lower() == "true"
    conf, section = os.environ.get("RCLONE_CONFIG", ""), None
    if conf and os.path.isfile(conf):
        with open(conf) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1]
                elif section == "r2":
                    k, _, v = line.partition("=")
                    if k.strip() == "no_head":
                        return v.strip().lower() == "true"
    return False


def put(src, dst):
    target = real(dst)
    src = real(src)
    size = os.path.getsize(src)
    if os.path.exists(target):
        same = os.path.getsize(target) == size
        if "immutable" in flags and same:
            return "skipped"
        if "immutable" in flags:
            die("%s: immutable file modified" % dst)
        if locked(dst):
            die("%s: %s" % (dst, REFUSAL))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(src, target)
    if SHORT and target.endswith(".age"):
        with open(target, "r+b") as fh:
            fh.truncate(max(size - 1, 0))
    if dst.startswith("r2:") and not no_head():
        die("%s: Failed to copy: NotImplemented: Not Implemented status code: 501, request id: , host id: "
            % os.path.basename(dst))
    return "copied"


cmd = positional[0]
rest = positional[1:]
if cmd == "config" and rest[:1] == ["file"]:
    print("Configuration file is stored at:")
    print(os.environ.get("RCLONE_CONFIG", "/nonexistent/rclone.conf"))
elif cmd == "copyto":
    put(rest[0], rest[1])
elif cmd == "copy":
    src, dst = rest
    if not os.path.isdir(src):
        die("directory not found", 3)
    excludes = flags.get("exclude", [])
    failed = 0
    for base, _, files in os.walk(src):
        for name in sorted(files):
            if any(fnmatch.fnmatch(name, pat) for pat in excludes):
                continue
            path = os.path.join(base, name)
            if "min-size" in flags and os.path.getsize(path) < 1:
                continue
            rel = os.path.relpath(path, src)
            try:
                outcome = put(path, dst.rstrip("/") + "/" + rel)
            except SystemExit:
                failed += 1  # like rclone: this file is reported, the others still go, the exit status says it
                continue
            if outcome == "copied" and flags.get("log-file"):
                with open(flags["log-file"][0], "a") as fh:
                    fh.write("INFO  : %s: Copied (new)\\n" % rel)
    if failed:
        sys.exit(1)
elif cmd == "lsjson":
    target = real(rest[0])
    if os.path.isfile(target):
        print(json.dumps([{"Name": os.path.basename(target), "Size": os.path.getsize(target), "IsDir": False}]))
    elif os.path.isdir(target):
        print(json.dumps([{"Name": n, "Size": os.path.getsize(os.path.join(target, n)), "IsDir": False}
                          for n in sorted(os.listdir(target)) if os.path.isfile(os.path.join(target, n))]))
    else:
        die("directory not found", 3)
elif cmd == "lsf":
    target = real(rest[0])
    if os.path.isfile(target):
        print(os.path.basename(target))
    elif os.path.isdir(target):
        includes = flags.get("include", ["*"])
        limit = None
        if "min-age" in flags:
            limit = time.time() - float(flags["min-age"][0].rstrip("d")) * 86400
        for n in sorted(os.listdir(target)):
            p = os.path.join(target, n)
            if os.path.isfile(p) and any(fnmatch.fnmatch(n, pat) for pat in includes) and (limit is None or os.path.getmtime(p) < limit):
                print(n)
    else:
        die("directory not found", 3)
elif cmd == "deletefile":
    target = real(rest[0])
    if not os.path.isfile(target):
        die("object not found", 4)
    if locked(rest[0]):
        die("%s: %s" % (rest[0], REFUSAL))
    os.remove(target)
elif cmd == "cat":
    target = real(rest[0])
    if not os.path.isfile(target):
        die("object not found", 3)
    with open(target, "rb") as fh:
        data = fh.read(int(flags["count"][0])) if "count" in flags else fh.read()
    sys.stdout.buffer.write(data)
else:
    die("the stand-in rclone does not know " + cmd, 9)
"""

DOCKER_STUB = """#!__PY__
import json, os, sys

STATE = os.environ["DOCKER_STUB_STATE"]
with open(STATE) as fh:
    state = json.load(fh)
args = sys.argv[1:]


def save():
    with open(STATE, "w") as fh:
        json.dump(state, fh)


if args[:1] == ["compose"]:
    if "exec" not in args:
        sys.exit(0)
    tail = args[args.index("exec") + 1:]
    tail = [a for a in tail if a != "-T"]
    assert tail[0] == "postgres", tail
    prog, rest = tail[1], tail[2:]
    if prog == "psql":
        query = [rest[i + 1] for i, a in enumerate(rest) if a == "-c"][-1]
        if "alembic_version" in query:
            print("0093")
        elif "json_build_object" in query:
            print(json.dumps({"core.fixtures": 10, "auth.users": 2}))
        else:
            print("")
    elif prog == "pg_dump" and "--version" in rest:
        print("pg_dump (PostgreSQL) 16.15")
    elif prog == "pg_dump":
        out = [a for a in rest if a.startswith("--file=")][0].split("=", 1)[1]
        with open(os.path.join(os.environ["PREDIGOL_DATA"], "backups", "db", os.path.basename(out)), "wb") as fh:
            fh.write(b"PGDMP-stand-in " + os.urandom(64))
    elif prog == "pg_restore":
        sys.exit(1 if os.environ.get("DOCKER_STUB_RESTORE_FAILS") else 0)
    sys.exit(0)

if args[:2] == ["ps", "-a"]:
    if "-q" in args:
        volume = [a.split("=", 1)[1] for a in args if a.startswith("volume=")][0]
        print("\\n".join("c%d" % n for n, c in enumerate(state.get("containers", [])) if volume in state.get("uses", {}).get(c, [])))
    else:
        print("\\n".join(state.get("containers", [])))
elif args[:2] == ["image", "ls"]:
    repo = args[2]
    print("\\n".join(r.split(":", 1)[1] for r in state["images"] if r.split(":", 1)[0] == repo))
elif args[:2] == ["image", "inspect"]:
    print(state["images"][args[-1]])
elif args[:2] == ["image", "rm"]:
    if args[2] in state.get("busy", []):
        sys.stderr.write("conflict: image is being used\\n")
        sys.exit(1)
    state["images"].pop(args[2], None)
    state.setdefault("removed", []).append(args[2])
    save()
elif args[:2] == ["image", "prune"]:
    state.setdefault("calls", []).append("image prune")
    save()
    print("Total reclaimed space: " + ("1.2GB" if state.get("reclaim") else "0B"))
elif args[:2] == ["builder", "prune"]:
    state.setdefault("calls", []).append("builder prune " + " ".join(args[2:]))
    save()
    print("Total:\t" + ("3.4GB" if state.get("reclaim") else "0B"))
elif args[:2] == ["system", "df"]:
    print("Images 1GB (reclaimable 0B)")
elif args[:2] == ["volume", "inspect"]:
    name = args[-1]
    if name not in state.get("volumes", {}):
        sys.exit(1)
    print(state["volumes"][name].get("project", ""))
elif args[:2] == ["volume", "rm"]:
    if args[2] in state.get("volume_rm_fails", []):
        sys.stderr.write("Error response from daemon: unable to remove volume %s\\n" % args[2])
        sys.exit(1)
    state["volumes"].pop(args[2])
    state.setdefault("removed_volumes", []).append(args[2])
    save()
else:
    sys.stderr.write("the stand-in docker does not know %s\\n" % args)
    sys.exit(9)
"""

AGE_STUB = """#!/usr/bin/env bash
# Stand-in for age: [-r RECIPIENT] [-o OUT] [IN]. Not encryption; it has age's first line so that the scripts' checks see an
# age file. Like age it refuses a recipient that is not a public key, and reads stdin / writes stdout when given no file.
out=""; in=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r) case "$2" in age1*) ;; *) echo "age: error: malformed recipient" >&2; exit 1 ;; esac; shift 2 ;;
    -o) out="$2"; shift 2 ;;
    -d | -i) shift ;;
    *) in="$1"; shift ;;
  esac
done
emit() { echo "age-encryption.org/v1"; cat "${in:-/dev/stdin}"; }
if [[ -n "$out" ]]; then emit > "$out"; else emit; fi
"""

DATE_STUB = """#!/usr/bin/env bash
# date, but "now" is FAKE_NOW when it is set (the scripts name a dump after the second it was taken).
if [[ -n "${FAKE_NOW:-}" ]]; then
  for a in "$@"; do [[ "$a" == -d ]] && exec "$REAL_DATE" "$@"; done
  exec "$REAL_DATE" -d "$FAKE_NOW" "$@"
fi
exec "$REAL_DATE" "$@"
"""


@dataclass
class Sandbox:
    root: Path
    extra_env: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.stubs = self.root / "stubs"
        self.data = self.root / "data"
        self.bucket_root = self.root / "bucket"
        self.env_file = self.root / "predigol.env"
        self.calls = self.root / "rclone-calls.log"
        self.docker_state = self.root / "docker.json"
        for d in (self.stubs, self.data, self.bucket_root / "bucket", self.root / "home"):
            d.mkdir(parents=True, exist_ok=True)
        py = sys.executable
        for name, body in (
            ("rclone", RCLONE_STUB),
            ("docker", DOCKER_STUB),
            ("age", AGE_STUB),
            ("date", DATE_STUB),
        ):
            path = self.stubs / name
            path.write_text(body.replace("__PY__", py))
            path.chmod(0o755)
        self.env_file.write_text(
            "PREDIGOL_DOMAIN=test.localhost\nBACKUP_RCLONE_REMOTE=r2:bucket\nBACKUP_AGE_RECIPIENT=age1stand-in\n"
            "RAW_RCLONE_REMOTE=r2:bucket/raw\nBACKUP_KEEP_DAILY=3\nBACKUP_KEEP_WEEKLY=2\n"
        )
        self.env_file.chmod(0o600)
        # The remote "r2" as bin/r2-setup.sh leaves it (no_head included: without it the real R2 makes rclone 1.60.x call every
        # upload a failure, and the stand-in rclone does the same). A test that wants another config writes its own.
        (self.root / "rclone.conf").write_text(
            "[r2]\ntype = s3\nprovider = Cloudflare\nenv_auth = false\naccess_key_id = stand-in-key\n"
            "secret_access_key = stand-in-secret\nendpoint = https://stand-in.invalid\nacl = private\n"
            "no_check_bucket = true\nno_head = true\n"
        )
        self.set_docker()

    @property
    def state(self) -> Path:
        return self.data / "state"

    @property
    def backups(self) -> Path:
        return self.data / "backups" / "db"

    @property
    def bucket(self) -> Path:
        return self.bucket_root / "bucket"

    def set_env(self, **values: str | None) -> None:
        """Rewrite NAME=value lines of the sandbox's predigol.env (None removes the line)."""
        lines = [
            ln for ln in self.env_file.read_text().splitlines() if ln.split("=", 1)[0] not in values
        ]
        lines += [f"{k}={v}" for k, v in values.items() if v is not None]
        self.env_file.write_text("\n".join(lines) + "\n")

    def set_docker(self, **state: object) -> None:
        self.docker_state.write_text(json.dumps(state))

    def docker(self) -> dict:
        return json.loads(self.docker_state.read_text())

    def rclone_calls(self) -> list[list[str]]:
        if not self.calls.exists():
            return []
        return [json.loads(ln)["argv"] for ln in self.calls.read_text().splitlines()]

    def env(self, **extra: str) -> dict[str, str]:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("RCLONE_", "BACKUP_", "PITR_", "FAKE_", "DOCKER_"))
        }
        env.update(
            PATH=f"{self.stubs}:{env['PATH']}",
            HOME=str(self.root / "home"),
            PREDIGOL_ENV_FILE=str(self.env_file),
            PREDIGOL_APP_ENV_FILE=str(self.root / "app.env"),
            PREDIGOL_DATA=str(self.data),
            RCLONE_STUB_ROOT=str(self.bucket_root),
            RCLONE_STUB_LOG=str(self.calls),
            RCLONE_CONFIG=str(self.root / "rclone.conf"),
            DOCKER_STUB_STATE=str(self.docker_state),
            REAL_DATE=shutil.which("date") or "/usr/bin/date",
        )
        env.update(self.extra_env)
        env.update(extra)
        return env

    def run(self, script: str, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(BIN / script), *args],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
