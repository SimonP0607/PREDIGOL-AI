"""PrediGol's forecast in the AI packet (plan F5: ``packet-v6``, ``brief-v7``, ``narrative-v3``, ``leak-audit-v4``).

The packet is what a review or a brief may know about a match at one moment. From ``packet-v6`` it carries what PrediGol itself
stated about the match by that moment (``models.match_forecasts``): a probability and its interval per core market, whether it was
calibrated and which outcome is the likely one - and no price, no edge: the likely outcome is not the best paid one, and the brief is
told so. What the tests hold: that the block is exactly what had been written by the packet's moment (a packet for a past moment is
the forecast a reader could have had), that its absence names nothing missing while an error is named, that a claim may cite it and
its numbers count as the packet's, that the rules' narrative says it as a probability apart from the cards, and that the nightly
audit (``forecast_known``) finds a packet that read the future, a forecast that never existed and a forecast older than the one
PrediGol had stated."""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from fbi.ai import claims, prompts
from fbi.ai import packet as packet_module
from fbi.ai.calendar import local_day
from fbi.ai.packet import Packet, PacketBuilder, store_packet
from fbi.forecasting import match_forecast as mf
from fbi.intel import leakage
from fbi.intel.narrative import expected
from fbi.intel.narrative import markets as narrative_markets
from tests.integration.test_match_forecast import AT, CUT, SHEET, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

RULE = "forecast_known"
READ = AT + timedelta(hours=1)


def forecast_world(w: World, *, champion: bool = True) -> int:
    """A match both goal models priced, the total of which has a champion calibrator and a recent price; forecast written at AT."""
    fid = w.fixture()
    for model in ("poisson", "dixon_coles"):
        w.predict_all(fid, model)
    if champion:
        w.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
        w.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(minutes=40))
    w.write(fid)
    return fid


def built(w: World, fid: int, at: datetime = READ) -> Packet:
    packet = PacketBuilder(w.db).build(fid, at=at)
    assert packet is not None
    return packet


def forecast_of(packet: Packet) -> dict[str, Any]:
    block = packet.content["forecast"]
    assert isinstance(block, dict)
    return block


def by_market(packet: Packet) -> dict[str, dict[str, Any]]:
    return {m["market"]: m for m in forecast_of(packet)["markets"]}


# ── the block ────────────────────────────────────────────────────────────────

def test_the_packet_carries_what_predigol_stated_by_its_moment(world: World) -> None:  # noqa: F811
    fid = forecast_world(world)
    packet = built(world, fid)

    assert packet.version == packet_module.PACKET_VERSION == "packet-v8"
    block = forecast_of(packet)
    assert block["version"] == "forecast-v1"
    assert [m["market"] for m in block["markets"]] == ["1X2", "OU", "BTTS"], "the result, the total, both teams to score"
    markets = by_market(packet)
    assert {k: (m["calibration"], m["basis"]) for k, m in markets.items()} == {
        "1X2": ("UNCALIBRATED", "no_champion"), "OU": ("CALIBRATED", "champion"), "BTTS": ("UNCALIBRATED", "no_champion")}
    for key, m in markets.items():
        outcomes = m["outcomes"]
        assert [o["selection"] for o in outcomes] == list(next(s for (k, _), s in SHEET.items() if k == key))
        assert sum(o["p"] for o in outcomes) == pytest.approx(1.0, abs=0.0025), key
        assert m["likely"] == max(outcomes, key=lambda o: o["p"])["selection"]
        assert all(o["p_lo"] <= o["p"] <= o["p_hi"] for o in outcomes)
        assert m["model"] == "dixon_coles" and m["known_at"] and m["data_cutoff_at"]
    assert markets["1X2"]["likely"] == "Home" and markets["OU"]["line"] == "2.50"
    assert "forecast" not in packet.missing, "its absence is silent; only an error is named"
    source = next(s for s in packet.sources if s["block"] == "forecast")
    assert source["table"] == "models.match_forecasts" and source["version"] == "forecast-v1"
    assert set(source["known_at"]) == {"1X2@0.00", "OU@2.50", "BTTS@0.00"}


def test_the_block_is_a_probability_and_nothing_that_reads_as_a_price(world: World) -> None:  # noqa: F811
    packet = built(world, forecast_world(world))
    for m in forecast_of(packet)["markets"]:
        assert set(m) == {"market", "line", "model", "calibration", "basis", "known_at", "data_cutoff_at", "likely", "outcomes"}
        assert all(set(o) == {"selection", "p", "p_lo", "p_hi"} for o in m["outcomes"]), "no odds, no edge, no value, no pick"


def test_a_packet_for_a_past_moment_is_the_forecast_a_reader_could_have_had(world: World) -> None:  # noqa: F811
    fid = forecast_world(world, champion=False)
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(hours=1), shift=0.12)
    world.write(fid, AT + timedelta(hours=3))

    early, late = built(world, fid, AT + timedelta(hours=1)), built(world, fid, AT + timedelta(hours=4))
    assert by_market(early)["1X2"]["outcomes"][0]["p"] == pytest.approx(0.50), "what was said then"
    assert by_market(late)["1X2"]["outcomes"][0]["p"] == pytest.approx(0.62), "and what was said later"
    assert early.hash != late.hash, "a forecast that moved is a new context"

    before = built(world, fid, AT - timedelta(hours=1))
    assert "forecast" not in before.content, "nothing had been stated yet"
    assert "forecast" not in before.missing


def test_a_match_without_a_forecast_has_no_block_and_names_nothing_missing(world: World) -> None:  # noqa: F811
    fid = world.fixture()
    packet = built(world, fid)
    assert "forecast" not in packet.content and "forecast" not in packet.missing


def test_a_forecast_that_cannot_be_read_is_named_and_costs_the_rest_of_the_packet_nothing(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = forecast_world(world)
    intact = built(world, fid)
    monkeypatch.setattr(packet_module, "FORECAST_SQL", "SELECT 1 FROM models.no_such_table WHERE %(fixture)s = %(at)s AND %(version)s = ''")
    broken = built(world, fid)

    assert broken.content["forecast"] == {"version": "forecast-v1", "error": "UndefinedTable"}
    assert "forecast" in broken.missing, "an error is named: a gap that looks like a match PrediGol has no forecast for would hide it"
    for block in ("fixture", "market", "models", "standings", "dossier"):
        assert broken.content[block] == intact.content[block], block


def test_the_packet_reads_what_the_worker_writes() -> None:
    assert packet_module.FORECAST_VERSION == mf.VERSION
    assert set(packet_module.FORECAST_ORDER) == set(mf.FAMILIES), "every market the worker forecasts has a place in the packet"


# ── the claims and the words ────────────────────────────────────────────────

def test_a_claim_may_cite_the_forecast_and_its_numbers_are_the_packets(world: World) -> None:  # noqa: F811
    packet = built(world, forecast_world(world))
    stored = claims.corpus_numbers(packet.content, {})
    assert "forecast" in claims.BLOCKS and claims.REF.match("P:forecast")

    home = by_market(packet)["1X2"]["outcomes"][0]["p"]
    fine = claims.ClaimOut(text=f"PrediGol estima {home * 100:.1f} % de que gane el local", type="DATA", refs=["P:forecast"])
    assert claims.refused(fine, stored=stored, evidence_status={}) is None, "the packet's own number, as a percentage"
    invented = claims.ClaimOut(text="PrediGol estima 71.3 % de que gane el local", type="DATA", refs=["P:forecast"])
    why = claims.refused(invented, stored=stored, evidence_status={})
    assert why is not None and "71.3" in why, "a number that is not in the packet is refused, whatever block it cites"
    unknown = claims.ClaimOut(text="PrediGol espera algo", type="INFERENCE", refs=["P:forecasts"])
    assert claims.refused(unknown, stored=stored, evidence_status={}) == "cites a packet block that does not exist"


def test_the_brief_is_told_the_likely_outcome_is_not_the_best_paid_one() -> None:
    assert prompts.BRIEF_VERSION == "brief-v7"
    system = " ".join(prompts.BRIEF_SYSTEM.split())
    assert "P:forecast" in system and "sin calibrar" in system
    assert "not the best paid one" in system and "never present the forecast as a pick, as value or as a reason to bet" in system
    assert "models, forecast, quality" in system, "it is listed among the blocks a claim may cite"
    assert "brief-v7" not in prompts.REVIEW_SYSTEM, "the review's prompt did not change"


def test_the_rules_narrative_says_what_predigol_expects_as_a_probability_apart_from_the_cards(world: World) -> None:  # noqa: F811
    packet = built(world, forecast_world(world))
    sentence = expected(packet.content)

    assert sentence.startswith("PrediGol espera: ")
    assert "50.0 %, sin calibrar" in sentence, "the result is the model's own number and says so"
    assert "más de 2.5 goles (" in sentence
    assert sentence.count("sin calibrar") == 2, "the total is calibrated, the other two are not"
    assert sentence.endswith("Es una probabilidad, no un precio.")
    for word in ("cuota", "valor", "apuesta", "recomend"):
        assert word not in sentence.lower(), word

    card = {"market": "1X2", "selection": "Draw", "line": "0", "p_model": 0.26, "p_market": 0.22}
    text = narrative_markets(packet.content, [card])
    assert text.startswith(sentence), "what PrediGol expects first"
    assert "1X2 Draw: modelo 26.0 % frente a mercado 22.0 %." in text, "then the cards, the model against the market"
    assert narrative_markets({}, []) == "Ningún mercado destaca frente al precio."


# ── the nightly proof ──────────────────────────────────────────────────────

def audited(w: World, at: datetime = READ) -> dict[str, Any]:
    """The rule on the Bogotá day of ``at`` (one call per test: the audit keeps every run under its ``checked_at``)."""
    out: dict[str, Any] = leakage.audit_day(w.db, day=local_day(at), at=at + timedelta(hours=1))[RULE]
    return out


def handmade(w: World, fid: int, content: dict[str, Any], at: datetime) -> int:
    """A stored packet whose content was written by hand: what a faulty reader would have put there."""
    row = w.db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) VALUES (%s, %s, %s, %s, %s, %s) "
        "RETURNING id", (fid, "packet-v6", at, at, hashlib.sha256(repr((fid, at, content)).encode()).hexdigest(),
                         Jsonb(content))).fetchone()
    assert row is not None
    return int(row[0])


def tampered(packet: Packet, change: Any) -> dict[str, Any]:
    content = copy.deepcopy(packet.content)
    change(content["forecast"]["markets"])
    return content


def test_the_rule_is_in_the_audit_and_the_version_says_so() -> None:
    assert RULE in leakage.RULES and leakage.VERSION == "leak-audit-v6" and RULE in (leakage.__doc__ or "")


def test_an_honest_packet_passes_one_check_per_market(world: World) -> None:  # noqa: F811
    fid = forecast_world(world)
    packet = built(world, fid)
    store_packet(world.db, packet, built_at=READ)

    assert audited(world) == {"checked": 3, "violations": 0, "examples": []}
    rows = world.db.execute("SELECT version, n_checked, n_violations FROM intel.audit_checks WHERE rule = %s", (RULE,)).fetchall()
    assert rows == [("leak-audit-v6", 3, 0)], "the run is kept in the ledger of the audit with its version"


def test_a_packet_without_a_forecast_is_not_counted(world: World) -> None:  # noqa: F811
    packet = built(world, world.fixture())
    store_packet(world.db, packet, built_at=READ)
    assert audited(world) == {"checked": 0, "violations": 0, "examples": []}


def test_a_packet_that_read_the_future_is_found(world: World) -> None:  # noqa: F811
    fid = forecast_world(world)
    packet = built(world, fid)
    content = tampered(packet, lambda ms: ms[0].update(known_at=(READ + timedelta(minutes=5)).isoformat()))
    pid = handmade(world, fid, content, READ)

    result = audited(world)
    assert result["checked"] == 3 and result["violations"] == 1 and result["examples"] == [pid]


def test_a_forecast_that_never_existed_is_found(world: World) -> None:  # noqa: F811
    fid = forecast_world(world)
    packet = built(world, fid)
    content = tampered(packet, lambda ms: ms[1].update(known_at=(AT - timedelta(minutes=3)).isoformat()))  # no set was written then
    pid = handmade(world, fid, content, READ)

    result = audited(world)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_forecast_of_another_model_than_the_one_stored_is_found(world: World) -> None:  # noqa: F811
    fid = forecast_world(world)
    packet = built(world, fid)
    pid = handmade(world, fid, tampered(packet, lambda ms: ms[2].update(model="poisson")), READ)

    result = audited(world)
    assert result["violations"] == 1 and result["examples"] == [pid]


def test_a_packet_that_read_an_older_forecast_than_the_one_stated_is_found(world: World) -> None:  # noqa: F811
    fid = forecast_world(world, champion=False)
    packet = built(world, fid)  # cites the set written at AT
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(hours=1), shift=0.12)
    world.write(fid, AT + timedelta(hours=2))  # PrediGol then stated something else
    pid = handmade(world, fid, copy.deepcopy(packet.content), AT + timedelta(hours=3))  # a packet of 15:00 still citing the 12:00 set

    result = audited(world, AT + timedelta(hours=3))
    assert result["checked"] == 3 and result["violations"] == 3, "all three markets had been restated"
    assert result["examples"] == [pid]


def test_a_packet_built_before_the_newer_set_is_not_stale_for_having_been_built_then(world: World) -> None:  # noqa: F811
    fid = forecast_world(world, champion=False)
    early = built(world, fid, AT + timedelta(hours=1))
    store_packet(world.db, early, built_at=AT + timedelta(hours=1))
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(hours=1), shift=0.12)
    world.write(fid, AT + timedelta(hours=2))

    assert audited(world, AT + timedelta(hours=1)) == {"checked": 3, "violations": 0, "examples": []}, (
        "the newer set did not exist at the packet's moment")
