"""INT-T02 (IA-033): the LAB protocols are registered before any result and cannot change silently."""

from __future__ import annotations

import dataclasses
import math

import pytest

from fbi.research import protocol as proto

PINNED = {
    "INT-A02": "2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d",
    "INT-A09": "400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36",
    "INT-B09": "2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232",
    "INT-A08": "a37fdb4265f407c892e11f793ce86a083667ec491f0251fdd4d1f1d3603a1c43",
    "INT-C02": "f954582c9594c509dfc93f4abd9a847292a023d74dc5495daf0eead00bd0cc63",
}
"""A registered protocol is frozen: changing one is a new version with its own PR, never an edit of these lines to make a test pass."""


def test_every_registered_protocol_is_pinned_and_unchanged() -> None:
    assert set(proto.PROTOCOLS) == set(PINNED)
    for key, fp in PINNED.items():
        assert proto.fingerprint(proto.PROTOCOLS[key]) == fp, key


def test_a_protocol_fixes_everything_before_the_data() -> None:
    for p in proto.PROTOCOLS.values():
        for f in dataclasses.fields(p):
            value = getattr(p, f.name)
            assert value not in ("", (), None), (p.key, f.name)
        assert p.key.startswith("INT-") and p.version.startswith("proto-")
        assert p.version.endswith("-v1")
        assert p.registered_on == "2026-11-11"


def test_the_plan_lab_experiments_of_wave_one_have_a_protocol() -> None:
    for key in ("INT-A02", "INT-A09", "INT-B09"):
        assert proto.require(key).key == key


def test_e6_and_the_replay_bank_are_registered_before_their_first_run() -> None:
    """INT-A08 (E6, IA-052) and INT-C02 (the replay bank, IA-047): registered on their own, before any of their data is read."""
    for key, version in (("INT-A08", "proto-int-a08-v1"), ("INT-C02", "proto-int-c02-v1")):
        p = proto.require(key)
        assert p.version == version and p.seed == 20261111
        assert proto.stamp(key)["fingerprint"] == PINNED[key]


def test_an_experiment_without_a_protocol_does_not_run() -> None:
    with pytest.raises(LookupError, match="no hay protocolo registrado"):
        proto.require("INT-Z99")


def test_a_result_carries_key_version_and_fingerprint() -> None:
    s = proto.stamp("INT-A02")
    assert s == {"protocol": "INT-A02", "version": "proto-int-a02-v1", "fingerprint": PINNED["INT-A02"],
                 "framework": "lab-protocol-v1"}


def test_canonical_json_is_stable_and_order_free() -> None:
    p = proto.PROTOCOLS["INT-B09"]
    assert proto.canonical(p) == proto.canonical(dataclasses.replace(p))
    assert '"key":"INT-B09"' in proto.canonical(p)


def test_power_for_a_mean_is_the_textbook_7_85() -> None:
    assert (proto.z(0.975) + proto.z(0.80)) ** 2 == pytest.approx(7.849, abs=1e-3)
    assert proto.n_for_mean(1.0, 1.0) == 8
    assert proto.n_for_mean(2.0, 0.5) == math.ceil(7.84887 * 16)
    assert proto.n_for_mean(1.0, 0.1, two_sided=False) < proto.n_for_mean(1.0, 0.1)


def test_minimum_detectable_effect_inverts_the_sample_size() -> None:
    n = proto.n_for_mean(1.5, 0.3)
    assert proto.mde_for_mean(1.5, n) <= 0.3 < proto.mde_for_mean(1.5, n - 1)
    assert proto.mde_for_mean(1.0, 1) == pytest.approx(2.8016, abs=1e-4)


def test_power_for_two_proportions() -> None:
    assert proto.n_for_two_proportions(0.5, 0.6) == 388
    assert proto.n_for_two_proportions(0.6, 0.5) == 388
    assert proto.n_for_two_proportions(0.5, 0.55) > proto.n_for_two_proportions(0.5, 0.6)


@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5])
def test_quantiles_reject_impossible_probabilities(bad: float) -> None:
    with pytest.raises(ValueError):
        proto.z(bad)


def test_power_inputs_are_checked() -> None:
    with pytest.raises(ValueError):
        proto.n_for_mean(0.0, 1.0)
    with pytest.raises(ValueError):
        proto.n_for_mean(1.0, 0.0)
    with pytest.raises(ValueError):
        proto.n_for_two_proportions(0.5, 0.5)
    with pytest.raises(ValueError):
        proto.mde_for_mean(1.0, 0)
