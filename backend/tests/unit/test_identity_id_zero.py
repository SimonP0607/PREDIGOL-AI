"""An unidentified person (provider id 0) never becomes an identity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from fbi.ingestion.identity import apply_people


class _Cur:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def __enter__(self) -> _Cur:
        return self

    def __exit__(self, *a: object) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append(params)

    def fetchone(self) -> tuple[int]:
        return (1,)


class _Conn:
    def __init__(self) -> None:
        self.cur = _Cur()

    def cursor(self, **_: object) -> _Cur:
        return self.cur


class _Person:
    def __init__(self, pid: int, name: str) -> None:
        self.provider_id, self.name, self.position = pid, name, None


def test_id_zero_is_skipped_and_counted() -> None:
    conn = _Conn()
    players = cast(Any, [_Person(0, "enrick reuperne"), _Person(7, "Real Player")])
    coaches = cast(Any, [_Person(0, "unknown coach")])
    rep = apply_people(cast(Any, conn), players, coaches, payload_hash="h", fetched_at=datetime.now(UTC))
    assert rep.skipped_no_id == 2
    assert rep.players_written == 1 and rep.coaches_written == 0
    assert [c[0] for c in conn.cur.calls] == [7]
