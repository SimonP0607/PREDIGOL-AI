"""IA-015: an item of the provider's injury report stands while the latest report lists it, however long ago it was first listed.

The history of the report (``core.player_availability_obs``) writes only what CHANGES: an unchanged answer writes nothing, so the item the
collector builds from it is dated by the FIRST time the entry was seen. The old rule outdated every item retrieved more than ``CHECK_MARGIN``
(2 h) before the latest check of the season's list - and the list is re-read every 4 h, so an absence that still stood was dropped from the AI
packet at the first re-read. Now the latest report decides (``classify(provider_listed=...)``); held on the pure function.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.ai.evidence import CHECK_MARGIN, ProviderListing, Row, classify, provider_listing

AT = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=20)
FIXTURE = 1
TEAM = 10
KNEE = ("Missing Fixture", "Knee Injury")
DOUBT = ("Questionable", "Muscle Injury")


def provider_item(i: int, player: int, what: tuple[str, str] = KNEE, *, hours_ago: float = 6, kind: str = "injury") -> Row:
    """An item of the provider's report, as ``collect_provider`` stores it: no publication date, retrieved when the entry was first listed."""
    retrieved = AT - timedelta(hours=hours_ago)
    return Row(i, FIXTURE, TEAM, player, f"player {player}", kind, "provider", "provider", None, "out", None, retrieved,
               f"absence:{FIXTURE}:{player}", "PROBABLE", {"player_name": f"Player {player}", "absence_type": what[0], "reason": what[1],
                                                            "assertion": "out"})


def listing(player: int, what: tuple[str, str] = KNEE) -> ProviderListing:
    return provider_listing(FIXTURE, player, *what)


def decide(rows: list[Row], *, checked_minutes_ago: float = 10, listed: set[ProviderListing] | None) -> dict[int, tuple[str, str]]:
    return dict(classify(rows, kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=AT - timedelta(minutes=checked_minutes_ago),
                         provider_listed=listed))


def test_an_absence_still_listed_six_hours_after_it_was_first_seen_keeps_its_status() -> None:
    """Listed 6 h ago, the list re-read 10 min ago with him still on it: not outdated."""
    out = decide([provider_item(1, 9001, hours_ago=6)], listed={listing(9001)})
    assert out[1] == ("PROBABLE", "the data provider's report"), "the latest report still lists him"


def test_an_absence_the_latest_report_no_longer_lists_is_outdated() -> None:
    out = decide([provider_item(1, 9001, hours_ago=6)], listed=set())
    assert out[1] == ("OUTDATED", "no longer in the provider's latest injury report")


def test_it_does_not_depend_on_how_old_the_item_is() -> None:
    """Cleared minutes after he was listed is still cleared; listed for days and still on the list still stands."""
    just_cleared = decide([provider_item(1, 9001, hours_ago=0.5)], listed=set())
    assert just_cleared[1][0] == "OUTDATED", "inside the old margin, but the report no longer names him"
    for_days = decide([provider_item(1, 9001, hours_ago=72, kind="suspension")], listed={listing(9001)})
    assert for_days[1][0] == "PROBABLE"


def test_a_changed_type_or_reason_outdates_the_old_entry_and_keeps_the_new_one() -> None:
    """A doubt that became a knee injury: the doubt is no longer on the list, the injury is."""
    out = decide([provider_item(1, 9002, DOUBT, hours_ago=10), provider_item(2, 9002, KNEE, hours_ago=6)], listed={listing(9002, KNEE)})
    assert out[1][0] == "OUTDATED" and out[2][0] == "PROBABLE"


def test_only_the_cleared_player_goes_and_the_entry_is_of_this_match() -> None:
    rows = [provider_item(1, 9001), provider_item(2, 9002, DOUBT, kind="doubtful")]
    out = decide(rows, listed={listing(9002, DOUBT)})
    assert (out[1][0], out[2][0]) == ("OUTDATED", "PROBABLE")
    other_match = {provider_listing(FIXTURE + 1, 9001, *KNEE)}
    assert decide([provider_item(1, 9001)], listed=other_match)[1][0] == "OUTDATED", "listed for another match is not listed for this one"


def test_without_a_check_of_the_list_nothing_is_outdated_by_it() -> None:
    out = classify([provider_item(1, 9001)], kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None, provider_listed=set())
    assert out[1][0] == "PROBABLE", "nobody asked for the list: it cannot have dropped him"


def test_the_other_rules_are_unchanged() -> None:
    """A confirmed starter is not absent, whatever the report still says; a web report is not judged by the provider's list."""
    starter = classify([provider_item(1, 9001)], kickoff=KO, at=AT, lineup_starters={TEAM: {9001}},
                       absences_checked_at=AT - timedelta(minutes=10), provider_listed={listing(9001)})
    assert starter[1] == ("OUTDATED", "the player is in the confirmed starting line-up")
    web = Row(5, FIXTURE, TEAM, 9003, "player 9003", "injury", "web", "media", "marca.com", "out", AT - timedelta(hours=6),
              AT - timedelta(hours=6), "s5", "PROBABLE", {})
    assert decide([web], listed=set())[5][0] == "PROBABLE"


def test_a_caller_that_does_not_know_the_list_keeps_the_margin() -> None:
    """``provider_listed=None``: the rule it always had (the only caller with the list, ``collect_provider``, passes it)."""
    beyond = CHECK_MARGIN + timedelta(minutes=30)
    item = provider_item(1, 9001, hours_ago=beyond.total_seconds() / 3600)
    assert decide([item], checked_minutes_ago=0, listed=None)[1][0] == "OUTDATED"
    assert decide([provider_item(1, 9001, hours_ago=1)], checked_minutes_ago=0, listed=None)[1][0] == "PROBABLE"
