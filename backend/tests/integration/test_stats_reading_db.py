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


def test_the_trends_read_equal_the_trends_c13_serves_and_become_facts(db: psycopg.Connection[Any], seed: Seed) -> None:
    """RP-6.2 on a real season: the trend rows Intelligence reads are those of C-13, the league reference comes with each, a fact keeps its
    document and the percentile places a team among the peers of the league at the cut-off."""
    from fbi.stats import facts as sf

    cs, ids = _written(db, seed)
    at = T0 + timedelta(days=120, hours=1)
    served = stats_profile.build_team(db, ids[0], season=cs, scope="season", context="all", at=at).entities[0]
    doc = rd.read(db, kind="team", entity_id=ids[0], competition_season_id=cs, scope="season", context="all", as_of=at)
    assert doc.status == "ok" and not isinstance(served.team, Missing)
    served_trends = [] if isinstance(served.team.trends, Missing) else served.team.trends.items
    assert [t.key for t in doc.trends] == [t.key for t in served_trends] and doc.trends, "the season has trends"
    for read, sv in zip(doc.trends, served_trends, strict=True):
        assert (read.hits, read.n, read.pct, read.wilson_low, read.wilson_high) == (sv.hits, sv.n, sv.pct, sv.wilson_low, sv.wilson_high)
        assert read.league_pct == (None if isinstance(sv.league_pct, Missing) else sv.league_pct)
    keys = [t.key for t in doc.trends]
    peers = sf.peers(db, competition_season_id=cs, scope="season", context="all", keys=keys, as_of=at, min_sample=1)
    assert set(peers) <= set(keys) and all(len(v) <= len(ids) for v in peers.values())
    facts, left = sf.facts_of(doc, peers=peers, min_sample=1)
    assert len(facts) + len(left) == len(doc.trends)
    assert all(x.document_id == doc.document_id and x.league_pct is not None for x in facts)
    assert sf.peers(db, competition_season_id=cs, scope="season", context="all", keys=keys, as_of=T0, min_sample=1) == {}, "nothing before it was written"


def test_the_cuts_by_venue_and_the_halves_are_read_from_the_stored_documents(db: psycopg.Connection[Any], seed: Seed) -> None:
    """RP-6.3 against a real database: home and away are the documents of those contexts with their own sample, the halves are the document's
    own block, and the cut by rival strength says it is not in the documents."""
    from fbi.stats import cuts

    cs, ids = _written(db, seed)
    at = T0 + timedelta(days=120, hours=1)
    seen = 0
    for team in ids[:4]:
        c = cuts.read_team_cuts(db, team_id=team, competition_season_id=cs, scope="season", as_of=at)
        for cut, context in ((c.home, "home"), (c.away, "away")):
            doc = rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope="season", context=context, as_of=at)
            assert (cut.sample, cut.document_id) == (doc.sample, doc.document_id)
            assert cut.state == cuts.state_of(doc.sample, cuts.MIN_MATCHES)
            seen += 1
        whole = rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope="season", context="all", as_of=at)
        block = whole.body.get("halves")
        if isinstance(block, dict) and "missing_reason" not in block:
            assert c.halves.sample == block["matches_with_data"]
        assert c.rival_strength.reason == cuts.NOT_IN_DOCUMENTS
    assert seen == 8


def test_the_controls_on_real_documents_cutoff_stale_and_small_sample(db: psycopg.Connection[Any], seed: Seed) -> None:
    """RP-6.4: the same documents, the three controls, and the provoked leak that must fail."""
    from fbi.stats import controls

    cs, ids = _written(db, seed)
    written = T0 + timedelta(days=120)
    team = ids[0]
    doc = rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope="season", as_of=written + timedelta(hours=1))
    assert doc.status == "ok"
    ok = controls.check(db, doc, as_of=written + timedelta(hours=1), min_sample=1)
    assert ok.codes in ((), (controls.STALE,)), "the league of the test may have played after the document was written"
    # the cut-off before the document: refused, nothing else said
    early = rd.read(db, kind="team", entity_id=team, competition_season_id=cs, scope="season", as_of=written - timedelta(minutes=1))
    assert controls.check(db, early, as_of=written - timedelta(minutes=1), min_sample=1).codes == (controls.AFTER_CUTOFF,)
    # a threshold above the sample of the document: said
    big = controls.check(db, doc, as_of=written + timedelta(hours=1), min_sample=doc.sample + 1)
    assert controls.SMALL_SAMPLE in big.codes
    # a match finished AFTER the document was computed makes it stale
    db.execute("UPDATE core.fixtures SET status_group = 'finished', kickoff_at = %s WHERE id = (SELECT id FROM core.fixtures "
               "WHERE competition_season_id = %s AND (home_team_id = %s OR away_team_id = %s) LIMIT 1)",
               (written - timedelta(days=1), cs, team, team))
    assert controls.last_match_at(db, doc, as_of=written + timedelta(hours=1)) == written - timedelta(days=1)
    assert controls.STALE not in controls.check(db, doc, as_of=written + timedelta(hours=1), min_sample=1).codes
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE status_group = 'finished' AND competition_season_id = %s "
               "AND (home_team_id = %s OR away_team_id = %s)", (written + timedelta(minutes=30), cs, team, team))
    assert controls.STALE in controls.check(db, doc, as_of=written + timedelta(hours=1), min_sample=1).codes
    # every figure the document cites carries a date the cut-off can check; a leak provoked on purpose fails
    cites = [doc.citation(r.key) for r in doc.readings]
    assert controls.assert_no_leak(cites, as_of=written + timedelta(hours=1)) > 0
    with pytest.raises(controls.LeakError):
        controls.assert_no_leak(cites, as_of=written - timedelta(minutes=1))


def test_the_report_of_the_controls_reads_the_documents_and_finds_no_leak(db: psycopg.Connection[Any], seed: Seed) -> None:
    from fbi.stats import controls_report

    _written(db, seed)
    written = T0 + timedelta(days=120)
    got = controls_report.report(db, at=written + timedelta(hours=1), min_sample=1, replay_days=3650)
    assert got["replay"]["facts_with_a_leak"] == 0
    assert got["replay"]["moments"] > 0 and got["replay"]["refused_after_cutoff"] <= got["replay"]["moments"]
    assert set(got["upcoming"]["controls"]) == set(__import__("fbi.stats.controls", fromlist=["CODES"]).CODES)
    assert got["upcoming"]["documents_with_a_leak"] == 0
