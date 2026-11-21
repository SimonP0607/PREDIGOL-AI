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
    "AD-A03": "205e671347e7c9ab21a4fb0ab03d1b6c66a2c4d9e44494f937e3e23707653bae",
    "AD-B03": "989b82a53fe35ae6712f39ce71d75588a1f868e38b9a2832ba2e393162364bd5",
    "AD-B07": "aac10f7f5cc48dfbf136283f0c76d1c6043556536b137e7df2bd4cbe05299128",
    "AD-K02": "6eff7d3066cbeed274d457c2694f478e339fc8232610be74f4c56f54e570def1",
    "AD-C08": "7ae65569c4f330956c9437c99a1224f36448d94fdba90d371d7ec6eb144943a4",
    "AD-C09": "f0bd0d90c7747bcab6e48dde47676c64b784d2d18fe9e78635c21efbc2106ed8",
    "AD-K03": "c5638110bd730e99a7d841caace34731bafb73cfac2c93d3c9bef89e49c719d3",
    "AD-K04": "9d37ca84b4dba0aa37e0b40cd9add0be4ea96951bac59e6c53802763482a9d14",
}
"""A registered protocol is frozen: changing one is a new version with its own PR, never an edit of these lines to make a test pass."""

PINNED_PM = {
    "PM-10-08": "9a8fdf48f635dda1977a6ea992a92ea9abf45050bd6233f3500a2d20ad45e50b",
    "PM-08-07": "3b3ac95d82db8166233b56206279723fb6419b5f890af6442a40a8b2dbd41488",
    "PM-09-07": "ed4015968c20d75928c9cd3bf6f73bcb555364ae7f0e6d326c3d32f33dd324ab",
    "PM-12-03-OP26": "99998f67d326b09666b976d3905ca8ade4dc730226e65a8e472d87df00338dca",
    "PM-12-03-OP27": "c8525423220e3cd5e188c2b9980a57cdd7291bf7e4aef5a5deb6bd549060eda5",
    "PM-12-03-OP29": "1b1ae6591a075429012021e8f4564631358f22c096160d153e50175a1a927a4c",
    "PM-12-03-OP30": "9192d1f5cab413e04052b326b3922b36f1dd60e5e340b5b52de353a74ea9ccd1",
}
"""IA-154: the LAB lines of the plan PM, registered on 21-nov-2026 before their export was taken; frozen the same way."""


def test_every_registered_protocol_is_pinned_and_unchanged() -> None:
    assert set(proto.PROTOCOLS) == set(PINNED)
    for key, fp in PINNED.items():
        assert proto.fingerprint(proto.PROTOCOLS[key]) == fp, key


def test_a_protocol_fixes_everything_before_the_data() -> None:
    for p in [*proto.PROTOCOLS.values(), *proto.PM_LAB.values()]:
        for f in dataclasses.fields(p):
            value = getattr(p, f.name)
            assert value not in ("", (), None), (p.key, f.name)
        assert p.key.startswith(("INT-", "AD-", "PM-")) and p.version.startswith("proto-")
        assert p.version.endswith("-v1")
        # the protocols of the Intelligence plan were registered on 11-nov; those of the plan of the definitive architecture (AD-...) from
        # its approval on 16-nov (AD-B07, 17-nov, the day it was written: before its LAB run); the LAB lines of the plan PM (IA-154) on
        # 21-nov, before the lab-export-v2 export they read was taken
        if p.key.startswith("INT-"):
            assert p.registered_on == "2026-11-11"
        elif p.key.startswith("AD-"):
            assert p.registered_on in ("2026-11-16", "2026-11-17")
        else:
            assert p.registered_on == "2026-11-21" and p.seed == 20261121


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


def test_battery_v4_is_registered_before_its_first_run() -> None:
    """AD-A03 (IA-065): the protocol of battery-v4, registered before any of its answers exists; the owner signs it (v4-sign --confirm-owner)."""
    p = proto.require("AD-A03")
    assert p.version == "proto-ad-a03-v1" and p.seed == 20261116
    assert "0 % por defecto" in p.pass_rule and "3 %" in p.pass_rule
    assert proto.stamp("AD-A03")["fingerprint"] == PINNED["AD-A03"]


def test_the_stable_seal_is_registered_before_its_first_reading() -> None:
    """AD-B03 (IA-073): the shadow version forecast-v1-seal starts writing with its deploy; the protocol that will judge it is older."""
    p = proto.require("AD-B03")
    assert p.version == "proto-ad-b03-v1" and p.seed == 20261116
    assert proto.stamp("AD-B03")["fingerprint"] == PINNED["AD-B03"]


def test_the_count_calibrator_is_registered_before_its_lab_run() -> None:
    """AD-B07 (IA-095): count-cal-v1 for corners and cards, one verdict per family; registered before the walk-forward reads any data."""
    p = proto.require("AD-B07")
    assert p.version == "proto-ad-b07-v1" and p.seed == 20261117 and p.registered_on == "2026-11-17"
    assert "VALIDADO" in p.pass_rule and "NO VALIDADO" in p.reject_rule and "INSUFICIENTE" in p.reject_rule
    assert "1.500 partidos" in p.min_sample and "60 días" in p.min_sample
    assert proto.stamp("AD-B07")["fingerprint"] == PINNED["AD-B07"]


def test_the_validation_board_is_registered_before_it_reads_any_outcome() -> None:
    """AD-K02 (IA-113): the board's thresholds, its yardstick and its correction, fixed before the board looks at a result."""
    p = proto.require("AD-K02")
    assert p.version == "proto-ad-k02-v1" and p.seed == 20261117
    assert "Bonferroni" in p.primary_metric and "+6,24 %" in p.pass_rule and "ECE" in p.pass_rule
    assert proto.stamp("AD-K02")["fingerprint"] == PINNED["AD-K02"]


def test_the_credibility_by_type_is_registered_before_its_first_snapshot() -> None:
    """AD-C08 (IA-126): the minimum of resolved claims and the coverage of the interval, fixed before any credibility-v2 is read."""
    p = proto.require("AD-C08")
    assert p.version == "proto-ad-c08-v1" and p.seed == 20261117 and p.registered_on == "2026-11-17"
    assert "30 afirmaciones resueltas" in p.min_sample and "nunca sube ni baja un estado" in p.alternative
    assert proto.stamp("AD-C08")["fingerprint"] == PINNED["AD-C08"]


def test_the_extraction_protocol_is_registered_unsigned_before_the_bank_is_labelled() -> None:
    """AD-C09 (IA-127): extract-protocol-v1 - precision 47 of 50, corrected recall, labellers' agreement - registered before any page is
    labelled; it is the owner who signs it (scripts/ia_page_bank.py sign --confirm-owner), never the code, and row 17 stays as it is."""
    p = proto.require("AD-C09")
    assert p.version == "proto-ad-c09-v1" and p.seed == 20261117 and p.registered_on == "2026-11-17"
    assert "47 de sus 50" in p.pass_rule and "Bonferroni" in p.primary_metric and "fila 17" in p.pass_rule
    assert "nunca contra research v1" in p.question and "las etiquetas no entrenan nada" in p.split
    assert proto.stamp("AD-C09")["fingerprint"] == PINNED["AD-C09"]


def test_the_readers_and_sources_performance_is_registered_unsigned_with_its_power_before_any_report() -> None:
    """AD-K03 (IA-135): perf-v1 - each reader against the rules on the same selections, each source by type of fact - with the sample its
    power calculation asks (1.327 selections examined) fixed before the first report; the owner signs it, never the code."""
    p = proto.require("AD-K03")
    assert p.version == "proto-ad-k03-v1" and p.seed == 20261117 and p.registered_on == "2026-11-17"
    assert proto.n_for_mean(0.13, 0.01) == 1327 and "1.327" in p.min_sample and "Bonferroni" in p.primary_metric
    assert "ningún peso, umbral ni versión cambia" in p.alternative and "INSUFICIENTE" in p.reject_rule
    assert proto.stamp("AD-K03")["fingerprint"] == PINNED["AD-K03"]


def test_the_regression_of_the_replay_bank_is_registered_with_its_proposed_tolerance() -> None:
    """AD-K04 (IA-136): replay-regression-v1 - the upper end of the IC95 within 5 points, PROPOSED (the owner signs it), its causes
    and the rule that a verdict is never measured again over the same stored runs."""
    p = proto.require("AD-K04")
    assert p.version == "proto-ad-k04-v1" and p.seed == 20261111 and p.registered_on == "2026-11-17"
    assert "≤ 0,05" in p.pass_rule and "PROPUESTA" in p.pass_rule and "no se repite sobre las mismas ejecuciones" in p.stopping
    assert proto.stamp("AD-K04")["fingerprint"] == PINNED["AD-K04"]


def test_the_lab_lines_of_the_plan_pm_are_registered_before_their_export() -> None:
    """IA-154: PM-10-08, PM-08-07, PM-09-07 and one protocol per line of PM-12-03 (OP-26, OP-27, OP-29, OP-30; OP-28 stays with the
    Intelligence plan's E4/E6 and is not touched), registered on 21-nov-2026 before the lab-export-v2 export was read."""
    keys = {"PM-10-08", "PM-08-07", "PM-09-07", "PM-12-03-OP26", "PM-12-03-OP27", "PM-12-03-OP29", "PM-12-03-OP30"}
    assert set(proto.PM_LAB) == set(PINNED_PM) == keys
    assert not set(proto.PM_LAB) & set(proto.PROTOCOLS), "the signable catalogue (fbi.protosign, C-11) admits only INT-/AD- keys"
    for key in keys:
        p = proto.require(key)
        assert proto.fingerprint(p) == PINNED_PM[key], key
        assert "lab-export-v2" in p.data and p.version == f"proto-{key.lower()}-v1"
        assert proto.stamp(key)["fingerprint"] == PINNED_PM[key]
    # OP-29 is a new protocol: it does not repeat INT-A02 (rejected on 11-nov) and changes no figure
    assert "INT-A02" in proto.require("PM-12-03-OP29").question
    # nothing leaves the LAB: a pass is at most a candidate for the model gate, never production without the owner's signature
    for key in ("PM-12-03-OP26", "PM-12-03-OP27", "PM-12-03-OP29", "PM-12-03-OP30"):
        assert "firma del dueño" in proto.require(key).pass_rule
    assert "DM-14" in proto.require("PM-09-07").pass_rule
    assert "nunca baja un mínimo vigente" in proto.require("PM-10-08").pass_rule
