"""The synthetic journey's walk (plan UX, A2), against a recorded platform: the steps a reader takes, in order, the
match of today it opens, and what a failing step looks like - without a database or a network."""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from apps.worker import scheduler

from fbi.ops import synthetic
from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

CFG = synthetic.JourneyConfig(base_url="https://predigol.test", email="synthetic@predigol.test",
                              password="Synthetic-pass-2026!")
TODAY = date(2026, 10, 25)


def platform(*, fail: str | None = None, stage: str = "full", matches: list[dict[str, object]] | None = None,
             seen: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if fail == path:
            return httpx.Response(500, json={"status": "error"})
        if path == "/login":
            return httpx.Response(200, text="<!doctype html><html lang=\"es\"><body>Inicia sesión</body></html>")
        if path == "/api/v1/auth/login":
            assert request.headers["x-requested-with"] == "predigol"
            body = json.loads(request.content)
            ok = body == {"email": CFG.email, "password": CFG.password}
            return httpx.Response(200 if ok else 401, json={"stage": stage} if ok else {"status": "error"})
        if path == "/api/v1/matches":
            return httpx.Response(200, json={"status": "ok", "data": matches or []})
        return httpx.Response(204 if path == "/api/v1/auth/logout" else 200, json={"status": "ok"})

    return httpx.Client(base_url=CFG.base_url, transport=httpx.MockTransport(handler))


def test_the_reader_walk_in_order_with_the_match_of_today() -> None:
    seen: list[httpx.Request] = []
    steps = synthetic.walk(CFG, client=platform(matches=[{"id": 77}, {"id": 78}], seen=seen), today=TODAY)
    assert [s.name for s in steps] == ["page", "sign_in", "home", "matches_today", "match_center", "picks",
                                       "my_picks", "sign_out"]
    assert all(s.ok for s in steps)
    paths = [r.url.path for r in seen]
    assert "/api/v1/matches/77/center" in paths
    asked = next(r for r in seen if r.url.path == "/api/v1/matches")
    assert asked.url.params["date_from"] == asked.url.params["date_to"] == "2026-10-25"


def test_a_day_without_matches_skips_the_centre_without_failing() -> None:
    steps = synthetic.walk(CFG, client=platform(matches=[]), today=TODAY)
    assert "match_center" not in [s.name for s in steps] and all(s.ok for s in steps)


def test_a_failed_step_is_named_with_its_status_and_the_walk_still_signs_out() -> None:
    steps = synthetic.walk(CFG, client=platform(fail="/api/v1/picks"), today=TODAY)
    failed = [s for s in steps if not s.ok]
    assert [s.problem() for s in failed] == ["picks: HTTP 500"]
    assert steps[-1].name == "sign_out" and steps[-1].ok


@pytest.mark.parametrize(("stage", "fail", "first_problem"), [
    ("mfa", None, "sign_in: HTTP 200 (a sign-in step is still owed)"),
    ("full", "/login", "page: HTTP 500"),
])
def test_a_sign_in_that_does_not_finish_stops_the_walk(stage: str, fail: str | None, first_problem: str) -> None:
    steps = synthetic.walk(CFG, client=platform(stage=stage, fail=fail), today=TODAY)
    problems = [s.problem() for s in steps if not s.ok]
    assert problems[0] == first_problem
    if stage == "mfa":
        assert [s.name for s in steps] == ["page", "sign_in"], "nothing is visited without a finished sign-in"


def test_an_unreachable_platform_is_a_failed_step_never_an_exception() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(base_url=CFG.base_url, transport=httpx.MockTransport(down))
    steps = synthetic.walk(CFG, client=client, today=TODAY)
    assert [(s.name, s.ok, s.note) for s in steps] == [("page", False, "ConnectError"), ("sign_in", False, "ConnectError")]


def test_the_configuration_is_whole_or_absent_and_never_shows_the_password(tmp_path: Path) -> None:
    secret = tmp_path / "synthetic.pw"
    secret.write_text("From-a-file-2026!\n")
    env = {"FBI_SYNTHETIC_BASE_URL": "https://predigolai.com/", "FBI_SYNTHETIC_EMAIL": "synthetic@predigol.test",
           "FBI_SYNTHETIC_PASSWORD_FILE": str(secret)}
    cfg = synthetic.config_from_env(env)
    assert cfg is not None and cfg.base_url == "https://predigolai.com" and cfg.password == "From-a-file-2026!"
    assert "From-a-file" not in repr(cfg) and "synthetic@" not in repr(cfg)
    for missing in env:
        assert synthetic.config_from_env({k: v for k, v in env.items() if k != missing}) is None, missing
    assert synthetic.config_from_env({**env, "FBI_SYNTHETIC_BASE_URL": "predigolai.com"}) is None
    assert synthetic.config_from_env({**env, "FBI_SYNTHETIC_PASSWORD_FILE": str(tmp_path / "nope")}) is None


def test_the_worker_runs_it_every_15_minutes_bounded_and_known_to_the_watchdog() -> None:
    """main() cannot run in a unit test: the registration is read from the scheduler's source, as for the other
    jobs (a job the watchdog does not know stays "running" for ever after a restart)."""
    tree = ast.parse(Path(scheduler.__file__).read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_deadline" and isinstance(n.args[0], ast.Constant)
             and n.args[0].value == "synthetic_journey"]
    assert len(calls) == 1 and isinstance(calls[0].args[1], ast.Constant)
    assert calls[0].args[1].value == synthetic.JOB_TYPE == "synthetic_journey"
    assert synthetic.JOB_TYPE in scheduler.WORKER_JOB_TYPES and synthetic.JOB_TYPE in JOB_TIMEOUTS
    assert timeout_for(synthetic.JOB_TYPE).total_seconds() == 300
    assert synthetic.EVERY_MINUTES == 15
    source = Path(scheduler.__file__).read_text()
    assert "if synthetic_config() is not None:" in source, "off until the owner configures it"
