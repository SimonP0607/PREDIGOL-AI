"""The download of the published picks (plan PM, PM-14-08): what is in the file, and what never is."""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fbi.api.contracts.transparency import PublishedPick
from fbi.api.services import transparency_export as export

AT = datetime(2032, 9, 20, 12, tzinfo=UTC)


def pick(**over: object) -> PublishedPick:
    base: dict[str, object] = {
        "day": date(2032, 9, 19), "kickoff_at": datetime(2032, 9, 19, 20, tzinfo=UTC),
        "published_at": datetime(2032, 9, 19, 9, tzinfo=UTC), "competition": "Premier League", "country": "England",
        "home": "A", "away": "B", "market": "1X2", "selection": "Home", "line": Decimal("0"), "odds": Decimal("2.00"),
        "p_model": Decimal("0.55"), "p_market": Decimal("0.50"), "result": "WIN", "units": Decimal("1"), "score_home": 2,
        "score_away": 1}
    base.update(over)
    return PublishedPick(**base)  # type: ignore[arg-type]


def rows(text: str) -> list[list[str]]:
    assert text.startswith("﻿"), "a spreadsheet reads the accents"
    return list(csv.reader(io.StringIO(text[1:])))


def test_the_wilson_interval_is_the_textbook_one() -> None:
    assert export.wilson(0, 0) is None
    low, high = export.wilson(5, 10)  # type: ignore[misc]
    assert (low, high) == (Decimal("0.2366"), Decimal("0.7634"))
    low, high = export.wilson(0, 10)  # type: ignore[misc]
    assert low == Decimal("0.0000") and high == Decimal("0.2775"), "a 0 % sample is not certain: the interval says so"
    low, high = export.wilson(100, 100)  # type: ignore[misc]
    assert high == Decimal("1.0000") and low < Decimal("0.97")


def test_a_bigger_sample_narrows_the_interval() -> None:
    small = export.wilson(6, 10)
    big = export.wilson(600, 1000)
    assert small is not None and big is not None
    assert big[1] - big[0] < small[1] - small[0]


def test_the_csv_has_one_line_per_pick_with_as_many_cells_as_headings() -> None:
    table = rows(export.picks_csv([pick(), pick(result="PENDING", units=None, score_home=None, score_away=None)],
                                  tz="America/Bogota", language="es"))
    assert len(table) == 3 and {len(r) for r in table} == {17}
    head = dict(zip(table[0], table[1], strict=True))
    assert head["mercado"] == "1X2" and head["cuota_publicada"] == "2.00" and head["prob_dicha"] == "0.55"
    assert head["resultado"] == "Ganado" and head["unidades"] == "1" and head["goles_local"] == "2"
    pending = dict(zip(table[0], table[2], strict=True))
    assert pending["unidades"] == "" and pending["goles_local"] == "", "not settled is empty, never a zero"


def test_the_headings_follow_the_readers_language() -> None:
    en = rows(export.picks_csv([pick()], tz="UTC", language="en-GB"))
    assert en[0][0] == "day" and en[1][en[0].index("result")] == "Won"


def test_no_heading_is_a_return_on_investment() -> None:
    for lang in ("es", "en"):
        for part in ("picks", "calibration"):
            for heading in export.HEADINGS[lang][part]:
                assert not any(w in heading for w in ("roi", "yield", "rentab", "profit", "beneficio", "total"))


def test_a_text_that_a_spreadsheet_would_run_is_defused() -> None:
    table = rows(export.picks_csv([pick(home="=HYPERLINK(1)", away="+cmd")], tz="UTC", language="es"))
    assert table[1][5].startswith("'=") and table[1][6].startswith("'+")


def test_the_json_carries_the_notes_and_never_a_return() -> None:
    cal: dict[str, Any] = {"picks_won_or_lost": 3, "min_sample": 25, "min_bin": 30, "hit_rate": None, "bins": [], "omitted": 0, "method": "x"}
    body = json.loads(export.picks_json([pick()], cal, tz="UTC", at=AT))
    assert body["count"] == 1 and body["picks"][0]["odds"] == "2.00" and body["calibration"] == cal
    assert any("no return" in n for n in body["notes"])
    assert "roi" not in json.dumps(body).lower().replace("no return on investment", "")


def test_the_calibration_csv_has_the_interval_of_every_range() -> None:
    cal = {"bins": [{"from": Decimal("0.5"), "to": Decimal("0.6"), "mean_said": Decimal("0.55"), "observed": Decimal("0.5"),
                     "n": 40, "interval_95": {"from": Decimal("0.35"), "to": Decimal("0.65")}}]}
    table = rows(export.calibration_csv(cal, language="en"))
    assert table[0][-3:] == ["interval_95_from", "interval_95_to", "picks"] and table[1][-3:] == ["0.35", "0.65", "40"]
