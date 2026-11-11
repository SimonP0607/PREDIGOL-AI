"""CI-007 - continuous deployment: the workflow that deploys by itself after a green CI and the script that decides what it may release."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "release"
SCRIPT = ROOT / "ci_auto_plan.sh"
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy-auto.yml"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t.invalid",
           "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": "/tmp"}


def git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def release_checkout(app: Path, part: str, files: dict[str, str], subject: str) -> None:
    """What the server holds: a repository whose HEAD is a release commit (tree = the part's folder)."""
    repo = app / part
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    commit(repo, files, subject)


class World:
    def __init__(self, tmp: Path) -> None:
        self.repo = tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        self.app = tmp / "app"

    def run(self, head: str = "HEAD") -> subprocess.CompletedProcess[str]:
        env = {**GIT_ENV, "PREDIGOL_APP_DIR": str(self.app)}
        return subprocess.run(["bash", str(SCRIPT), "local", head], cwd=self.repo, env=env, capture_output=True, text=True, check=False)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def both(c: int) -> dict[str, str]:
    return {"backend/app.py": f"b{c}\n", "web/app.ts": f"w{c}\n"}


def test_nothing_to_release_when_production_runs_this_commit(world: World) -> None:
    first = commit(world.repo, both(1), "one")
    release_checkout(world.app, "backend", {"app.py": "b1\n"}, f"release x: backend (monorepo {first[:12]})")
    release_checkout(world.app, "web", {"app.ts": "w1\n"}, f"release x: web (monorepo {first[:12]})")
    out = world.run()
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "PARTS=none"


def test_only_the_parts_that_changed_are_released(world: World) -> None:
    first = commit(world.repo, both(1), "one")
    release_checkout(world.app, "backend", {"app.py": "b1\n"}, f"release x: backend (monorepo {first[:12]})")
    release_checkout(world.app, "web", {"app.ts": "w1\n"}, f"release x: web (monorepo {first[:12]})")
    commit(world.repo, {"backend/app.py": "b2\n"}, "backend only")
    assert world.run().stdout.strip().splitlines()[-1] == "PARTS=backend"
    commit(world.repo, {"web/app.ts": "w2\n"}, "web too")
    assert world.run().stdout.strip().splitlines()[-1] == "PARTS=backend,web"
    commit(world.repo, {"docs/readme.md": "x\n"}, "docs do not count")
    assert world.run().stdout.strip().splitlines()[-1] == "PARTS=backend,web"


def test_it_refuses_when_production_was_released_from_outside_this_repository(world: World) -> None:
    commit(world.repo, both(1), "one")
    release_checkout(world.app, "backend", {"app.py": "other\n"}, "release ia-p3b: backend (monorepo b942bb539ba4)")
    release_checkout(world.app, "web", {"app.ts": "w1\n"}, "release x: web (monorepo b942bb539ba4)")
    out = world.run()
    assert out.returncode == 1 and "not in this repository" in out.stderr and "PARTS=" not in out.stdout


def test_it_refuses_when_main_does_not_contain_what_production_was_cut_from(world: World) -> None:
    base = commit(world.repo, both(1), "one")
    git(world.repo, "checkout", "-q", "-b", "side")
    side = commit(world.repo, {"backend/app.py": "side\n"}, "side work released from outside main")
    git(world.repo, "checkout", "-q", "main")
    commit(world.repo, {"backend/app.py": "b2\n"}, "main moves on")
    release_checkout(world.app, "backend", {"app.py": "side\n"}, f"release x: backend (monorepo {side[:12]})")
    release_checkout(world.app, "web", {"app.ts": "w1\n"}, f"release x: web (monorepo {base[:12]})")
    out = world.run()
    assert out.returncode == 1 and "does not contain" in out.stderr


def test_it_refuses_a_checkout_that_the_release_kit_did_not_cut(world: World) -> None:
    first = commit(world.repo, both(1), "one")
    release_checkout(world.app, "backend", {"app.py": "b1\n"}, "hand edited on the server")
    release_checkout(world.app, "web", {"app.ts": "w1\n"}, f"release x: web (monorepo {first[:12]})")
    out = world.run()
    assert out.returncode == 1 and "not cut by the release kit" in out.stderr


# ---- the workflow --------------------------------------------------------------------------------------------------------------------

def _wf() -> dict[Any, Any]:
    import yaml

    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_the_auto_workflow_runs_only_after_the_ci_of_main_and_only_when_switched_on() -> None:
    wf = _wf()
    triggers = wf.get(True, wf.get("on"))
    assert isinstance(triggers, dict) and list(triggers) == ["workflow_run"]
    assert triggers["workflow_run"]["workflows"] == ["Backend CI", "Web CI"] and triggers["workflow_run"]["branches"] == ["main"]
    condition = " ".join(str(_wf()["jobs"]["plan"]["if"]).split())
    for needed in ("github.ref == 'refs/heads/main'", "vars.AUTO_DEPLOY == 'true'", "workflow_run.conclusion == 'success'",
                   "workflow_run.event == 'push'", "head_repository.full_name == github.repository"):
        assert needed in condition, f"the plan job must require {needed} (no forks, no pull requests, a kill switch)"


def test_the_auto_workflow_holds_the_key_only_in_its_own_environment_and_never_interpolates_into_a_shell() -> None:
    wf = _wf()
    jobs = wf["jobs"]
    assert "environment" not in jobs["plan"] and "DEPLOY_SSH_KEY" not in str(jobs["plan"])
    assert jobs["release"]["environment"] == "production-auto" and jobs["release"]["needs"] == "plan"
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.DEPLOY_SSH_KEY") == 1 and "secrets.GITHUB_TOKEN" not in text
    assert re.search(r"group:\s*deploy-production", text), "it shares the queue of the manual Deploy: never two releases at once"
    for name, job in jobs.items():
        for step in job["steps"]:
            run = step.get("run")
            assert run is None or "${{" not in run, f"{name}/{step.get('name')}: values reach the shell through env, never through an expression"
    for verb in re.findall(r'ssh predigol-gh "(\w+)', text):
        assert verb in {"discard", "start", "status"}, verb
    assert "--owner-ok" not in text and "scp " not in text and "rsync" not in text


# ---- the clock of the release job (CI-019) -------------------------------------------------------------------------------------------
# A chain with its backup and its restore test outlasts four hours; GitHub cuts a job at six. The job has ONE clock: it waits for a busy
# server, follows its chain until the clock runs out, and when it does it ends RED saying the chain goes on. It never calls that a deploy.

GITHUB_JOB_LIMIT_MINUTES = 360


def _release_steps() -> dict[str, dict[str, Any]]:
    return {str(step.get("name")): step for step in _wf()["jobs"]["release"]["steps"]}


def test_the_release_job_has_one_clock_that_fits_under_the_limit_of_github() -> None:
    release = _wf()["jobs"]["release"]
    steps = _release_steps()
    names = list(steps)
    clock = steps["Reloj del trabajo (hasta cuándo puede seguir la cadena)"]
    found = re.search(r"\+ (\d+) \* 60 \)\)", clock["run"])
    assert clock["id"] == "clock" and found, "the clock is one number of minutes from the start of the job"
    minutes = int(found.group(1))
    assert minutes + 10 <= release["timeout-minutes"] < GITHUB_JOB_LIMIT_MINUTES, "the job says why it stops before GitHub kills it"
    assert names.index("Reloj del trabajo (hasta cuándo puede seguir la cadena)") < names.index("Llave de despliegue y huella del servidor")
    follow = steps["Arrancar la cadena y seguirla"]
    assert follow["env"]["DEADLINE"] == "${{ steps.clock.outputs.deadline }}" and "while (( $(date +%s) < DEADLINE ))" in follow["run"]
    assert "seq 1" not in follow["run"], "a fixed count of minutes ignores what the precheck already waited"
    waited = re.search(r'ci_precheck\.sh predigol-gh "\$KIT_NAME" (\d+) (\d+) ', next(s["run"] for n, s in steps.items() if n.startswith("Precheck")))
    assert waited, "the precheck states how long it waits for a busy server"
    tries, pause = int(waited.group(1)), int(waited.group(2))
    assert 30 * 60 <= tries * pause < minutes * 60 // 2, "long enough for a backup to end, short enough to leave the chain most of the clock"


def _follow(tmp_path: Path, statuses: list[str], deadline: str) -> tuple[subprocess.CompletedProcess[str], str, int]:
    """Runs the step that starts and follows the chain against a `ssh` that answers `start` and then the n-th status; `sleep` is short."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for i, text in enumerate(statuses, start=1):
        (tmp_path / f"s{i}").write_text(text, encoding="utf-8")
    (bindir / "ssh").write_text(
        '#!/usr/bin/env bash\necho "$2" >> "$FAKE/calls"\ncase "$2" in start*) exit 0 ;; esac\n'
        'n=$(cat "$FAKE/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$FAKE/n"\n'
        'f="$FAKE/s$n"; [ -f "$f" ] || f="$FAKE/s$(ls "$FAKE" | grep -c "^s[0-9]")"; cat "$f"\n',
        encoding="utf-8",
    )
    (bindir / "sleep").write_text(f"#!/usr/bin/env bash\nexec {shutil.which('sleep')} 0.3\n", encoding="utf-8")
    for tool in ("ssh", "sleep"):
        (bindir / tool).chmod(0o755)
    summary = tmp_path / "summary.md"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "FAKE": str(tmp_path), "KIT": "20261111T1247Z-auto-10d637d", "DEADLINE": deadline,
           "GITHUB_STEP_SUMMARY": str(summary)}
    script = _release_steps()["Arrancar la cadena y seguirla"]["run"]
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=False, timeout=60)
    calls = (tmp_path / "calls").read_text(encoding="utf-8").splitlines() if (tmp_path / "calls").exists() else []
    return out, summary.read_text(encoding="utf-8") if summary.exists() else "", len(calls)


def _in(seconds: int) -> str:
    return str(int(time.time()) + seconds)


def test_the_job_is_green_only_when_it_saw_the_chain_deploy(tmp_path: Path) -> None:
    out, summary, _ = _follow(tmp_path, ["STATE: running (step_backup)\n", "STATE: deployed 20261111T1247Z-auto-10d637d\nsmoke OK\n"], _in(30))
    assert out.returncode == 0 and "### Desplegado" in summary and "sigue en marcha" not in summary


def test_the_job_is_red_when_the_chain_stopped(tmp_path: Path) -> None:
    out, summary, _ = _follow(tmp_path, ["STATE: stopped at step_restore_test\n"], _in(30))
    assert out.returncode == 1 and "SE DETUVO" in summary and "### Desplegado" not in summary


def test_when_the_clock_runs_out_the_job_is_red_and_says_the_chain_goes_on(tmp_path: Path) -> None:
    out, summary, calls = _follow(tmp_path, ["STATE: running (step_backup)\n"], _in(2))
    assert out.returncode == 1, "a job that did not see the end never claims a deploy"
    assert "sigue en marcha" in out.stdout and "### La cadena sigue en marcha" in summary and "### Desplegado" not in summary
    assert "chain.log" in summary and 2 <= calls <= 12, "it followed the chain until its clock, not for a fixed count"


@pytest.mark.parametrize("bad", ["", "soon", "12", "1762870000; id"])
def test_a_clock_that_is_not_a_time_starts_nothing(tmp_path: Path, bad: str) -> None:
    out, _, calls = _follow(tmp_path, ["STATE: running\n"], bad)
    assert out.returncode == 1 and "bad deadline" in out.stdout and calls == 0, "the chain is not started without a clock to follow it"
