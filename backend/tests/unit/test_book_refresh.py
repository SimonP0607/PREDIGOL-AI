"""The book refreshes, without a database (plan Cuotas, BE-011; ``fbi.odds.book_refresh``): which points they ask, when a match
is due, how much today allows, that they ask exactly the matches the capture asks, that one job name ties them to the extractor's
skip and the ledger's claim, and that nothing runs while the switches are off."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fbi.core.config.odds import OddsCaptureSettings
from fbi.ingestion.ledger import BOOK_REFRESH_JOB
from fbi.odds import book_refresh
from fbi.odds.book_refresh import Budget, Candidate, plan, provider_left, refresh_only_points
from fbi.odds.quote_extract import SKIPPED_JOB
from fbi.ops.run_watchdog import JOB_TIMEOUTS
from fbi.providers.quota import ReportedQuota

KO = datetime(2026, 11, 14, 15, 0, tzinfo=UTC)
WINDOWS = (4320, 2880, 1440, 720, 360, 180)
POINTS = refresh_only_points(WINDOWS)
ROOT = Path(__file__).parents[2]


def candidate(fid: int = 1, *, kickoff: datetime = KO, last: datetime | None = None, priced: bool = True,
              status: str = "NS") -> Candidate:
    return Candidate(fixture_id=fid, provider_fixture_id=9000 + fid, kickoff_at=kickoff, status_short=status,
                     last_asked=last, priced=priced)


def due(minutes_before: float, **kw: object) -> list[int]:
    return [t.point for t in plan([candidate(**kw)], at=KO - timedelta(minutes=minutes_before), points=POINTS,  # type: ignore[arg-type]
                                  tolerance=45)]


def test_the_refreshes_never_ask_a_model_window() -> None:
    assert len(POINTS) == 24 and not set(POINTS) & set(WINDOWS)
    assert POINTS[:2] == (4140, 3960) and POINTS[-6:] == (300, 240, 120, 60, 30, 10)


def test_a_point_is_due_while_its_band_is_open_and_done_once_asked_after_its_instant() -> None:
    assert due(300) == [300] and due(256) == [300] and due(250) == [], "T-300's band is 255 to 300"
    assert due(25) == [30] and due(8) == [10] and due(3) == [10]
    assert due(1) == [], "the last two minutes are never asked"
    assert due(250, last=KO - timedelta(minutes=241)) == [], "the band of T-240 is not open yet at T-250"
    assert due(230, last=KO - timedelta(minutes=241)) == [240], "asked a minute before the point: due"
    assert due(230, last=KO - timedelta(minutes=240)) == [], "asked at the point (by a refresh or the capture): done"
    assert due(100) == [120] and due(100, last=KO - timedelta(minutes=110)) == []


def test_only_a_match_the_provider_priced_and_that_has_not_started_is_asked() -> None:
    assert due(300, priced=False) == []
    assert due(300, status="1H") == [] and due(300, status="FT") == []
    assert due(300, status="PST") == [300] and due(300, status="TBD") == [300]


def test_the_nearest_to_kick_off_go_first() -> None:
    at = KO - timedelta(minutes=100)
    tasks = plan([candidate(1, kickoff=KO + timedelta(minutes=400)), candidate(2),
                  candidate(3, kickoff=KO + timedelta(minutes=140)), candidate(4, kickoff=KO + timedelta(minutes=600))],
                 at=at, points=POINTS, tolerance=45)
    assert [(t.fixture_id, t.point) for t in tasks] == [(2, 120), (3, 240), (1, 540)], "T-700 is between two bands"
    assert tasks[0].minutes_to_ko == 100


def budget(*, spent: int = 1000, ours: int = 40_000, provider: int | None = 50_000) -> Budget:
    return Budget(daily_budget=8000, spent_today=spent, ours_left=ours, provider_left=provider, floor=7000)


def test_the_budget_is_the_tightest_of_its_own_ours_and_the_providers() -> None:
    assert budget().allowance == 7000, "its own budget"
    assert budget(ours=9000).allowance == 2000, "our quota above the floor"
    assert budget(provider=7500).allowance == 500, "the provider's count"
    assert budget(provider=None).allowance == 7000, "an unknown count limits nothing"
    assert budget(ours=6000).allowance == 0, "under the floor: cut, never negative"
    assert budget(spent=9000).allowance == 0


def test_the_providers_count_counts_only_on_its_own_day() -> None:
    today = ReportedQuota(KO, 75_000, 51_000, 450, 300)
    assert provider_left(today, at=KO + timedelta(hours=1)) == 51_000
    assert provider_left(today, at=KO + timedelta(days=1)) is None, "yesterday's count says nothing of today"
    assert provider_left(None, at=KO) is None
    assert provider_left(ReportedQuota(KO, None, None, 450, 300), at=KO) is None


def _where(sql: str) -> list[str]:
    """The JOIN and WHERE lines of a query, placeholders and spacing normalised."""
    body = sql[sql.index("FROM core.fixtures f"):]
    body = body[:body.index("ORDER BY")]
    lines = [re.sub(r"%\(\w+\)s|%s", "?", " ".join(line.split())) for line in body.splitlines()]
    return [line for line in lines if line]


def test_the_refreshes_ask_exactly_the_matches_the_capture_asks() -> None:
    """The plan's rule: "the same eligibility as odds_capture / scripts/capture_odds.py". A change of one without the other fails
    here."""
    from scripts.capture_odds import UPCOMING_SQL

    capture, refresh = _where(UPCOMING_SQL), _where(book_refresh.ELIGIBLE_SQL)
    assert capture == refresh, (capture, refresh)


def test_one_job_name_ties_the_refreshes_to_the_extractors_skip_and_the_ledgers_claim() -> None:
    assert book_refresh.JOB == BOOK_REFRESH_JOB == SKIPPED_JOB == "odds_book_refresh"
    assert JOB_TIMEOUTS[book_refresh.JOB] == timedelta(minutes=20)
    scheduler = (ROOT / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")
    assert '"odds_book_refresh"' in scheduler and "book_refresh_enabled" in scheduler


class _NoDatabase:
    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the job touched the connection ({name}) while off")


def test_with_the_switches_off_the_job_does_not_even_ask_the_database() -> None:
    assert asyncio.run(book_refresh.run_refresh_job(_NoDatabase(), "/nowhere", enabled=False)) is None  # type: ignore[arg-type]
    assert asyncio.run(book_refresh.run_refresh_job(_NoDatabase(), "/nowhere")) is None  # type: ignore[arg-type]


@pytest.mark.parametrize(("book", "refresh", "on"), [("0", "0", False), ("1", "0", False), ("0", "1", False),
                                                    ("1", "1", True), ("on", "yes", True), ("1", "maybe", False)])
def test_the_refreshes_run_only_with_the_book_on_too(book: str, refresh: str, on: bool) -> None:
    assert OddsCaptureSettings(odds_book=book, odds_book_refresh=refresh).book_refresh_enabled is on


def test_the_defaults_are_off_with_their_budget_and_floor() -> None:
    cfg = OddsCaptureSettings(_env_file=None)  # type: ignore[call-arg]
    assert cfg.odds_book_refresh == "0" and cfg.book_refresh_enabled is False
    assert cfg.odds_book_daily_budget == 8000 and cfg.odds_book_reserve == 6000


def test_the_capture_settings_say_what_production_measured_and_keep_the_model_windows() -> None:
    doc = " ".join((OddsCaptureSettings.__doc__ or "").split())
    for measured in ("1,578 matches", "median 103 minutes", "84 %", "AFTER our T-180 capture"):
        assert measured in doc, measured
    assert "returns the same row and burns quota" not in doc, "the contradicted premise is gone"
    with pytest.raises(ValueError, match="below 180 minutes"):
        OddsCaptureSettings(odds_prematch_windows="4320,120")
    assert OddsCaptureSettings(_env_file=None).prematch_windows == list(WINDOWS)  # type: ignore[call-arg]


def test_the_owner_guide_says_what_the_code_does() -> None:
    guide = " ".join((ROOT / "docs" / "owner" / "CUOTAS_REFRESCOS_Y_API_BE011.md").read_text(encoding="utf-8").split())
    cfg = OddsCaptureSettings(_env_file=None)  # type: ignore[call-arg]
    for needed in ("FBI_ODDS_BOOK_REFRESH", "FBI_ODDS_BOOK_DAILY_BUDGET", "FBI_ODDS_BOOK_RESERVE", "FBI_ODDS_EXPLORER",
                   "0129", "market.book_asks", "raw.provider_reported_quota", "odds_book_refresh", "/admin/odds/health",
                   "mc9a7bec97ca", str(cfg.odds_book_daily_budget), str(cfg.odds_book_reserve), "alembic downgrade 0128"):
        assert needed in guide, needed
