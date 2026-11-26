"""RP-6.1 against a real database: what Intelligence reads of every team document equals what C-13 serves for the same entity, scope and
context, and a document written after the cut-off is not read."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import psycopg
import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.stats_profile import StatsContext, StatsScope
from fbi.api.services import stats_profile
from fbi.stats import data as sd
from fbi.stats import job
from fbi.stats import reading as rd

from .conftest import Seed
from .test_stats_documents_db import T0, _league, _season

pytestmark = pytest.mark.integration


def _written(db: psycopg.Connection[Any], seed: Seed) -> tuple[int, list[int]]:
    cs, ids, _ = _league(db, seed)
    job.write_season(db, sd.load_season(db, _season(db, cs)), 7, T0 + timedelta(days=120))
    return cs, ids


def test_every_team_figure_equals_what_c13_serves(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, ids = _written(db, seed)
    at = T0 + timedelta(days=120, hours=1)
    checked = 0
    for team in ids[:4]:
        for scope, context in (("season", "all"), ("u10", "all"), ("u5", "home"), ("season", "away")):
            try:
                served = stats_profile.build_team(db, team, season=cs, scope=cast(StatsScope, scope), context=cast(StatsContext, context),
                                                  at=at).entities[0]
            except Exception:
                assert rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope=scope, context=context).status == "no_document"
                continue
            doc = rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope=scope, context=context, as_of=at)
            assert doc.status == "ok" and not isinstance(served.team, Missing)
            assert doc.calc_version == served.calc_version and doc.computed_at == served.computed_at
            assert [r.key for r in doc.readings] == [f.key for f in served.team.figures]
            for r, f in zip(doc.readings, served.team.figures, strict=True):
                assert r.matches_with_data == f.matches_with_data
                assert r.value == (None if isinstance(f.value, Missing) else f.value), (team, scope, context, r.key)
                checked += 1
    assert checked > 100


def test_a_document_written_after_the_cutoff_is_not_read_and_a_missing_one_says_so(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, ids = _written(db, seed)
    written = T0 + timedelta(days=120)
    before = rd.read(db, kind="team", entity_id=ids[0], competition_season_id=cs, scope="season", as_of=written - timedelta(minutes=1))
    assert before.status == "after_cutoff" and before.readings == ()
    assert rd.read(db, kind="team", entity_id=ids[0], competition_season_id=cs, scope="season", as_of=written).status == "ok"
    gone = rd.read(db, kind="team", entity_id=ids[0], competition_season_id=cs, scope="u20", context="home")
    assert gone.status == "no_document" and gone.readings == ()
