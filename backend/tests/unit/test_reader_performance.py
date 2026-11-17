"""AD-K03 (IA-135): the performance of the readers against the rules on the same selections and of the sources by type of fact
(``perf-v1`` under the protocol ``AD-K03``). Metrics against cases computed by hand; nothing decides. No database, no model."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from scripts import ia_reader_performance as script

from fbi.ai import intervals
from fbi.ai.agents import attribution
from fbi.evalpass import performance as perf
from fbi.evalpass import performance_reads as reads
from fbi.evaluation import selection
from fbi.research import protocol

D0 = date(2026, 10, 1)


def test_the_needed_sample_is_the_power_calculation_the_protocol_wrote_before_looking() -> None:
    p = protocol.require("AD-K03")
    assert perf.NEEDED == protocol.n_for_mean(0.13, 0.01) == 1327
    assert "1.327" in p.reject_rule and "1.327" in p.min_sample and "1.326,5" in p.power_note
    assert f"{perf.MIN_DAYS} días" in p.reject_rule and f"{perf.MIN_DISCORDANT} selecciones" in p.reject_rule
    assert "30 hechos resueltos" in p.pass_rule and perf.MIN_FACTS == 30
    assert "Bonferroni" in p.primary_metric and p.seed == perf.SEED and p.registered_on == "2026-11-17"
    assert p.key == perf.PROTOCOL


def test_it_reads_the_versions_of_the_rules_it_measures() -> None:
    assert reads.ATTRIBUTION_VERSION == attribution.VERSION == "attr-v1"
    assert set(perf.AGAINST) == set(attribution.AGAINST_STANCES) and set(perf.NO_SIDE) == set(attribution.NO_SIDE)


@pytest.mark.parametrize("k, n", [(0, 0), (0, 10), (7, 10), (10, 10), (412, 1327)])
def test_the_wilson_interval_is_the_platforms(k: int, n: int) -> None:
    mine, theirs = perf.wilson(k, n), intervals.wilson(k, n)
    assert (mine is None) == (theirs is None)
    if mine is not None and theirs is not None:
        assert mine == pytest.approx(theirs, abs=1e-12)


def j(i: int, *, stance: str = "NEUTRAL", rules: str | None = "APPROVE", clv: float | None = 0.0, reader: str = "match/match-v5",
      outcome: str = "VOID", toward: bool | None = None, days: int = 20) -> perf.Judged:
    return perf.Judged(reader=reader, fixture_id=i // 3, selection=f"1X2:home:{i}", day=D0 + timedelta(days=i % days), stance=stance,
                       rules_word=rules, clv=clv, outcome=outcome, toward_close=toward)


def test_the_difference_is_the_value_the_veto_takes_out_of_what_the_rules_let_through() -> None:
    assert j(1, stance="CONCERN", clv=-0.04).difference == pytest.approx(0.04), "vetoing a selection with negative CLV adds value"
    assert j(1, stance="REJECT_SIGNAL", clv=0.03).difference == pytest.approx(-0.03)
    assert j(1, stance="CONCERN", rules="DOWNGRADE", clv=-0.04).difference == 0.0, "the rules had already stopped it"
    assert j(1, stance="CONCERN", rules="ABSTAIN", clv=-0.04).discordant, "an abstention of the rules lets it through (filter 6)"
    assert j(1, stance="SUPPORT", clv=-0.04).difference == 0.0
    assert not j(1, rules=None).examined and not j(1, clv=None).examined and not j(1, clv=math.nan).examined


def population(*, vetoed_clv: float, n: int = perf.NEEDED + 13, vetoes: int = 60, reader: str = "match/match-v5") -> list[perf.Judged]:
    out = [j(i, stance="CONCERN", clv=vetoed_clv, reader=reader) for i in range(vetoes)]
    return out + [j(i, clv=0.02 if i % 2 else -0.02, reader=reader) for i in range(vetoes, n)]


@pytest.mark.parametrize("vetoed_clv, verdict", [(-0.30, "APORTA"), (0.30, "RESTA"), (0.0, "SIN_DIFERENCIA")])
def test_a_reader_with_the_sample_gets_the_verdict_of_its_interval(vetoed_clv: float, verdict: str) -> None:
    got = perf.reader_entry(population(vetoed_clv=vetoed_clv), m=1)
    assert got["verdict"] == verdict and got["missing"] == []
    assert got["examined"] == perf.NEEDED + 13 and got["discordant"] == 60 and got["days"] == 20
    expected = -vetoed_clv * 60 / (perf.NEEDED + 13)
    assert got["difference"]["mean"] == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("n, vetoes, days, missing", [(perf.NEEDED - 1, 60, 20, "examinadas"), (perf.NEEDED + 10, 29, 20, "vetos"),
                                                     (perf.NEEDED + 10, 60, 13, "días")])
def test_below_the_preregistered_sample_a_reader_is_insufficient_without_conclusion(n: int, vetoes: int, days: int, missing: str) -> None:
    items = [j(i, stance="CONCERN" if i < vetoes else "NEUTRAL", clv=-0.5 if i < vetoes else 0.0, days=days) for i in range(n)]
    got = perf.reader_entry(items, m=1)
    assert got["verdict"] == "INSUFICIENTE" and any(m.startswith(missing) for m in got["missing"])


def test_bonferroni_counts_the_readers_that_reach_the_sample_and_the_player_is_named_without_attribution() -> None:
    items = population(vetoed_clv=-0.3) + population(vetoed_clv=0.0, reader="stats/stats-v4") + [j(1, reader="council/council-v1@ma-v1")]
    got = perf.readers(items)
    assert got["bonferroni"] == {"m": 2, "level": 0.975}
    assert got["readers"]["match/match-v5"]["difference"]["level"] == 0.975
    assert got["readers"]["council/council-v1@ma-v1"]["verdict"] == "INSUFICIENTE"
    assert got["readers"]["player/*"]["verdict"] == "INSUFICIENTE" and "Jugador" in got["readers"]["player/*"]["missing"][0]


def test_the_attribution_comes_with_its_wilson_intervals() -> None:
    items = [j(i, stance="SUPPORT", outcome="HIT" if i < 7 else "MISS", toward=i < 4) for i in range(10)] + [j(20, stance="ABSTAIN")]
    got = perf.reader_entry(items, m=1)["attribution"]
    assert got["hits"]["k"] == 7 and got["hits"]["n"] == 10 and got["hits"]["ci95"] == [round(x, 4) for x in intervals.wilson(7, 10) or ()]
    assert got["toward_close"]["k"] == 4 and got["toward_close"]["n"] == 10
    assert got["no_side"] == {"k": 1, "n": 11, "share": round(1 / 11, 4), "ci95": [round(x, 4) for x in intervals.wilson(1, 11) or ()]}


def test_the_interval_resamples_whole_days() -> None:
    values = [(D0, 1.0), (D0, 1.0), (D0 + timedelta(days=1), 0.0)]
    mean, lo, hi = perf.by_day(values, replicates=500)
    assert mean == pytest.approx(2 / 3) and lo == 0.0 and hi == 1.0, "a day is drawn whole: the mean of a draw is 0, 2/3 or 1"
    assert perf.by_day([(D0, 0.5)]) == (0.5, None, None) and perf.by_day([]) == (None, None, None)


def c(eid: int, status: str, *, source: str | None = "marca.com", fact: str | None = "out", sel: int = 0,
      clv: float | None = 0.01) -> perf.Cited:
    return perf.Cited(evidence_id=eid, source=source, fact_type=fact, status=status, day=D0 + timedelta(days=eid % 5), fixture_id=eid,
                      selection=f"s{sel}", clv=clv)


def test_a_source_is_measured_by_its_facts_each_counted_once() -> None:
    cited = [c(i, "sostenido") for i in range(27)] + [c(100 + i, "contradicho") for i in range(3)]
    cited += [c(5, "sostenido", sel=1)]  # the same fact cited by another selection: one fact
    cited += [c(200, "no_evaluable"), c(300, "sostenido", source=None), c(301, "sostenido", fact="doubtful")]
    cited += [c(400 + i, "contradicho", source="other.com") for i in range(30)]
    got = perf.sources(cited)
    cell = next(x for x in got["cells"] if x["source"] == "marca.com")
    assert cell["held"]["k"] == 27 and cell["held"]["n"] == 30 and cell["unevaluable"] == 1 and cell["status"] == "medida"
    assert cell["relation_to_others"] == "por_encima" and cell["others_share"] == 0.0
    assert cell["citing_selections"]["n"] == 32 and "descriptivo" in cell["citing_selections"]["note"]
    assert got["without_source_or_type"] == 2 and got["facts"] == 61 and got["measured"] == 2


def test_below_thirty_resolved_facts_a_source_is_insufficient() -> None:
    got = perf.sources([c(i, "sostenido") for i in range(29)])
    assert got["cells"][0]["status"] == "INSUFICIENTE" and got["cells"][0]["relation_to_others"] == "insuficiente"


def test_the_report_informs_and_decides_nothing() -> None:
    doc = perf.report([], [], period={"start": "a", "end": "b"})
    assert doc["decides"] is False and doc["signed_by_owner"] is False and doc["protocol"]["protocol"] == "AD-K03"
    assert doc["needed"] == {"examined": 1327, "days": 14, "discordant": 30, "facts": 30} and "AD-K07" in doc["notice_es"]


# -- the reads ----------------------------------------------------------------------------------------------------------------------

def test_the_stances_are_one_per_selection_and_reader_with_the_rules_word_before_kick_off() -> None:
    sql = reads.STANCES_SQL
    assert "signal = 'VERDICT'" in sql and "classified_by = 'code'" in sql and "x.engine = 'rules'" in sql
    assert "x.reviewed_at < a.kickoff_at" in sql and "(a.engine = 'ma-v1') DESC" in sql
    assert not any(w in sql.upper() for w in ("INSERT ", "UPDATE ", "DELETE "))
    assert "e.version = %(version)s" in reads.CITED_SQL


def test_rows_become_what_the_metrics_read() -> None:
    at = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)  # 1 am UTC is still 1-nov in Bogotá
    row = {"agent": "council", "agent_version": "council-v1", "arm": "ma-v1-h", "fixture_id": 9, "market_key": "OU", "selection": "over",
           "line": Decimal("2.50"), "kickoff_at": at, "stance": "DOWNGRADE", "rules_word": "APPROVE", "clv": Decimal("-0.0300"),
           "outcome": "HIT", "toward_close": True}
    got = reads.judged_of([row])[0]
    assert got.reader == "council/council-v1@ma-v1-h" and got.selection == "OU:over:2.5" and got.day == date(2026, 11, 1)
    assert got.discordant and got.difference == pytest.approx(0.03)
    assert reads.judged_of([{**row, "agent": "match", "agent_version": "match-v5", "arm": "*"}])[0].reader == "match/match-v5"


@pytest.mark.parametrize("name, url, source", [("Marca", "https://www.marca.com/futbol/x", "marca.com"), ("AS", None, "as"),
                                               (None, None, None), ("  ", "", None)])
def test_the_source_of_a_fact_is_its_host_or_its_name(name: str | None, url: str | None, source: str | None) -> None:
    assert reads.source_of(name, url) == source


def test_the_facts_of_an_evaluation_become_what_the_metrics_read() -> None:
    row = {"fixture_id": 4, "market_key": "1X2", "selection": "home", "line": Decimal("0"),
           "kickoff_at": datetime(2026, 11, 2, 18, tzinfo=UTC), "clv": 0.01, "evidence_id": 11, "claim": "out", "status": "sostenido"}
    assert reads.cited_of([row], {11: "marca.com"}) == [perf.Cited(11, "marca.com", "out", "sostenido", date(2026, 11, 2), 4,
                                                                   "1X2:home:0", 0.01)]
    assert reads.cited_of([{**row, "evidence_id": None}], {}) == []
    assert selection.EVIDENCE_RULES == "eval-evidence-v1", "the statuses are those of eval-sel-v1"


def test_the_window_of_the_command_is_bogota_days() -> None:
    start, end = script.bounds(date(2026, 11, 1), date(2026, 11, 3), at=datetime(2026, 12, 1, tzinfo=UTC))
    assert start == datetime(2026, 11, 1, 5, tzinfo=UTC) and end == datetime(2026, 11, 3, 5, tzinfo=UTC)
    with pytest.raises(ValueError):
        script.bounds(date(2026, 11, 3), date(2026, 11, 3), at=datetime(2026, 12, 1, tzinfo=UTC))
