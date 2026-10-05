"""The audit's player profile check: a field the provider's profile does not have is its gap, not ours."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fbi.truth.findings import Kind, Severity, Tally
from fbi.truth.internal import player_profiles


class FakeConn:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    def cursor(self, **_: Any) -> FakeConn:
        return self

    def __enter__(self) -> FakeConn:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, *_: Any) -> None:
        return None

    def fetchone(self) -> dict[str, Any]:
        return self.row


def test_a_profile_read_without_a_birth_date_is_the_providers_gap() -> None:
    row = {"appeared": 100, "known": 100, "with_birth_date": 60, "with_nationality": 70, "with_height": 50,
           "asked_birth_date": 38, "asked_nationality": 30, "asked_height": 50}
    t = Tally("players")
    player_profiles(FakeConn(row), datetime(2026, 10, 5, tzinfo=UTC), t)  # type: ignore[arg-type]
    found = {(f.field, f.kind, f.severity) for f in t.findings}
    assert found == {("birth_date", Kind.MISSING_IN_DB, Severity.MEDIUM),     # 2 never asked: ours
                     ("birth_date", Kind.PROVIDER_LAG, Severity.INFO),        # 38 asked: the provider's
                     ("nationality", Kind.PROVIDER_LAG, Severity.INFO),       # 30 asked, 0 left: nothing of ours
                     ("height_cm", Kind.PROVIDER_LAG, Severity.INFO)}
    [ours] = [f for f in t.findings if f.kind is Kind.MISSING_IN_DB]
    assert ours.note == "2 whose profile (/players/profiles) was never read"
    assert (t.checked, t.matched) == (100, 98)
