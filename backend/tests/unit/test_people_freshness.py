"""People and squads in the dataset register: asked and answered with nothing is the provider's gap (UNAVAILABLE),
not a person or team we never read (UNKNOWN) - 5 Oct 2026: the 300 'never read' squads had all been asked twice."""

from datetime import UTC, datetime, timedelta

from fbi.truth.freshness import Freshness, _people, _squads

AT = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


def test_a_squad_asked_with_an_empty_answer_is_the_providers_gap() -> None:
    rows = [{"competition": "FA Cup", "season": 2026, "provider_team_id": 11936, "squad_checked_at": None,
             "asked_at": AT - timedelta(days=1), "asked_results": 0},
            {"competition": "FA Cup", "season": 2026, "provider_team_id": 1, "squad_checked_at": None,
             "asked_at": None, "asked_results": None},
            {"competition": "FA Cup", "season": 2026, "provider_team_id": 2, "squad_checked_at": None,
             "asked_at": AT - timedelta(days=20), "asked_results": 0},
            {"competition": "FA Cup", "season": 2026, "provider_team_id": 3, "squad_checked_at": AT - timedelta(days=2),
             "asked_at": AT - timedelta(days=2), "asked_results": 1}]
    d = _squads(rows, AT)
    assert d.counts[Freshness.UNAVAILABLE.value] == 1
    assert d.counts[Freshness.UNKNOWN.value] == 2, "never asked, or asked too long ago to count"
    assert d.counts[Freshness.FRESH.value] == 1


def test_people_asked_by_id_without_a_profile_are_the_providers_gap() -> None:
    [players, coaches] = _people([
        {"dataset": "players", "total": 100, "profiled": 80, "old_profile": 5, "known": 99, "provider_none": 10},
        {"dataset": "coaches", "total": 50, "profiled": 20, "old_profile": 0, "known": 50, "provider_none": 25}])
    assert (players.counts[Freshness.UNAVAILABLE.value], players.counts[Freshness.UNKNOWN.value]) == (10, 5)
    assert (coaches.counts[Freshness.UNAVAILABLE.value], coaches.counts[Freshness.UNKNOWN.value]) == (25, 5)
