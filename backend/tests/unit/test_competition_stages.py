"""The one reader of round labels (plan F2): what every label the provider has ever sent for a tracked competition means.

The labels are the provider's real ones - ``tests/fixtures/competition_stage_labels.tsv`` holds each distinct
(stage, has match days) pair of the 245,872 fixtures of the 162 tracked competitions on 22 Oct 2026 - so a rule that
reads a family of labels differently fails here before it changes what a stored stage means.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fbi.competitions import phases, stages

ZOO = Path(__file__).resolve().parent.parent / "fixtures" / "competition_stage_labels.tsv"


def zoo() -> list[tuple[int, bool, str]]:
    rows = []
    for line in ZOO.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        n, numbered, label = line.split("\t", 2)
        rows.append((int(n), numbered == "1", label))
    return rows


# ── the label ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("label", "stage", "phase", "day"), [
    ("Regular Season - 12", "Regular Season", "Regular Season", 12),
    ("Apertura - 7", "Apertura", "Apertura", 7),
    ("Apertura - Quadrangular - 3", "Apertura - Quadrangular", "Apertura", 3),
    ("Apertura - Quarter-finals", "Apertura - Quarter-finals", "Apertura", None),
    ("Round of 16", "Round of 16", "Round of 16", None),
    ("Group A - 2", "Group A", "Group A", 2),
    ("MLS Cup - Conference Semi-finals", "MLS Cup - Conference Semi-finals", "MLS Cup", None),
    (None, "", "", None),
])
def test_a_label_is_a_stage_and_a_match_day(label: str | None, stage: str, phase: str, day: int | None) -> None:
    assert stages.stage_of(label) == stage
    assert stages.phase_of(label) == phase
    assert stages.match_day_of(label) == day


def test_the_bracket_of_a_stage_is_its_phase_or_the_bare_family() -> None:
    # the Apertura's quarter-finals and the Clausura's are two brackets; "Quarter-finals" and "Final" are one
    assert stages.bracket_key("Apertura - Quarter-finals") == stages.bracket_key("Apertura - Final") == "Apertura"
    assert stages.bracket_key("Clausura - Final") == "Clausura"
    assert stages.bracket_key("Quarter-finals") == stages.bracket_key("Round of 16") == ""


def test_folding_removes_accents_and_case() -> None:
    assert stages.fold("Reclasificación") == stages.fold("RECLASIFICACION") == "reclasificacion"


# ── what a label says ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("label", "numbered", "kind", "role", "round_key", "teams"), [
    ("Regular Season", True, "league", "league", None, None),
    ("Apertura", True, "league", "league", None, None),
    ("Group Stage", True, "league", "group", None, None),
    ("League Stage", True, "league", "group", None, None),  # the Swiss-model league phase is a group stage
    ("Group A", True, "league", "group", None, None),
    ("Championship Round", True, "league", "league", None, None),
    ("Apertura - Quadrangular", True, "league", "league", None, None),
    ("Club Friendlies", False, "friendly", "friendly", None, None),
    ("Round of 16", False, "knockout", "knockout", "round_of_16", 16),
    ("Round of 32", False, "knockout", "knockout", "round_of_32", 32),
    ("8th Finals", False, "knockout", "knockout", "round_of_16", 16),
    ("16th Finals", False, "knockout", "knockout", "round_of_32", 32),
    ("1/8-finals", False, "knockout", "knockout", "round_of_16", 16),
    ("1/128-finals", False, "knockout", "knockout", "round_of_256", 256),
    ("Quarter-finals", False, "knockout", "knockout", "quarter_final", 8),
    ("Semi-finals", False, "knockout", "knockout", "semi_final", 4),
    ("Final", False, "knockout", "final", "final", 2),
    ("Grand Final", False, "knockout", "final", "final", 2),
    ("Clausura - Final", False, "knockout", "final", "final", 2),
    ("Apertura - Quarter-finals", False, "knockout", "knockout", "quarter_final", 8),
    ("MLS Cup - Conference Semi-finals", False, "knockout", "knockout", "semi_final", 4),
    ("3rd Place Final", False, "knockout", "third_place", "third_place", 2),
    ("Third Place", False, "knockout", "third_place", "third_place", 2),
    ("7th place", False, "knockout", "placement", "place_7", 2),
    ("Play-offs", False, "knockout", "playoff", "playoff", None),
    ("Play-In Round", False, "knockout", "playoff", "playoff", None),
    ("Relegation Decider", False, "knockout", "playoff", "playoff", None),
    ("Promotion Play-offs - Semi-finals", False, "knockout", "knockout", "semi_final", 4),
    ("Relegation Play-offs - Final", False, "knockout", "final", "final", 2),
    ("1st Round", False, "knockout", "knockout", "round_1", None),
    ("3rd Round", False, "knockout", "knockout", "round_3", None),
    ("2nd Qualifying Round", False, "qualifying", "qualifying", "round_2", None),
    ("Preliminary Round", False, "qualifying", "qualifying", "preliminary", None),
    ("Extra Preliminary Round", False, "qualifying", "qualifying", "extra_preliminary", None),
    ("Wild Card", False, "unresolved", "unresolved", None, None),
    ("R60310", False, "unresolved", "unresolved", None, None),
])
def test_what_a_label_says(label: str, numbered: bool, kind: str, role: str, round_key: str | None,
                           teams: int | None) -> None:
    reading = stages.classify(label, numbered=numbered)
    assert (reading.kind, reading.role, reading.round_key, reading.teams) == (kind, role, round_key, teams)
    assert reading.resolved is (kind != "unresolved")
    assert reading.is_knockout_like is (kind in ("knockout", "qualifying"))


def test_the_same_words_mean_a_league_stage_with_match_days_and_a_bracket_without() -> None:
    # CONCACAF's World Cup qualifying "Final Round - 3" is a round-robin; an unnumbered "Final Round" is a tie
    assert stages.classify("Final Round", numbered=True).kind == "league"
    assert stages.classify("Final Round", numbered=False).kind == "knockout"
    # a knock-out word still wins when the rounds carry a number (a cup's numbered quarter-finals)
    assert stages.classify("Quarter-finals", numbered=True).kind == "knockout"


def test_a_stage_of_replays_belongs_to_the_stage_it_replays() -> None:
    replays = stages.classify("1st Round Replays", numbered=False)
    assert replays.replay and replays.base == "1st Round" and replays.kind == "knockout"
    qualifying = stages.classify("1st Round Qualifying Replays", numbered=False)
    assert qualifying.replay and qualifying.base == "1st Round Qualifying" and qualifying.kind == "qualifying"
    assert not stages.classify("1st Round", numbered=False).replay


def test_an_unread_label_is_kept_and_says_so() -> None:
    reading = stages.classify("R60310", numbered=False)
    assert reading.stage == "R60310" and reading.rule == "no_rule" and not reading.resolved


# ── the real catalogue ──────────────────────────────────────────────────────


def test_the_catalogue_file_is_what_it_claims() -> None:
    rows = zoo()
    assert len(rows) == 277
    assert sum(n for n, _, _ in rows) == 245_872


def test_almost_every_fixture_of_the_real_catalogue_sits_in_a_stage_that_is_read() -> None:
    rows = zoo()
    total = sum(n for n, _, _ in rows)
    unread = sum(n for n, numbered, label in rows if not stages.classify(label, numbered=numbered).resolved)
    # 27 fixtures of 4 internal ids ("R60310") - and nothing else - were unread on 22 Oct 2026
    assert unread == 27
    assert unread / total < 0.0002
    unread_labels = {label for _, numbered, label in rows if not stages.classify(label, numbered=numbered).resolved}
    assert all(re.fullmatch(r"R\d+", label) for label in unread_labels)


def test_every_label_of_the_real_catalogue_has_a_consistent_reading() -> None:
    for _, numbered, label in zoo():
        reading = stages.classify(label, numbered=numbered)
        assert reading.stage == label and reading.phase == stages.phase_of(label)
        assert reading.base == (stages.REPLAYS.sub("", label).strip() if reading.replay else label)
        if reading.kind == "league":
            assert reading.role in ("league", "group") and reading.round_key is None
        if reading.kind == "friendly":
            assert reading.role == "friendly"
        if reading.kind in ("knockout", "qualifying"):
            assert reading.role not in ("league", "group", "friendly", "unresolved")
        if reading.round_key and reading.round_key.startswith("round_of_"):
            assert reading.teams == int(reading.round_key.rsplit("_", 1)[1])


# ── the standings keep reading stages as they did ───────────────────────────

_MATCH_DAY = re.compile(r"\s*-\s*\d+\s*$")
_KNOCKOUT = re.compile(
    r"final|play-?offs?|knockout|round of|quarter|semi|8th|16th|1/\d|qualifying|qualification|preliminary|"
    r"promotion|relegation (?:play|deciding)|third place|3rd place|super cup|repechage|elimination", re.IGNORECASE)
_STRICT = re.compile(r"final|semi|quarter|round of|1/\d|8th|16th|32nd|play-?offs?(?!\s*group)|knockout|"
                     r"repechage|third place|3rd place", re.IGNORECASE)
_LEAGUE_FORMAT = re.compile(
    r"\bgroups?\b|quadrangular|hexagonal|triangular|pentagonal|octagonal|league (?:stage|phase)|round robin|"
    r"championship round|relegation round|regular season", re.IGNORECASE)
_NUMBERED_LEAGUE = re.compile(r"final (?:round|stage|phase|tournament)", re.IGNORECASE)
_QUALIFYING = re.compile(r"qualif|preliminary", re.IGNORECASE)
_UNNUMBERED = re.compile(r"\b\d+(?:st|nd|rd|th) (?:round|phase)\b|\bround \d+\b", re.IGNORECASE)
_FRIENDLY = re.compile(r"friendl", re.IGNORECASE)


def phases_1_stage_kind(stage: str, *, numbered: bool) -> str:
    """``fbi.competitions.phases.stage_kind`` as it was in ``phases-1``, copied word for word and frozen: the
    reference the canonical reader is compared with."""
    if _FRIENDLY.search(stage):
        return "friendly"
    if _LEAGUE_FORMAT.search(stage):
        return "league"
    if numbered:
        return "knockout" if _STRICT.search(stage) and not _NUMBERED_LEAGUE.search(stage) else "league"
    if _QUALIFYING.search(stage):
        return "qualifying"
    if _KNOCKOUT.search(stage) or _UNNUMBERED.search(stage):
        return "knockout"
    return "league"


CHANGED_FROM_PHASES_1 = {
    # single matches and ties the league tables must not count: a play-in, the placement matches of a tournament,
    # a relegation decider, a Mexican "reclasificación" (the first knock-out round of a liguilla), play-offs
    "Play-In Round", "MLS Cup - Play-In Round", "Apertura - Reclasificación", "Clausura - Reclasificacion",
    "Relegation", "Relegation Decider", "Apertura - Play Offs", "Clausura - Play Offs",
    "5th place", "7th place", "9th place", "11th place", "13th place", "15th place", "17th place", "19th place",
    # internal ids the provider sometimes writes instead of a round name: read as nothing, not as a league
    "R60310", "R66244", "R79396", "R73389",
}


def test_the_canonical_reader_differs_from_phases_1_on_exactly_the_labels_that_were_decided() -> None:
    differing = {label for _, numbered, label in zoo()
                 if phases_1_stage_kind(label, numbered=numbered) != stages.classify(label, numbered=numbered).kind}
    assert differing == CHANGED_FROM_PHASES_1


def test_a_reading_that_was_changed_is_always_towards_knockout_or_unresolved() -> None:
    for _, numbered, label in zoo():
        old = phases_1_stage_kind(label, numbered=numbered)
        new = stages.classify(label, numbered=numbered).kind
        if old != new:
            assert old == "league" and new in ("knockout", "unresolved"), label


def test_the_standings_read_stages_through_the_canonical_reader() -> None:
    assert phases.VERSION == "phases-2"
    for _, numbered, label in zoo():
        canonical = stages.classify(label, numbered=numbered).kind
        expected = "league" if canonical == "unresolved" else canonical
        assert phases.stage_kind(label, numbered=numbered) == expected, label
    assert phases.stage_of("Apertura - 7") == stages.stage_of("Apertura - 7") == "Apertura"
