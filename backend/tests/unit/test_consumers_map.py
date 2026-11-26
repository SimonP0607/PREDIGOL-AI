"""RP-0.3: the consumers map finds names, classifies where and how, and guards what is marked to consolidate or retire."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import consumers_map as cm

CAND = cm.Candidate("x", "tabla de prueba", cm.RETIRE, (r"intel\.thing", r"thing-v1"), ("intel.thing",))


def _scan(tmp_path: Path, **files: str) -> dict[str, list[dict[str, str]]]:
    paths = []
    for name, text in files.items():
        p = tmp_path / name
        p.write_text(text)
        paths.append(p)
    return _scan_in_root(CAND, paths)


def _scan_in_root(cand: cm.Candidate, paths: list[Path]) -> dict[str, list[dict[str, str]]]:
    # the paths of the temp files are not under the repository: classify them as they would be inside backend/src
    out: list[dict[str, str]] = []
    import re

    for p in paths:
        text = p.read_text()
        if any(re.search(rx, text) for rx in cand.patterns):
            out.append({"path": p.name, "package": "x", "class": "módulo", "kind": cm.kind(text, cand.tables)})
    return {cand.key: out}


def test_a_write_is_told_from_a_read(tmp_path: Path) -> None:
    found = _scan(tmp_path, a="INSERT INTO intel.thing (id) VALUES (1)", b="SELECT * FROM intel.thing", c="nothing here")
    kinds = {r["path"]: r["kind"] for r in found["x"]}
    assert kinds == {"a": "escribe", "b": "lee o cita"}


def test_a_version_name_counts_as_a_mention(tmp_path: Path) -> None:
    assert [r["path"] for r in _scan(tmp_path, a="uses thing-v1 somewhere")["x"]] == ["a"]


def test_classification_by_place() -> None:
    root = cm.ROOT
    assert cm.classify(root / "backend/tests/unit/test_x.py") == "prueba"
    assert cm.classify(root / "backend/scripts/x.py") == "script"
    assert cm.classify(root / "backend/apps/worker/scheduler.py") == "trabajo"
    assert cm.classify(root / "backend/src/fbi/shadowjobs/x.py") == "trabajo"
    assert cm.classify(root / "backend/src/fbi/api/routes/x.py") == "ruta"
    assert cm.classify(root / "backend/src/fbi/decision/x.py") == "módulo"
    assert cm.classify(root / "web/src/lib/x.ts") == "web"
    assert cm.package(root / "backend/src/fbi/decision/x.py") == "decision"


def test_a_new_consumer_of_something_to_retire_is_flagged_but_not_of_something_kept() -> None:
    def doc(destiny: str, files: list[str]) -> dict[str, object]:
        return {"candidatos": {"x": {"destino": destiny, "consumidores": files}}}

    frozen = doc(cm.RETIRE, ["a.py"])
    assert cm.new_consumers(doc(cm.RETIRE, ["a.py", "b.py"]), frozen) == {"x": ["b.py"]}
    assert cm.new_consumers(doc(cm.RETIRE, ["a.py"]), frozen) == {}
    assert cm.new_consumers(doc(cm.KEEP, ["a.py", "b.py"]), frozen) == {}


def test_the_candidates_of_section_17_all_have_a_destiny_and_patterns() -> None:
    assert len({c.key for c in cm.CANDIDATES}) == len(cm.CANDIDATES)
    for c in cm.CANDIDATES:
        assert c.destiny in (cm.KEEP, cm.CONSOLIDATE, cm.RETIRE)
        assert c.patterns


def test_the_committed_map_is_what_the_code_gives_and_no_candidate_to_retire_has_a_new_consumer() -> None:
    doc = cm.document(cm.scan())
    assert cm.OUT_MD.read_text(encoding="utf-8") == cm.render(doc), "run python -m scripts.consumers_map"
    frozen = json.loads(cm.OUT_JSON.read_text())
    assert cm.new_consumers(doc, frozen) == {}, "a new consumer of something marked to consolidate or retire"
    assert cm.OUT_JSON.read_text() == json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def test_every_candidate_lists_its_consumers_or_says_it_has_none() -> None:
    doc = cm.document(cm.scan())
    for key, c in doc["candidatos"].items():
        assert c["archivos"] >= c["sin_pruebas"] >= 0, key
        assert c["consumidores"] or c["sin_pruebas"] == 0, key
