"""The identity audit judges national flags by PrediGol's own classification (core.team_kind) once it exists, and
coach careers by whether the coachs feed asked - not by the provider's flag or a missing table."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from fbi.truth.v2.identity import evidence

T0 = datetime(2026, 10, 4, tzinfo=UTC)


def keys(checks: Mapping[str, list[dict[str, Any]]]) -> set[str]:
    return {e.key for e in evidence(checks, {}, T0)}


def test_national_flags_follow_the_classification_not_the_providers_flag() -> None:
    provider_disagrees: dict[str, list[dict[str, Any]]] = {"national_flags": [{"club_rows_in_national_comps": 61, "national_rows_in_club_comps": 3}]}
    assert "identity:national_flags" in keys(provider_disagrees), "no classification yet: the flags are the evidence"
    classified = {**provider_disagrees, "team_kind": [{"teams": 8165, "national_playing_club": 0,
                                                       "club_playing_only_national": 0, "differs_from_provider": 64}]}
    assert "identity:national_flags" not in keys(classified)
    broken = {**provider_disagrees, "team_kind": [{"teams": 8165, "national_playing_club": 2,
                                                   "club_playing_only_national": 0}]}
    assert "identity:national_flags" in keys(broken)


def test_coach_careers_are_a_gap_only_until_the_feed_asks() -> None:
    assert "identity:coach_career" in keys({"coach_career_stored": [{"coaches": 4571, "teams_asked": 0}]})
    assert "identity:coach_career" not in keys({"coach_career_stored": [{"coaches": 4571, "teams_asked": 120}]})


def test_a_completed_identity_run_clears_the_entries_it_writes_in_area_coaches_too() -> None:
    """identity:coach_career is an area-coaches entry; clearing only area identity left it OPEN."""
    from scripts.audit_data_truth import clearing_scopes

    assert clearing_scopes("identity") == [("identity", "identity:"), ("coaches", "identity:")]
    assert clearing_scopes("fields") == [("normalization", "normalization:")]
    assert clearing_scopes("fixtures") == [("fixtures", "fixtures:")]
