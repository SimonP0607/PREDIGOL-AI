"""IA-150 (plan PM, PM-06-03): how long before kick-off an absence reaches PrediGol by each channel already in use - the
figures, the lead against the provider's report with its intervals, and nothing of a player's health leaving the report."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

from scripts import ia_absence_timing as cli

from fbi.ingestion import absence_timing as at

KO = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)


def _case(n: int, **hours_before: float | None) -> at.Case:
    first = {ch: (None if h is None else KO - timedelta(hours=h)) for ch, h in hours_before.items()}
    return at.Case(fixture=1000 + n, player=n, kickoff_at=KO, league=39, kind="lesion", first=first)  # type: ignore[arg-type]


def test_hours_before_kickoff_per_channel_and_after_kickoff_counted_apart() -> None:
    cases = [_case(1, proveedor_parte=50), _case(2, proveedor_parte=60), _case(3, proveedor_parte=-12), _case(4)]
    fig = at.channel_figures(cases, "proveedor_parte")
    assert (fig["absences"], fig["before_kickoff"], fig["after_kickoff"]) == (3, 2, 1)
    assert fig["median_h"] == 55.0 and fig["small_sample"] is True
    assert at.channel_figures(cases, "prensa_medios")["absences"] == 0


def test_the_lead_against_the_provider_report_uses_only_pairs_both_brought_before_kickoff() -> None:
    cases = [_case(i, proveedor_parte=40, prensa_medios=46) for i in range(30)]  # the press 6 h earlier
    cases += [_case(100, proveedor_parte=40, prensa_medios=-1),  # the press after kick-off: no pair
              _case(101, prensa_medios=10)]  # the press alone: counted apart
    lead = at.against_reference(cases, "prensa_medios")
    assert lead["pairs"] == 30 and lead["median_lead_h"] == 6.0 and lead["earlier"] == 30
    assert lead["earlier_share"] == 1.0 and lead["earlier_share_ci95"][0] > 0.85
    assert lead["median_lead_ci95_h"] == [6.0, 6.0] and lead["small_sample"] is False
    assert lead["only_this_channel_before_kickoff"] == 1


def test_intervals_are_reproducible_and_honest() -> None:
    values = [float(x) for x in range(1, 41)]
    assert at.bootstrap(values) == at.bootstrap(values)  # fixed seed
    lo, hi = at.bootstrap(values) or (0.0, 0.0)
    assert lo < 20.5 < hi
    assert at.bootstrap([3.0]) is None and at.wilson(0, 0) is None
    lo, hi = at.wilson(1, 2) or (0.0, 0.0)
    assert lo < 0.5 < hi and hi - lo > 0.6  # two pairs say almost nothing
    assert at.quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5 and at.quantile([], 0.5) is None


def test_the_kind_is_reduced_and_never_a_diagnosis() -> None:
    row = {"fixture": 1, "player": 2, "kickoff_at": KO, "league": 39, "kind": "Knee Injury",
           **dict.fromkeys(at.CHANNELS)}
    assert at.case_of(row).kind == "otro"  # anything but the three words is not passed on
    assert re.search(at.SUSPENSION_RE, "yellow cards") and re.search(at.SUSPENSION_RE, "red card")
    assert re.search(at.NOT_HEALTH_RE, "coach's decision") and not re.search(at.NOT_HEALTH_RE, "knee injury")


def test_the_query_selects_no_reason_no_name_no_claim() -> None:
    select = at.CASES_SQL.rsplit("SELECT w.provider_fixture_id", 1)[1].split("FROM keys k", 1)[0]
    for word in ("reason", "player_name", "claim", "source_url", "name"):
        assert word not in select, word
    assert "o.origin = 'answer'" in at.CASES_SQL  # the 0078 snapshot is a copy, not an arrival
    assert "INSERT" not in at.CASES_SQL.upper() and "UPDATE" not in at.CASES_SQL.upper()


def test_the_summary_says_what_waits_for_the_owner() -> None:
    cases = [_case(i, proveedor_parte=50 + i, alineacion=0.5) for i in range(25)]
    out = at.summarise(cases, cadence=[{"league": 39, "reads": 14, "median_gap_h": 28.3}])
    assert out["version"] == "absence-timing-v1" and out["absences"] == 25 and out["kinds"] == {"lesion": 25}
    assert [c["channel"] for c in out["channels"]] == list(at.CHANNELS)
    assert any("DM-07" in p for p in out["pending_signature"]) and any("DM-05" in p for p in out["pending_signature"])
    assert out["cadence"] == [{"league": 39, "reads": 14, "median_gap_h": 28.3}]
    text = json.dumps(out)
    assert "Knee" not in text and "Injury" not in text


def test_the_sample_is_fixed_ids_and_times_only() -> None:
    cases = [_case(i, proveedor_parte=40 + i) for i in range(50)]
    a, b = at.sample(cases, 20), at.sample(cases, 20)
    assert a == b and len(a) == 20
    assert set(a[0]) == {"fixture", "player", "kickoff_at", "league", "kind", *at.CHANNELS}


def test_the_table_renders_every_channel() -> None:
    cases = [_case(i, proveedor_parte=50, prensa_medios=60) for i in range(3)]
    data = {"window": {"since": "2026-10-25T00:00:00+00:00", "until": "2026-11-21T00:00:00+00:00",
                       "measured_at": "2026-11-20T21:40:00+00:00"}, **at.summarise(cases)}
    text = cli.render(data)
    for name in cli.NAMES.values():
        assert name in text
    assert "Pendiente de firma" in text and "pequeña" in text
