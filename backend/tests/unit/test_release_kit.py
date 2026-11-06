"""The release toolkit (deploy/release, plan CI/CD C3): the server-side scripts are templates, and a template that does not parse or that names a
token build_kit.sh does not fill would only fail on the server, in the middle of a release. These tests fail it here, in the CI."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2] / "deploy" / "release"
TEMPLATES = sorted((ROOT / "templates" / "server").glob("*"))
EXTRAS = sorted((ROOT / "extras").rglob("*.sh"))
TOKENS = {"__STAMP__", "__REL__", "__PARTS__", "__BE_FROM__", "__BE_WANT__", "__WEB_FROM__", "__WEB_WANT__", "__MODEL_FP__"}

GATE = ROOT / "templates" / "gate" / "predigol-gh-deploy"  # C4: the forced command of the GitHub deploy key (not a server template: it lives on the server for good)
GATE_SUITE = Path(__file__).resolve().parents[1] / "vps_shell" / "test_gh_deploy_gate.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def test_there_are_templates() -> None:
    names = {p.name for p in TEMPLATES}
    assert {"chain.sh", "step_deploy.sh", "step_precheck.sh", "step_backup.sh", "step_smoke.sh", "step_verify.sh", "quiet.sh"} <= names


@pytest.mark.parametrize("path", [*TEMPLATES, *EXTRAS, GATE, ROOT / "ci_ssh_setup.sh", ROOT / "ci_precheck.sh", ROOT / "build_kit.sh", ROOT / "ship.sh", ROOT / "gate.sh"], ids=lambda p: p.name)
def test_every_script_parses(path: Path) -> None:
    out = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr


def test_a_template_only_names_tokens_the_builder_fills() -> None:
    seen = {"__" + m.lstrip("_") for p in TEMPLATES for m in re.findall(r"__[A-Z_]+__", p.read_text(encoding="utf-8"))}  # backend___REL__ = backend_ + token
    assert seen <= TOKENS, seen - TOKENS
    builder = (ROOT / "build_kit.sh").read_text(encoding="utf-8")
    for token in seen:
        assert token in builder, f"build_kit.sh does not fill {token}"


def test_no_template_keeps_a_release_of_the_past() -> None:
    """A template that still says ia-p04, a stamp or a commit of the release it was cut from would deploy the wrong thing."""
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"ia-p04|\b2026\d{4}T\d{4}Z\b|\b[0-9a-f]{12}\b(?=\" \"(backend|web) checkout)", text), p.name


def test_the_chain_never_starts_a_deploy_without_the_owners_word() -> None:
    ship = (ROOT / "ship.sh").read_text(encoding="utf-8")
    assert "--owner-ok" in ship and "needs --owner-ok" in ship


def test_the_parts_reach_the_templates_as_words_not_as_a_comma_list() -> None:
    """The templates ask ``case " $PARTS " in *" backend "*``: a list written ``backend,web`` made the first real deploy say that the backend was
    not released (it stopped, nothing moved). The builder takes the commas out when it fills ``__PARTS__``."""
    build = (ROOT / "build_kit.sh").read_text(encoding="utf-8")
    assert "s|__PARTS__|${PARTS//,/ }|g" in build
    for p in TEMPLATES:
        text = p.read_text(encoding="utf-8")
        if "__PARTS__" in text:
            assert 'case " $PARTS " in' in text, f"{p.name} matches the parts some other way than the builder fills them"


@pytest.mark.skipif(shutil.which("jq") is None or shutil.which("tar") is None, reason="needs jq and tar")
def test_the_github_door_suite_passes() -> None:
    out = subprocess.run(["bash", str(GATE_SUITE)], capture_output=True, text=True, check=False, timeout=300)
    assert out.returncode == 0, out.stdout[-3000:] + out.stderr[-1000:]
    m = re.search(r"RESULT: (\d+) ok, (\d+) failed", out.stdout)
    assert m is not None and int(m.group(2)) == 0 and int(m.group(1)) >= 60, out.stdout[-500:]


def test_ship_has_a_gate_mode_that_still_needs_the_owners_word() -> None:
    ship = (ROOT / "ship.sh").read_text(encoding="utf-8")
    assert "--gate" in ship and "predigol-gh-deploy" in ship
    gate_block = ship.split("if (( GATE ))", 1)[1].split("\nfi\n", 1)[0]
    assert "(( OK )) || die" in gate_block, "in gate mode --start must still need --owner-ok"


# ---- C4: the deploy workflow and its CI-side helper ------------------------------------------------------------------------------------
WORKFLOW = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "deploy.yml"
SSH_SETUP = ROOT / "ci_ssh_setup.sh"


def _workflow() -> dict[Any, Any]:
    import yaml

    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_the_deploy_workflow_is_a_button_and_nothing_else() -> None:
    wf = _workflow()
    triggers = wf.get(True, wf.get("on"))  # YAML reads a bare `on` as the boolean True
    assert isinstance(triggers, dict) and list(triggers) == ["workflow_dispatch"], "deploy.yml must only run when a person presses the button"


def test_every_job_that_can_reach_the_server_waits_for_the_production_environment() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    for name, job in jobs.items():
        text = str(job)
        touches_server = "DEPLOY_SSH_KEY" in text or "predigol-gh" in text
        if touches_server:
            assert job.get("environment") == "production", f"job {name} uses the deploy key without the production environment (the owner's approval)"
    assert jobs["plan"].get("if") == "github.ref == 'refs/heads/main'", "only main can be released"
    assert "environment" not in jobs["plan"], "plan must not hold the key"
    assert jobs["go"].get("needs") == "prepare" and jobs["go"].get("if") == "inputs.mode == 'deploy'"


def test_the_secret_only_appears_in_the_environment_bound_steps() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("secrets.DEPLOY_SSH_KEY") == 2, "the key is read twice (prepare and go), nowhere else"
    assert "secrets.GITHUB_TOKEN" not in text and "github.token" in text


def test_no_run_step_interpolates_a_github_expression() -> None:
    jobs = _workflow()["jobs"]
    assert isinstance(jobs, dict)
    for jname, job in jobs.items():
        for step in job["steps"]:
            run = step.get("run")
            assert run is None or "${{" not in run, f"{jname}/{step.get('name')}: values reach the shell through env, never through ${{{{ }}}} in run (script injection)"


def test_the_workflow_follows_the_server_door_and_never_a_shell() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ship.sh --host predigol-gh" in text and "--gate" in text and "--owner-ok" not in text, "the owner's word is the approval, not a flag typed by CI"
    for verb in re.findall(r'ssh predigol-gh "(\w+)', text):
        assert verb in {"discard", "start", "status"}, verb
    assert "scp " not in text and "rsync" not in text


needs_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="needs ssh-keygen")


def _real_key(tmp_path: Path) -> tuple[str, str]:
    """A fresh ed25519 key without passphrase: its private text and its public line."""
    path = tmp_path / "k"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(path)], check=True)
    public = subprocess.run(["ssh-keygen", "-y", "-f", str(path)], capture_output=True, text=True, check=True).stdout.strip()
    return path.read_text(encoding="utf-8"), public


def _setup(home: Path, key: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "SSH_HOME": str(home), "DEPLOY_SSH_KEY": key, "DEPLOY_HOST": "203.0.113.5",
           "DEPLOY_KNOWN_HOSTS": "203.0.113.5 ssh-ed25519 AAAAHOSTKEY"}
    return subprocess.run(["bash", str(SSH_SETUP)], env=env, capture_output=True, text=True, check=False)


@needs_keygen
def test_ci_ssh_setup_writes_a_pinned_restricted_client_and_prints_no_secret(tmp_path: Path) -> None:
    key, _ = _real_key(tmp_path)
    secret_body = key.splitlines()[1]
    out = _setup(tmp_path / "home", key)
    assert out.returncode == 0, out.stderr
    assert secret_body not in out.stdout + out.stderr
    tmp_path = tmp_path / "home"
    ssh = tmp_path / ".ssh"
    cfg = (ssh / "config").read_text(encoding="utf-8")
    assert "Host predigol-gh" in cfg and "StrictHostKeyChecking yes" in cfg and "IdentitiesOnly yes" in cfg and "BatchMode yes" in cfg
    assert oct((ssh / "predigol_gh_deploy").stat().st_mode & 0o777) == "0o600"
    assert (ssh / "known_hosts_predigol").read_text(encoding="utf-8").startswith("203.0.113.5 ssh-ed25519")


def _mangled(key: str) -> dict[str, str]:
    """The ways a private key is known to arrive from a Windows paste or from a one-line secret field."""
    lines = key.strip().splitlines()
    return {
        "lf": key.strip(),
        "crlf": key.strip().replace("\n", "\r\n"),
        "utf8-bom": "\ufeff" + key.strip(),
        "bom-and-crlf": "\ufeff" + key.strip().replace("\n", "\r\n"),
        "one-line": " ".join(lines),
        "tabs": "\t".join(lines),
        "indented": "\n".join("  " + line for line in lines),
        "trailing-blank-lines": key.strip() + "\n\n  \n",
    }


@needs_keygen
@pytest.mark.parametrize("variant", list(_mangled("-----BEGIN X-----\nA\n-----END X-----")))
def test_ci_ssh_setup_straightens_a_key_that_arrived_mangled(tmp_path: Path, variant: str) -> None:
    """Every known mangling comes out as the exact file ssh-keygen wrote, so ssh can load it (CI-010: the first automatic deploys
    stopped at "error in libcrypto")."""
    key, public = _real_key(tmp_path)
    home = tmp_path / "home"
    assert _setup(home, _mangled(key)[variant]).returncode == 0
    written = home / ".ssh" / "predigol_gh_deploy"
    assert written.read_text(encoding="utf-8") == key
    loaded = subprocess.run(["ssh-keygen", "-y", "-f", str(written)], capture_output=True, text=True, check=False)
    assert loaded.stdout.strip() == public


@needs_keygen
def test_ci_ssh_setup_says_what_is_wrong_with_a_key_that_does_not_load_without_printing_it(tmp_path: Path) -> None:
    broken = "-----BEGIN OPENSSH PRIVATE KEY-----\nTOPSECRETGARBAGE\n-----END OPENSSH PRIVATE KEY-----"
    out = _setup(tmp_path, broken)
    assert out.returncode == 1
    assert "does not load" in out.stderr and "header=yes footer=yes" in out.stderr and "save DEPLOY_SSH_KEY again" in out.stderr
    assert "TOPSECRETGARBAGE" not in out.stdout + out.stderr


@needs_keygen
def test_ci_ssh_setup_reports_a_key_without_header_or_footer(tmp_path: Path) -> None:
    out = _setup(tmp_path, "just some text that is not a key")
    assert out.returncode == 1 and "header=no footer=no" in out.stderr
    assert "just some text" not in out.stdout + out.stderr


@pytest.mark.parametrize("missing", ["DEPLOY_SSH_KEY", "DEPLOY_HOST", "DEPLOY_KNOWN_HOSTS"])
def test_ci_ssh_setup_refuses_when_a_value_is_missing(tmp_path: Path, missing: str) -> None:
    env = {"PATH": "/usr/bin:/bin", "SSH_HOME": str(tmp_path), "DEPLOY_SSH_KEY": "k", "DEPLOY_HOST": "h", "DEPLOY_KNOWN_HOSTS": "h ssh-ed25519 A"}
    env[missing] = ""
    out = subprocess.run(["bash", str(SSH_SETUP)], env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 1 and missing in out.stderr


def test_ci_ssh_setup_refuses_a_host_with_options_in_it(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "SSH_HOME": str(tmp_path), "DEPLOY_SSH_KEY": "k", "DEPLOY_HOST": "h\n  ProxyCommand x", "DEPLOY_KNOWN_HOSTS": "h ssh-ed25519 A"}
    out = subprocess.run(["bash", str(SSH_SETUP)], env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 1 and not (tmp_path / ".ssh" / "config").exists()


@needs_keygen
def test_ci_ssh_setup_drops_windows_line_endings_from_the_key_and_the_host_line(tmp_path: Path) -> None:
    """The first rehearsal failed with `error in libcrypto`: the secret had been set from a Windows file (CRLF)."""
    key, _ = _real_key(tmp_path)
    env = {
        "PATH": "/usr/bin:/bin",
        "SSH_HOME": str(tmp_path / "home"),
        "DEPLOY_SSH_KEY": key.replace("\n", "\r\n"),
        "DEPLOY_HOST": "203.0.113.5",
        "DEPLOY_KNOWN_HOSTS": "203.0.113.5 ssh-ed25519 AAAAHOSTKEY\r",
    }
    out = subprocess.run(["bash", str(SSH_SETUP)], env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    ssh = tmp_path / "home" / ".ssh"
    assert b"\r" not in (ssh / "predigol_gh_deploy").read_bytes()
    assert b"\r" not in (ssh / "known_hosts_predigol").read_bytes()


# ---- C4: the precheck as CI runs it ------------------------------------------------------------------------------------------------------
PRECHECK = ROOT / "ci_precheck.sh"


def _fake_ssh(tmp_path: Path, answers: list[str]) -> dict[str, str]:
    """A `ssh` that answers with the n-th text of `answers` (the n-th call), so the loop can be driven without a server."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for i, text in enumerate(answers, start=1):
        (tmp_path / f"a{i}").write_text(text, encoding="utf-8")
    (bindir / "ssh").write_text(
        '#!/usr/bin/env bash\nn=$(cat "$FAKE/n" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$FAKE/n"\n'
        'f="$FAKE/a$n"; [ -f "$f" ] || f="$FAKE/a$(ls "$FAKE" | grep -c "^a[0-9]")"; cat "$f"\n'
        'grep -q "^NOT OK" "$f" && exit 2; exit 0\n',
        encoding="utf-8",
    )
    (bindir / "ssh").chmod(0o755)
    return {"PATH": f"{bindir}:/usr/bin:/bin", "FAKE": str(tmp_path)}


def _run_precheck(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(PRECHECK), "h", "20261103T1000Z-x", "4", "0"], env=env, capture_output=True, text=True, check=False, timeout=60)


def test_ci_precheck_passes_when_every_line_is_ok(tmp_path: Path) -> None:
    out = _run_precheck(_fake_ssh(tmp_path, ["OK: a\nPRECHECK: every line OK\n"]))
    assert out.returncode == 0 and "every line OK (try 1)" in out.stdout


def test_ci_precheck_waits_while_the_server_is_only_busy(tmp_path: Path) -> None:
    busy = "not quiet: pid 1\nNOT OK: the server is not quiet (the lines above say who)\nPRECHECK: 1 line(s) NOT OK\n"
    out = _run_precheck(_fake_ssh(tmp_path, [busy, busy, "OK: x\nPRECHECK: every line OK\n"]))
    assert out.returncode == 0 and "every line OK (try 3)" in out.stdout and out.stdout.count("only waits for somebody else") == 2


def test_ci_precheck_fails_at_once_on_a_line_waiting_does_not_fix(tmp_path: Path) -> None:
    bad = "NOT OK: backend checkout = abc, the package was cut from def\nPRECHECK: 1 line(s) NOT OK\n"
    out = _run_precheck(_fake_ssh(tmp_path, [bad]))
    assert out.returncode == 1 and "that waiting does not fix" in out.stdout and "only waits" not in out.stdout


def test_ci_precheck_gives_up_when_the_server_never_calms_down(tmp_path: Path) -> None:
    busy = "NOT OK: lock deploy is HELD by x\nPRECHECK: 1 line(s) NOT OK\n"
    out = _run_precheck(_fake_ssh(tmp_path, [busy]))
    assert out.returncode == 1 and "still not ready after 4 tries" in out.stdout


def test_ci_precheck_fails_when_the_precheck_does_not_reach_its_last_line(tmp_path: Path) -> None:
    out = _run_precheck(_fake_ssh(tmp_path, ["OK: something\n"]))
    assert out.returncode == 1 and "did not reach its last line" in out.stdout


def test_ci_precheck_waits_for_exactly_what_the_chain_waits_for() -> None:
    """The list of lines that mean 'wait' is copied from chain.sh; if one changes, the other must follow."""
    pattern = re.compile(r"WAITABLE='([^']+)'")
    chain = pattern.search((ROOT / "templates" / "server" / "chain.sh").read_text(encoding="utf-8"))
    ci = pattern.search(PRECHECK.read_text(encoding="utf-8"))
    assert chain is not None and ci is not None and chain.group(1) == ci.group(1)


def test_the_kit_takes_the_migration_head_from_the_chain_not_from_the_highest_number(
    tmp_path: Path,
) -> None:
    """A line numbered below what it hangs from (UX 0095 hangs from 0119) must not hide the head."""
    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "repo"
    versions = repo / "migrations" / "versions"
    versions.mkdir(parents=True)
    for name, rev, down in (
        ("0118_a", "0118", "0117"),
        ("0119_b", "0119", "0118"),
        ("0095_c", "0095", "0119"),
        ("0106_d", "0106", "0095"),
    ):
        (versions / f"{name}.py").write_text(f'revision = "{rev}"\ndown_revision = "{down}"\n')
    run = lambda *a: subprocess.run(  # noqa: E731
        [git, "-C", str(repo), *a], check=True, capture_output=True, text=True
    ).stdout.strip()
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "t")
    script = Path(__file__).resolve().parents[2] / "deploy" / "release" / "build_kit.sh"
    fn = re.search(r"^mig_num\(\) \{.*?^\}", script.read_text(), re.S | re.M)
    assert fn is not None
    out = subprocess.run(
        ["bash", "-c", f"{fn.group(0)}\nmig_num HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert out == "0106"
