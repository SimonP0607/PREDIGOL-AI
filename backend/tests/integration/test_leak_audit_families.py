"""The leak audit holds the decisions of the families (plan F11, ``leak-audit-v7``): the forecast each one cites and the price it was taken at.

A decision of a family (``decision-fam-v1``, ``fbi.familydecisions``) has no pick, no calibrator, no review and no evidence, so the rules that join
those drop it out; and the consensus rule of the pipeline reads ``market.market_consensus``, which a family does not price from. Two rules are theirs:

* ``family_forecast_known``: the forecast the decision cites is a row that exists for that match, model, market, line and selection, was written and
  had its data cut off by the decision's moment, and was the newest of its model for that selection by then;
* ``family_price_known``: the bookmaker the decision names had quoted that very price for that selection and line by the decision's moment.

Here: an honest decision passes every rule and each layer is counted by its own; a decision that cites no forecast, one that never existed, one
that is not a number, one written after the decision, one whose data was cut off after it, one of another selection, or one that another had
replaced by then is found, and a restatement written only after the decision is not; a price that no book quoted, one quoted only after the
decision, or one quoted by another book is found, and a newer price that appeared later is not a leak; and both rules stay linear in the
decisions of the day. The transaction is rolled back afterwards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import count
from time import perf_counter
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds, local_day
from fbi.core import decision_versions as dv
from fbi.families import forecast
from fbi.familydecisions import decide as fd
from fbi.intel import leakage
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT
from .test_familydecisions_decide import KICKOFF, LINE, NOW, Market, scene

pytestmark = pytest.mark.integration

FORECAST_RULE, PRICE_RULE = "family_forecast_known", "family_price_known"
NONE = {"checked": 0, "violations": 0, "examples": []}
serial = count(1)
"""A number for every hand-made row and every run of the audit (the audit keeps each run under its ``checked_at``, once)."""


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


# ── the world ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Honest:
    fixture: int
    market: Market
    decision: int
    forecast: int
    book: int
    over: float
    under: float


def honest(db: psycopg.Connection[Any], w: World) -> Honest:
    """A match 23 hours away that the families forecast and three books price, and the one decision a pass of the families takes on it."""
    fid, market, (over, under) = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [(decision, filters, book)] = db.execute("SELECT id, filters, bookmaker_id FROM intel.decisions WHERE decision_version = %s",
                                             (fd.VERSION,)).fetchall()
    cited = next(f for f in filters if f["key"] == "model")["data"]["forecast_id"]
    return Honest(fid, market, int(decision), int(cited), int(book), over, under)


def columns(db: psycopg.Connection[Any], table: str) -> list[str]:
    schema, name = table.split(".")
    return [r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                                     "AND column_name <> 'id' ORDER BY ordinal_position", (schema, name)).fetchall()]


def copy_of(db: psycopg.Connection[Any], table: str, source: int, changes: dict[str, Any]) -> int:
    cols = columns(db, table)
    select = ", ".join(f"%({c})s" if c in changes else c for c in cols)
    row = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) SELECT {select} FROM {table} WHERE id = %(source)s RETURNING id",
                     {**changes, "source": source}).fetchone()
    assert row is not None
    return int(row[0])


def forged(db: psycopg.Connection[Any], source: int, **changes: Any) -> int:
    """A decision written by hand: the one ``source`` with something changed, as a faulty writer would have put it (the table is append-only:
    a correction, or a fault, is a new row)."""
    changes.setdefault("input_hash", f"forged-{source}-{next(serial)}")
    if "filters" in changes:
        changes["filters"] = Jsonb(changes["filters"])
    return copy_of(db, "intel.decisions", source, changes)


def restated(db: psycopg.Connection[Any], source: int, **changes: Any) -> int:
    """A forecast stored again with something changed (a restatement is a new row: the table is append-only)."""
    return copy_of(db, "models.match_forecasts", source, changes)


def citing(db: psycopg.Connection[Any], decision: int, forecast_id: Any) -> list[dict[str, Any]]:
    """The filters of a decision with the forecast its model filter names changed (``None``: it names none)."""
    [(filters,)] = db.execute("SELECT filters FROM intel.decisions WHERE id = %s", (decision,)).fetchall()
    for f in filters:
        if f["key"] == "model":
            if forecast_id is None:
                f["data"].pop("forecast_id")
            else:
                f["data"]["forecast_id"] = forecast_id
    return list(filters)


def instead(db: psycopg.Connection[Any], h: Honest, **changes: Any) -> int:
    """The honest decision taken away and one written by hand in its place: the audit then speaks of this one alone."""
    bad = forged(db, h.decision, **changes)
    db.execute("SET LOCAL fbi.intel_maintenance = 'on'")
    db.execute("DELETE FROM intel.decisions WHERE id = %s", (h.decision,))
    db.execute("SET LOCAL fbi.intel_maintenance = 'off'")
    return bad


def forecast_of(db: psycopg.Connection[Any], h: Honest, selection: str, line: str) -> int:
    [(found,)] = db.execute("SELECT id FROM models.match_forecasts WHERE fixture_id = %s AND version = %s AND market_key = 'CORNERS_OU' "
                            "AND selection = %s AND line = %s AND model_name = 'family-corners_ft'", (h.fixture, forecast.VERSION, selection, line)).fetchall()
    return int(found)


def audited(db: psycopg.Connection[Any], at: datetime = NOW) -> dict[str, dict[str, Any]]:
    """The whole audit on the Bogotá day of ``at``; each call is a run of its own."""
    return leakage.audit_day(db, day=local_day(at), at=at + timedelta(minutes=next(serial)))


def found(db: psycopg.Connection[Any], rule: str) -> dict[str, Any]:
    return audited(db)[rule]


# ── what the rules are, and the honest decision ──────────────────────────────────────────────────────────────────

def test_the_rules_are_in_the_audit_the_version_says_so_and_the_text_documents_them() -> None:
    assert leakage.VERSION == "leak-audit-v8"
    for rule in (FORECAST_RULE, PRICE_RULE):
        assert rule in leakage.RULES and rule in (leakage.__doc__ or "")
        assert "%(families)s" in leakage.RULES[rule], "they read the layer of the families by the constant of the core"
    assert "%(core)s" in leakage.RULES["consensus_known"], "and the consensus rule reads the pipeline's own layer"
    assert dv.DECISION_FAMILIES == fd.VERSION
    assert len({dv.DECISION_FAMILIES, dv.DECISION_CORE}) == 2, "two layers, two versions"


def test_an_honest_decision_of_a_family_passes_every_rule_and_the_ledger_keeps_the_run(db: psycopg.Connection[Any], w: World) -> None:
    honest(db, w)
    out = audited(db)
    assert out[FORECAST_RULE] == {"checked": 1, "violations": 0, "examples": []}
    assert out[PRICE_RULE] == {"checked": 1, "violations": 0, "examples": []}
    assert out["known_before_kickoff"]["checked"] == 1 and out["price_known"]["checked"] == 1, "the rules over every layer count it"
    for rule in ("pick_known", "calibrator_known", "review_known", "evidence_known", "consensus_known"):
        assert out[rule] == NONE, f"a family has no pick, calibrator, review or evidence, and the consensus rule is the pipeline's: {rule}"
    assert not [r for r, v in out.items() if v["violations"]], "nothing in the day is a violation"
    ledger = db.execute("SELECT rule, version, n_checked, n_violations FROM intel.audit_checks WHERE rule LIKE 'family\\_%' ORDER BY rule").fetchall()
    assert ledger == [(FORECAST_RULE, "leak-audit-v8", 1, 0), (PRICE_RULE, "leak-audit-v8", 1, 0)]


def test_a_day_without_decisions_of_the_families_checks_nothing(db: psycopg.Connection[Any], w: World) -> None:
    out = audited(db)
    assert out[FORECAST_RULE] == NONE and out[PRICE_RULE] == NONE


def test_each_layer_is_counted_by_its_own_rules(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    core = forged(db, h.decision, decision_version=dv.DECISION_CORE)
    out = audited(db)
    assert out[FORECAST_RULE]["checked"] == 1 and out[PRICE_RULE]["checked"] == 1, "a row under the core's version is not a family's"
    assert out["consensus_known"] == {"checked": 1, "violations": 1, "examples": [core]}, (
        "the pipeline's row needed a consensus of its market at the moment of its price, and there is none; the family's row is not asked for it")
    assert out["known_before_kickoff"]["checked"] == 2


# ── the forecast it cites ────────────────────────────────────────────────────────────────────────────────────────

def test_a_decision_that_cites_no_forecast_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    bad = instead(db, h, filters=citing(db, h.decision, None))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_forecast_that_never_existed_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    bad = instead(db, h, filters=citing(db, h.decision, 987_654_321))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


@pytest.mark.parametrize("cited", ["not-a-number", "", "1.5", "99999999999999999999", [3], {"id": 3}, True])
def test_a_citation_that_is_not_a_number_is_a_violation_and_never_stops_the_audit(db: psycopg.Connection[Any], w: World, cited: Any) -> None:
    h = honest(db, w)
    bad = instead(db, h, filters=citing(db, h.decision, cited))
    out = audited(db)
    assert out[FORECAST_RULE] == {"checked": 1, "violations": 1, "examples": [bad]}
    assert out[PRICE_RULE]["checked"] == 1, "the rest of the audit ran"


def test_a_forecast_written_after_the_decision_is_the_future_and_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    later = restated(db, h.forecast, known_at=NOW + timedelta(minutes=5))
    bad = instead(db, h, filters=citing(db, h.decision, later))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_forecast_whose_data_was_cut_off_after_the_decision_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    cut = restated(db, h.forecast, known_at=NOW, data_cutoff_ts=NOW + timedelta(minutes=10))
    bad = instead(db, h, filters=citing(db, h.decision, cut))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_forecast_whose_data_was_cut_off_at_the_very_moment_of_the_decision_is_the_forecast_of_the_moment(db: psycopg.Connection[Any],
                                                                                                         w: World) -> None:
    h = honest(db, w)
    now = restated(db, h.forecast, known_at=NOW - timedelta(minutes=1), data_cutoff_ts=NOW)
    instead(db, h, filters=citing(db, h.decision, now))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 0, "examples": []}


@pytest.mark.parametrize(("selection", "line"), [("Under", LINE), ("Over", "9.50")])
def test_a_forecast_of_another_selection_or_line_is_not_the_one_the_decision_is_about(db: psycopg.Connection[Any], w: World, selection: str,
                                                                                    line: str) -> None:
    h = honest(db, w)
    other = forecast_of(db, h, selection, line)
    assert other != h.forecast
    bad = instead(db, h, filters=citing(db, h.decision, other))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_forecast_of_another_model_than_the_one_named_is_not_the_one_the_decision_read(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    other = restated(db, h.forecast, known_at=AT + timedelta(minutes=10), model_name="family-another")
    bad = instead(db, h, filters=citing(db, h.decision, other))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_decision_that_read_an_older_forecast_than_the_one_that_stood_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    restated(db, h.forecast, known_at=AT + timedelta(minutes=30))  # the family stated something else half an hour after the first
    out = found(db, FORECAST_RULE)
    assert out == {"checked": 1, "violations": 1, "examples": [h.decision]}, "the decision of NOW cites the forecast of AT"


def test_a_restatement_written_only_after_the_decision_does_not_make_it_stale(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    restated(db, h.forecast, known_at=NOW + timedelta(minutes=5))
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 0, "examples": []}


def test_a_forecast_of_another_model_is_not_a_newer_forecast_of_this_one(db: psycopg.Connection[Any], w: World) -> None:
    """The pass reads the last forecast of each model of each selection (``FORECASTS_SQL``), so the rule asks the same."""
    h = honest(db, w)
    restated(db, h.forecast, known_at=AT + timedelta(minutes=30), model_name="family-another")
    assert found(db, FORECAST_RULE) == {"checked": 1, "violations": 0, "examples": []}


def test_the_decision_that_cites_the_forecast_that_stood_is_not_stale_when_it_is_the_newer_one(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    newer = restated(db, h.forecast, known_at=AT + timedelta(minutes=30))
    later = forged(db, h.decision, filters=citing(db, h.decision, newer), known_at=NOW + timedelta(minutes=10), price_at=NOW)
    out = found(db, FORECAST_RULE)
    assert out == {"checked": 2, "violations": 1, "examples": [h.decision]}, "the first still cites the older one, the second the one that stood"
    assert later not in out["examples"]


# ── the price it was taken at ────────────────────────────────────────────────────────────────────────────────────

def test_a_price_that_no_book_ever_quoted_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    bad = instead(db, h, odds=Decimal("7.777"))
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_price_quoted_only_after_the_decision_is_the_future_and_one_quoted_before_it_is_not(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    h.market.quote(h.book, 5.55, 1.15, NOW + timedelta(minutes=10))
    bad = instead(db, h, odds=Decimal("5.550"))
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}

    h.market.quote(h.book, 5.55, 1.15, NOW - timedelta(minutes=5))  # the same price, quoted by the same book before the decision
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 0, "examples": []}, "the book had quoted 5.55 five minutes before"


def test_a_price_that_another_book_quoted_is_not_the_price_of_the_book_named(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    quoter, other = w.books(3)[0], w.books(3)[2]
    h.market.quote(quoter, 4.44, 1.25, NOW - timedelta(minutes=5))
    bad = instead(db, h, odds=Decimal("4.440"), bookmaker_id=other)
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}
    ok = forged(db, bad, bookmaker_id=quoter)
    out = audited(db)[PRICE_RULE]
    assert (out["checked"], out["violations"], out["examples"]) == (2, 1, [bad]) and ok not in out["examples"]


def test_a_book_that_never_quoted_the_match_is_found(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    bad = instead(db, h, bookmaker_id=987_654)
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


@pytest.mark.parametrize("changes", [{"selection": "Under"}, {"line": Decimal("11.50")}], ids=["selection", "line"])
def test_the_price_of_another_selection_or_line_is_not_the_price_of_this_one(db: psycopg.Connection[Any], w: World, changes: dict[str, Any]) -> None:
    h = honest(db, w)
    bad = instead(db, h, **changes)
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 1, "examples": [bad]}


def test_a_newer_quote_that_appeared_later_does_not_make_the_decision_a_leak(db: psycopg.Connection[Any], w: World) -> None:
    """A payload read again by a newer extractor writes its quotes with the instant it was fetched: a quote can appear for a moment the decision
    could not have known of. The price the decision took had been the book's, and taking an older price is staleness, not a leak."""
    h = honest(db, w)
    h.market.quote(h.book, h.over + 0.50, h.under - 0.10, NOW - timedelta(minutes=20))  # captured before the decision, written after it
    assert found(db, PRICE_RULE) == {"checked": 1, "violations": 0, "examples": []}


# ── the rules over every layer, on a family's row ────────────────────────────────────────────────────────────────

def test_the_table_itself_refuses_a_decision_taken_after_the_kick_off_or_priced_after_it_was_taken(db: psycopg.Connection[Any], w: World) -> None:
    """So ``known_before_kickoff`` and ``price_known`` can only count a family's row, never find one: the rules are a second wall."""
    h = honest(db, w)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        forged(db, h.decision, known_at=KICKOFF + timedelta(hours=1))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        forged(db, h.decision, price_at=NOW + timedelta(minutes=1))


# ── the size ─────────────────────────────────────────────────────────────────────────────────────────────────────

SIZE, WRONG = 5_000, 60
"""Decisions of one Bogotá day (a busy night has a few thousand), and how many of them cite a forecast of another match / a price no book quoted."""
LIMIT, RUNS = 10.0, 3
"""Seconds, for the fastest of ``RUNS`` runs of a rule. Each rule is a handful of index probes per decision and takes a quarter of a second here; a rule that
grew with the square of the decisions (the ``h2h_known`` of 24 Oct 2026 took hours over 10,000 packets) would take minutes. The limit is generous and the
fastest run counts on purpose: a busy machine (the first full run on the final tree of F11 had a release package being built beside it) stretched one run
from 0.2 s to 5.6 s, and a test of the SHAPE of the cost must not fail for the load of the machine."""


def multiplied(db: psycopg.Connection[Any], h: Honest, n: int) -> tuple[list[int], list[int]]:
    """``n`` more matches like the one of the scene - the same quotes, the same forecast, the same decision - and the ids of the decisions that
    cite a forecast of another match (the first ``WRONG``) and those that name a price no book quoted (the next ``WRONG``)."""
    cols = columns(db, "core.fixtures")
    swap = {"provider_fixture_id": "8000000 + g", "kickoff_at": "f.kickoff_at + g * interval '1 second'"}
    select = ", ".join(swap.get(c, f"f.{c}") for c in cols)
    fixtures = sorted(r[0] for r in db.execute(f"INSERT INTO core.fixtures ({', '.join(cols)}) SELECT {select} FROM core.fixtures f "
                                               "CROSS JOIN generate_series(1, %(n)s) g WHERE f.id = %(src)s RETURNING id", {"n": n, "src": h.fixture}))
    assert len(fixtures) == n

    cols = columns(db, "market.odds_quotes")
    db.execute(f"INSERT INTO market.odds_quotes ({', '.join(cols)}) SELECT {', '.join('u.fid' if c == 'fixture_id' else f'q.{c}' for c in cols)} "
               "FROM market.odds_quotes q CROSS JOIN unnest(%(fx)s::bigint[]) AS u(fid) WHERE q.fixture_id = %(src)s", {"fx": fixtures, "src": h.fixture})

    cols = columns(db, "models.match_forecasts")
    own = dict(db.execute(f"INSERT INTO models.match_forecasts ({', '.join(cols)}) SELECT {', '.join('u.fid' if c == 'fixture_id' else f'mf.{c}' for c in cols)} "
                          "FROM models.match_forecasts mf CROSS JOIN unnest(%(fx)s::bigint[]) AS u(fid) WHERE mf.id = %(src)s RETURNING fixture_id, id",
                          {"fx": fixtures, "src": h.forecast}).fetchall())
    cited = [own[fixtures[(i + 1) % n]] if i < WRONG else own[fx] for i, fx in enumerate(fixtures)]
    prices = [Decimal("9.999") if WRONG <= i < 2 * WRONG else None for i in range(n)]

    cols = columns(db, "intel.decisions")
    swap = {"fixture_id": "u.fid", "input_hash": "'scale-' || u.fid", "odds": "coalesce(u.odds, d.odds)",
            "filters": "(SELECT jsonb_agg(CASE WHEN e ->> 'key' = 'model' THEN jsonb_set(e, '{data,forecast_id}', to_jsonb(u.cited)) ELSE e END ORDER BY o) "
                       "FROM jsonb_array_elements(d.filters) WITH ORDINALITY AS t(e, o))"}
    made = dict(db.execute(f"INSERT INTO intel.decisions ({', '.join(cols)}) SELECT {', '.join(swap.get(c, f'd.{c}') for c in cols)} "
                           "FROM intel.decisions d CROSS JOIN unnest(%(fx)s::bigint[], %(cited)s::bigint[], %(odds)s::numeric[]) AS u(fid, cited, odds) "
                           "WHERE d.id = %(src)s RETURNING fixture_id, id", {"fx": fixtures, "cited": cited, "odds": prices, "src": h.decision}).fetchall())
    for table in ("core.fixtures", "market.odds_quotes", "models.match_forecasts", "intel.decisions"):
        db.execute(f"ANALYZE {table}")  # as the statistics of a table in use are
    return [made[fx] for fx in fixtures[:WRONG]], [made[fx] for fx in fixtures[WRONG:2 * WRONG]]


def timed(db: psycopg.Connection[Any], rule: str) -> tuple[dict[str, Any], float]:
    """The row the rule gives and the time of its fastest run out of ``RUNS`` (the rule reads, it writes nothing: every run gives the same row)."""
    start, end = day_bounds(local_day(NOW))
    row: dict[str, Any] = {}
    fastest = float("inf")
    with db.cursor(row_factory=dict_row) as cur:
        for _ in range(RUNS):
            t0 = perf_counter()
            cur.execute(leakage.RULES[rule], {"start": start, "end": end, "core": dv.DECISION_CORE, "families": dv.DECISION_FAMILIES})
            row = cur.fetchone() or {}
            fastest = min(fastest, perf_counter() - t0)
    return row, fastest


def test_both_rules_stay_linear_in_the_decisions_of_the_day(db: psycopg.Connection[Any], w: World) -> None:
    h = honest(db, w)
    wrong_forecast, wrong_price = multiplied(db, h, SIZE)
    for rule, bad in ((FORECAST_RULE, wrong_forecast), (PRICE_RULE, wrong_price)):
        row, seconds = timed(db, rule)
        assert (row["n"], row["bad"]) == (SIZE + 1, WRONG), f"{rule}: every decision of the day, and exactly the ones made wrong"
        assert list(row["examples"]) == sorted(bad)[:5], "the first five of them, by id"
        assert seconds < LIMIT, f"{rule} took {seconds:.2f} s over {SIZE + 1} decisions"
