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

from fbi.decision import book_price, engine, replay
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
    assert cli.build_parser().parse_args(["replay", "--day", "2026-11-10"]).price == engine.CONSENSUS, "the default is decision-v1's price"
    w = world()
    [d] = engine.decide_all(w, book_price.priced([Candidate(CORE, KEY, {MODEL: pick()})], {FIXTURE: answer()}, family=CORE.name),
                            closes={KEY: engine.Close(2.1, 0.5, 6, AT, 9.0, REFRESH, None, None, book_price.VERSION)})
    section = replay.price_summary(pairs_of([d], odds=2.0, p_market=0.48, price_at=AT - timedelta(hours=5)), source=engine.BOOK)
    lines = cli.render_price(section | {"reader": {"matches": 1, "bodies_read": 2, "unreadable": 0}})
    text = "\n".join(lines)
    assert "price: book, 1/1 decisions with a price, 0 without its age" in text and "confirmed by {'refresh': 1}" in text
    assert "close: 1 decisions, minutes to kick-off p50 9.0" in text and "book read: 1 matches, 2 bodies" in text
    plain = cli.render_price(replay.price_summary(pairs_of([engine.decide(w, Candidate(CORE, KEY, {MODEL: pick()}))]), source=engine.CONSENSUS))
    assert len(plain) == 1 and plain[0].startswith("  price: consensus")


def test_the_command_reads_with_a_timeout_only_with_the_book() -> None:
    text = Path(cli.__file__).read_text(encoding="utf-8")
    assert "statement_timeout=95000" in cli.BOOK_TIMEOUT and "default_transaction_read_only=on" in cli.READ_ONLY
    assert "BOOK_TIMEOUT}\" if book else READ_ONLY" in text
