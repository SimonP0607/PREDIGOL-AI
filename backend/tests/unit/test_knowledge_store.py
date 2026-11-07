"""The Knowledge Store (``ks-v1``): each source's shape normalised to one record, the as-of rule in its pure parts, and the store's place in the shadow.

What a record is made of (kind, entity, aspect, a compact value, known_at, the source row and version, the confidence or status when the source has
one) is decided here from rows shaped like the database's; ``tests/integration/test_knowledge_store.py`` reads the real tables. The last tests hold
the store out of every decision path: it writes nothing, imports nothing of ours outside ``fbi.knowledge``, and ``fbi.intel.decision``, ``fbi.picks``,
``fbi.familydecisions.decide`` and ``fbi.api`` never import it - by their source and by what importing them loads."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.core import decision_versions as dv
from fbi.knowledge import store as ks

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
AT = datetime(2026, 11, 3, 12, tzinfo=UTC)
TEAM = ks.Entity("team", "7", "Club", ("7",), 33)


def test_compact_cuts_and_says_so() -> None:
    value = ks.compact({"a": list(range(25)), "n": Decimal("1.50"), "d": date(2026, 1, 2), "t": "x" * 1000, "deep": {"b": {"c": {"d": {"e": 1}}}}})
    assert value["a"][:ks.MAX_LIST] == list(range(ks.MAX_LIST)) and value["a"][-1] == {"_cut": "15 more of 25"}
    assert value["n"] == 1.5 and value["d"] == "2026-01-02" and len(value["t"]) == ks.MAX_TEXT + 1
    assert value["deep"]["b"]["c"] == {"d": {"_cut": "1 keys"}}


def test_a_bogota_day_is_known_once_it_is_over_there() -> None:
    assert ks.day_end(date(2026, 11, 2)) == datetime(2026, 11, 3, 5, tzinfo=UTC)
    assert ks.local_day(datetime(2026, 11, 3, 4, 59, tzinfo=UTC)) == date(2026, 11, 2)
    assert ks.local_day(datetime(2026, 11, 3, 5, tzinfo=UTC)) == date(2026, 11, 3)


def em_row(**kw: object) -> dict[str, object]:
    row: dict[str, object] = {"id": 11, "entity_type": "team", "entity_id": "7", "aspect": "market:1X2", "as_of_day": date(2026, 11, 1),
                              "built_at": datetime(2026, 11, 1, 23, tzinfo=UTC), "version": "memory-v4", "stats": {"settled": 3, "last10": list("WWLDWLWWLLW")},
                              "delta": {"settled": 1}, "confidence": Decimal("0.4120"), "evidence_ref": {"fixtures": [1, 2]}}
    row.update(kw)
    return row


def test_entity_memory_is_a_state_known_at_the_end_of_its_day_or_when_written() -> None:
    r = ks.from_entity_memory(em_row(), TEAM)
    assert (r.kind, r.entity_type, r.entity_id, r.aspect) == ("entity_state", "team", "7", "market:1X2")
    assert r.known_at == datetime(2026, 11, 2, 5, tzinfo=UTC), "written before the Bogota day was over: known when it was"
    assert r.source == ks.Source("intel.entity_memory", "11", "memory-v4") and r.confidence == pytest.approx(0.412)
    assert r.value["stats"]["last10"][-1] == {"_cut": "1 more of 11"} and r.value["evidence"] == {"fixtures": [1, 2]}
    rebuilt = ks.from_entity_memory(em_row(built_at=datetime(2026, 11, 5, tzinfo=UTC)), TEAM)
    assert rebuilt.known_at == datetime(2026, 11, 5, tzinfo=UTC), "a rebuilt row was not there before it was written"
    assert ks.from_entity_memory(em_row(confidence=None), TEAM).confidence is None


def test_family_memory_is_a_state_of_the_families() -> None:
    entity = ks.Entity("referee", "3", None, ("3",))
    row = {"id": 5, "version": "memory-fam-v1", "as_of_day": date(2026, 11, 1), "built_at": datetime(2026, 11, 2, 9, tzinfo=UTC), "entity_type": "referee",
           "entity_key": "3", "stats": {"all": {"n": 4}}, "delta": {}, "confidence": Decimal("0.2"), "evidence_ref": {"postmortems": 4}}
    r = ks.from_family_memory(row, entity)
    assert (r.kind, r.aspect, r.known_at, r.confidence) == ("entity_state", "families", datetime(2026, 11, 2, 9, tzinfo=UTC), 0.2)
    assert r.source.table == "intel.family_memory" and r.value["stats"] == {"all": {"n": 4}}


def ev_row(kind: str = "news_signal", **kw: object) -> dict[str, object]:
    row: dict[str, object] = {"id": 9, "created_at": AT - timedelta(days=1), "kind": kind, "entity_type": "player", "entity_id": "276", "fixture_id": 4,
                              "hypothesis": "a starter was missing", "evidence": {"side": "home"}, "result": "unreported absence", "confidence": 0.7,
                              "version": "mr-v1"}
    row.update(kw)
    return row


def test_an_ai_event_is_an_event_and_a_pattern_is_a_lesson() -> None:
    r = ks.from_memory_event(ev_row(), "player", "276")
    assert (r.kind, r.aspect, r.known_at, r.confidence, r.status) == ("event", "news_signal", AT - timedelta(days=1), 0.7, None)
    assert r.value["stored_as"] == "player:276" and r.value["fixture_id"] == 4
    assert ks.from_memory_event(ev_row("league_pattern"), "competition", "1").kind == "lesson"


def test_the_market_of_an_event_about_a_selection() -> None:
    assert ks.market_of("OU:Over:2.5") == "OU" and ks.market_of("1X2") == "1X2"


def mk_row(**kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 70, "fixture_id": 4, "version": "mk-v1", "supersedes": 69, "built_at": AT - timedelta(hours=2), "known_at": AT - timedelta(hours=5),
        "completeness": "partial", "quality": {"missing": ["c7_context"]},
        "layers": {"c1_result": {"status": "ok", "known_at": "2026-11-02T21:00:00Z", "sources": ["core.fixture_results"], "data": {"score": [2, 1]}},
                   "c7_context": {"status": "off"}},
    }
    row.update(kw)
    return row


def test_a_build_of_match_knowledge_is_one_episode_record_per_layer() -> None:
    records = ks.from_match_knowledge(mk_row())
    assert [r.aspect for r in records] == ["c1_result", "c7_context", "completeness"]
    result, context, whole = records
    assert result.kind == "episode" and result.entity_type == "fixture" and result.entity_id == "4"
    assert result.status == "ok" and result.valid_from == datetime(2026, 11, 2, 21, tzinfo=UTC) and result.value["data"] == {"score": [2, 1]}
    assert context.status == "off" and context.valid_from is None
    assert whole.status == "partial" and whole.value["supersedes"] == 69
    assert {r.known_at for r in records} == {AT - timedelta(hours=2)}, "a build is known once it was built, whatever it says it knew"
    assert all(r.source == ks.Source("intel.match_knowledge", "70", "mk-v1") for r in records)


def test_a_match_of_an_entity_is_its_result_layer() -> None:
    row = {"id": 70, "fixture_id": 4, "version": "mk-v1", "built_at": AT, "known_at": AT - timedelta(hours=1), "completeness": "complete",
           "kickoff_at": AT - timedelta(days=2), "result": {"status": "ok", "data": {"score": [0, 0]}}}
    r = ks.from_match_summary(row, TEAM)
    assert (r.kind, r.entity_type, r.aspect, r.status, r.known_at) == ("episode", "team", "match", "complete", AT)
    assert r.value == {"fixture_id": 4, "kickoff_at": (AT - timedelta(days=2)).isoformat(), "result": {"score": [0, 0]}}
    assert ks.from_match_summary({**row, "result": None}, TEAM).value["result"] == {}


def decision_row(**kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 3, "decision_version": dv.DECISION_FAMILIES, "known_at": AT - timedelta(days=2), "created_at": AT - timedelta(days=2),
        "checkpoint": "T-3h", "fixture_id": 4, "market_key": "CORNERS_OU", "selection": "Over", "line": Decimal("9.50"), "model_name": "corners",
        "odds": Decimal("1.910"), "p_model": Decimal("0.55"), "p_cal": None, "p_market": Decimal("0.5"), "score": None, "stake_units": Decimal("0"),
        "state": "INVESTIGACION", "reasons": ["shadow"], "settled_at": AT - timedelta(days=1), "computed_at": AT - timedelta(days=1),
        "result_status": "win", "profit_flat": Decimal("0.91"), "clv": Decimal("0.02"), "outcome_version": dv.OUTCOME_FAMILIES}
    row.update(kw)
    return row


def test_a_decision_says_its_layer_and_its_outcome_only_once_known() -> None:
    r = ks.from_decision(decision_row(), AT)
    assert (r.kind, r.entity_type, r.aspect, r.status) == ("event", "fixture", "decision:CORNERS_OU:Over:9.5", "INVESTIGACION")
    assert r.value["layer"] == "families" and r.value["outcome"]["result"] == "win" and r.source.version == dv.DECISION_FAMILIES
    late = ks.from_decision(decision_row(settled_at=AT + timedelta(minutes=1)), AT)
    assert late.value["outcome"] is None, "a settlement after the moment asked about was not known then"
    recomputed = ks.from_decision(decision_row(computed_at=AT + timedelta(minutes=1)), AT)
    assert recomputed.value["outcome"] is None
    unsettled = ks.from_decision(decision_row(settled_at=None, computed_at=None, result_status=None, profit_flat=None, clv=None), AT)
    assert unsettled.value["outcome"] is None
    assert ks.from_decision(decision_row(decision_version=dv.DECISION_CORE), AT).value["layer"] == "core"


def test_the_layers_are_the_platforms() -> None:
    assert dict(ks.DECISION_LAYERS) == dv.LAYERS, "the store keeps a copy of the layers (it imports nothing of ours); the copy must not drift"


def test_the_three_post_mortems_of_a_match() -> None:
    created = AT - timedelta(hours=3)
    selection = ks.from_postmortem({"id": 1, "fixture_id": 4, "created_at": created, "version": "pm-v6", "decision_id": 3, "market_key": "1X2",
                                    "selection": "Home", "line": Decimal("0"), "outcome": "won", "decision_quality": "GOOD", "verdict": "MERECIDO",
                                    "loss_class": None, "clv": Decimal("0.03"), "causes": []}, "intel.postmortems")
    assert (selection.aspect, selection.status, selection.known_at) == ("postmortem:1X2:Home:0.0", "MERECIDO", created)
    old = ks.from_postmortem({"id": 2, "fixture_id": 4, "created_at": created, "version": "pm-v5", "decision_id": 3, "market_key": None,
                              "outcome": "lost", "decision_quality": "BAD", "verdict": "ERROR", "causes": [{"code": "red_card"}]}, "intel.postmortems")
    assert old.aspect == "postmortem:decision" and old.value["causes"] == [{"code": "red_card"}]
    family = ks.from_postmortem({"id": 5, "fixture_id": 4, "created_at": created, "version": dv.POSTMORTEM_FAMILIES, "decision_id": 3, "family": "CORNERS",
                                 "market_key": "CORNERS_OU", "selection": "Over", "line": Decimal("9.5"), "result": "win", "quality": "GOOD",
                                 "verdict": "VARIANZA", "clv": None, "profit_flat": Decimal("0.9"), "causes": []}, "intel.family_postmortems")
    assert family.aspect == "postmortem:CORNERS:CORNERS_OU:Over:9.5" and family.status == "VARIANZA"
    match = ks.from_postmortem({"id": 8, "fixture_id": 4, "created_at": created, "version": "pm-v6", "outcome": {"score": "2-1"}, "findings": {}},
                               "intel.match_postmortems")
    assert (match.aspect, match.status, match.value["outcome"]) == ("postmortem:match", None, {"score": "2-1"})
    assert {r.kind for r in (selection, old, family, match)} == {"event"} and {r.entity_type for r in (selection, family, match)} == {"fixture"}


def hyp_row(**kw: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 12, "title": "League forecasts worse than the close", "hypothesis": "h", "target": "models", "proposed_by": "system",
        "evidence": {"competition_id": 1}, "status": "REJECTED", "created_at": AT - timedelta(days=5), "decided_at": AT - timedelta(days=2),
        "agent_version": None,
        "stage_history": [{"from": "PROPOSED", "to": "INVESTIGATING", "at": (AT - timedelta(days=3)).isoformat()},
                          {"from": "INVESTIGATING", "to": "REJECTED", "at": (AT + timedelta(days=1)).isoformat()}]}
    row.update(kw)
    return row


def test_a_hypothesis_has_the_status_it_had_then() -> None:
    entity = ks.Entity("competition", "1", None, ("1",))
    r = ks.from_hypothesis(hyp_row(), entity, AT)
    assert (r.kind, r.aspect, r.status, r.known_at) == ("hypothesis", "hypothesis:models", "INVESTIGATING", AT - timedelta(days=5))
    assert ks.status_as_of(hyp_row(), AT - timedelta(days=4)) == "PROPOSED"
    assert ks.status_as_of(hyp_row(), AT + timedelta(days=2)) == "REJECTED"
    assert ks.status_as_of(hyp_row(stage_history=[]), AT) == "REJECTED", "decided by then with no history: the status it has"
    assert ks.status_as_of(hyp_row(stage_history=[], decided_at=AT + timedelta(hours=1)), AT) == "PROPOSED"


def test_a_spell_seen_before_it_ended_is_open() -> None:
    row = {"provider_player_id": 276, "ordinal": 2, "provider_team_id": 33, "team_id": 7, "team_name": "Club", "valid_from": date(2025, 7, 1),
           "valid_to": date(2026, 12, 1), "source": "transfer", "matches": 40, "via": None, "version": "spells-v1", "built_at": AT - timedelta(days=9)}
    r = ks.from_spell(row, AT, entity=TEAM)
    assert (r.kind, r.aspect, r.valid_from, r.valid_to, r.known_at) == ("relation", "player-club", date(2025, 7, 1), None, AT - timedelta(days=9))
    assert r.source == ks.Source("core.player_spells", "276:2", "spells-v1") and r.value["start_known"] is True
    ended = ks.from_spell({**row, "valid_to": date(2026, 10, 1)}, AT, entity=TEAM)
    assert ended.valid_to == date(2026, 10, 1)


def test_caps_careers_and_officials() -> None:
    player = ks.Entity("player", "276", None, ("276",))
    caps = ks.from_caps({"provider_player_id": 276, "team_id": 9, "team_name": "Colombia", "caps": 3, "appeared": 2, "starts": 1,
                         "first_kickoff": AT - timedelta(days=90), "last_kickoff": AT - timedelta(days=30), "built_at": AT - timedelta(days=29),
                         "version": "caps-v1"}, entity=player)
    assert (caps.aspect, caps.value["caps"], caps.valid_to, caps.known_at) == ("player-national_team", 3, AT - timedelta(days=30), AT - timedelta(days=29))
    coach = ks.Entity("coach", "5", None, ("5", "p88"), 88)
    observed = AT - timedelta(days=4)
    career = ks.from_career({"provider_coach_id": 88, "coach_id": 5, "provider_team_id": 33, "team_id": 7, "team_name": "Club", "ordinal": 0,
                             "start_date": date(2025, 1, 1), "end_date": date(2027, 6, 30), "observed_at": observed, "normalizer_version": "n1"},
                            AT, entity=coach)
    assert (career.aspect, career.valid_to, career.known_at, career.source.version) == ("coach-club", None, observed, "n1")
    official = ks.from_official({"referee_id": 3, "fixture_id": 4, "alias_id": 8, "home_team_id": 7, "away_team_id": 8, "observed_at": observed,
                                 "kickoff_at": AT - timedelta(days=5)}, entity_type="referee", entity_id="3")
    assert (official.aspect, official.value["fixture_id"], official.valid_from) == ("referee-match", 4, AT - timedelta(days=5))


def test_the_second_guard_drops_anything_known_after() -> None:
    now = ks.from_memory_event(ev_row(created_at=AT), "player", "276")
    later = ks.from_memory_event(ev_row(created_at=AT + timedelta(microseconds=1)), "player", "276")
    assert ks._cut([now, later], AT) == [now]


def test_a_record_and_an_answer_as_plain_data() -> None:
    r = ks.from_entity_memory(em_row(), TEAM)
    answer = ks.Answer(TEAM, AT, (r,), (ks.Absent("intel.family_memory", "not_held", "why"),), {"ai.memory_events": 3})
    data = answer.as_dict()
    assert data["version"] == ks.VERSION and data["counts"] == {"entity_state": 1} and data["entity"]["canonical"] == "core.teams.id"
    assert data["records"][0]["known_at"] == "2026-11-02T05:00:00+00:00" and data["records"][0]["valid_from"] == "2026-11-01"
    assert data["absent"] == [{"source": "intel.family_memory", "reason": "not_held", "detail": "why"}] and data["truncated"] == {"ai.memory_events": 3}
    assert ks.dumps(data).startswith("{")


def test_overlap_counts_pairs_only_and_gaps() -> None:
    block = ks.overlap({"a": {"1", "2", "3"}, "b": {"2", "3", "4"}, "c": {"3"}})
    assert block["sources"] == {"a": 3, "b": 3, "c": 1} and block["union"] == 4 and block["in_every_source"] == 1
    assert block["pairs"] == {"a & b": 2, "a & c": 1, "b & c": 1}
    assert block["only_in"] == {"a": 1, "b": 1, "c": 0} and block["missing_from"] == {"a": 1, "b": 1, "c": 3}
    assert ks.overlap({})["union"] == 0


def test_every_source_that_cannot_hold_a_type_says_why() -> None:
    for source, types in ks.HOLDS.items():
        if set(types) != set(ks.ENTITY_TYPES):
            assert ks.WHY_NOT.get(source), source
    assert set(ks.COVERAGE_SQL) == set(ks.ENTITY_TYPES)


def test_a_naive_moment_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone"):
        ks._check(datetime(2026, 11, 3))  # noqa: DTZ001


def test_the_command_reads_its_arguments_and_prints_an_answer() -> None:
    from scripts import ia_knowledge as cli

    args = cli.parser().parse_args(["about", "--type", "referee", "--id", "3", "--at", "2026-11-01T12:00:00Z", "--aspect", "discipline", "--json"])
    assert (args.type, args.id, args.at, args.aspects, args.json) == ("referee", "3", datetime(2026, 11, 1, 12, tzinfo=UTC), ["discipline"], True)
    assert cli.moment("2026-11-01T12:00:00").tzinfo is UTC
    answer = ks.Answer(TEAM, AT, (ks.from_entity_memory(em_row(), TEAM),), (ks.Absent("intel.family_memory", "not_held", "why"),), {"x": 2})
    text = cli.text_of_answer(answer.as_dict())
    assert "team 7 - Club" in text and "[entity_state] market:1X2" in text and "absent  intel.family_memory: not_held" in text and "x: 2" in text
    report = {"version": ks.VERSION, "types": {"referee": {**ks.overlap({"a": {"1"}, "b": {"1", "2"}}), "not_held_by": ["c"], "legacy_string_keys": 4}}}
    assert "referee: 2 entities in all" in cli.text_of_coverage(report) and "keyed by a string (not counted): 4" in cli.text_of_coverage(report)


# ── in shadow ────────────────────────────────────────────────────────────────────────────────────────────────────────

WRITES = re.compile(r"\b(?:INSERT\s+INTO|DELETE\s+FROM|UPDATE|TRUNCATE|ALTER\s+TABLE|CREATE|DROP|COPY|MERGE\s+INTO)\s+[A-Za-z_]", re.IGNORECASE)


def code_strings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef)
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_the_store_and_its_command_write_nothing() -> None:
    for path in (SRC / "knowledge" / "store.py", ROOT / "scripts" / "ia_knowledge.py"):
        sql = [" ".join(s.split()) for s in code_strings(path) if re.search(r"\b(?:SELECT|FROM)\b", s)]
        assert len(sql) >= (10 if path.name == "store.py" else 0)
        assert not [s for s in sql if WRITES.search(s)], f"{path.name} holds a statement that writes"
        assert "commit(" not in path.read_text(encoding="utf-8")
    assert "conn.read_only = True" in (ROOT / "scripts" / "ia_knowledge.py").read_text(encoding="utf-8")


def imports_of(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
    return found


def test_the_store_imports_nothing_of_ours_outside_its_package() -> None:
    ours = {n for n in imports_of(SRC / "knowledge" / "store.py") if n.startswith("fbi.")}
    assert ours and all(n.startswith("fbi.knowledge") for n in ours), ours


DECISION_PATHS = ("intel/decision.py", "picks", "familydecisions/decide.py", "api")


def test_no_decision_path_names_the_store() -> None:
    files = [p for d in DECISION_PATHS for p in ((SRC / d).rglob("*.py") if (SRC / d).is_dir() else [SRC / d])]
    assert len(files) > 50 and all(p.exists() for p in files)
    for path in files:
        names = imports_of(path)
        assert "fbi.knowledge.store" not in names, f"{path.relative_to(SRC)} imports the Knowledge Store"
        assert "knowledge.store" not in path.read_text(encoding="utf-8"), f"{path.relative_to(SRC)} names the Knowledge Store"


def test_importing_the_decision_paths_does_not_load_the_store() -> None:
    """Transitively too: whatever ``fbi.intel.decision``, the pick engine, the families' decision and the whole API import, the store is not among it."""
    code = (
        "import importlib, pkgutil, sys\n"
        "import fbi.intel.decision, fbi.familydecisions.decide, fbi.picks, fbi.api\n"
        "for pkg in (fbi.picks, fbi.api):\n"
        "    for m in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + '.'):\n"
        "        importlib.import_module(m.name)\n"
        "print('fbi.knowledge.store' in sys.modules)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=240, check=False)
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1] == "False"
