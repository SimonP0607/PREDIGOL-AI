"""PM-11-07 (IA-158) against a real database: the chronicle's C-13 sheet reads the documents the nightly pass wrote
(``analytics.stat_documents``) and tells, for every match of the season, the figure the team's statistics page serves
(``fbi.api.services.stats_profile``); ``python -m scripts.chronicle_stat_check check`` finds zero differences. Off, nothing is read."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.chronicle import inputs
from fbi.chronicle import stat_sheet as ss
from fbi.stats import data as sd
from fbi.stats import job
from scripts import chronicle_stat_check as check_script

from .conftest import Seed
from .test_stats_documents_db import T0, _league, _season

pytestmark = pytest.mark.integration

AT = T0 + timedelta(days=120, hours=1)


def _written(db: psycopg.Connection[Any], seed: Seed) -> tuple[int, list[int], int]:
    cs, ids, upcoming = _league(db, seed)
    job.write_season(db, sd.load_season(db, _season(db, cs)), 7, T0 + timedelta(days=120))
    return cs, ids, upcoming


def test_the_sheet_reads_the_profiles_document(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, ids, upcoming = _written(db, seed)
    sheet = ss.read(db, upcoming, home_id=ids[0], away_id=ids[1])
    assert set(sheet) == {"home", "away"}
    home = sheet["home"]
    assert (home.competition_season_id, home.scope, home.context) == (cs, "u10", "all")
    profile, computed_at, scope = check_script.profile_of(db, ids[0], cs)
    assert scope == "u10" and computed_at == home.computed_at
    xg = home.xg()
    assert xg is not None and (xg[0], xg[1]) == (profile["xg_for"], profile["xg_against"])
    assert inputs.sheet_of(db, upcoming, home_id=ids[0], away_id=ids[1], sheet=False) is None, "off: nothing is read"
    assert inputs.sheet_of(db, upcoming, home_id=ids[0], away_id=ids[1], sheet=True) == sheet


def test_a_team_without_a_document_in_the_season_has_no_sheet(db: psycopg.Connection[Any], seed: Seed) -> None:
    _cs, ids, upcoming = _written(db, seed)
    stranger = db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (987999, 'Sin documento') RETURNING id").fetchone()
    assert stranger is not None
    assert set(ss.read(db, upcoming, home_id=ids[0], away_id=int(stranger[0]))) == {"home"}


def test_zero_differences_on_every_match_of_the_season(db: psycopg.Connection[Any], seed: Seed) -> None:
    _written(db, seed)
    out = check_script.check(db, sample=500, days=400, at=AT)
    assert out["matches"] >= 90 and out["xg_facts"] == 2 * out["matches"] - out["sides_without_xg"]
    assert out["xg_facts"] > 0
    assert out["differences"] == 0, out["examples"]
