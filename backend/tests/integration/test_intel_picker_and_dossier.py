"""The admin's match picker and the dossier of PLAN F6 (``fbi.api.services.intelligence``): which matches the console offers (a Bogotá day with the
ones the AI studied first, or a text within 45 days of that day), and what a dossier says about the AI's side of a match - the weighted
head-to-head, the scenarios, the status of the context factors the AI saw, the research its latest brief asked for, every claim the server
refused, the passes that ran - and the registry of context factors as it stands now.

One transaction, rolled back: the matches, packets, briefs and passes are written by hand on top of the seed (a day in 2031 no other test uses)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds
from fbi.api.services import intelligence as svc
from fbi.intel import factors as registry

from .conftest import Seed

pytestmark = pytest.mark.integration

DAY = date(2031, 3, 10)
START, END = day_bounds(DAY)
MIDDLE = START + (END - START) / 2
"""The point a text measures distance from: the middle of the chosen Bogotá day."""
SERIAL = iter(range(7_990_000, 8_000_000))


class Pitch:
    """A league of its own, and the matches written into it."""

    def __init__(self, db: psycopg.Connection[Any], name: str = "Picker League") -> None:
        self.db = db
        n = next(SERIAL)
        row = db.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                         "VALUES (%s, %s, 'league', 'club', 'domestic_league') RETURNING id", (n, name)).fetchone()
        assert row is not None
        row = db.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2031) RETURNING id",
                         (row[0],)).fetchone()
        assert row is not None
        self.season = int(row[0])
        self.teams: dict[str, int] = {}

    def team(self, name: str) -> int:
        if name not in self.teams:
            row = self.db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                                  (next(SERIAL), name)).fetchone()
            assert row is not None
            self.teams[name] = int(row[0])
        return self.teams[name]

    def match(self, home: str, away: str, kickoff: datetime) -> int:
        row = self.db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                              "kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                              (next(SERIAL), self.season, self.team(home), self.team(away), kickoff)).fetchone()
        assert row is not None
        return int(row[0])

    def packet(self, fixture: int, content: dict[str, Any] | None = None, *, at: datetime | None = None) -> int:
        when = at or START
        row = self.db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
                              "VALUES (%s, 'packet-v8', %s, %s, %s, %s) RETURNING id",
                              (fixture, when, when, f"{next(SERIAL):064d}", Jsonb(content or {}))).fetchone()
        assert row is not None
        return int(row[0])

    def brief(self, fixture: int, *, pass_: str = "first", research: list[dict[str, Any]] | None = None, escalate: bool = False,
              reasons: tuple[str, ...] = (), rejected: list[dict[str, str]] | None = None, at: datetime | None = None,
              summary: str = "Un resumen.") -> int:
        row = self.db.execute(
            "INSERT INTO ai.match_briefs (fixture_id, created_at, pass, version, engine, input_hash, status, escalate, reasons, "
            "uncertainty, data_quality, content, rejected) VALUES (%s, %s, %s, 'brief-v8', 'rules', %s, 'ok', %s, %s, 'medium', 'fair', "
            "%s, %s) RETURNING id",
            (fixture, at or START, pass_, f"h{next(SERIAL)}", escalate, list(reasons),
             Jsonb({"summary": summary, "research": research if research is not None else []}), Jsonb(rejected or []))).fetchone()
        assert row is not None
        return int(row[0])

    def ran(self, fixture: int, kind: str, *, at: datetime, counts: dict[str, int] | None = None, cost: str = "0.01") -> None:
        self.db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts, "
                        "cost_usd, note) VALUES (%s, %s, %s, %s, %s, %s, 'ok', %s, %s, 'una nota')",
                        (fixture, DAY, kind, at, at + timedelta(minutes=1), END, Jsonb(counts or {}), cost))


def ids(envelope: Any) -> list[int]:
    return [m["fixture_id"] for m in envelope.data["matches"]]


@pytest.fixture()
def pitch(db: psycopg.Connection[Any], seed: Seed) -> Pitch:
    return Pitch(db)


# ── the picker, by day ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_day_lists_the_matches_of_the_bogota_day_and_the_ones_the_ai_studied_first(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    morning = pitch.match("Alpha", "Beta", START + timedelta(hours=8))
    noon = pitch.match("Gamma", "Delta", START + timedelta(hours=12))
    late = pitch.match("Epsilon", "Zeta", START + timedelta(hours=23, minutes=30))
    before = pitch.match("Eta", "Theta", START - timedelta(minutes=1))
    after = pitch.match("Iota", "Kappa", END)
    pitch.packet(noon)
    pitch.packet(late)
    pitch.brief(late, research=[{"topic": "availability", "side": "both", "why": {"text": "x", "type": "DATA", "refs": []}},
                                {"topic": "preview", "side": "home", "why": {"text": "y", "type": "DATA", "refs": []}}],
                escalate=True)

    got = svc.matches(db, day=DAY)

    assert got.data["mode"] == "day" and got.data["day"] == "2031-03-10" and got.data["q"] is None
    assert ids(got) == [noon, late, morning], "the studied matches first, each group by kick-off; the day is the Bogotá day"
    assert before not in ids(got) and after not in ids(got)
    assert got.data["total"] == 3 and got.data["with_packet"] == 2
    row = {m["fixture_id"]: m for m in got.data["matches"]}
    assert row[late]["research_asked"] == 2 and row[late]["brief_escalate"] is True and row[late]["brief_pass"] == "first"
    assert row[noon]["research_asked"] == 0 and row[noon]["brief_pass"] is None and row[noon]["packet_as_of"] is not None
    assert row[morning]["packet_as_of"] is None
    assert (row[late]["home"], row[late]["away"], row[late]["competition"]) == ("Epsilon", "Zeta", "Picker League")


def test_the_picker_reads_the_newest_packet_and_brief_and_honours_the_limit(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    a = pitch.match("Alpha", "Beta", START + timedelta(hours=9))
    b = pitch.match("Gamma", "Delta", START + timedelta(hours=10))
    pitch.packet(a, at=START)
    pitch.packet(a, at=START + timedelta(hours=1))
    pitch.brief(a, pass_="first", research=[{"topic": "availability", "side": "both", "why": {}}], at=START)
    pitch.brief(a, pass_="pre", research=[], at=START + timedelta(hours=2))

    first, second = svc.matches(db, day=DAY, limit=1), svc.matches(db, day=DAY)

    assert ids(first) == [a] and first.data["total"] == 2, "the limit cuts the list, not the count"
    row = {m["fixture_id"]: m for m in second.data["matches"]}[a]
    assert row["brief_pass"] == "pre" and row["research_asked"] == 0, "the newest brief is the one that counts"
    assert datetime.fromisoformat(row["packet_as_of"]) == START + timedelta(hours=1), "the newest packet is the one that counts"
    assert ids(second) == [a, b]


def test_a_brief_written_before_brief_v8_has_no_research_and_a_malformed_one_counts_for_none(db: psycopg.Connection[Any],
                                                                                              pitch: Pitch) -> None:
    old, odd = pitch.match("Alpha", "Beta", START + timedelta(hours=9)), pitch.match("Gamma", "Delta", START + timedelta(hours=10))
    db.execute("INSERT INTO ai.match_briefs (fixture_id, created_at, pass, version, engine, input_hash, status, escalate, content) "
               "VALUES (%s, %s, 'first', 'brief-v7', 'rules', 'old', 'ok', false, %s)", (old, START, Jsonb({"summary": "viejo"})))
    db.execute("INSERT INTO ai.match_briefs (fixture_id, created_at, pass, version, engine, input_hash, status, escalate, content) "
               "VALUES (%s, %s, 'first', 'brief-v8', 'rules', 'odd', 'ok', false, %s)", (odd, START, Jsonb({"research": "a text"})))

    got = {m["fixture_id"]: m for m in svc.matches(db, day=DAY).data["matches"]}

    assert got[old]["research_asked"] == 0 and got[odd]["research_asked"] == 0 and got[old]["brief_pass"] == "first"


def test_an_empty_day_is_an_empty_list(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    got = svc.matches(db, day=date(2031, 7, 1))
    assert got.data["matches"] == [] and got.data["total"] == 0 and got.data["with_packet"] == 0


# ── the picker, by text ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_text_finds_the_matches_of_a_team_within_45_days_nearest_first_and_ignores_case(db: psycopg.Connection[Any],
                                                                                          pitch: Pitch) -> None:
    near = pitch.match("Real Picker", "Beta", MIDDLE + timedelta(days=3))
    away = pitch.match("Gamma", "REAL PICKER", MIDDLE - timedelta(days=10))
    edge = pitch.match("Real Picker", "Delta", MIDDLE - timedelta(days=45) + timedelta(hours=1))
    too_early = pitch.match("Real Picker", "Epsilon", MIDDLE - timedelta(days=45) - timedelta(hours=1))
    too_late = pitch.match("Real Picker", "Zeta", MIDDLE + timedelta(days=45) + timedelta(hours=1))
    other = pitch.match("Eta", "Theta", MIDDLE + timedelta(days=1))

    got = svc.matches(db, q="real pick", day=DAY)

    assert got.data["mode"] == "search" and got.data["q"] == "real pick"
    assert ids(got) == [near, away, edge], "nearest to the day first, inside 45 days either side"
    assert {too_early, too_late, other}.isdisjoint(ids(got))
    assert got.data["total"] == 3


def test_a_text_that_names_a_competition_finds_its_matches_and_one_that_names_neither_finds_nothing(db: psycopg.Connection[Any],
                                                                                                    seed: Seed) -> None:
    league = Pitch(db, name="Liga Zxqv Unica")
    a = league.match("Alpha", "Beta", MIDDLE + timedelta(days=2))
    b = league.match("Gamma", "Delta", MIDDLE - timedelta(days=1))

    assert ids(svc.matches(db, q="zxqv", day=DAY)) == [b, a]
    assert svc.matches(db, q="nobody has this name", day=DAY).data["matches"] == []


def test_a_number_is_also_a_match_id_and_that_match_comes_first_wherever_it_is(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    far = pitch.match("Alpha", "Beta", MIDDLE + timedelta(days=300))
    near = pitch.match("Gamma Prime", "Delta", MIDDLE + timedelta(days=1))
    # a team whose name holds the same digits
    byname = pitch.match(f"Club {far}", "Zeta", MIDDLE + timedelta(days=2))

    got = svc.matches(db, q=str(far), day=DAY)

    assert ids(got)[0] == far and byname in ids(got) and near not in ids(got)
    assert svc.matches(db, q="9" * 40, day=DAY).data["matches"] == [], "a number too big for an id is only a text"


def test_the_wildcards_of_like_written_by_a_person_are_letters(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    pct = pitch.match("Pct 50% FC", "Beta", MIDDLE + timedelta(days=1))
    pitch.match("Pct 500 FC", "Gamma", MIDDLE + timedelta(days=1))
    under = pitch.match("Under_Score", "Delta", MIDDLE + timedelta(days=1))
    pitch.match("UnderXScore", "Epsilon", MIDDLE + timedelta(days=1))
    back = pitch.match("Back\\Slash", "Zeta", MIDDLE + timedelta(days=1))

    assert ids(svc.matches(db, q="50%", day=DAY)) == [pct]
    assert ids(svc.matches(db, q="r_s", day=DAY)) == [under]
    assert ids(svc.matches(db, q="k\\s", day=DAY)) == [back]
    assert ids(svc.matches(db, q="%", day=DAY)) == [pct], "a lone percent sign matches only the names that hold one"


def test_a_text_of_spaces_is_the_day(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    a = pitch.match("Alpha", "Beta", START + timedelta(hours=9))
    assert svc.matches(db, q="   ", day=DAY).data["mode"] == "day" and ids(svc.matches(db, q="   ", day=DAY)) == [a]


# ── the dossier ────────────────────────────────────────────────────────────────────────────────────────────────────────

BLOCKS = {
    "h2h": {"version": "h2h-v2", "status": "DESCRIPTIVE", "n": 4, "n_effective": 2.6, "relevance": "media",
            "meetings": [{"fixture_id": 1, "days_ago": 120, "weight": 0.8}]},
    "scenarios": {"version": "scenarios-v1", "status": "DESCRIPTIVE", "table": {"home": {"win": "sube al 2.º"}}, "tie": None},
    "factors": {"version": "factors-v1", "h2h_weighted": {"version": "h2h-v2", "block": "h2h", "status": "DESCRIPTIVE",
                                                           "decision": None}},
}


def test_the_dossier_carries_the_ais_side_of_the_match(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    fx = pitch.match("Alpha", "Beta", START + timedelta(hours=9))
    pitch.packet(fx, {**BLOCKS, "stakes": {"x": 1}})
    ask = {"topic": "availability", "side": "both", "why": {"text": "No hay bajas.", "type": "DATA", "refs": ["P:absences"]}}
    refused = [{"group": "cards.why", "text": "Ventaja por el cara a cara.", "why": "rests on h2h_weighted, a DESCRIPTIVE factor"}]
    pitch.brief(fx, pass_="first", research=[ask], escalate=True, reasons=("important_news",), rejected=refused, at=START)
    pitch.ran(fx, "first", at=START + timedelta(minutes=5), counts={"research_requested": 1, "web_searches": 0})
    pitch.ran(fx, "pre", at=START + timedelta(hours=5), counts={
        "research_asked": 1, "research_searched": 1, "web_searches": 2})
    pitch.ran(fx, "final", at=START + timedelta(hours=8), counts={
        "research_asked": 1, "research_unserved_no_search_pass": 1})

    got = svc.dossier(db, fx).data

    assert got["h2h"] == BLOCKS["h2h"] and got["scenarios"] == BLOCKS["scenarios"] and got["factors"] == BLOCKS["factors"]
    assert got["stakes"] == {"x": 1}
    brief = got["brief"]
    assert brief["pass"] == "first" and brief["version"] == "brief-v8" and brief["status"] == "ok"
    assert brief["escalate"] is True and brief["reasons"] == ["important_news"]
    assert (brief["uncertainty"], brief["data_quality"]) == ("medium", "fair")
    assert brief["research"] == [ask] and brief["summary"] == "Un resumen."
    assert brief["refused"] == refused and brief["refused_total"] == 1
    assert [p["pass"] for p in got["passes"]] == ["final", "pre", "first"], "the newest pass first"
    final, pre, first = got["passes"]
    assert final["research"] == {"requested": 0, "asked": 1, "searched": 0, "unserved": {"no_search_pass": 1}, "web_searches": 0}
    assert pre["research"] == {"requested": 0, "asked": 1, "searched": 1, "unserved": {}, "web_searches": 2}
    assert first["research"]["requested"] == 1 and first["note"] == "una nota" and first["status"] == "ok"
    assert first["day"] == "2031-03-10" and first["cost_usd"] == 0.01


def test_the_dossier_of_a_match_the_ai_never_saw_is_empty_not_an_error(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    fx = pitch.match("Alpha", "Beta", START + timedelta(hours=9))

    got = svc.dossier(db, fx).data

    assert got["packet"] is None and got["brief"] is None and got["passes"] == []
    assert got["h2h"] is None and got["scenarios"] is None and got["factors"] is None
    assert (got["fixture"]["home"], got["fixture"]["away"]) == ("Alpha", "Beta")


def test_the_dossier_lists_a_dozen_passes_and_forty_refusals_at_most(db: psycopg.Connection[Any], pitch: Pitch) -> None:
    fx = pitch.match("Alpha", "Beta", START + timedelta(hours=9))
    pitch.packet(fx)
    pitch.brief(fx, rejected=[{"group": "context", "text": f"claim {n}", "why": "x"} for n in range(svc.REFUSED_SHOWN + 5)])
    for n in range(svc.PASSES_SHOWN + 3):
        db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status) "
                   "VALUES (%s, %s, 'first', %s, %s, %s, 'ok') ON CONFLICT DO NOTHING",
                   (fx, DAY + timedelta(days=n), START, START + timedelta(minutes=1), END))

    got = svc.dossier(db, fx).data

    assert len(got["passes"]) == svc.PASSES_SHOWN
    assert len(got["brief"]["refused"]) == svc.REFUSED_SHOWN and got["brief"]["refused_total"] == svc.REFUSED_SHOWN + 5


def test_an_unknown_match_is_a_404(db: psycopg.Connection[Any], seed: Seed) -> None:
    from fbi.api.errors import ApiError

    with pytest.raises(ApiError) as caught:
        svc.dossier(db, 2**62)
    assert (caught.value.status, caught.value.code) == (404, "not_found")


# ── the registry of context factors ────────────────────────────────────────────────────────────────────────────────────


def test_the_registry_page_shows_every_factor_descriptive_until_a_person_validates_one(db: psycopg.Connection[Any], seed: Seed) -> None:
    at = datetime.now(UTC) - timedelta(hours=2)

    before = svc.factors(db).data
    assert before["version"] == registry.VERSION
    assert [f["key"] for f in before["factors"]] == [f.key for f in registry.CATALOGUE]
    assert all(f["status"] == "DESCRIPTIVE" and f["decision"] is None and f["decisions"] == [] for f in before["factors"])
    assert all(f["label"] and f["claim"] and f["block"] and f["version"] for f in before["factors"])

    registry.promote(db, registry.H2H, experiment="h2h-vs-form", result={"brier_delta": -0.002}, reason="mejora el Brier en walk-forward",
                     who="Simon", at=at)
    registry.retire(db, registry.H2H, reason="el segundo experimento no lo confirma", who="Simon", at=at + timedelta(minutes=30))
    registry.promote(db, registry.TACTICS, experiment="tactics-x", result={"n": 1}, reason="una razón suficiente", who="Simon", at=at)

    after = {f["key"]: f for f in svc.factors(db).data["factors"]}
    assert after[registry.TACTICS]["status"] == "VALIDATED" and after[registry.TACTICS]["decision"]["experiment"] == "tactics-x"
    h2h = after[registry.H2H]
    assert h2h["status"] == "DESCRIPTIVE", "retired: back where it was born"
    assert [d["status"] for d in h2h["decisions"]] == ["DESCRIPTIVE", "VALIDATED"], "the decisions, newest first"
    assert h2h["decisions"][1]["experiment"] == "h2h-vs-form" and h2h["decisions"][1]["who"] == "Simon"
    assert h2h["decisions"][0]["previous_id"] == h2h["decisions"][1]["id"]
    assert after[registry.SCENARIOS]["decisions"] == []
