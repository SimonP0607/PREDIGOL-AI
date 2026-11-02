"""The brief is paid again only for a material change (Plan Maestro IA, section 19), on a stored match.

A price that moves 2 % reuses the brief a model wrote; one that moves 4 % writes another. A line-up, an absence, a piece of evidence, a
new kick-off, a new scenario or a new candidate pay again. What the brief does not read as context (a model figure that is not a
candidate's, the data-quality score) does not. The server's reasons to look closer are the packet's of NOW, not the stored brief's.
Rolled back (``FBI_AI_BRIEF_MATERIAL=0``) only an identical input is reused, as before.

No network and no key: the model is ``FakeProvider``. One transaction, rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.brief import Brief, make_brief
from fbi.ai.config import AiSettings
from fbi.ai.packet import Packet, store_packet
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed
from .test_ai_decision_layer import Savepoints, brief_reply

AT = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=6)
SHADOW = AiSettings(mode="shadow")
ROLLED_BACK = AiSettings(mode="shadow", switches={"brief_material": "off"})
HAIKU = "claude-haiku-5-5"


def fixture_block(seed: Seed, **over: Any) -> dict[str, Any]:
    return {"id": seed.fixture_id, "status": "NS", "kickoff_at": KO.isoformat(), "kickoff_changes": [],
            "home": {"id": seed.home_team_id, "name": "Home FC"},
            "away": {"id": seed.away_team_id, "name": "Away FC"}} | over


def content(seed: Seed, *, odds: float = 2.4, **over: Any) -> dict[str, Any]:
    c: dict[str, Any] = {
        "fixture": fixture_block(seed),
        "quality": {"competition_score": {"class": "MODEL_READY", "score": 0.9}, "fixture_validation": None,
                    "lineups_confirmed": False},
        "market": {"observed": True, "selections": [
            {"market": "1X2", "selection": "Home", "line": "0", "p_fair": 0.45, "best_odds": odds, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.45, "movement": 0.0},
            {"market": "1X2", "selection": "Draw", "line": "0", "p_fair": 0.28, "best_odds": 3.5, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.28, "movement": 0.0},
            {"market": "1X2", "selection": "Away", "line": "0", "p_fair": 0.27, "best_odds": 3.6, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.27, "movement": 0.0}]},
        "models": {"dixon_coles": {"version_id": 1, "selections": [
            {"market": "1X2", "selection": "Home", "line": "0", "p": 0.52, "p_lo": 0.47, "p_hi": 0.57},
            {"market": "1X2", "selection": "Draw", "line": "0", "p": 0.25, "p_lo": 0.21, "p_hi": 0.29},
            {"market": "1X2", "selection": "Away", "line": "0", "p": 0.23, "p_lo": 0.19, "p_hi": 0.27}]}},
        "absences": {"checked": True, "home": {"players": [], "weight": 0, "key_out": 0},
                     "away": {"players": [], "weight": 0, "key_out": 0}},
        "lineups": {"confirmed": False},
        "stakes": {"home": {"pressure": "mid_table"}, "away": {"pressure": "mid_table"}},
        "evidence": [],
    }
    return c | over


def packet_of(seed: Seed, **kw: Any) -> Packet:
    return Packet(seed.fixture_id, AT, content(seed, **kw))


def card(odds: str = "2.400", **over: Any) -> list[dict[str, Any]]:
    base: dict[str, Any] = {"market": "1X2", "selection": "Home", "line": "0", "kind": "value", "odds": odds,
                            "bookmaker": "BK", "p_model": "0.5200", "p_low": "0.4700", "p_market": "0.4500",
                            "fair_odds": "1.92", "minimum_odds": "2.23", "edge": "0.0700", "ev": "0.248",
                            "verdict": "recommended"}
    return [base | over]


def writer() -> FakeProvider:
    return FakeProvider(lambda r: brief_reply(), name="anthropic")


def read(db: psycopg.Connection[Any], model: FakeProvider, p: Packet, *, cards: list[dict[str, Any]] | None = None,
         at: datetime = AT, settings: AiSettings = SHADOW, use_llm: bool = True) -> Brief:
    conn: Any = Savepoints(db)
    cs = card() if cards is None else cards
    return make_brief(conn, settings, p, store_packet(conn, p, built_at=at), cards=cs, candidates=len(cs), pass_kind="pre",
                      at=at, use_llm=use_llm, ledger=UsageLedger(shared(db)), provider=(model, HAIKU))


def briefs(db: psycopg.Connection[Any], seed: Seed) -> int:
    row = db.execute("SELECT count(*) FROM ai.match_briefs WHERE fixture_id = %s", (seed.fixture_id,)).fetchone()
    return int(row[0]) if row else 0


def test_a_brief_is_stored_with_the_material_it_was_written_under(db: psycopg.Connection[Any], seed: Seed) -> None:
    first = read(db, writer(), packet_of(seed))
    row = db.execute("SELECT material_hash, material FROM ai.match_briefs WHERE id = %s", (first.id,)).fetchone()
    assert row is not None and row[0] and row[1]["v"] == "material-v1" and row[1]["hash"] == row[0]
    assert row[1]["numbers"]["card_odds|1X2|Home|0"] == "2.400" and set(row[1]["parts"]) >= {"lineups", "cards", "priced"}


def test_a_price_that_moves_two_percent_does_not_pay_for_the_brief_again_and_one_that_moves_four_does(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    assert first.engine == "llm" and not first.reused and len(model.requests) == 1
    two = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"))  # +2 %
    assert two.reused and two.reuse == "material" and two.id == first.id
    assert len(model.requests) == 1 and briefs(db, seed) == 1, "no call, no new row"
    four = read(db, model, packet_of(seed, odds=2.496), cards=card("2.496"))  # +4 %
    assert not four.reused and four.engine == "llm" and four.id != first.id
    assert len(model.requests) == 2 and briefs(db, seed) == 2


def test_drift_is_counted_against_what_the_model_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    for price in (2.42, 2.44, 2.46):  # a cent or two at a time: each is within 3 % of the 2.40 the model read
        step = read(db, model, packet_of(seed, odds=price), cards=card(f"{price:.3f}"))
        assert step.reused and step.id == first.id, price
    assert len(model.requests) == 1
    over = read(db, model, packet_of(seed, odds=2.48), cards=card("2.480"))  # +3.3 % since the reading, +0.8 % since the last look
    assert not over.reused and len(model.requests) == 2


def changes(seed: Seed) -> dict[str, dict[str, Any]]:
    """What the plan calls a material change, as the blocks of a packet that shows it."""
    return {
        "lineup": {"lineups": {"confirmed": True, "home": {"formation": "4-3-3", "coach": "A", "starters": [1, 2, 3]},
                               "away": {"formation": "4-4-2", "coach": "B", "starters": [4, 5, 6]}}},
        "absence": {"absences": {"checked": True, "away": {"players": [], "weight": 0, "key_out": 0},
                                 "home": {"players": [{"player_id": 77, "name": "Delantero", "type": "Missing Fixture",
                                                       "reason": "Knee", "key": True, "first_choice_gk": False,
                                                       "weight": 0.3}], "weight": 0.3, "key_out": 1}}},
        "evidence": {"evidence": [{"id": 31, "status": "PROBABLE", "origin": "web", "kind": "injury", "claim": "x"}]},
        "kickoff": {"fixture": fixture_block(seed, kickoff_at=(KO + timedelta(hours=2)).isoformat())},
        "suspension": {"fixture": fixture_block(seed, status="SUSP")},
        "scenario": {"stakes": {"home": {"pressure": "title_race"}, "away": {"pressure": "mid_table"}}},
    }


@pytest.mark.parametrize("what", ["lineup", "absence", "evidence", "kickoff", "suspension", "scenario"])
def test_what_the_plan_calls_a_material_change_pays_again(db: psycopg.Connection[Any], seed: Seed, what: str) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    after = read(db, model, packet_of(seed, **changes(seed)[what]))
    assert not after.reused and after.id != first.id and len(model.requests) == 2, what


def test_a_new_candidate_pays_again(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    read(db, model, packet_of(seed))
    both = card() + card(market="OU", selection="Over", line="2.5", odds="1.900", p_model="0.5000")
    assert not read(db, model, packet_of(seed), cards=both).reused and len(model.requests) == 2


def test_what_the_brief_does_not_read_as_context_does_not_pay_again(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    models = content(seed)["models"]
    models["dixon_coles"]["selections"][1]["p"] = 0.30  # the draw: not a candidate's number
    quality = {"competition_score": {"class": "MODEL_READY", "score": 0.5}, "fixture_validation": None, "lineups_confirmed": False}
    after = read(db, model, packet_of(seed, models=models, quality=quality))
    assert after.reused and after.reuse == "material" and after.id == first.id and len(model.requests) == 1


def test_the_servers_reasons_are_those_of_the_packet_now(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    assert first.reasons == ["candidate"]
    moved = content(seed, odds=2.448)
    moved["market"]["selections"][0]["movement"] = 0.05  # the de-vigged price moved 5 points since the opening
    after = read(db, model, Packet(seed.fixture_id, AT, moved), cards=card("2.448"))
    assert after.reused and after.reuse == "material" and after.id == first.id
    assert after.reasons == ["candidate", "market_move"] and after.escalate, "the reuse tells what the match is like now"
    stored = db.execute("SELECT reasons FROM ai.match_briefs WHERE id = %s", (first.id,)).fetchone()
    assert stored is not None and list(stored[0]) == ["candidate"], "the stored brief is untouched"


def test_the_flags_the_model_itself_raised_are_kept(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = FakeProvider(lambda r: brief_reply(uncertainty="high", escalate=True), name="anthropic")
    first = read(db, model, packet_of(seed))
    assert "high_uncertainty" in first.reasons
    after = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"))
    assert after.reused and after.reasons == ["candidate", "high_uncertainty"] and after.escalate


def test_rolled_back_only_an_identical_input_is_reused(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed), settings=ROLLED_BACK)
    same = read(db, model, packet_of(seed), settings=ROLLED_BACK)
    assert same.reused and same.reuse == "hash" and same.id == first.id and len(model.requests) == 1
    two = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"), settings=ROLLED_BACK)  # +2 %: the old hash changes
    assert not two.reused and len(model.requests) == 2


def test_an_identical_input_is_reused_by_its_hash_before_the_material_is_looked_at(db: psycopg.Connection[Any],
                                                                                    seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    again = read(db, model, packet_of(seed))
    assert again.reused and again.reuse == "hash" and again.id == first.id and len(model.requests) == 1


def test_a_brief_older_than_a_day_and_a_half_is_not_carried_over(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed))
    soon = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"), at=AT + timedelta(hours=35))
    assert soon.reused and soon.id == first.id
    late = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"), at=AT + timedelta(hours=37))
    assert not late.reused and len(model.requests) == 2


def test_a_brief_the_model_could_not_write_is_never_the_snapshot(db: psycopg.Connection[Any], seed: Seed) -> None:
    broken = FakeProvider(lambda r: {"nothing": "of the schema"}, name="anthropic")
    first = read(db, broken, packet_of(seed))
    assert first.status == "invalid_output"
    model = writer()
    after = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"))
    assert not after.reused and after.engine == "llm" and len(model.requests) == 1


def test_a_brief_the_rules_wrote_is_never_the_snapshot(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = writer()
    first = read(db, model, packet_of(seed), use_llm=False)
    assert first.engine == "rules" and len(model.requests) == 0
    row = db.execute("SELECT material_hash FROM ai.match_briefs WHERE id = %s", (first.id,)).fetchone()
    assert row is not None and row[0] is None
    after = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"))
    assert after.engine == "llm" and not after.reused and len(model.requests) == 1


def test_another_prompt_version_is_never_carried_over(db: psycopg.Connection[Any], seed: Seed,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    model = writer()
    read(db, model, packet_of(seed))
    monkeypatch.setattr("fbi.ai.brief.BRIEF_VERSION", "brief-v99-test")
    after = read(db, model, packet_of(seed, odds=2.448), cards=card("2.448"))
    assert not after.reused and len(model.requests) == 2


def test_a_snapshot_that_cannot_be_read_pays_as_before(db: psycopg.Connection[Any], seed: Seed,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import material

    def broken(*_a: Any, **_k: Any) -> Any:
        raise TypeError("a block of a shape nobody expected")

    monkeypatch.setattr(material, "material_of", broken)
    model = writer()
    first = read(db, model, packet_of(seed))
    assert first.engine == "llm" and not first.reused and len(model.requests) == 1, "the cycle does not stop"
    row = db.execute("SELECT material_hash FROM ai.match_briefs WHERE id = %s", (first.id,)).fetchone()
    assert row is not None and row[0] is None
