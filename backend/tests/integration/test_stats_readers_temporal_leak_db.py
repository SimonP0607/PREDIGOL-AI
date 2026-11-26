"""RP-13.2 (leaks, the part that needs no model): every reader of the statistics of RP-6.1 to RP-6.3 is asked for a moment BEFORE the documents were
written, over a real season, and none of them hands over a figure, a trend, a fact or a cut. One minute later - the moment of writing - every one of
them reads. The same loop over all the teams, scopes and contexts that have a document, so a reader added later that forgets the cut-off fails here."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.stats import cuts, facts, job
from fbi.stats import data as sd
from fbi.stats import reading as rd

from .conftest import Seed
from .test_stats_documents_db import T0, _league, _season

pytestmark = pytest.mark.integration

COMBOS = (("season", "all"), ("season", "home"), ("season", "away"), ("u10", "all"), ("u5", "all"))


def test_no_reader_of_the_statistics_hands_over_the_future(
    db: psycopg.Connection[Any], seed: Seed
) -> None:
    cs, ids, _ = _league(db, seed)
    written = T0 + timedelta(days=120)
    job.write_season(db, sd.load_season(db, _season(db, cs)), 7, written)
    before, at = written - timedelta(minutes=1), written
    seen_ok = seen_refused = 0
    for team in ids[:6]:
        for scope, context in COMBOS:
            early = rd.read(
                db,
                kind="team",
                entity_id=team,
                competition_season_id=cs,
                scope=scope,
                context=context,
                as_of=before,
            )
            now = rd.read(
                db,
                kind="team",
                entity_id=team,
                competition_season_id=cs,
                scope=scope,
                context=context,
                as_of=at,
            )
            if now.status != "ok":
                continue
            assert early.status == "after_cutoff", (team, scope, context)
            assert (
                early.readings == ()
                and early.trends == ()
                and early.document_id is None
                and early.computed_at is None
            )
            assert early.citation(now.readings[0].key) is None, "a refused document cites nothing"
            assert facts.facts_of(early, min_sample=1) == (
                [],
                [{"team_id": team, "key": None, "reason": facts.NO_DOCUMENT}],
            )
            seen_ok += 1
            seen_refused += 1
        early_cuts = cuts.read_team_cuts(
            db, team_id=team, competition_season_id=cs, scope="season", as_of=before
        )
        now_cuts = cuts.read_team_cuts(
            db, team_id=team, competition_season_id=cs, scope="season", as_of=at
        )
        for cut_early, cut_now in (
            (early_cuts.home, now_cuts.home),
            (early_cuts.away, now_cuts.away),
        ):
            assert cut_early.sample == 0 and cut_early.document_id is None, (
                team,
                "a cut before the document was written",
            )
            assert cut_now.document_id is not None
    assert seen_ok == seen_refused > 20
    keys = ["goals_over_2_5"]
    assert (
        facts.peers(
            db,
            competition_season_id=cs,
            scope="season",
            context="all",
            keys=keys,
            as_of=before,
            min_sample=1,
        )
        == {}
    )
