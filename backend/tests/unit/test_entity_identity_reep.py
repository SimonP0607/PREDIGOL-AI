"""AD-H01 (IA-071): the pinned Reep release - a file with another sha256 is refused - and how it is read."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
from pathlib import Path

import pytest

from fbi.people.identity import reep

HEADERS = {
    "bridges": ["reep_id", "provider", "namespace", "external_id", "entity_type", "independence_bucket", "route_scope",
                "rule_id", "confidence", "attached_at"],
    "entities": ["reep_id", "entity_type", "canonical_name", "gender", "country", "birth_date", "birth_date_iso",
                 "dob_precision", "grade", "bucket_count", "corroboration_buckets", "metadata_json", "updated_at"],
    "overlay_links": ["reep_id", "source", "external_id", "qid", "property", "confidence", "dob_check", "entity_type",
                      "evidence", "created_at"],
    "overlay_aliases": ["reep_id", "source", "qid", "name", "alias", "language", "lang", "name_source", "confidence",
                        "link_confidence", "dob_check", "evidence", "created_at"],
    "provider_aliases": ["reep_id", "alias", "alias_kind", "provider"],
    "redirects": ["from_id", "to_id", "reason", "created_at"],
}


def _write(folder: Path, name: str, rows: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS[name])
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in HEADERS[name]})
    data = gzip.compress(buf.getvalue().encode(), mtime=0)
    (folder / f"{name}.csv.gz").write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _release(folder: Path) -> dict[str, str]:
    return {
        "bridges": _write(folder, "bridges", [
            {"reep_id": "rp_old", "provider": "api_football", "namespace": "player", "external_id": "306",
             "entity_type": "player", "rule_id": "r", "confidence": "1.0"},
            {"reep_id": "rp_x", "provider": "api_football", "namespace": "player", "external_id": "999",
             "entity_type": "player", "rule_id": "r", "confidence": "1.0"},
            {"reep_id": "rc_k", "provider": "api_football", "namespace": "manager", "external_id": "40",
             "entity_type": "coach", "rule_id": "r", "confidence": "0.98"},
            {"reep_id": "rm_1", "provider": "api_football", "namespace": "match", "external_id": "1",
             "entity_type": "match", "rule_id": "r", "confidence": "1.0"},
            {"reep_id": "rp_new", "provider": "transfermarkt", "namespace": "spieler", "external_id": "148455",
             "entity_type": "player", "rule_id": "r", "confidence": "1.0"},
            {"reep_id": "rp_new", "provider": "transfermarkt", "namespace": "spiel", "external_id": "77",
             "entity_type": "match", "rule_id": "r", "confidence": "1.0"},
        ]),
        "entities": _write(folder, "entities", [{"reep_id": "rp_new", "entity_type": "player",
                                                 "canonical_name": "Mohamed Salah"}]),
        "overlay_links": _write(folder, "overlay_links", [{"reep_id": "rp_new", "source": "wikidata", "qid": "Q1354960",
                                                           "property": "transfermarkt:P2446", "confidence": "0.85",
                                                           "dob_check": "dob-agrees"}]),
        "overlay_aliases": _write(folder, "overlay_aliases", [
            {"reep_id": "rp_new", "alias": "محمد صلاح", "language": "ar", "name_source": "label", "confidence": "0.8"},
            {"reep_id": "rp_new", "alias": "Q1354960", "language": "abstract", "name_source": "sitelink_title_clean"},
        ]),
        "provider_aliases": _write(folder, "provider_aliases", [{"reep_id": "rp_old", "alias": "M. Salah",
                                                                 "alias_kind": "initial_name"}]),
        "redirects": _write(folder, "redirects", [{"from_id": "rp_old", "to_id": "rp_new"}]),
    }


@pytest.fixture
def pinned_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    hashes = _release(tmp_path)
    files = {n: reep.PinnedFile(f"k/{n}.csv.gz", h, 0) for n, h in hashes.items()}
    monkeypatch.setitem(reep.RELEASES, "test-1", reep.Release("test-1", "0" * 64, files))
    return tmp_path


def test_the_pinned_release_is_the_one_measured_by_ia_041() -> None:
    release = reep.pinned(reep.DEFAULT_RELEASE)
    assert reep.DEFAULT_RELEASE == "2026-10-19.1"
    assert set(release.files) == set(reep.FILES)
    assert all(len(f.sha256) == 64 for f in release.files.values())


def test_a_release_that_is_not_pinned_is_refused() -> None:
    with pytest.raises(reep.ReleaseMismatchError):
        reep.pinned("2026-10-25.1")


def test_the_same_files_pass_and_a_changed_file_is_refused(pinned_release: Path) -> None:
    first = reep.verify(pinned_release, "test-1")
    assert reep.verify(pinned_release, "test-1") == first
    (pinned_release / "redirects.csv.gz").write_bytes(gzip.compress(b"from_id,to_id,reason,created_at\n", mtime=0))
    with pytest.raises(reep.ReleaseMismatchError, match="redirects"):
        reep.verify(pinned_release, "test-1")


def test_a_missing_file_is_refused(pinned_release: Path) -> None:
    (pinned_release / "entities.csv.gz").unlink()
    with pytest.raises(reep.ReleaseMismatchError, match="missing"):
        reep.verify(pinned_release, "test-1")


def test_a_listing_with_another_hash_is_refused() -> None:
    with pytest.raises(reep.ReleaseMismatchError):
        reep.check_listing(b'{"files": {}}', reep.DEFAULT_RELEASE)


def test_reading_keeps_our_bridges_resolves_redirects_and_takes_only_ids_and_names(pinned_release: Path) -> None:
    data = reep.read(pinned_release, {"player": {306}, "coach": {40}})
    assert set(data.bridges) == {("player", 306), ("coach", 40)}, "not ours (999) and not a match"
    assert data.bridges[("player", 306)][0].reep_id == "rp_new", "the redirect is followed"
    ext = {(e.system, e.namespace, e.external_id) for e in data.externals["rp_new"]}
    assert ext == {("transfermarkt", "spieler", "148455"), ("wikidata", "", "Q1354960")}, "a match id is not an entity"
    assert data.names["rp_new"] == "Mohamed Salah"
    assert sorted(a.text for a in data.aliases["rp_new"]) == ["M. Salah", "محمد صلاح"], "a bare QID is no name"
