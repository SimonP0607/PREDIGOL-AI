"""IA-069 (plan piece AD-D05), without a database: what a line-up's content is, when two observations are the same arrival, the
watch's switch and budget, the report's figures, and that the watch writes only its own rows and is off by default."""

from __future__ import annotations

import ast
import asyncio
import itertools
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fbi.ingestion import lineup_watch
from fbi.ingestion.lineup_arrivals import ARRIVAL_HORIZON, lineup_content
from fbi.ingestion.lineup_timing import MatchTiming, overall, summarise
from fbi.ingestion.lineup_watch import (
    Budget,
    Due,
    WatchSettings,
    batches,
    provider_left,
    requests_per_day,
    run_watch_job,
)
from fbi.ops.run_watchdog import JOB_TIMEOUTS
from fbi.providers.api_football.details import LineupPlayerRef, LineupRef
from fbi.providers.quota import ReportedQuota

ROOT = Path(__file__).parents[2]
KO = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)


def _player(pid: int, *, starter: bool = True, number: int | None = None) -> LineupPlayerRef:
    return LineupPlayerRef(provider_player_id=pid, name=f"P{pid}", number=number if number is not None else pid % 99,
                           position="M", grid="2:1" if starter else None, is_starter=starter)


def _lineup(players: tuple[LineupPlayerRef, ...], *, formation: str | None = "4-3-3") -> LineupRef:
    return LineupRef(provider_fixture_id=1, provider_team_id=10, formation=formation, provider_coach_id=5,
                     coach_name="Coach", players=players)


ELEVEN = tuple(_player(100 + n) for n in range(11)) + tuple(_player(200 + n, starter=False) for n in range(7))


# ── content ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_same_lineup_in_another_order_is_the_same_content() -> None:
    a, b = lineup_content(_lineup(ELEVEN)), lineup_content(_lineup(tuple(reversed(ELEVEN))))
    assert a == b
    assert (a.starters, a.players, a.formation) == (11, 18, "4-3-3")
    assert re.fullmatch(r"[0-9a-f]{64}", a.content_hash) and re.fullmatch(r"[0-9a-f]{64}", a.starters_hash)


def test_a_corrected_starter_changes_both_hashes_and_a_shirt_number_only_the_content() -> None:
    base = lineup_content(_lineup(ELEVEN))
    swapped = list(ELEVEN)
    swapped[0], swapped[11] = _player(200, starter=True), _player(100, starter=False)
    corrected = lineup_content(_lineup(tuple(swapped)))
    assert corrected.content_hash != base.content_hash and corrected.starters_hash != base.starters_hash
    renumbered = lineup_content(_lineup((_player(100, number=77), *ELEVEN[1:])))
    assert renumbered.content_hash != base.content_hash and renumbered.starters_hash == base.starters_hash
    assert lineup_content(_lineup(ELEVEN, formation="4-4-2")).content_hash != base.content_hash


def test_a_player_listed_twice_counts_once_as_the_writer_stores_him() -> None:
    assert lineup_content(_lineup((*ELEVEN, ELEVEN[0]))) == lineup_content(_lineup(ELEVEN))


def test_the_arrivals_keep_the_late_post_match_read_and_not_the_history_backfill() -> None:
    assert timedelta(hours=26) < ARRIVAL_HORIZON <= timedelta(hours=48)


# ── the switch ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_watch_is_off_by_default_and_only_the_word_shadow_turns_it_on() -> None:
    assert WatchSettings.from_env({}) == WatchSettings() and not WatchSettings().enabled
    assert WatchSettings.from_env({"FBI_LINEUP_WATCH": " Shadow "}).enabled
    for word in ("on", "1", "true", "shadwo", "", "SHADOW-ON"):
        assert not WatchSettings.from_env({"FBI_LINEUP_WATCH": word}).enabled, word


def test_a_number_not_understood_or_out_of_bounds_falls_back_to_its_default() -> None:
    cfg = WatchSettings.from_env({"FBI_LINEUP_WATCH": "shadow", "FBI_LINEUP_WATCH_MINUTES": "0",
                                  "FBI_LINEUP_WATCH_DAILY_BUDGET": "60000", "FBI_LINEUP_WATCH_PER_RUN": "x",
                                  "FBI_LINEUP_WATCH_RESERVE": "-1"})
    assert (cfg.every_minutes, cfg.daily_budget, cfg.per_run, cfg.reserve) == (3, 1_200, 8, 6_000)
    cfg = WatchSettings.from_env({"FBI_LINEUP_WATCH_MINUTES": "5", "FBI_LINEUP_WATCH_DAILY_BUDGET": "600"})
    assert (cfg.every_minutes, cfg.daily_budget) == (5, 600)


class _NoDatabase:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the watch touched the database while off ({name})")


def test_off_the_pass_does_nothing_not_even_a_query() -> None:
    assert asyncio.run(run_watch_job(_NoDatabase(), cfg=WatchSettings())) is None  # type: ignore[arg-type]


# ── what is due and what today allows ────────────────────────────────────────────────────────────────────────────────


def test_batches_of_twenty_nearest_kickoff_first() -> None:
    due = [Due(i, 5000 + i, KO + timedelta(minutes=45 - i)) for i in range(45)]
    groups = batches(due)
    assert [len(g) for g in groups] == [20, 20, 5]
    assert groups[0][0].kickoff_at == min(d.kickoff_at for d in due)
    assert all(a.kickoff_at <= b.kickoff_at for g in groups for a, b in itertools.pairwise(g))
    assert batches([]) == []


def test_the_allowance_is_the_smallest_of_its_budget_and_what_is_left_above_the_floor() -> None:
    assert Budget(1_200, 100, 40_000, None, 9_000).allowance == 1_100
    assert Budget(1_200, 1_200, 40_000, None, 9_000).allowance == 0, "its own day is spent"
    assert Budget(1_200, 0, 9_004, None, 9_000).allowance == 4, "near our daily limit it stops"
    assert Budget(1_200, 0, 40_000, 9_002, 9_000).allowance == 2, "and near the provider's"
    assert Budget(1_200, 0, 5_000, 3_000, 9_000).allowance == 0, "never negative"
    assert Budget(1_200, 0, 40_000, None, 9_000).as_dict()["allowance"] == 1_200


def test_the_providers_count_counts_only_when_it_is_of_today() -> None:
    at = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    today = ReportedQuota(at - timedelta(minutes=5), 75_000, 52_000, 450, 400)
    assert provider_left(today, at=at) == 52_000
    assert provider_left(ReportedQuota(at - timedelta(days=1), 75_000, 1, None, None), at=at) is None
    assert provider_left(None, at=at) is None


def test_a_day_of_passes_costs_one_request_per_twenty_due_in_each_pass() -> None:
    assert requests_per_day([0, 1, 20, 21, 122]) == 0 + 1 + 1 + 2 + 7
    # the busiest 3-minute day measured (16-nov-2026, 30 days) asked 752: under the default daily budget
    assert 752 < WatchSettings().daily_budget < 6_000 * 0.25


# ── the report ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _match(fid: int, comp: int, minutes: float | None, *, channel: str = "detail_writer",
           changed: bool = False) -> MatchTiming:
    both = None if minutes is None else KO - timedelta(minutes=minutes)
    return MatchTiming(fid, KO, comp, f"Comp {comp}", "league", 0 if both is None else 2, both, both,
                       None if both is None else channel, changed)


def test_the_report_counts_per_competition_and_flags_a_small_sample() -> None:
    ms = [_match(1, 1, 30), _match(2, 1, 20, channel="lineup_watch"), _match(3, 1, -5), _match(4, 1, None),
          _match(5, 2, 60, changed=True)]
    rows = summarise(ms)
    first = rows[0]
    assert (first["competition_id"], first["played"], first["with_lineups"], first["before_kickoff"]) == (1, 4, 3, 2)
    assert first["median_min"] == 20.0 and first["first_by_watch"] == 1 and first["small_sample"] is True
    assert first["official"] is None, "no permitted source dates the official publication"
    assert first["p10_min"] is not None and first["p10_min"] < first["median_min"] < (first["p90_min"] or 0)
    assert rows[1]["starter_changed"] == 1
    total = overall(ms)
    assert (total["played"], total["with_lineups"], total["before_kickoff"], total["first_by_watch"]) == (5, 4, 3, 1)
    assert total["median_min"] == 25.0


# ── the wiring and the isolation ─────────────────────────────────────────────────────────────────────────────────────


def test_the_job_is_registered_in_its_own_loop_with_a_deadline_and_only_when_on() -> None:
    src = (ROOT / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")
    assert JOB_TIMEOUTS[lineup_watch.JOB] == timedelta(minutes=10)
    tree = ast.parse(src)
    sets = {t.id: ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)}
    assert "'lineup_watch'" in sets["OWN_LOOP_JOBS"] and "'lineup_watch'" in sets["WORKER_JOB_TYPES"]
    jobs = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_job" and any(k.arg == "id" and isinstance(k.value, ast.Constant)
                                                 and k.value.value == "lineup_watch" for k in n.keywords)]
    assert len(jobs) == 1 and "_deadline('lineup_watch', 'lineup_watch'" in ast.unparse(jobs[0])
    assert "if lineup_watch.enabled:" in src


def test_the_watch_writes_its_arrivals_and_nothing_the_product_reads() -> None:
    src = (ROOT / "src" / "fbi" / "ingestion" / "lineup_watch.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):  # the docstrings explain what it does not touch: only the code counts
        body = getattr(node, "body", None)
        if isinstance(body, list):
            kept = [n for n in body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                                            and isinstance(n.value.value, str))]
            setattr(node, "body", kept or [ast.Pass()])  # noqa: B010
    code = ast.unparse(tree)
    for forbidden in ("apply_fixture_details", "apply_fixtures_payload", "write_states", "INSERT INTO core.fixture_lineups ",
                      "UPDATE core.", "decision", "picks."):
        assert forbidden not in code, forbidden
    assert 'channel="lineup_watch"' in src


def test_the_migration_chains_on_0139_and_keeps_first_seen_at_by_trigger() -> None:
    text = (ROOT / "migrations" / "versions" / "0140_lineup_first_seen.py").read_text(encoding="utf-8")
    assert 'revision = "0140"' in text and 'down_revision = "0139"' in text
    assert "NEW.first_seen_at := OLD.first_seen_at" in text
    assert "BEFORE UPDATE OR DELETE ON core.fixture_lineup_arrivals" in text


@pytest.mark.parametrize("name", ["FBI_LINEUP_WATCH", "FBI_LINEUP_WATCH_MINUTES", "FBI_LINEUP_WATCH_DAILY_BUDGET",
                                  "FBI_LINEUP_WATCH_RESERVE", "FBI_LINEUP_WATCH_PER_RUN"])
def test_every_switch_is_in_the_owners_guide(name: str) -> None:
    guide = (ROOT / "docs" / "owner" / "IA_069_ALINEACION_A_TIEMPO.md").read_text(encoding="utf-8")
    assert f"`{name}`" in guide
