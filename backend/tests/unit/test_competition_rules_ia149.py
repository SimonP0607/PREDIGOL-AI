"""IA-149 (plan PM, PM-03-09): the regulations of the Torneo (Primera B, 240) and the Copa (241) 2026 coded IN SHADOW - the files
validate and carry the PDF's SHA-256, ``rules_for`` keeps answering «reglamento no codificado» (``pending_review``) to every
reader, and only the read-only shadow tools see them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from scripts import ia_rules

from fbi.competitions import rules as rl
from fbi.competitions import season_tables as st

TORNEO, COPA = 240, 241

# The provider's round labels of season 2026 in production (core.fixtures, read-only, 20-nov-2026 21:09 UTC).
LABELS_240 = ["Apertura - 1", "Apertura - 15", "Apertura Quadrangular - 1", "Apertura Quadrangular - 6", "Apertura - Final",
              "Clausura - 1", "Clausura - 15", "Clausura - Quadrangular - 1", "Clausura - Quadrangular - 6"]
LABELS_241 = ["Group Stage - 1", "Group Stage - 5", "Play-offs", "Round of 16", "Quarter-finals", "Semi-finals"]


def _shadow(league: int) -> rl.Coded:
    answer = rl.rules_for(league, 2026, include_shadow=True)
    assert isinstance(answer, rl.Coded)
    return answer


# ── what a reader gets: nothing new ─────────────────────────────────────────


@pytest.mark.parametrize("league", [TORNEO, COPA])
def test_a_reader_still_gets_reglamento_no_codificado_pending_the_cotejo(league: int) -> None:
    answer = rl.rules_for(league, 2026)
    assert isinstance(answer, rl.NotCoded)
    assert answer.status == "reglamento_no_codificado" and answer.reason == "pending_review"
    assert "cotejo" in answer.detail.lower() and "IA_149_COTEJO" in answer.detail
    entry = rl.library().coverage.entry(league)
    assert entry is not None and entry.status == "not_coded" and entry.reason == "pending_review"


def test_a_coded_answer_of_another_competition_is_unchanged() -> None:
    answer = rl.rules_for(239, 2026)
    assert isinstance(answer, rl.Coded)
    assert set(answer.as_json()) == {"status", "league_id", "season", "version", "file", "sha256", "gaps", "reader"}


def test_nothing_the_scenarios_or_the_profiles_read_is_coded_for_them() -> None:
    lib = rl.library()
    coded = {f.rules.league_id for f in lib.files if f.rules.state == "coded"}  # scenario_store.live_seasons
    assert TORNEO not in coded and COPA not in coded
    assert rl.summary(lib)["shadow_versions"] == ["240 v1", "241 v1"]


# ── what the shadow tools get ───────────────────────────────────────────────


@pytest.mark.parametrize(("league", "sha", "edition"), [
    (TORNEO, "abe959c6811bcc989b8ba97f09a3281864a50b8c19a864162c557b993c32d319", "V0 - 21/01/26"),
    (COPA, "ebfcac5d1de5f61a317304ac76a2fa78523b5ddce5a744ddcd740db2bf25b413", "V1 - 25/08/26"),
])
def test_the_shadow_version_answers_with_the_pdf_fingerprint(league: int, sha: str, edition: str) -> None:
    answer = _shadow(league)
    out = answer.as_json()
    assert out["status"] == "coded" and out["state"] == "shadow" and "cotejo" in out["pending"].lower()
    source = answer.rules.sources[0]
    assert source.sha256 == sha and source.edition == edition
    assert source.url.startswith("https://dimayor.com.co/wp-content/uploads/2026/")


def test_every_label_of_2026_falls_in_exactly_one_phase() -> None:
    for league, labels in ((TORNEO, LABELS_240), (COPA, LABELS_241)):
        rules = _shadow(league).rules
        for label in labels:
            owners = [(t.key, p.key) for t, p in rules.phases() if p.covers(label)]
            assert len(owners) == 1, (league, label, owners)


def test_torneo_has_the_two_spellings_of_the_cuadrangulares_and_its_tables() -> None:
    rules = _shadow(TORNEO).rules
    first = rules.phase_of_round("Apertura Quadrangular - 3")
    second = rules.phase_of_round("Clausura - Quadrangular - 3")
    assert first is not None and second is not None
    assert (first[0].key, first[1].key, second[0].key, second[1].key) == ("torneo_i", "cuadrangulares", "torneo_ii",
                                                                          "cuadrangulares")
    _t, fase_1 = rules.phase("torneo_i.fase_1")
    assert (fase_1.teams, fase_1.matches_per_team) == (16, 15)
    assert {t.key for t in rules.tables} == {"tabla_torneo_i", "tabla_torneo_ii", "reclasificacion"}
    assert rules.table("reclasificacion").counts == ("torneo_i.*", "torneo_ii.*")
    assert rules.gap("promotion") is not None  # arts. 19-25 said, never computed


def test_copa_v1_plays_the_round_of_16_and_the_quarter_finals_in_one_match() -> None:
    rules = _shadow(COPA).rules
    legs = {p.key: (p.knockout.legs, p.knockout.level) for _t, p in rules.phases() if p.knockout is not None}
    assert legs == {
        "fase_1b": (2, ("points_over_legs", "aggregate", "penalties")),
        "octavos": (1, ("penalties",)),  # art. 17: no extra time; V5 had two legs
        "cuartos": (1, ("penalties",)),
        "semifinales": (2, ("points_over_legs", "aggregate", "penalties")),
        "final": (2, ("points_over_legs", "aggregate", "penalties")),
    }
    _t, groups = rules.phase("copa.fase_1a")
    assert (groups.groups, groups.group_size, groups.matches_per_team) == (4, 5, 4)
    assert [s.sha256 is not None for s in rules.sources] == [True, True]  # V1 and the V5 it replaced
    assert rules.gap("continental") is not None  # art. 18 stays the 239 file's cup_winner slot


def test_the_season_tables_compute_from_the_shadow_file() -> None:
    rules = _shadow(TORNEO).rules
    final = [st.Match(2026, 1, "Apertura - Final", "FT", 10, 20, 2, 3),
             st.Match(2026, 2, "Apertura - Final", "FT", 20, 10, 1, 1)]
    reading = st.compute(rules, 2026, final)
    assert reading.champions["torneo_i"]["team"] == 20  # 4 points to 1 over the legs (Envigado, 26-29 May 2026)
    assert reading.champions["torneo_ii"]["team"] is None


# ── the schema and the validator ────────────────────────────────────────────


MINIMAL = {
    "schema": "competition-rules/1", "league_id": 999, "competition": "Test League", "country": "Nowhere", "version": 1,
    "seasons": [2026],
    "sources": [{"publisher": "Test FA", "title": "Test regulation", "url": "https://example.org/r.pdf",
                 "checked_at": "2026-11-20", "applies_to": "season 2026", "sha256": "0" * 64}],
    "tournaments": [{"key": "season", "name": "Season", "phases": [{
        "key": "league", "name": "League", "format": "league", "rounds": ["Regular Season - *"], "teams": 4,
        "schedule": "double_round_robin", "ranking": {"tiebreakers": ["goal_difference", "lots"]}}]}],
}


def _write(root: Path, data: dict[str, object], *, reason: str = "pending_review") -> None:
    (root / "999_test_league").mkdir(parents=True, exist_ok=True)
    (root / "999_test_league" / "v1.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    (root / rl.COVERAGE_FILE).write_text(yaml.safe_dump({
        "schema": "competition-rules-coverage/1", "measured_at": "2026-11-20", "measured_from": "a test, not production",
        "competitions": [{"league_id": 999, "name": "Test League", "country": "Nowhere", "type": "league",
                          "status": "not_coded", "reason": reason, "detail": "waiting"}]}), encoding="utf-8")


@pytest.mark.parametrize(("change", "fragment"), [
    ({"state": "shadow"}, "says what it waits for"),
    ({"pending": "the cotejo"}, "only a shadow version"),
    ({"state": "shadow", "pending": "x", "retired_reason": "no"}, "retired_reason only"),
])
def test_the_schema_refuses_a_shadow_version_without_its_wait(change: dict[str, object], fragment: str, tmp_path: Path) -> None:
    _write(tmp_path, {**MINIMAL, **change})
    with pytest.raises(rl.RulesError, match=fragment):
        rl.load_files(tmp_path)


def test_a_bad_fingerprint_is_refused(tmp_path: Path) -> None:
    data = yaml.safe_load(yaml.safe_dump(MINIMAL))
    data["sources"][0]["sha256"] = "not-a-hash"
    _write(tmp_path, data)
    with pytest.raises(rl.RulesError, match="sha256"):
        rl.load_files(tmp_path)


def test_the_validator_ties_a_shadow_file_to_pending_review(tmp_path: Path) -> None:
    shadow = {**MINIMAL, "state": "shadow", "pending": "the owner's cotejo"}
    _write(tmp_path, shadow)
    assert rl.validate(tmp_path) == []
    lib = rl.Library.read(tmp_path)
    assert isinstance(lib.rules_for(999, 2026), rl.NotCoded)
    assert isinstance(lib.rules_for(999, 2026, include_shadow=True), rl.Coded)
    _write(tmp_path, shadow, reason="not_yet_coded")
    assert any("pending_review" in p for p in rl.validate(tmp_path))
    _write(tmp_path, MINIMAL)  # a coded file listed as pending_review
    problems = rl.validate(tmp_path)
    assert any("is pending_review and has no shadow file" in p for p in problems)


# ── the command line ────────────────────────────────────────────────────────


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, object]]:
    code = ia_rules.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_show_needs_shadow_to_answer_the_shadow_version(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "show", "--league", "241", "--season", "2026")
    assert code == 0 and out["status"] == "reglamento_no_codificado" and out["reason"] == "pending_review"
    code, out = _run(capsys, "show", "--league", "241", "--season", "2026", "--shadow")
    assert code == 0 and out["status"] == "coded" and out["state"] == "shadow"
    assert out["rules"]["sources"][0]["sha256"].startswith("ebfcac5d")  # type: ignore[index]


def test_load_never_records_a_shadow_version(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(capsys, "load", "--dry-run")
    assert code == 0
    planned = out["planned"]
    assert isinstance(planned, list) and {p["league_id"] for p in planned}.isdisjoint({TORNEO, COPA})
    assert out["shadow_not_recorded"] == [
        {"league_id": 240, "version": 1, "file": "240_primera_b_colombia/v1.yaml"},
        {"league_id": 241, "version": 1, "file": "241_copa_colombia/v1.yaml"}]
