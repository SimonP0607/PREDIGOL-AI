"""Plan EA against a real database: the nightly pass reads a competition season (``fbi.stats.data``), writes its documents
(``analytics.stat_documents``, revision 0167) and C-13 / C-14 read them back (``fbi.api.services.stats_profile``, ``market_probs``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.contracts.intelligence.base import Missing
from fbi.api.contracts.intelligence.market_probs import MarketProbs
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.stats_profile import StatsProfile
from fbi.api.problem import ApiError
from fbi.api.services import market_probs, stats_profile
from fbi.stats import data as sd
from fbi.stats import job

from .conftest import Seed

T0 = datetime(2034, 2, 1, 18, tzinfo=UTC)


def _league(db: psycopg.Connection[Any], seed: Seed, teams: int = 10) -> tuple[int, list[int], int]:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
                "VALUES (987001, 'Liga EA', 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id")
    comp = cur.fetchone()[0]  # type: ignore[index]
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id", (comp,))
    cs = cur.fetchone()[0]  # type: ignore[index]
    ids = []
    for i in range(teams):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (987100 + i, f"Club EA {i}"))
        ids.append(cur.fetchone()[0])  # type: ignore[index]
    k = 0
    for h in range(teams):
        for a in range(teams):
            if h == a:
                continue
            k += 1
            ko = T0 + timedelta(days=k)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                        "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                        (9871000 + k, cs, ids[h], ids[a], ko))
            fid = cur.fetchone()[0]  # type: ignore[index]
            cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, settled_at) "
                        "VALUES (%s, 2, 1, 1, 0, %s)", (fid, ko + timedelta(hours=2)))
            for side, corners, xg in (("home", 6, 1.7), ("away", 3, 0.8)):
                cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, shots, shots_on_target, corners, fouls, "
                            "yellow_cards, red_cards, saves, possession_pct, passes, passes_accurate, expected_goals, payload_hash, "
                            "fetched_at) VALUES (%s, %s, 'api-football', 12, 5, %s, 11, 2, 0, 3, 50, 400, 320, %s, %s, %s)",
                            (fid, side, corners, xg, seed.payload_hash, ko + timedelta(hours=3)))
            for seq, (minute, extra, side, kind, detail) in enumerate(
                    ((20, None, "home", "Goal", "Normal Goal"), (55, None, "away", "Goal", "Normal Goal"),
                     (90, 4, "home", "Goal", "Normal Goal"), (30, None, "away", "Card", "Yellow Card"))):
                cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, extra_minute, team_side, event_type, "
                            "detail, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, %s, %s, %s, %s, %s)",
                            (fid, seq, minute, extra, side, kind, detail, seed.payload_hash, ko + timedelta(hours=3)))
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                "VALUES (9879999, %s, %s, %s, %s) RETURNING id", (cs, ids[0], ids[1], T0 + timedelta(days=200)))
    upcoming = cur.fetchone()[0]  # type: ignore[index]
    return cs, ids, upcoming


def _season(db: psycopg.Connection[Any], cs: int) -> sd.Season:
    found = [s for s in sd.seasons(db, min_matches=job.MIN_MATCHES) if s.id == cs]
    assert found, "the season with 90 finished matches is a season the pass reads"
    return found[0]


def test_the_pass_reads_a_season_and_writes_its_documents(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, _ids, _ = _league(db, seed)
    data = sd.load_season(db, _season(db, cs))
    assert len(data.matches) == 90
    m = data.matches[0]
    assert m.numbers["corners_ft_home"] == 6 and m.team_stats["home"]["xg"] == pytest.approx(1.7)
    assert m.events is not None and len(m.events) == 4
    written = job.write_season(db, data, None, T0 + timedelta(days=120))
    rows = db.execute("SELECT kind, count(*) FROM analytics.stat_documents WHERE competition_season_id = %s GROUP BY 1",
                      (cs,)).fetchall()
    counts = dict(rows)
    assert counts["league"] == 1 and counts["team"] == written - 1
    league = db.execute("SELECT doc FROM analytics.stat_documents WHERE kind = 'league' AND entity_id = %s", (cs,)).fetchone()
    cover = {c["key"]: c for c in league[0]["coverage"]}  # type: ignore[index]
    assert cover["xg_for"]["publishable"] is True and cover["fouls"]["share"] == 1.0


def test_a_second_pass_replaces_the_first_and_prunes_what_it_no_longer_writes(db: psycopg.Connection[Any], seed: Seed) -> None:
    cs, _ids, _ = _league(db, seed)
    data = sd.load_season(db, _season(db, cs))
    job.write_season(db, data, None, T0 + timedelta(days=120))
    db.execute("INSERT INTO analytics.stat_documents (kind, entity_id, competition_season_id, scope, context, calc_version, sample, doc, "
               "computed_at) VALUES ('team', 1, %s, 'u20', 'home', 'team-agg-v1', 1, '{}', %s)", (cs, T0))
    job.write_season(db, data, None, T0 + timedelta(days=121))
    left = db.execute("SELECT count(*) FROM analytics.stat_documents WHERE competition_season_id = %s AND computed_at < %s",
                      (cs, T0 + timedelta(days=121))).fetchone()
    assert left == (0,)


def test_c13_reads_the_documents_back(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    cs, ids, upcoming = _league(db, seed)
    job.write_season(db, sd.load_season(db, _season(db, cs)), 7, T0 + timedelta(days=120))
    at = T0 + timedelta(days=120, hours=1)
    answer = stats_profile.build_team(db, ids[0], scope="u5", context="home", at=at)
    e = answer.entities[0]
    assert e.competition.competition_season_id == cs and e.scope == "u5" and e.context == "home"
    assert e.available_scopes == ["u5", "season"], "nine home matches: no scope of ten or twenty"
    assert not isinstance(e.team, Missing) and e.team.record.matches == 5
    assert e.audit.run_id == 7
    public = to_public(answer, StatsProfile)
    assert "audit" not in public.model_dump()["entities"][0]
    preview = stats_profile.build_preview(db, upcoming, scope="season", at=at)
    assert [x.role for x in preview.entities] == ["local", "visitante"]
    assert [x.context for x in preview.entities] == ["home", "away"]
    compare = stats_profile.build_compare(db, "equipo", ids[0], ids[1], at=at)
    assert len(compare.entities) == 2
    with pytest.raises(ApiError):
        stats_profile.build_team(db, ids[0], scope="u10", context="home", at=at)
    monkeypatch.setenv("FBI_STATS_V2", "0")
    with pytest.raises(ApiError):
        stats_profile.public_team(db, ids[0])


def test_c14_answers_a_match_without_prices(db: psycopg.Connection[Any], seed: Seed) -> None:
    _cs, ids, upcoming = _league(db, seed)
    answer = market_probs.build(db, upcoming, at=T0 + timedelta(days=150))
    assert answer.markets.items == [] and answer.markets.missing_reason == "sin_datos"
    assert to_public(answer, MarketProbs).home.id == ids[0]
