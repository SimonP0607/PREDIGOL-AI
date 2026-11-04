"""CI-007 - continuous deployment: the workflow that deploys by itself after a green CI and the script that decides what it may release."""

from __future__ import annotations

import re
import subprocess
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
