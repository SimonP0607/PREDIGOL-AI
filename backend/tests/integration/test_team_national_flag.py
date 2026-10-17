"""A team nobody has described is not thereby a club.

core.teams.is_national was NOT NULL DEFAULT false, and a team can enter the
database from two places. /teams says whether a side is a national team. A
FIXTURE payload carries only an id and a name - and the default then asserted
"club" about five teams nobody had described. Four of the five were national
youth sides: South Africa U23, Luxembourg U19, Montenegro U19, Spain U20.

That is the same defect as "Friendlies Clubs" carrying an Elo weight of 0.90.
The competition scope and the history weighting both read this flag, so a wrong
value here does not stay here.
"""

from __future__ import annotations

import psycopg
import pytest

from fbi.providers.api_football.details import iter_teams
from tests.integration.conftest import Seed


def teams_payload(national: object) -> dict[str, object]:
    """One /teams entry, with whatever the provider said about `national`."""
    return {
        "response": [
            {
                "team": {
                    "id": 10195,
                    "name": "South Africa U23",
                    "code": None,
                    "country": "South-Africa",
                    "founded": None,
                    "national": national,
                    "logo": "",
                },
                "venue": {"id": None, "name": None},
            }
        ]
    }


def test_the_provider_saying_national_is_believed() -> None:
    assert next(iter(iter_teams(teams_payload(True)))).is_national is True


def test_the_provider_saying_club_is_believed() -> None:
    assert next(iter(iter_teams(teams_payload(False)))).is_national is False


@pytest.mark.parametrize("missing", [None, "", 0, "true"])
def test_the_provider_not_saying_leaves_it_unknown(missing: object) -> None:
    """It used to come out False. A non-boolean is not a boolean, and guessing
    which one it meant is how a national team becomes a club."""
    assert next(iter(iter_teams(teams_payload(missing)))).is_national is None


def test_a_team_created_from_a_fixture_payload_claims_nothing(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The path that produced the five rows: an id and a name, with the column's
    old default supplying an answer nobody had given."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO core.teams (provider_team_id, name) VALUES (999001, 'x') "
            "RETURNING is_national"
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] is None


def test_the_scope_evidence_counts_unknown_separately(
    db: psycopg.Connection, seed: Seed
) -> None:
    """The competition scope reads this flag, so it has to be able to say how
    many of the teams it looked at were simply never described - rather than
    folding them into the club count and resolving a World Cup as club football,
    which is a mistake this project has already made once."""
    from fbi.catalog.scopes import EVIDENCE_SQL

    assert "unknown_seen" in EVIDENCE_SQL
    assert "is_national IS NULL" in EVIDENCE_SQL
