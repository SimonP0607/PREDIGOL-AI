"""A season is not one table: stages from round labels, tables mapped to them, the table a match is shown with.

The structures are the provider's real ones (``/standings`` and ``/fixtures`` round labels, 4 Oct 2026):
Colombia (Apertura / Clausura, and the 2023 quadrangular groups both labelled "Group A"/"Group B"),
Argentina (each phase in two groups), Peru (Apertura, Clausura and the "Tabla Anual" aggregate), Ecuador
(cumulative championship / placement / relegation groups), MLS (conferences), the World Cup (groups and the
ranking of third-placed teams), the Champions League (one league-phase table after knock-out
qualifying rounds), Eerste Divisie (period tables). The P0 bug: the Match Center took each team's
newest row across ALL tables of the season, so Llaneros (Clausura) met America de Cali (Apertura).
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from fbi.competitions.phases import (
    Match,
    RoundCount,
    Stage,
    TableIn,
    choose,
    current_stage,
    is_split,
    map_tables,
    phase_of,
    stage_kind,
    stage_of,
    stages_from_rounds,
)

NOW = datetime(2026, 10, 4, 12, tzinfo=UTC)
WEEK = timedelta(days=7)


def rr(teams: list[int], rounds: int | None = None) -> list[list[tuple[int, int]]]:
    """Round-robin pairings (circle method), one list of (home, away) per round."""
    t: list[int | None] = list(teams)
    if len(t) % 2:
        t.append(None)
    n = len(t)
    out = []
    for _ in range(n - 1):
        out.append([(a, b) for a, b in ((t[i], t[n - 1 - i]) for i in range(n // 2)) if a is not None and b is not None])
        t = [t[0], t[-1], *t[1:-1]]
    return out[:rounds] if rounds else out


class Build:
    """A season's fixtures: league stages played as round-robins, knock-out rounds as single matches."""

    def __init__(self) -> None:
        self.fixtures: list[tuple[str, int, int, datetime]] = []

    def league(self, stage: str, teams: list[int], start: datetime, rounds: int | None = None, *,
               numbered: bool = True) -> Build:
        for r, pairs in enumerate(rr(teams, rounds), 1):
            for h, a in pairs:
                self.fixtures.append((f"{stage} - {r}" if numbered else stage, h, a, start + (r - 1) * WEEK))
        return self

    def tie(self, round_label: str, home: int, away: int, at: datetime) -> Build:
        self.fixtures.append((round_label, home, away, at))
        return self

    def matches(self) -> list[Match]:
        return [Match(stage_of(r), h, a, k, k < NOW) for r, h, a, k in self.fixtures]

    def stages(self) -> list[Stage]:
        by: dict[str, list[datetime]] = {}
        for r, _, _, k in self.fixtures:
            by.setdefault(r, []).append(k)
        return stages_from_rounds(RoundCount(r, min(ks), max(ks), len(ks), sum(1 for k in ks if k < NOW))
                                  for r, ks in by.items())

    def played(self, teams: list[int], stages: tuple[str, ...], at: datetime, lag: int = 0) -> dict[int, int | None]:
        """Each team's finished games in the stages before ``at``, ``lag`` fewer (a provider behind)."""
        n: Counter[int] = Counter()
        for m in self.matches():
            if m.finished and m.kickoff < at and m.stage in stages:
                n[m.home] += 1
                n[m.away] += 1
        return {t: max(n[t] - lag, 0) for t in teams}


def keys(maps: list) -> dict[str, tuple[str | None, str, str]]:
    return {m.key: (m.stage, m.kind, m.method) for m in maps}


# ── stages from round labels ────────────────────────────────────────────────


def test_stage_and_phase_from_round_labels() -> None:
    assert stage_of("Clausura - 12") == "Clausura"
    assert stage_of("Apertura - Quadrangular - 3") == "Apertura - Quadrangular"
    assert stage_of("Regular Season - 34") == "Regular Season"
    assert stage_of("Round of 16") == "Round of 16"
    assert stage_of(None) == ""
    assert phase_of("Apertura - Quarter-finals") == "Apertura"
    assert phase_of("Clausura") == "Clausura"
    assert phase_of("League A") == "League A"


@pytest.mark.parametrize(("stage", "numbered", "kind"), [
    ("Regular Season", True, "league"),
    ("Apertura", True, "league"),
    ("Apertura - Quadrangular", True, "league"),
    ("Apertura - Quarter-finals", False, "knockout"),
    ("Apertura - Final", False, "knockout"),
    ("Group Stage", True, "league"),
    ("League Stage", True, "league"),
    ("League A", True, "league"),
    ("Championship Group", True, "league"),
    ("Relegation Round", True, "league"),
    ("Conference League Play-off Group", True, "league"),
    ("Promotion Round", True, "league"),
    ("Opening", False, "league"),
    ("Round of 16", False, "knockout"),
    ("Knockout Round Play-offs", False, "knockout"),
    ("Play-offs", False, "knockout"),
    ("MLS Cup - Round 1", False, "knockout"),
    ("1st Round", False, "knockout"),
    ("1st Phase", True, "league"),
    ("Qualification Round 1", False, "qualifying"),
    ("2nd Qualifying Round", False, "qualifying"),
    ("Promotion Play-offs - Semi-finals", False, "knockout"),
    ("Club Friendlies", True, "friendly"),
])
def test_stage_kinds(stage: str, numbered: bool, kind: str) -> None:
    assert stage_kind(stage, numbered=numbered) == kind


def test_stages_are_ordered_by_first_kickoff_and_count_fixtures() -> None:
    s = Build().league("Clausura", [1, 2, 3, 4], datetime(2026, 7, 24, tzinfo=UTC)) \
               .league("Apertura", [1, 2, 3, 4], datetime(2026, 1, 16, tzinfo=UTC)) \
               .tie("Apertura - Final", 1, 2, datetime(2026, 6, 3, tzinfo=UTC)).stages()
    assert [(x.name, x.phase, x.kind, x.fixtures) for x in s] == [
        ("Apertura", "Apertura", "league", 6), ("Apertura - Final", "Apertura", "knockout", 1),
        ("Clausura", "Clausura", "league", 6)]
    assert is_split(s)
    assert current_stage(s, NOW).name == "Clausura"  # type: ignore[union-attr]


# ── Colombia: Apertura and Clausura are two tables (the P0 case) ────────────


TEAMS20 = list(range(1, 21))
AMERICA, LLANEROS = 3, 17


def colombia_2026() -> Build:
    b = Build().league("Apertura", TEAMS20, datetime(2026, 1, 16, 20, tzinfo=UTC))
    for i, (h, a) in enumerate([(1, 8), (2, 7), (3, 6), (4, 5)]):
        b.tie("Apertura - Quarter-finals", h, a, datetime(2026, 5, 9, tzinfo=UTC) + timedelta(hours=i))
    b.tie("Apertura - Semi-finals", 1, 3, datetime(2026, 5, 16, tzinfo=UTC))
    b.tie("Apertura - Final", 1, 3, datetime(2026, 6, 3, tzinfo=UTC))
    return b.league("Clausura", TEAMS20, datetime(2026, 7, 24, 20, tzinfo=UTC))


def test_colombia_each_phase_has_its_own_table_and_a_clausura_match_gets_the_clausura_table() -> None:
    b = colombia_2026()
    at = NOW - timedelta(hours=2)
    tables = [TableIn("Apertura", b.played(TEAMS20, ("Apertura",), at)),
              TableIn("Clausura", b.played(TEAMS20, ("Clausura",), at))]
    assert {t.played[AMERICA] for t in tables} == {19, 11}  # the two rows the old Match Center mixed
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert keys(maps) == {"Apertura": ("Apertura", "full", "label"), "Clausura": ("Clausura", "full", "label")}
    assert all(m.agree == 20 for m in maps)
    ko = datetime(2026, 10, 9, 1, tzinfo=UTC)
    c = choose("Clausura - 12", ko, b.stages(), maps, (LLANEROS, AMERICA))
    assert c is not None and c.stage == "Clausura" and c.reason == "fixture_stage"
    assert dict(c.keys) == {LLANEROS: "Clausura", AMERICA: "Clausura"}


def test_colombia_knockout_round_gets_its_phase_league_table() -> None:
    b = colombia_2026()
    at = datetime(2026, 6, 1, tzinfo=UTC)
    tables = [TableIn("Apertura", b.played(TEAMS20, ("Apertura",), at))]
    maps = map_tables(tables, b.stages(), b.matches(), at)
    c = choose("Apertura - Final", datetime(2026, 6, 3, tzinfo=UTC), b.stages(), maps, (1, 3))
    assert c is not None and (c.stage, c.reason) == ("Apertura", "phase_league_stage")


def test_a_phase_never_borrows_another_phase_table() -> None:
    """Colombia 2025: the provider served only the Clausura tables. An Apertura final gets no table, a
    first Clausura match before the Clausura table exists gets none either - never the other phase's."""
    b = colombia_2026()
    at = NOW
    only_clausura = map_tables([TableIn("Clausura", b.played(TEAMS20, ("Clausura",), at))], b.stages(), b.matches(), at)
    assert choose("Apertura - Final", datetime(2026, 6, 3, tzinfo=UTC), b.stages(), only_clausura, (1, 3)) is None
    early = datetime(2026, 7, 20, tzinfo=UTC)
    only_apertura = map_tables([TableIn("Apertura", b.played(TEAMS20, ("Apertura",), early))], b.stages(),
                               b.matches(), early)
    assert choose("Clausura - 1", datetime(2026, 7, 24, 20, tzinfo=UTC), b.stages(), only_apertura, (1, 2)) is None


def test_colombia_2023_repeated_group_labels_map_to_their_own_quadrangular_by_games() -> None:
    """The provider labels both quadrangular stages' groups "Group A"/"Group B"; the parser keeps the
    second pair as "Group A #2"/"Group B #2". Games played tell which phase each belongs to."""
    b = Build().league("Apertura", TEAMS20, datetime(2023, 1, 20, tzinfo=UTC))
    b.league("Apertura - Quadrangular", [1, 2, 3, 4], datetime(2023, 5, 20, tzinfo=UTC))
    b.league("Apertura - Quadrangular", [5, 6, 7, 8], datetime(2023, 5, 20, 2, tzinfo=UTC))
    b.tie("Apertura - Final", 1, 5, datetime(2023, 6, 25, tzinfo=UTC))
    b.league("Clausura", TEAMS20, datetime(2023, 7, 15, tzinfo=UTC))
    b.league("Clausura - Quadrangular", [1, 2, 9, 10], datetime(2023, 11, 20, tzinfo=UTC))
    b.league("Clausura - Quadrangular", [5, 6, 11, 12], datetime(2023, 11, 20, 2, tzinfo=UTC))
    b.tie("Clausura - Final", 1, 5, datetime(2023, 12, 18, tzinfo=UTC))
    at = datetime(2024, 1, 10, tzinfo=UTC)
    aq, cq = ("Apertura - Quadrangular",), ("Clausura - Quadrangular",)
    tables = [TableIn("Apertura", b.played(TEAMS20, ("Apertura",), at)),
              TableIn("Group A", b.played([1, 2, 3, 4], aq, at)), TableIn("Group B", b.played([5, 6, 7, 8], aq, at)),
              TableIn("Clausura", b.played(TEAMS20, ("Clausura",), at)),
              TableIn("Group A #2", b.played([1, 2, 9, 10], cq, at)),
              TableIn("Group B #2", b.played([5, 6, 11, 12], cq, at))]
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert keys(maps) == {
        "Apertura": ("Apertura", "full", "label"), "Clausura": ("Clausura", "full", "label"),
        "Group A": ("Apertura - Quadrangular", "group", "games"), "Group B": ("Apertura - Quadrangular", "group", "games"),
        "Group A #2": ("Clausura - Quadrangular", "group", "games"),
        "Group B #2": ("Clausura - Quadrangular", "group", "games")}
    assert next(m for m in maps if m.key == "Group A").label == "Group A"
    c = choose("Clausura - Quadrangular - 4", datetime(2023, 12, 10, tzinfo=UTC), b.stages(), maps, (1, 9))
    assert c is not None and dict(c.keys) == {1: "Group A #2", 9: "Group A #2"}
    final = choose("Clausura - Final", datetime(2023, 12, 18, tzinfo=UTC), b.stages(), maps, (1, 5))
    assert final is not None and final.stage == "Clausura - Quadrangular"
    assert dict(final.keys) == {1: "Group A #2", 5: "Group B #2"}


# ── Argentina: each phase in two groups ────────────────────────────────────


def argentina() -> Build:
    a, b2 = [1, 2, 3, 4], [5, 6, 7, 8]
    b = Build().league("Apertura", a, datetime(2026, 1, 22, tzinfo=UTC)).league("Apertura", b2, datetime(2026, 1, 22, 3, tzinfo=UTC))
    b.tie("Apertura - Round of 16", 1, 6, datetime(2026, 5, 9, tzinfo=UTC))
    b.league("Clausura", a, datetime(2026, 7, 23, tzinfo=UTC)).league("Clausura", b2, datetime(2026, 7, 23, 3, tzinfo=UTC))
    return b.tie("Clausura - 4", 1, 5, datetime(2026, 10, 10, tzinfo=UTC))  # an interzonal match


def argentina_tables(b: Build, at: datetime) -> list[TableIn]:
    a, b2 = [1, 2, 3, 4], [5, 6, 7, 8]
    return [TableIn("Apertura - Group A", b.played(a, ("Apertura",), at)),
            TableIn("Apertura - Group B", b.played(b2, ("Apertura",), at)),
            TableIn("Clausura - Group A", b.played(a, ("Clausura",), at)),
            TableIn("Clausura - Group B", b.played(b2, ("Clausura",), at))]


def test_argentina_groups_of_each_phase_and_an_interzonal_match() -> None:
    b = argentina()
    maps = map_tables(argentina_tables(b, NOW), b.stages(), b.matches(), NOW)
    assert keys(maps) == {"Apertura - Group A": ("Apertura", "group", "label"),
                          "Apertura - Group B": ("Apertura", "group", "label"),
                          "Clausura - Group A": ("Clausura", "group", "label"),
                          "Clausura - Group B": ("Clausura", "group", "label")}
    c = choose("Clausura - 4", datetime(2026, 10, 10, tzinfo=UTC), b.stages(), maps, (1, 5))
    assert c is not None and dict(c.keys) == {1: "Clausura - Group A", 5: "Clausura - Group B"}
    ko = choose("Apertura - Round of 16", datetime(2026, 5, 9, tzinfo=UTC), b.stages(), maps, (1, 6))
    assert ko is not None and ko.stage == "Apertura" and dict(ko.keys) == {1: "Apertura - Group A",
                                                                            6: "Apertura - Group B"}


# ── Peru: an annual aggregate is shown, never used for a match ─────────────


def test_peru_tabla_anual_is_an_aggregate() -> None:
    teams = list(range(1, 9))
    b = Build().league("Apertura", teams, datetime(2026, 1, 30, tzinfo=UTC)) \
               .league("Clausura", teams, datetime(2026, 7, 17, tzinfo=UTC))
    tables = [TableIn("Primera Division: Apertura", b.played(teams, ("Apertura",), NOW)),
              TableIn("Primera Division: Clausura", b.played(teams, ("Clausura",), NOW)),
              TableIn("Primera Division: Tabla Anual", b.played(teams, ("Apertura", "Clausura"), NOW))]
    maps = map_tables(tables, b.stages(), b.matches(), NOW)
    assert keys(maps) == {"Primera Division: Apertura": ("Apertura", "full", "label"),
                          "Primera Division: Clausura": ("Clausura", "full", "label"),
                          "Primera Division: Tabla Anual": (None, "aggregate", "games")}
    assert next(m for m in maps if m.kind == "aggregate").stages == ("Apertura", "Clausura")
    c = choose("Clausura - 9", NOW + WEEK, b.stages(), maps, (1, 2))
    assert c is not None and set(c.keys.values()) == {"Primera Division: Clausura"}


# ── Ecuador: cumulative groups after a regular season ───────────────────────


def test_ecuador_cumulative_groups_map_by_label() -> None:
    teams = list(range(1, 17))
    champ, place, releg = [1, 2, 3, 4, 5, 6], [7, 8, 9, 10], [11, 12, 13, 14, 15, 16]
    b = Build().league("Regular Season", teams, datetime(2026, 2, 21, tzinfo=UTC))
    start = datetime(2026, 9, 19, tzinfo=UTC)
    b.league("Championship Group", champ, start, 2).league("Placement Group", place, start, 2) \
     .league("Relegation Group", releg, start, 2)
    every = ("Regular Season", "Championship Group", "Placement Group", "Relegation Group")
    tables = [TableIn("Liga Pro: Regular season", b.played(teams, ("Regular Season",), NOW)),
              TableIn("Liga Pro: Championship Group", b.played(champ, every, NOW)),
              TableIn("Liga Pro: Placement Group", b.played(place, every, NOW)),
              TableIn("Liga Pro: Relegation Group", b.played(releg, every, NOW))]
    maps = map_tables(tables, b.stages(), b.matches(), NOW)
    assert keys(maps) == {"Liga Pro: Regular season": ("Regular Season", "full", "label"),
                          "Liga Pro: Championship Group": ("Championship Group", "full", "label"),
                          "Liga Pro: Placement Group": ("Placement Group", "full", "label"),
                          "Liga Pro: Relegation Group": ("Relegation Group", "full", "label")}
    assert next(m for m in maps if m.stage == "Championship Group").note.startswith("cumulative")
    c = choose("Championship Group - 3", NOW + WEEK, b.stages(), maps, (1, 2))
    assert c is not None and set(c.keys.values()) == {"Liga Pro: Championship Group"}


# ── MLS: two conferences of one regular season ─────────────────────────────


def test_mls_conferences_and_a_cup_play_off() -> None:
    east, west = [1, 2, 3, 4], [5, 6, 7, 8]
    b = Build().league("Regular Season", east + west, datetime(2026, 2, 21, tzinfo=UTC))
    b.tie("MLS Cup - Round 1", 1, 2, datetime(2026, 10, 25, tzinfo=UTC))
    tables = [TableIn("Eastern Conference", b.played(east, ("Regular Season",), NOW)),
              TableIn("Western Conference", b.played(west, ("Regular Season",), NOW))]
    maps = map_tables(tables, b.stages(), b.matches(), NOW)
    assert keys(maps) == {"Eastern Conference": ("Regular Season", "group", "games"),
                          "Western Conference": ("Regular Season", "group", "games")}
    assert not is_split(b.stages())
    c = choose("MLS Cup - Round 1", datetime(2026, 10, 25, tzinfo=UTC), b.stages(), maps, (1, 5))
    assert c is not None and c.reason == "previous_stage"
    assert dict(c.keys) == {1: "Eastern Conference", 5: "Western Conference"}


# ── World Cup: groups, the third-placed ranking, a knockout round ──────────


def world_cup() -> tuple[Build, dict[str, list[int]]]:
    groups = {"Group A": [1, 2, 3, 4], "Group B": [5, 6, 7, 8], "Group C": [9, 10, 11, 12]}
    b = Build()
    for i, teams in enumerate(groups.values()):
        b.league("Group Stage", teams, datetime(2026, 6, 11, i, tzinfo=UTC))
    b.tie("Round of 32", 1, 6, datetime(2026, 6, 28, tzinfo=UTC))
    return b, groups


def test_world_cup_groups_and_ranking_of_third_placed_teams() -> None:
    b, groups = world_cup()
    at = datetime(2026, 6, 27, tzinfo=UTC)
    tables = [TableIn(k, b.played(v, ("Group Stage",), at)) for k, v in groups.items()]
    tables.append(TableIn("Group Stage", b.played([3, 7, 11], ("Group Stage",), at)))
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert keys(maps) == {"Group A": ("Group Stage", "group", "games"), "Group B": ("Group Stage", "group", "games"),
                          "Group C": ("Group Stage", "group", "games"),
                          "Group Stage": ("Group Stage", "ranking", "label")}
    c = choose("Round of 32", datetime(2026, 6, 28, tzinfo=UTC), b.stages(), maps, (1, 6))
    assert c is not None and (c.stage, c.reason) == ("Group Stage", "previous_stage")
    assert dict(c.keys) == {1: "Group A", 6: "Group B"}
    third = choose("Group Stage - 3", datetime(2026, 6, 25, tzinfo=UTC), b.stages(), maps, (3, 4))
    assert third is not None and dict(third.keys) == {3: "Group A", 4: "Group A"}  # never the ranking


def test_a_provider_a_match_day_behind_still_ranks_the_only_league_stage() -> None:
    b, groups = world_cup()
    at = datetime(2026, 6, 27, tzinfo=UTC)
    tables = [TableIn(k, b.played(v, ("Group Stage",), at, lag=1)) for k, v in groups.items()]
    tables.append(TableIn("Group Stage", b.played([3, 7, 11], ("Group Stage",), at, lag=1)))
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert {m.key: m.method for m in maps} == {"Group A": "single", "Group B": "single", "Group C": "single",
                                                "Group Stage": "label"}
    assert {m.key: m.kind for m in maps}["Group Stage"] == "ranking"


# ── Champions League: knock-out qualifying, then one league-phase table ────


def test_champions_league_qualifying_rounds_have_no_table() -> None:
    teams = list(range(1, 9))
    b = Build().tie("1st Qualifying Round", 9, 10, datetime(2026, 7, 7, tzinfo=UTC)) \
               .tie("Play-offs", 1, 9, datetime(2026, 8, 18, tzinfo=UTC)) \
               .league("League Stage", teams, datetime(2026, 9, 8, tzinfo=UTC))
    at = NOW
    maps = map_tables([TableIn("UEFA Champions League", b.played(teams, ("League Stage",), at))], b.stages(),
                      b.matches(), at)
    assert keys(maps) == {"UEFA Champions League": ("League Stage", "full", "games")}
    assert choose("Play-offs", datetime(2026, 8, 18, tzinfo=UTC), b.stages(), maps, (1, 9)) is None
    c = choose("League Stage - 5", NOW + WEEK, b.stages(), maps, (1, 2))
    assert c is not None and c.reason == "fixture_stage"


# ── period tables, pre-season tables, unknown structures ───────────────────


def test_period_tables_are_kept_but_never_used_for_a_match() -> None:
    teams = list(range(1, 9))
    b = Build().league("Regular Season", teams, datetime(2026, 8, 7, tzinfo=UTC))
    at = NOW
    p1_end = datetime(2026, 8, 7, tzinfo=UTC) + 2 * WEEK
    tables = [TableIn("Eerste Divisie", b.played(teams, ("Regular Season",), at)),
              TableIn("Eerste Divisie: Period 1", b.played(teams, ("Regular Season",), p1_end))]
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert keys(maps) == {"Eerste Divisie": ("Regular Season", "full", "games"),
                          "Eerste Divisie: Period 1": (None, "other", "unmapped")}
    c = choose("Regular Season - 7", NOW + WEEK, b.stages(), maps, (1, 2))
    assert c is not None and set(c.keys.values()) == {"Eerste Divisie"}


def test_a_table_of_zeros_before_a_stage_starts_maps_to_the_stage_about_to_start() -> None:
    teams = list(range(1, 9))
    b = Build().league("Apertura", teams, datetime(2026, 1, 16, tzinfo=UTC)) \
               .league("Clausura", teams, datetime(2026, 10, 10, tzinfo=UTC))
    maps = map_tables([TableIn("", dict.fromkeys(teams, 0))], b.stages(), b.matches(), NOW)
    assert keys(maps) == {"": ("Clausura", "full", "games")}


def test_a_season_without_fixtures_shows_its_one_table_unmapped() -> None:
    maps = map_tables([TableIn("Superliga", {1: 3, 2: 3})], [], [], NOW)
    assert keys(maps) == {"Superliga": (None, "full", "unmapped")}
    assert choose("Regular Season - 4", NOW, [], maps, (1, 2)) is None


def test_label_with_accents_names_the_stage() -> None:
    teams = [1, 2, 3, 4]
    b = Build().league("Apertura", teams, datetime(2026, 1, 16, tzinfo=UTC))
    maps = map_tables([TableIn("Primera División: Apertura", b.played(teams, ("Apertura",), NOW))], b.stages(),
                      b.matches(), NOW)
    assert maps[0].stage == "Apertura" and maps[0].method == "label"


# ── structures found by the first audit run (4 Oct 2026) ───────────────────


def test_euro_groups_as_stages_their_ranking_and_a_round_of_16() -> None:
    """Euro 2024: rounds "Group A - 1" make each group a stage of its own; the provider's "Ranking of
    third-placed teams" spans them (a ranking, not an aggregate: each team played in one group); a
    Round of 16 match between two groups shows each team's group."""
    groups = {"Group A": [1, 2, 3, 4], "Group B": [5, 6, 7, 8], "Group C": [9, 10, 11, 12]}
    b = Build()
    for i, (g, teams) in enumerate(groups.items()):
        b.league(g, teams, datetime(2024, 6, 14, i, tzinfo=UTC))
    b.tie("Round of 16", 1, 6, datetime(2024, 6, 29, tzinfo=UTC))
    at = datetime(2024, 6, 28, tzinfo=UTC)
    tables = [TableIn(g, b.played(t, (g,), at)) for g, t in groups.items()]
    tables.append(TableIn("Ranking of third-placed teams", b.played([3, 7, 11], tuple(groups), at)))
    maps = map_tables(tables, b.stages(), b.matches(), at)
    assert keys(maps) == {"Group A": ("Group A", "full", "label"), "Group B": ("Group B", "full", "label"),
                          "Group C": ("Group C", "full", "label"),
                          "Ranking of third-placed teams": (None, "ranking", "games")}
    assert not is_split(b.stages()), "groups that are stages of their own are one phase"
    c = choose("Round of 16", datetime(2024, 6, 29, tzinfo=UTC), b.stages(), maps, (1, 6))
    assert c is not None and c.reason == "previous_stage" and dict(c.keys) == {1: "Group A", 6: "Group B"}


def test_a_period_table_equal_to_the_season_so_far_never_replaces_the_season_table() -> None:
    """Eerste Divisie in its first period: "Period 1" counts the same games as the regular season, so both
    agree with the stage; the season's table (named by its label) ranks it, the period table is "other"."""
    teams = list(range(1, 9))
    b = Build().league("Regular Season", teams, datetime(2026, 8, 7, tzinfo=UTC))
    at = datetime(2026, 9, 1, tzinfo=UTC)
    same = b.played(teams, ("Regular Season",), at)
    maps = map_tables([TableIn("Eerste Divisie: Period 1", same), TableIn("Eerste Divisie: Regular season", same)],
                      b.stages(), b.matches(), at)
    assert keys(maps) == {"Eerste Divisie: Period 1": ("Regular Season", "other", "games"),
                          "Eerste Divisie: Regular season": ("Regular Season", "full", "label")}
    c = choose("Regular Season - 5", at, b.stages(), maps, (1, 2))
    assert c is not None and set(c.keys.values()) == {"Eerste Divisie: Regular season"}


def test_a_numbered_final_round_is_a_league_stage() -> None:
    """CONCACAF World Cup qualifying: "Final Round - 1..6" is the round-robin of three groups, not a final.
    Its tables must never be pinned on the 2nd Round, whose teams played fewer games."""
    assert stage_kind("Final Round", numbered=True) == "league"
    assert stage_kind("Final Round", numbered=False) == "knockout"
    second = Build().league("2nd Round", [1, 2, 3, 4, 5], datetime(2024, 6, 5, tzinfo=UTC))
    at = datetime(2025, 12, 1, tzinfo=UTC)
    final_tables = [TableIn("Group A", {1: 6, 2: 6, 3: 6, 4: 6})]
    maps = map_tables(final_tables, second.stages(), second.matches(), at)
    assert keys(maps) == {"Group A": (None, "full", "unmapped")}, "6 games each: not the 2nd Round's table"
    full = Build().league("2nd Round", [1, 2, 3, 4, 5], datetime(2024, 6, 5, tzinfo=UTC)) \
                  .league("Final Round", [1, 2, 3, 4], datetime(2025, 9, 4, tzinfo=UTC)) \
                  .league("Final Round", [1, 2, 3, 4], datetime(2025, 10, 30, tzinfo=UTC))
    maps = map_tables([TableIn("Group A", full.played([1, 2, 3, 4], ("Final Round",), at))], full.stages(),
                      full.matches(), at)
    assert keys(maps) == {"Group A": ("Final Round", "full", "games")}


def test_a_lagging_group_in_a_season_of_several_stages_is_placed_by_its_teams() -> None:
    """Libertadores: knock-out qualifying rounds, then the group stage. A group whose table is a match day
    behind is still the group stage's: all its teams play there and none counts more games."""
    b = Build().tie("Qualification Round 1", 9, 10, datetime(2026, 2, 4, tzinfo=UTC))
    b.league("Group Stage", [1, 2, 3, 4], datetime(2026, 4, 7, tzinfo=UTC))
    b.league("Group Stage", [5, 6, 7, 8], datetime(2026, 4, 7, 2, tzinfo=UTC))
    at = datetime(2026, 6, 1, tzinfo=UTC)
    maps = map_tables([TableIn("Group A", b.played([1, 2, 3, 4], ("Group Stage",), at, lag=1)),
                       TableIn("Group B", b.played([5, 6, 7, 8], ("Group Stage",), at))], b.stages(), b.matches(), at)
    assert keys(maps) == {"Group A": ("Group Stage", "group", "single"), "Group B": ("Group Stage", "group", "games")}


def test_third_place_match_is_a_knockout_round() -> None:
    assert stage_kind("3rd place", numbered=False) == "knockout"
    assert stage_kind("3rd Place Final", numbered=False) == "knockout"
