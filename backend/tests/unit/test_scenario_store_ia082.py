"""The shadow side of the scenarios engine (IA-082): the switch is off by default (and anything unknown is off), the goal model is
fitted only on results known three hours after kick-off inside the spec's window and leaves a team it does not know without a
distribution, the input hash changes with any input, the comparison with stakes-v5 says what it contradicts, and migration 0147 adds
one append-only table and nothing else. The database side is exercised in ``tests/integration/test_migration_0147_scenario_readings.py``."""

from __future__ import annotations

import importlib.util
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from fbi.competitions import rules as rl
from fbi.competitions import scenario_compare as cmp
from fbi.competitions import scenario_store as store
from fbi.competitions import scenarios as sc

ROOT = Path(__file__).resolve().parents[2]
AT = datetime(2026, 11, 16, 12, tzinfo=UTC)
SPEC = store.GoalSpec(0.002, 1.0, 730)


@pytest.mark.parametrize(("value", "expected"), [(None, "off"), ("", "off"), ("shadow", "shadow"), (" SHADOW ", "shadow"),
                                                 ("on", "off"), ("1", "off")])
def test_the_switch_is_off_unless_it_says_shadow(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: str) -> None:
    if value is None:
        monkeypatch.delenv(store.SWITCH, raising=False)
    else:
        monkeypatch.setenv(store.SWITCH, value)
    assert store.mode() == expected


def test_the_shadow_step_does_nothing_with_the_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(store.SWITCH, raising=False)

    class Boom:
        def cursor(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("the database is not touched with the switch off")

    assert store.run_shadow(Boom(), at=AT) == {"skipped": "switch_off"}  # type: ignore[arg-type]


def _history(n_rounds: int = 12) -> list[store.Played]:
    rng = np.random.default_rng(1)
    teams = list(range(1, 11))
    out: list[store.Played] = []
    day = AT - timedelta(days=400)
    for _ in range(n_rounds):
        for h in teams:
            for a in teams:
                if h != a and rng.random() < 0.2:
                    out.append(store.Played(day, h, a, int(rng.poisson(1.5)), int(rng.poisson(1.1))))
                    day += timedelta(hours=7)
    return out


def test_the_model_is_fitted_on_what_was_known_and_gives_a_distribution_per_match() -> None:
    history = _history()
    late = store.Played(AT - timedelta(hours=1), 1, 2, 9, 0)  # kicked off an hour ago: not known yet
    old = store.Played(AT - timedelta(days=800), 1, 2, 9, 0)  # outside the window
    targets = [store.Target(1, 1, 2), store.Target(2, 3, 99)]
    scores, info = store.fit_scores([*history, late, old], targets, at=AT, spec=SPEC)
    assert info["n_train"] == len(history)
    assert info["model"] == "dixon_coles" and info["spec"] == "xi=0.002,penalty=1,window=730d"
    assert set(scores) == {1} and info["uncovered"] == {"2": "a team has no result in the training window"}
    m = scores[1]
    assert m.shape[0] == m.shape[1] and math.isclose(float(m.sum()), 1.0, rel_tol=1e-3) and (m >= 0).all()


def test_too_little_history_gives_no_distribution() -> None:
    scores, info = store.fit_scores(_history(1)[:20], [store.Target(1, 1, 2)], at=AT, spec=SPEC)
    assert scores == {} and "fewer than" in info["error"]


def test_the_input_hash_changes_with_any_input() -> None:
    answer = rl.rules_for(39, 2025)
    fx = [sc.Fixture(1, "Regular Season - 1", 1, 2, 1, 0), sc.Fixture(2, "Regular Season - 2", 2, 1)]
    base = store.input_hash(answer, fx, {}, {"model": "dixon_coles"}, sims=100, seed=1, focus=[2])
    assert base == store.input_hash(answer, list(reversed(fx)), {}, {"model": "dixon_coles"}, sims=100, seed=1, focus=[2])
    changed = [
        store.input_hash(answer, [fx[0], sc.Fixture(2, "Regular Season - 2", 2, 1, 0, 0)], {}, {"model": "dixon_coles"},
                         sims=100, seed=1, focus=[2]),
        store.input_hash(answer, fx, {"T": [sc.ProviderRow(1, 3, 1)]}, {"model": "dixon_coles"}, sims=100, seed=1, focus=[2]),
        store.input_hash(answer, fx, {}, {"model": "dixon_coles", "n_train": 5}, sims=100, seed=1, focus=[2]),
        store.input_hash(answer, fx, {}, {"model": "dixon_coles"}, sims=200, seed=1, focus=[2]),
        store.input_hash(answer, fx, {}, {"model": "dixon_coles"}, sims=100, seed=2, focus=[2]),
        store.input_hash(answer, fx, {}, {"model": "dixon_coles"}, sims=100, seed=1, focus=[]),
    ]
    assert base not in changed and len(set(changed)) == len(changed)


# ── against stakes-v5 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _reading(objectives: list[dict[str, Any]], *, fact: bool = False, gaps: tuple[str, ...] = ()) -> dict[str, Any]:
    rows = [{"objetivo": o["objetivo"], "zona": o["zona"], "estado": o["estado"], "condicional": o.get("condicional", False),
             "probabilidad": o.get("probabilidad"), "decidido": {"demostrado": o["estado"] != "abierto" and not o.get("condicional")}}
            for o in objectives]
    return {"status": "ok", "rules": {"gaps": [{"topic": g} for g in gaps]}, "tables": [{"key": "t", "teams": [{"team": 7, "objetivos": rows}]}],
            "teams": {"7": {"demostrado": fact, "motivos": [] if fact else ["hueco_reglamento:continental"]}}}


def test_settled_against_an_open_objective_is_a_contradiction() -> None:
    reading = _reading([{"objetivo": "clasificacion", "zona": "next_phase", "estado": "abierto", "probabilidad": 0.5}])
    out = cmp.compare_side({"pressure": "settled", "settled": True, "rule": "stakes-v5"}, reading, 7)
    assert out["contradice"] and out["contradicciones"][0]["tipo"] == "cerrado_pero_abierto"


def test_settled_with_only_a_conditional_zone_open_or_nothing_proved_is_said_apart() -> None:
    conditional = _reading([{"objetivo": "plaza_continental", "zona": "continental", "estado": "abierto", "condicional": True}])
    out = cmp.compare_side({"pressure": "settled"}, conditional, 7)
    assert not out["contradice"] and out["contradicciones"][0]["tipo"] == "cerrado_pero_condicional"
    decided = _reading([{"objetivo": "titulo", "zona": "champion", "estado": "descartado"}])
    out = cmp.compare_side({"pressure": "settled"}, decided, 7)
    assert not out["contradice"] and out["contradicciones"][0]["tipo"] == "cerrado_no_demostrable"
    proved = _reading([{"objetivo": "titulo", "zona": "champion", "estado": "descartado"}], fact=True)
    assert cmp.compare_side({"pressure": "settled"}, proved, 7)["contradicciones"] == []


def test_pressure_on_a_decided_zone_and_a_zone_the_rules_do_not_have() -> None:
    reading = _reading([{"objetivo": "evitar_descenso", "zona": "relegation", "estado": "conseguido"}])
    out = cmp.compare_side({"pressure": "relegation"}, reading, 7)
    assert out["contradicciones"][0]["tipo"] == "presion_sobre_decidido"
    out = cmp.compare_side({"pressure": "promotion"}, reading, 7)
    assert out["contradicciones"][0]["tipo"] == "zona_inexistente"
    gapped = _reading([{"objetivo": "evitar_descenso", "zona": "relegation", "estado": "abierto"}], gaps=("continental",))
    out = cmp.compare_side({"pressure": "europe"}, gapped, 7)
    assert out["contradicciones"][0]["tipo"] == "no_verificable" and not out["contradice"]


def test_nothing_to_compare_without_stakes_or_rules() -> None:
    assert cmp.compare_side(None, _reading([]), 7)["status"] == "sin_stakes"
    assert cmp.compare_side({"pressure": "settled"}, {"status": sc.NOT_CODED}, 7)["contradicciones"] == []


# ── migration 0147 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────


MIGRATION = ROOT / "migrations" / "versions" / "0147_scenario_readings.py"


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0147", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recorder:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.statements.append(sql)


def render(direction: str) -> list[str]:
    module = load_migration()
    recorder = Recorder()
    vars(module)["op"] = recorder
    getattr(module, direction)()
    return recorder.statements


def test_0147_chains_on_the_rules_migration() -> None:
    m = load_migration()
    assert (m.revision, m.down_revision) == ("0147", "0146")


def test_0147_creates_one_append_only_table_and_writes_no_row() -> None:
    statements = render("upgrade")
    assert statements[0] == "SET LOCAL lock_timeout = '10s'"
    sql = "\n".join(statements)
    assert sql.count("CREATE TABLE") == 1 and "CREATE TABLE intel.scenario_readings" in sql
    assert "BEFORE UPDATE OR DELETE ON intel.scenario_readings" in sql and "EXECUTE FUNCTION ai.refuse_change()" in sql
    assert f"'{sc.NOT_CODED}'" in sql
    for verb in ("INSERT", "UPDATE intel.", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
        assert verb not in sql


def test_0147_downgrade_drops_only_what_it_created() -> None:
    assert render("downgrade") == ["SET LOCAL lock_timeout = '10s'", "DROP TABLE IF EXISTS intel.scenario_readings"]
