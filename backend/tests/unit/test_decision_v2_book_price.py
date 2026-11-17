"""The odds book's price as of a moment, the second price source of decision-v2 (``fbi.decision.book_price``, plan INT-A06, IA-037), without a
database: the answer in force by the moment (never after it), a body priced exactly as the capture's consensus prices it, the candidates priced
by the book and only the core's, the age and the source the decision keeps, the close for the CLV, and the price section of the replay's
report. The SQL against a real database is in tests/integration/test_decision_v2_book_price.py."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from scripts import ia_decision_v2 as cli

from fbi.decision import book_price, engine, price_age, replay
from fbi.decision.book_price import CAPTURE, REFRESH, Answer, BookReader, Indexed, Quoted, TaggedAsk
from fbi.decision.families import CORE, FORECAST_FAMILIES, Candidate
from fbi.domain.market_probability import DevigMethod
from fbi.intel import decision
from fbi.market.consensus import BookQuote, consensus
from fbi.storage.payload_store import PayloadStore, body_hash

from .test_decision_v2_engine import AT, KEY, MODEL, pick, world

PID = 9_001
FIXTURE = KEY[0]
KO = AT + timedelta(hours=3)
BOOKS = {8: 1, 11: 2, 16: 3}
"""provider bookmaker id -> ``market.bookmakers.id``."""


def body(*, home: float = 2.0, update: str | None = "2026-11-05T14:00:00+00:00", fixture: int = PID, unlisted: bool = False) -> dict[str, Any]:
    """An answer of ``/odds?fixture=`` as the provider sends it: three bookmakers price the match's 1X2 and its goals at 2.5. Up to a home price
    of 2.15 every book keeps a margin (a book without one is left out of the consensus, as a stale quote)."""
    prices = {8: (home, 3.5, 3.9, 1.9, 1.95), 11: (home + 0.05, 3.4, 3.8, 1.92, 1.9), 16: (home - 0.05, 3.6, 4.0, 1.88, 1.98)}
    if unlisted:
        prices[77] = (home + 0.5, 3.0, 3.0, 1.8, 1.8)
    entry: dict[str, Any] = {"fixture": {"id": fixture}, "bookmakers": [
        {"id": b, "name": f"Book {b}", "bets": [
            {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": f"{h:.2f}"}, {"value": "Draw", "odd": f"{d:.2f}"},
                                                         {"value": "Away", "odd": f"{a:.2f}"}]},
            {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": f"{o:.2f}"}, {"value": "Under 2.5", "odd": f"{u:.2f}"}]}]}
        for b, (h, d, a, o, u) in prices.items()]}
    if update is not None:
        entry["update"] = update
    return {"get": "odds", "results": 1, "response": [entry]}


def stored(root: Path, b: dict[str, Any], name: str) -> Indexed:
    """The body written to a RAW store as the capture writes it (a gzipped envelope), and its index row."""
    path = root / f"{name}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"endpoint": "/odds", "body": b}))
    return Indexed(body_hash(b), path.name, 200, 1, {"fixture": str(PID), "page": "1"})


def reader(root: Path, asks: list[TaggedAsk], index: list[Indexed]) -> BookReader:
    return BookReader(PayloadStore(root), {FIXTURE: (PID, KO)}, {FIXTURE: sorted(asks, key=lambda a: a.asked_at)},
                      {i.payload_hash: i for i in index}, BOOKS)


def at(minutes_before_ko: float) -> datetime:
    return KO - timedelta(minutes=minutes_before_ko)


# -- a body, priced as the capture's consensus prices it -------------------------------------------------------------------------------------

def test_a_body_is_priced_as_the_consensus_prices_the_same_quotes() -> None:
    b = body()
    prices, stamp = book_price.price_body(b, provider_fixture_id=PID, kickoff_at=KO, bookmakers=BOOKS)
    quotes = [BookQuote(BOOKS[bk["id"]], m, s, Decimal(line), Decimal(o)) for bk in b["response"][0]["bookmakers"]
              for m, rows in (("1X2", bk["bets"][0]["values"]), ("OU", bk["bets"][1]["values"]))
              for v in rows for s, line, o in [(v["value"].split(" ")[0], v["value"].split(" ")[1] if " " in v["value"] else "0", v["odd"])]]
    expected = {(r.market_key, r.selection, Decimal(r.line).quantize(decision.LINE_Q)): r for r in consensus(quotes, methods=(DevigMethod.SHIN,))}
    assert set(prices) == set(expected) and len(prices) == 5, "Home/Draw/Away and Over/Under 2.5"
    for k, q in prices.items():
        r = expected[k]
        assert (q.best_odds, q.p_fair, q.n_bookmakers, q.best_bookmaker_id) == (float(r.best_odds), round(r.p_fair, 6), r.n_bookmakers,
                                                                                r.best_bookmaker_id), "rounded as the consensus is stored"
    assert prices[("1X2", "Home", Decimal("0.00"))].best_odds == 2.05 and prices[("1X2", "Home", Decimal("0.00"))].best_bookmaker_id == 2
    assert stamp == datetime(2026, 11, 5, 14, 0, tzinfo=UTC)


def test_a_body_prices_only_its_own_match_and_an_unlisted_bookmaker_keeps_an_id_above_every_listed_one() -> None:
    assert book_price.price_body(body(fixture=PID + 1), provider_fixture_id=PID, kickoff_at=KO, bookmakers=BOOKS) == ({}, None)
    prices, _ = book_price.price_body(body(unlisted=True), provider_fixture_id=PID, kickoff_at=KO, bookmakers=BOOKS)
    home = prices[("1X2", "Home", Decimal("0.00"))]
    assert home.n_bookmakers == 4 and home.best_odds == 2.5 and home.best_bookmaker_id == book_price.UNKNOWN_BOOKMAKER + 77


def test_the_provider_stamp_is_read_with_its_zone_and_a_missing_one_is_none() -> None:
    assert book_price.provider_stamp(body(update="2026-11-05T14:00:00Z"), PID) == datetime(2026, 11, 5, 14, tzinfo=UTC)
    assert book_price.provider_stamp(body(update="2026-11-05T14:00:00"), PID) == datetime(2026, 11, 5, 14, tzinfo=UTC), "no zone: UTC"
    assert book_price.provider_stamp(body(update=None), PID) is None
    assert book_price.provider_stamp(body(update="ayer"), PID) is None


# -- the answer in force, as of the moment ----------------------------------------------------------------------------------------------------

def test_the_answer_in_force_is_the_newest_ask_by_the_moment_a_capture_or_a_refresh(tmp_path: Path) -> None:
    a, b = stored(tmp_path, body(home=2.0), "a"), stored(tmp_path, body(home=2.1), "b")
    asks = [TaggedAsk(CAPTURE, at(180), 1, a.payload_hash), TaggedAsk(REFRESH, at(60), 1, b.payload_hash),
            TaggedAsk(CAPTURE, at(40), 1, a.payload_hash), TaggedAsk(REFRESH, at(10), 0, None)]
    r = reader(tmp_path, asks, [a, b])
    home = ("1X2", "Home", Decimal("0.00"))
    before = r.answer_at(FIXTURE, at(200))
    assert before.state == "never_asked" and not before.prices
    first = r.answer_at(FIXTURE, at(100))
    assert (first.state, first.confirmed_by, first.checked_at, first.prices[home].best_odds) == ("priced", CAPTURE, at(180), 2.05)
    refreshed = r.answer_at(FIXTURE, at(50))
    assert (refreshed.confirmed_by, refreshed.checked_at, refreshed.prices[home].best_odds) == (REFRESH, at(60), 2.15), "the refresh is newer"
    back = r.answer_at(FIXTURE, at(20))
    assert (back.confirmed_by, back.checked_at, back.since, back.prices[home].best_odds) == (CAPTURE, at(40), at(40), 2.05), "A -> B -> A reads A"
    gone = r.answer_at(FIXTURE, at(5))
    assert (gone.state, gone.checked_at, gone.prices) == ("withdrawn", at(10), {}), "an empty answer withdraws every price"
    assert r.close(FIXTURE).state == "withdrawn"
    assert len(r.bodies) == 2, "each body is read from RAW once"


def test_an_ask_after_the_moment_is_never_read() -> None:
    asks = [TaggedAsk(CAPTURE, at(180), 1, "a"), TaggedAsk(REFRESH, at(60), 1, "b")]
    found, _ = book_price.readings(asks, {h: Indexed(h, h, 200, 1, {"fixture": str(PID)}) for h in "ab"}, fixture_id=FIXTURE,
                                   provider_fixture_id=PID)
    chosen = book_price.in_force(asks, found, fixture_id=FIXTURE, kickoff_at=KO, at=at(61))
    assert chosen.checked_at == at(180), "the refresh of a minute later did not exist yet"
    assert book_price.kind_of(asks, at(60)) == REFRESH and book_price.kind_of(asks, at(1)) is None


def test_a_body_the_provider_did_not_answer_for_the_match_leaves_the_older_one_in_force(tmp_path: Path) -> None:
    a = stored(tmp_path, body(home=2.0), "a")
    bad = replace(stored(tmp_path, body(home=2.1), "b"), http_status=500)
    other = replace(stored(tmp_path, body(home=2.12), "c"), params={"fixture": str(PID + 1)})
    asks = [TaggedAsk(CAPTURE, at(180), 1, a.payload_hash), TaggedAsk(REFRESH, at(60), 1, bad.payload_hash),
            TaggedAsk(REFRESH, at(30), 1, other.payload_hash)]
    answer = reader(tmp_path, asks, [a, bad, other]).answer_at(FIXTURE, at(20))
    assert (answer.state, answer.checked_at, answer.confirmed_by) == ("priced", at(180), CAPTURE)


def test_a_body_missing_from_raw_shows_nothing_of_the_match_and_says_why(tmp_path: Path) -> None:
    a = stored(tmp_path, body(), "a")
    (tmp_path / a.file_path).unlink()
    r = reader(tmp_path, [TaggedAsk(CAPTURE, at(180), 1, a.payload_hash)], [a])
    answer = r.answer_at(FIXTURE, at(100))
    assert (answer.state, answer.checked_at, answer.prices) == (book_price.UNREADABLE, at(180), {})
    assert r.problems and "not in the RAW store" in r.problems[0]


def test_a_file_that_does_not_give_its_hash_is_not_believed(tmp_path: Path) -> None:
    a = replace(stored(tmp_path, body(), "a"), payload_hash="f" * 64)
    answer = reader(tmp_path, [TaggedAsk(CAPTURE, at(180), 1, a.payload_hash)], [a]).answer_at(FIXTURE, at(100))
    assert answer.state == book_price.UNREADABLE


# -- the candidates, priced by the book ------------------------------------------------------------------------------------------------------

QUOTED = Quoted(2.2, 0.47, 5, 1.05, 0.01, 4)


def answer(**kw: Any) -> Answer:
    base: dict[str, Any] = {"fixture_id": FIXTURE, "state": "priced", "checked_at": AT - timedelta(minutes=12), "confirmed_by": REFRESH,
                            "since": AT - timedelta(hours=2), "payload_hash": "h", "provider_update_at": AT - timedelta(hours=3),
                            "prices": {KEY[1:]: QUOTED}}
    return Answer(**(base | kw))


def test_the_core_candidates_take_every_price_field_from_the_book_and_the_others_are_left_alone() -> None:
    row = pick()
    core = Candidate(CORE, KEY, {MODEL: row, "elo": dict(row)})
    family = Candidate(FORECAST_FAMILIES[0], (FIXTURE, "corners_ft_ou", "Over", Decimal("9.50")), {MODEL: dict(row)}, model_hint=MODEL)
    out = book_price.priced([core, family], {FIXTURE: answer()}, family=CORE.name)
    assert out[1] is family, "a family of F10 keeps its own price (the quotes in force)"
    for r in out[0].models.values():
        assert (r["best_odds"], r["p_fair"], r["n_bookmakers"], r["best_bookmaker_id"], r["price_at"]) == (2.2, 0.47, 5, 4, AT - timedelta(minutes=12))
        assert (r["price_source"], r["price_confirmed_by"], r["price_missing"]) == (engine.BOOK, REFRESH, None)
        assert r["p_model"] == row["p_model"], "only the price moves"
    assert core.models[MODEL]["best_odds"] == row["best_odds"] == 2.0, "the candidate given is untouched"


def test_a_selection_the_book_does_not_price_has_no_price_and_says_why() -> None:
    def missing(a: Answer | None) -> dict[str, Any]:
        return book_price.book_fields(a, KEY)

    assert missing(None)["price_missing"] == "never_asked"
    assert missing(answer(prices={}))["price_missing"] == book_price.NOT_QUOTED
    withdrawn = missing(answer(state="withdrawn", prices={}))
    assert withdrawn["price_missing"] == "withdrawn" and all(withdrawn[f] is None for f in book_price.PRICE_FIELDS)


def test_the_decision_judges_the_book_price_and_keeps_its_source_age_and_stamp() -> None:
    w = world()
    [c] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer()}, family=CORE.name)
    d = engine.decide(w, c)
    assert (d.price.source, d.price.confirmed_by, d.price.age_minutes, d.price.odds) == (engine.BOOK, REFRESH, 12.0, 2.2)
    assert d.price.provider_update_at == AT - timedelta(hours=3) and d.price.missing is None
    assert d.verdict("market").ok is True
    js = d.as_json()["price"]
    assert (js["source"], js["confirmed_by"], js["missing"]) == ("book", "refresh", None)
    [old] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer(checked_at=AT - timedelta(hours=4))}, family=CORE.name)
    assert "price_stale" in engine.decide(w, old).codes, "decision-v1's thresholds judge the book's age"


def test_without_a_book_price_the_market_stage_says_so_with_decision_v1s_code() -> None:
    [c] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer(state="withdrawn", prices={})}, family=CORE.name)
    d = engine.decide(world(), c)
    assert d.state == "REJECTED" and d.reason == "no_price" and d.price.missing == "withdrawn"
    assert d.verdict("market").why == "sin precio vigente en el libro (withdrawn)"
    assert d.price.age_minutes is None and d.price.confirmed_by is None


def test_the_default_price_is_decision_v1s_consensus_of_a_capture() -> None:
    d = engine.decide(world(), Candidate(CORE, KEY, {MODEL: pick()}))
    assert (d.price.source, d.price.confirmed_by, d.price.missing, d.close) == (engine.CONSENSUS, CAPTURE, None, None)
    assert d.verdict("market").why.startswith("6 casas")
    assert engine.decide(world(), Candidate(CORE, KEY, {MODEL: pick(odds=None)})).verdict("market").why == "sin precio de mercado observado"  # type: ignore[arg-type]


# -- the close, for the CLV ------------------------------------------------------------------------------------------------------------------

def test_the_close_is_the_last_answer_before_kick_off_with_its_distances(tmp_path: Path) -> None:
    a, b = stored(tmp_path, body(home=2.0), "a"), stored(tmp_path, body(home=2.1, update="2026-11-05T16:30:00+00:00"), "b")
    r = reader(tmp_path, [TaggedAsk(CAPTURE, at(180), 1, a.payload_hash), TaggedAsk(REFRESH, at(9), 1, b.payload_hash)], [a, b])
    closes = book_price.closes(r, [FIXTURE, 404])
    home = closes[(FIXTURE, "1X2", "Home", Decimal("0.00"))]
    assert (home.odds, home.confirmed_by, home.minutes_to_kickoff, home.provider_minutes_to_kickoff) == (2.15, REFRESH, 9.0, 90.0)
    assert home.version == book_price.VERSION and len(closes) == 5, "every selection the answer prices; an unknown match none"
    assert book_price.close_of(answer(state="withdrawn", prices={}), KO) == {}


def test_the_close_travels_with_the_decision_and_changes_nothing_of_it() -> None:
    w = world()
    c = Candidate(CORE, KEY, {MODEL: pick()})
    close = engine.Close(2.1, 0.5, 6, AT, 9.0, REFRESH, None, None, book_price.VERSION)
    [plain] = engine.decide_all(w, [c])
    [carried] = engine.decide_all(w, [c], closes={KEY: close})
    assert carried.close == close and plain.close is None
    assert replace(carried, close=None) == plain
    assert carried.as_json()["close"]["minutes_to_kickoff"] == 9.0


# -- the replay's price section and the command -------------------------------------------------------------------------------------------

def pairs_of(decided: list[engine.Decision2], **row: Any) -> list[replay.Pair]:
    return [(dict(row) | {"id": i, "known_at": AT}, "core", d) for i, d in enumerate(decided, 1)]


def test_the_price_section_counts_the_decisions_without_an_age_and_their_age() -> None:
    w = world()
    decided = [engine.decide(w, Candidate(CORE, KEY, {MODEL: pick(price_age=timedelta(minutes=m))})) for m in (10, 30, 50)]
    out = replay.price_summary([*pairs_of(decided), ({"id": 9, "known_at": AT}, "core", None)], source=engine.CONSENSUS)
    assert (out["source"], out["decisions"], out["with_price"], out["without_age"]) == ("consensus", 3, 3, 0)
    assert out["age_minutes"]["p50"] == 30.0 and out["age_minutes"]["max"] == 50.0
    assert "against_v1" not in out and "close" not in out, "the default report measures, and adds nothing of the book"


def test_with_the_book_the_section_compares_with_decision_v1s_price_and_reports_the_close() -> None:
    w = world()
    close = engine.Close(2.1, 0.5, 6, AT, 9.0, REFRESH, AT - timedelta(hours=1), 70.0, book_price.VERSION)
    [c] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer()}, family=CORE.name)
    [d] = engine.decide_all(w, [c], closes={KEY: close})
    [none] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer(prices={})}, family=CORE.name)
    rows = pairs_of([d, engine.decide(w, none)], odds=2.0, p_market=0.48, price_at=AT - timedelta(hours=5))
    out = replay.price_summary(rows, source=engine.BOOK)
    assert (out["with_price"], out["without_age"], out["confirmed_by"], out["missing"]) == (1, 0, {"refresh": 1}, {"not_quoted": 1})
    assert out["v1_age_minutes"]["p50"] == 300.0 and out["age_minutes"]["p50"] == 12.0
    assert out["against_v1"]["rows"] == 1 and out["against_v1"]["odds_gap_pct"]["p50"] == 10.0 and out["against_v1"]["odds_moved"] == 1
    assert out["against_v1"]["p_gap_pp"]["p50"] == pytest.approx(1.0)
    assert out["close"]["decisions"] == 1 and out["close"]["minutes_to_kickoff"]["p50"] == 9.0
    assert out["close"]["provider_minutes_to_kickoff"]["p50"] == 70.0


def test_the_replay_refuses_an_unknown_price_and_the_book_without_its_store() -> None:
    nothing = cast(psycopg.Connection[Any], None)
    with pytest.raises(ValueError, match="price must be one of"):
        replay.replay_day(nothing, day=AT.date(), price="mercado")
    with pytest.raises(ValueError, match="RAW store"):
        replay.replay_day(nothing, day=AT.date(), price=engine.BOOK)


def test_the_command_takes_the_price_source_and_prints_it() -> None:
    args = cli.build_parser().parse_args(["replay", "--day", "2026-11-10", "--price", "book", "--raw", "/data/raw"])
    assert (args.price, args.raw) == ("book", "/data/raw")
    plain_args = cli.build_parser().parse_args(["replay", "--day", "2026-11-10"])
    assert (plain_args.price, plain_args.rules) == (None, engine.RULES_V20)
    assert replay.price_of(plain_args.rules, plain_args.price) == engine.CONSENSUS, "the default is decision-v1's price"
    w = world()
    [d] = engine.decide_all(w, book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer()}, family=CORE.name),
                            closes={KEY: engine.Close(2.1, 0.5, 6, AT, 9.0, REFRESH, None, None, book_price.VERSION)})
    section = replay.price_summary(pairs_of([d], odds=2.0, p_market=0.48, price_at=AT - timedelta(hours=5)), source=engine.BOOK)
    lines = cli.render_price(section | {"reader": {"matches": 1, "bodies_read": 2, "unreadable": 0}})
    text = "\n".join(lines)
    assert "price: book, 1/1 decisions with a price, 0 without its age" in text and "confirmed by {'refresh': 1}" in text
    assert "close: 1 decisions, minutes to kick-off p50 9.0" in text and "book read: 1 matches, 2 bodies" in text
    plain = cli.render_price(replay.price_summary(pairs_of([engine.decide(w, Candidate(CORE, KEY, {MODEL: pick()}))]), source=engine.CONSENSUS))
    assert len(plain) == 2 and plain[0].startswith("  price: consensus")
    assert plain[1] == "    price states {'vigente': 1} under price-age-v1: 0/1 priced past their limit (0.00%)"


def test_the_command_reads_with_a_timeout_only_with_the_book() -> None:
    text = Path(cli.__file__).read_text(encoding="utf-8")
    assert "statement_timeout=95000" in cli.BOOK_TIMEOUT and "default_transaction_read_only=on" in cli.READ_ONLY
    assert "BOOK_TIMEOUT}\" if book else READ_ONLY" in text


# -- decision-v2.1: the book's price and the age rule by horizon (plan 2026, AD-B06, IA-067) -------------------------------------------------

V2 = price_age.V2


def limit_at(minutes_to_kickoff: float) -> float:
    return V2.limit(minutes_to_kickoff, decision.checkpoint_of(minutes_to_kickoff, important=False, lineups=False)).market.total_seconds() / 60


@pytest.mark.parametrize(("minutes", "limit"), [(44, 45), (45, 75), (46, 75), (344, 75), (345, 195), (346, 195), (10, 45), (2160, 195)])
def test_each_band_starts_15_minutes_before_the_ask_that_opens_it(minutes: float, limit: float) -> None:
    assert limit_at(minutes) == limit


@pytest.mark.parametrize("minutes", [44, 45, 46, 344, 345, 346])
def test_a_price_as_old_as_its_limit_is_in_force_and_a_second_older_is_not(minutes: float) -> None:
    cp = decision.checkpoint_of(minutes, important=False, lineups=False)
    lim = V2.limit(minutes, cp).market
    at_limit = V2.check(priced=True, age=lim, minutes_to_kickoff=minutes, checkpoint=cp)
    over = V2.check(priced=True, age=lim + timedelta(seconds=1), minutes_to_kickoff=minutes, checkpoint=cp)
    assert (at_limit.state, at_limit.reason, at_limit.max_age_minutes) == (price_age.VIGENTE, None, limit_at(minutes))
    assert (over.state, over.reason, over.rule) == (price_age.ANTIGUO, price_age.OVER_LIMIT, "price-age-v2")


def test_the_rule_travels_as_data_with_its_version_bands_lead_and_states() -> None:
    js = V2.as_json()
    assert js["version"] == "price-age-v2" and js["lead_minutes"] == 15.0 and js["require_age"] is True
    assert [(b["name"], b["from_minutes"], b["to_minutes"], b["max_age_minutes"], b["nominal_from_minutes"]) for b in js["bands"]] == [
        ("far", 345.0, None, 195.0, 360.0), ("near", 45.0, 345.0, 75.0, 60.0), ("last", 0.0, 45.0, 45.0, 0.0)]
    assert js["states"] == ["vigente", "antiguo", "sin_precio"] and js["final_rule"] == "band"
    assert json.loads(json.dumps(js)) == js, "plain JSON, for the contracts"
    rs = engine.RULESETS[engine.RULES_V21].as_json()
    assert (rs["label"], rs["price"], rs["age"]["version"]) == ("decision-v2.1", "book", "price-age-v2")


def test_decision_v2_0_keeps_decision_v1s_limits_imported_not_copied() -> None:
    v1 = price_age.V1
    assert v1.bands[0].max_age is decision.MAX_PRICE_AGE and v1.final_max_age is decision.FINAL_FRESH and not v1.require_age
    assert engine.DEFAULT_RULES is engine.RULESETS[engine.RULES_V20] and engine.DEFAULT_RULES.price == engine.CONSENSUS
    assert engine.DEFAULT_RULES.age is v1 and v1.flat
    assert v1.limit(59, "T-60m").final == decision.FINAL_FRESH and v1.limit(300, "T-6h").final is None


def booked(**kw: Any) -> dict[str, Any]:
    """A core candidate's row priced by the book (its price and age as ``pick`` gives them)."""
    return pick(**kw) | {"price_source": engine.BOOK, "price_confirmed_by": REFRESH, "price_missing": None}


def decide_at(minutes: float, age: timedelta | None, rules: engine.Ruleset = engine.DEFAULT_RULES) -> engine.Decision2:
    row = booked(kickoff=timedelta(minutes=minutes), price_age=age or timedelta(0))
    if age is None:
        row["price_at"] = None
    return engine.decide(world(), Candidate(CORE, KEY, {MODEL: row}), rules=rules)


V21 = engine.RULESETS[engine.RULES_V21]


def test_the_default_ruleset_decides_as_before_and_says_so() -> None:
    for minutes, age in ((300, 20), (300, 190), (59, 40), (2000, 150)):
        plain = engine.decide(world(), Candidate(CORE, KEY, {MODEL: booked(kickoff=timedelta(minutes=minutes), price_age=timedelta(minutes=age))}))
        assert plain == decide_at(minutes, timedelta(minutes=age)), "decision-v2.0 is the default"
        assert plain.rules == engine.RULES_V20 and plain.price.age_rule == "price-age-v1"
    assert decide_at(300, timedelta(minutes=190)).verdict("market").why == "precio de hace 3.2 h", "decision-v1's words, as before"
    assert decide_at(59, timedelta(minutes=40)).reason == "price_not_fresh"


def test_far_from_kick_off_195_minutes_pass_where_decision_v1_stops_at_3_hours() -> None:
    old, new = decide_at(346, timedelta(minutes=190)), decide_at(346, timedelta(minutes=190), V21)
    assert "price_stale" in old.codes and old.price.state == price_age.ANTIGUO
    assert "price_stale" not in new.codes and new.verdict("market").ok is True
    assert (new.rules, new.price.state, new.price.band, new.price.max_age_minutes) == ("decision-v2.1", "vigente", "far", 195.0)


def test_between_345_and_45_minutes_a_price_older_than_75_minutes_is_old() -> None:
    d = decide_at(344, timedelta(minutes=100), V21)
    assert d.state == "WATCH" and d.reason == "price_stale" and d.price.state == price_age.ANTIGUO
    assert d.verdict("market").why == "precio de hace 100 min: máximo 75 min a 344 min del saque (price-age-v2)"
    assert d.verdict("market").data["band"] == "near"
    assert "price_stale" not in decide_at(344, timedelta(minutes=100)).codes, "decision-v1 accepted it (3 h)"


def test_at_the_t60_checkpoint_a_late_refresh_does_not_age_the_price_and_stage_9_holds_the_band() -> None:
    # a decision at 59 min reads the refresh of T-120 (about 65 min old) while the one of T-60 is late: decision-v1's 30 min refuse it
    old, new = decide_at(59, timedelta(minutes=65)), decide_at(59, timedelta(minutes=65), V21)
    assert old.checkpoint == new.checkpoint == "T-60m" and old.reason == "price_not_fresh"
    assert "price_not_fresh" not in new.codes and new.verdict("price").ok is True and new.price.max_age_minutes == 75.0
    late = decide_at(30, timedelta(minutes=50), V21)
    assert {"price_stale", "price_not_fresh"} <= set(late.codes) and late.state == "WATCH"
    assert late.verdict("price").why == "precio de hace 50 min en T-60m (máximo 45 min, price-age-v2)"


def test_a_price_without_its_age_is_old_under_the_new_rule_and_says_why() -> None:
    d = decide_at(300, None, V21)
    assert d.reason == "price_stale" and (d.price.state, d.price.state_reason) == (price_age.ANTIGUO, price_age.NO_AGE)
    assert d.verdict("market").why == "precio sin edad: no se puede comprobar (price-age-v2)"
    assert "price_stale" not in decide_at(300, None).codes, "decision-v1's rule never asked for an age"


def test_without_a_price_the_state_is_sin_precio_with_the_books_own_reason() -> None:
    [c] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer(state="withdrawn", prices={})}, family=CORE.name)
    d = engine.decide(world(), c, rules=V21)
    assert (d.state, d.reason, d.price.state, d.price.state_reason) == ("REJECTED", "no_price", price_age.SIN_PRECIO, "withdrawn")
    plain = engine.decide(world(), Candidate(CORE, KEY, {MODEL: booked(odds=None)}), rules=V21)
    assert (plain.price.state, plain.price.state_reason, plain.price.age_rule) == (price_age.SIN_PRECIO, price_age.NO_PRICE, "price-age-v2")
    js = d.as_json()
    assert js["rules"] == "decision-v2.1" and (js["price"]["state"], js["price"]["age_rule"]) == ("sin_precio", "price-age-v2")


def test_the_new_ruleset_judges_the_book_price_with_its_age() -> None:
    [c] = book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer(checked_at=AT - timedelta(minutes=190))}, family=CORE.name)
    assert "price_stale" in engine.decide(world(), c).codes, "decision-v1's 3 h"
    d = engine.decide(world(), c, rules=V21)
    assert d.price.source == engine.BOOK and d.price.state == price_age.ANTIGUO and d.price.max_age_minutes == 75.0, "5 h: the near band"


# -- the replay: the ruleset, the other rulesets, the states -------------------------------------------------------------------------------

def test_a_ruleset_brings_its_price_and_a_variant_names_another() -> None:
    assert replay.price_of(engine.RULES_V21, None) == engine.BOOK and replay.price_of(engine.RULES_V21, engine.CONSENSUS) == engine.CONSENSUS
    assert replay.variant("decision-v2.0") == ("decision-v2.0", "consensus") and replay.variant("decision-v2.0:book") == ("decision-v2.0", "book")
    with pytest.raises(ValueError, match="rules must be one of"):
        replay.variant("decision-v9")
    with pytest.raises(ValueError, match="price must be one of"):
        replay.variant("decision-v2.0:mercado")
    nothing = cast(psycopg.Connection[Any], None)
    with pytest.raises(ValueError, match="RAW store"):
        replay.replay_day(nothing, day=AT.date(), rules=engine.RULES_V21)
    with pytest.raises(ValueError, match="RAW store"):
        replay.replay_day(nothing, day=AT.date(), against=["decision-v2.0:book"])


def test_versus_counts_the_changes_by_stage_and_direction_and_none_to_recommended() -> None:
    w = world()
    rows = [(346, 190), (344, 100), (59, 65), (300, 20)]
    items: list[replay.Versus] = []
    for i, (minutes, age) in enumerate(rows, 1):
        c = Candidate(CORE, KEY, {MODEL: booked(kickoff=timedelta(minutes=minutes), price_age=timedelta(minutes=age))})
        items.append(({"id": i, "known_at": AT, "fixture_id": FIXTURE, "market_key": "1X2", "selection": "Home", "line": 0}, "core",
                      engine.decide(w, c, rules=V21), engine.decide(w, c)))
    items.append(({"id": 9, "known_at": AT, "fixture_id": FIXTURE, "market_key": "1X2", "selection": "Home", "line": 0}, "core", None, None))
    v = replay.versus_summary(items, main=("decision-v2.1", "book"), other=("decision-v2.0", "consensus"))
    assert (v["main"], v["other"], v["rows"], v["changed"]) == ("decision-v2.1:book", "decision-v2.0:consensus", 4, 3)
    assert v["transitions"] == {"WATCH -> RECOMMENDED": 1, "RECOMMENDED -> WATCH": 1, "CAUTION -> RECOMMENDED": 1}
    assert v["by_stage"] == {"market": 2, "price": 1} and v["by_stage_direction"] == {"market:baja": 1, "market:sube": 1, "price:sube": 1}
    assert (v["up"], v["down"], v["to_recommended"]) == (2, 1, 2), "a toy world approves everything else; production's edge gate does not"
    assert v["price_state_changes"] == {"antiguo -> vigente": 2, "vigente -> antiguo": 1}
    assert v["other_price_states"]["rules"] == ["price-age-v1"] and v["other_price_states"]["old"] == 2
    assert v["examples"][1]["why"] == "precio de hace 100 min: máximo 75 min a 344 min del saque (price-age-v2)"


def test_the_price_section_counts_the_states_by_band_and_the_share_past_the_limit() -> None:
    w = world()
    decided = [engine.decide(w, Candidate(CORE, KEY, {MODEL: booked(kickoff=timedelta(minutes=m), price_age=timedelta(minutes=a))}), rules=V21)
               for m, a in ((400, 20), (400, 200), (100, 30), (30, 10))]
    decided.append(engine.decide(w, Candidate(CORE, KEY, {MODEL: booked(odds=None)}), rules=V21))
    s = replay.price_summary(pairs_of(decided), source=engine.BOOK)["states"]
    assert s["rules"] == ["price-age-v2"] and s["by_state"] == {"antiguo": 1, "sin_precio": 1, "vigente": 3}
    assert s["by_band"] == {"far": {"antiguo": 1, "vigente": 1}, "last": {"vigente": 1}, "near": {"sin_precio": 1, "vigente": 1}}
    assert (s["priced"], s["old"], s["old_rate"]) == (4, 1, 0.25) and s["reasons"] == {"antiguo:over_limit": 1, "sin_precio:no_price": 1}
    assert "by_source" not in s, "one source: no breakdown"
    family = engine.decide(w, Candidate(CORE, KEY, {MODEL: pick(price_age=timedelta(minutes=200))}), rules=V21)
    mixed = replay.price_summary(pairs_of([*decided, family]), source=engine.BOOK)["states"]
    assert mixed["rules"] == ["price-age-v1", "price-age-v2"] and set(mixed["by_source"]) == {"book", "consensus"}
    assert mixed["by_source"]["book"]["old_rate"] == 0.25 and mixed["by_source"]["consensus"]["by_band"] == {"any": {"antiguo": 1}}


def test_the_rule_by_horizon_judges_only_the_books_prices_the_others_keep_decision_v1s() -> None:
    assert V21.age_for(engine.BOOK) is price_age.V2 and V21.age_for(engine.CONSENSUS) is price_age.V1
    assert engine.DEFAULT_RULES.age_for(engine.BOOK) is price_age.V1, "decision-v2.0 judges every price by decision-v1's rule"
    own = Candidate(CORE, KEY, {MODEL: pick(kickoff=timedelta(minutes=344), price_age=timedelta(minutes=100))})
    d = engine.decide(world(), own, rules=V21)
    assert d.price.age_rule == "price-age-v1" and "price_stale" not in d.codes and d.rules == "decision-v2.1"
    assert engine.decide(world(), own) == replace(d, rules=engine.RULES_V20), "a price not from the book: the same decision"
    js = V21.as_json()
    assert (js["age_sources"], js["other_sources_age"]) == (["book"], "price-age-v1")


def test_the_command_takes_the_ruleset_and_the_rulesets_against_and_reads_the_book_only_when_one_needs_it() -> None:
    args = cli.build_parser().parse_args(["replay", "--day", "2026-11-14", "--rules", "decision-v2.1", "--against", "decision-v2.0",
                                          "--against", "decision-v2.0:book"])
    assert (args.rules, args.price, args.against) == ("decision-v2.1", None, ["decision-v2.0", "decision-v2.0:book"])
    assert cli.needs_book(None, "decision-v2.1", []) and cli.needs_book(None, "decision-v2.0", ["decision-v2.0:book"])
    assert not cli.needs_book(None, "decision-v2.0", ["decision-v2.0"]) and not cli.needs_book("consensus", "decision-v2.1", [])
    v = {"changed": 1, "rows": 4, "up": 0, "down": 1, "to_recommended": 0, "transitions": {"CAUTION -> WATCH": 1}, "by_stage": {"market": 1},
         "price_state_changes": {}, "examples": []}
    assert cli.render_versus("decision-v2.0:consensus", v)[0].startswith("  versus decision-v2.0:consensus: 1/4 changed state (0 up, 1 down")
