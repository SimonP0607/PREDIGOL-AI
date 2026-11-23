"""PM-12-05 (IA-159): the LAB loads an external dataset only when the register says so, and the register follows «origen antes que
etiqueta» - an open label never makes a dataset loadable; Wyscout and the routes of OP-54 wait for DM-08; every line of PM-12-05 has its
state (en curso, cerrada, esperando dictamen)."""

from __future__ import annotations

import dataclasses
import json

import pytest
from scripts import lab_datasets as lab


def test_the_register_is_consistent() -> None:
    assert lab.validate() == []


def test_every_line_of_the_task_has_its_state() -> None:
    assert {x.op: x.state for x in lab.LINES} == {"OP-41": "en_curso", "OP-48": "cerrada", "OP-53": "esperando_dictamen",
                                                  "OP-54": "esperando_dictamen"}
    assert all(x.limit and x.next_step for x in lab.LINES)


@pytest.mark.parametrize("key", ["wyscout-pappalardo-2019", "bsd-xg-por-tiro", "anotacion-manual-de-tiros"])
def test_the_routes_of_dm08_wait_for_the_opinion(key: str) -> None:
    v = lab.check(key)
    assert not v.allowed and "DM-08" in v.reason


def test_an_open_label_on_a_restricted_origin_is_never_loadable() -> None:
    for d in lab.DATASETS:
        if d.state == "no_usar":
            assert not lab.check(d.key).allowed
    cc0 = lab.BY_KEY["transfermarkt-dcaribou"]
    assert cc0.label == "CC0" and not lab.check(cc0.key).allowed


def test_permitido_needs_its_origin_not_its_label() -> None:
    base = lab.BY_KEY["predigol-bancos-etiquetados"]
    assert lab.check(base.key).allowed
    by_label = dataclasses.replace(base, key="x", origin="", origin_allows_reuse=None, label="CC0")
    assert "permitido sin origen declarado" in lab.problems(by_label)
    assert not lab.check("x", (by_label,)).allowed
    restricted = dataclasses.replace(base, key="y", origin="Extracción de un portal", origin_allows_reuse=False, label="CC BY 4.0")
    assert any("la etiqueta no basta" in p for p in lab.problems(restricted))
    pending = dataclasses.replace(base, key="z", opinion="DM-08")
    assert not lab.check("z", (pending,)).allowed


def test_an_unlisted_dataset_is_refused() -> None:
    v = lab.check("statsbomb-open-data")
    assert not v.allowed and "no está en el registro" in v.reason


def test_the_command_line(capsys: pytest.CaptureFixture[str]) -> None:
    assert lab.main(["check", "wyscout-pappalardo-2019"]) == 1
    assert json.loads(capsys.readouterr().out)["allowed"] is False
    assert lab.main(["list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["version"] == lab.VERSION and listed["register_problems"] == [] and len(listed["lines"]) == 4
