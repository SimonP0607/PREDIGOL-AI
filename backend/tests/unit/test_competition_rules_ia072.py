"""IA-072 (AD-B01): the competition rules as data - the schema refuses what is not a rule read from a source, the coverage names
every tracked competition, and ``rules_for`` answers the version in force or «reglamento no codificado» with its reason."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from fbi.competitions import rules as rl

MINIMAL = {
    "schema": "competition-rules/1", "league_id": 999, "competition": "Test League", "country": "Nowhere", "version": 1,
    "seasons": [2026],
    "sources": [{"publisher": "Test FA", "title": "Test regulation", "url": "https://example.org/r.pdf",
                 "checked_at": "2026-11-16", "applies_to": "season 2026"}],
    "tournaments": [{"key": "season", "name": "Season", "phases": [{
        "key": "league", "name": "League", "format": "league", "rounds": ["Regular Season - *"], "teams": 4,
        "schedule": "double_round_robin", "ranking": {"tiebreakers": ["goal_difference", "goals_for", "lots"]},
        "zones": [{"kind": "champion", "from": 1, "to": 1}, {"kind": "relegation", "last": 1}]}]}],
}


def _write(root: Path, folder: str, name: str, data: dict[str, object]) -> None:
    (root / folder).mkdir(parents=True, exist_ok=True)
    (root / folder / name).write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _coverage(root: Path, *entries: dict[str, object]) -> None:
    (root / rl.COVERAGE_FILE).write_text(yaml.safe_dump({
        "schema": "competition-rules-coverage/1", "measured_at": "2026-11-16",
        "measured_from": "a test, not production at all", "competitions": list(entries)}), encoding="utf-8")


def _variant(**changes: object) -> dict[str, object]:
    data = yaml.safe_load(yaml.safe_dump(MINIMAL))
    data.update(changes)
    return data


# ── the repository's own files ──────────────────────────────────────────────


def test_the_repository_rules_and_coverage_validate() -> None:
    assert rl.validate() == []


def test_the_coverage_lists_the_83_tracked_leagues_each_coded_or_with_a_reason() -> None:
    lib = rl.Library.read()
    leagues = [c for c in lib.coverage.competitions if c.type == "league"]
    assert len(leagues) == 83  # 81 on 16-nov-2026, plus Venezuela (299) and Colombia's Primera B (240) on 19-nov (PM-00-02)
    assert all(c.status == "coded" or (c.reason and c.detail) for c in lib.coverage.competitions)
    coded = {c.league_id for c in lib.coverage.competitions if c.status == "coded"}
    # the five big European leagues, Colombia, Brazil, Argentina, MLS, Liga MX - and the Champions League among the cups
    assert coded == {39, 140, 135, 78, 61, 239, 71, 128, 253, 262, 2}
    libertadores = lib.coverage.entry(13)
    assert libertadores is not None and libertadores.status == "not_coded" and libertadores.reason == "source_unreachable"


def test_every_coded_file_links_an_official_https_source_checked_on_a_day() -> None:
    for f in rl.load_files():
        assert f.rules.sources, f.path
        for s in f.rules.sources:
            assert s.url.startswith("https://") and s.checked_at >= date(2026, 11, 16), f.path


def test_no_regulation_text_is_kept_only_parameters_and_notes() -> None:
    for f in rl.load_files():
        raw = (rl.RULES_DIR / f.path).read_text(encoding="utf-8")
        assert len(raw) < 16_000, f"{f.path}: a rules file holds parameters and links, not the regulation"


# ── the reader ──────────────────────────────────────────────────────────────


def test_a_competition_without_a_file_is_reglamento_no_codificado_with_the_coverage_reason() -> None:
    answer = rl.rules_for(13, 2026)
    assert isinstance(answer, rl.NotCoded)
    assert answer.status == "reglamento_no_codificado" and answer.reason == "source_unreachable" and "403" in answer.detail
    unknown = rl.rules_for(424242, 2026)
    assert isinstance(unknown, rl.NotCoded) and unknown.reason == "not_yet_coded"
    assert unknown.as_json()["status"] == "reglamento_no_codificado"


def test_a_season_the_file_does_not_cover_is_not_coded_never_borrowed_from_another_season() -> None:
    answer = rl.rules_for(61, 2026)  # Ligue 1: only the 2025/26 regulation was read
    assert isinstance(answer, rl.NotCoded) and answer.reason == "season_not_covered"
    assert isinstance(rl.rules_for(61, 2025), rl.Coded)
    assert isinstance(rl.rules_for(239, 2025), rl.NotCoded)  # Colombia: only 2026


def test_serie_a_and_liga_mx_answer_a_version_per_season() -> None:
    a25, a26 = rl.rules_for(135, 2025), rl.rules_for(135, 2026)
    assert isinstance(a25, rl.Coded) and isinstance(a26, rl.Coded)
    assert (a25.rules.version, a26.rules.version) == (1, 2)
    assert "244/A" in a26.rules.sources[0].title and "331/A" in a25.rules.sources[0].title


def test_colombia_2026_changes_format_inside_the_year_and_the_round_label_says_which() -> None:
    answer = rl.rules_for(239, 2026)
    assert isinstance(answer, rl.Coded)
    r = answer.rules
    found_i = r.phase_of_round("Apertura - Quarter-finals")
    found_ii = r.phase_of_round("Clausura - Quadrangular - 3")
    assert found_i is not None and found_ii is not None
    t1, p1 = found_i
    t2, p2 = found_ii
    assert (t1.key, p1.key, p1.format) == ("liga_i", "cuartos", "knockout")
    assert (t2.key, p2.key, p2.format, p2.groups, p2.group_size) == ("liga_ii", "cuadrangulares", "groups", 2, 4)
    assert r.phase_of_round("Apertura - 7") == r.phase("liga_i.fase_1")
    assert r.phase_of_round("Clausura - 19") == r.phase("liga_ii.fase_1")
    assert r.phase_of_round("Clausura - Quadrangular - 3") != r.phase_of_round("Apertura - Semi-finals")
    descenso = r.table("descenso")
    assert (descenso.kind, descenso.metric, descenso.seasons) == ("average", "points_per_match", 3)
    assert descenso.zones[0].positions(20) == range(19, 21)
    reclas = r.table("reclasificacion")
    assert reclas.counts == ("liga_i.*", "liga_ii.*") and all(z.conditional for z in reclas.zones)


def test_liga_mx_dropped_the_play_in_between_the_apertura_2025_and_the_clausura_2026() -> None:
    v1 = rl.rules_for(262, 2025)
    v2 = rl.rules_for(262, 2026)
    assert isinstance(v1, rl.Coded) and isinstance(v2, rl.Coded)
    ap = v1.rules.phase("apertura.calificacion")[1]
    cl = v1.rules.phase("clausura.calificacion")[1]
    assert [(z.kind, z.from_, z.to) for z in ap.zones] == [("next_phase", 1, 6), ("playoff_place", 7, 10)]
    assert [(z.kind, z.from_, z.to) for z in cl.zones] == [("next_phase", 1, 8)]
    assert v1.rules.phase_of_round("Apertura - Play-In Final") == v1.rules.phase("apertura.play_in")
    assert v2.rules.phase_of_round("Apertura - Play-In Final") is None
    assert [z.to for z in v2.rules.phase("apertura.calificacion")[1].zones] == [8]


def test_argentina_relegation_is_a_listed_gap_not_a_rule() -> None:
    answer = rl.rules_for(128, 2026)
    assert isinstance(answer, rl.Coded)
    gap = answer.rules.gap("relegation")
    assert gap is not None and "93" in gap.reason
    assert not any(z.kind == "relegation" for _t, p in answer.rules.phases() for z in p.zones)
    assert answer.as_json()["gaps"][0]["topic"] == "relegation"


def test_the_version_in_force_on_a_day(tmp_path: Path) -> None:
    _write(tmp_path, "999_test_league", "v1.yaml", _variant(valid_to="2026-06-30"))
    later = _variant(version=2, valid_from="2026-07-01")
    later["tournaments"][0]["phases"][0]["zones"] = [{"kind": "champion", "from": 1, "to": 2}]  # type: ignore[index]
    _write(tmp_path, "999_test_league", "v2.yaml", later)
    _coverage(tmp_path, {"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league", "status": "coded"})
    assert rl.validate(tmp_path) == []
    lib = rl.Library.read(tmp_path)
    march, september = lib.rules_for(999, 2026, on=date(2026, 3, 1)), lib.rules_for(999, 2026, on=date(2026, 9, 1))
    assert isinstance(march, rl.Coded) and isinstance(september, rl.Coded)
    assert (march.rules.version, september.rules.version) == (1, 2)
    newest = lib.rules_for(999, 2026)
    assert isinstance(newest, rl.Coded) and newest.rules.version == 2


def test_a_retired_version_answers_not_coded_with_its_reason(tmp_path: Path) -> None:
    _write(tmp_path, "999_test_league", "v1.yaml", _variant(state="retired", retired_reason="the zone was misread"))
    _coverage(tmp_path, {"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league", "status": "not_coded",
                         "reason": "version_retired", "detail": "v1 retired: the zone was misread"})
    lib = rl.Library.read(tmp_path)
    answer = lib.rules_for(999, 2026)
    assert isinstance(answer, rl.NotCoded) and answer.reason == "version_retired" and "misread" in answer.detail


# ── the validator refuses what is not a rule from a source ──────────────────


@pytest.mark.parametrize(("change", "fragment"), [
    ({"sources": []}, "sources"),
    ({"sources": [{"publisher": "X FA", "title": "Rules", "url": "http://insecure.example/r.pdf", "checked_at": "2026-11-16",
                   "applies_to": "2026"}]}, "url"),
    ({"state": "retired"}, "retired version says why"),
    ({"seasons": [2026, 2026]}, "distinct"),
    ({"surprise": 1}, "Extra inputs"),
])
def test_the_schema_refuses(change: dict[str, object], fragment: str, tmp_path: Path) -> None:
    _write(tmp_path, "999_test_league", "v1.yaml", _variant(**change))
    with pytest.raises(rl.RulesError, match=fragment):
        rl.load_files(tmp_path)


def test_a_terminal_criterion_ends_the_list_and_zones_stay_inside_the_table(tmp_path: Path) -> None:
    bad = _variant()
    bad["tournaments"][0]["phases"][0]["ranking"] = {"tiebreakers": ["lots", "goal_difference"]}  # type: ignore[index]
    _write(tmp_path, "999_test_league", "v1.yaml", bad)
    with pytest.raises(rl.RulesError, match="ends the list"):
        rl.load_files(tmp_path)
    bad = _variant()
    bad["tournaments"][0]["phases"][0]["zones"] = [{"kind": "relegation", "from": 4, "to": 6}]  # type: ignore[index]
    _write(tmp_path, "999_test_league", "v1.yaml", bad)
    with pytest.raises(rl.RulesError, match="beyond a table"):
        rl.load_files(tmp_path)


def test_the_validator_ties_files_to_the_coverage(tmp_path: Path) -> None:
    _write(tmp_path, "999_test_league", "v1.yaml", MINIMAL)
    _coverage(tmp_path, {"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league", "status": "not_coded",
                         "reason": "not_yet_coded", "detail": "pending"},
              {"league_id": 5, "name": "Other", "country": "Nowhere", "type": "league", "status": "coded"})
    problems = rl.validate(tmp_path)
    assert any("says league 999 is not coded" in p for p in problems)
    assert any("league 5 is marked coded and has no coded file" in p for p in problems)
    _coverage(tmp_path, {"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league", "status": "not_coded"})
    assert any("says why" in p for p in rl.validate(tmp_path))


def test_two_versions_cannot_answer_for_the_same_season_on_the_same_days(tmp_path: Path) -> None:
    _write(tmp_path, "999_test_league", "v1.yaml", MINIMAL)
    _write(tmp_path, "999_test_league", "v2.yaml", _variant(version=2))
    _coverage(tmp_path, {"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league", "status": "coded"})
    assert any("both answer" in p for p in rl.validate(tmp_path))


def test_summary_reports_coverage_and_what_production_tracks_that_is_missing() -> None:
    lib = rl.Library.read()
    s = rl.summary(lib, {39: "Premier League", 777777: "Not listed"})
    assert s["leagues"] == 83 and s["leagues_coded"] == 10 and s["tracked_missing_from_coverage"] == [777777]
    assert s["not_coded_by_reason"]["source_unreachable"] == 1
