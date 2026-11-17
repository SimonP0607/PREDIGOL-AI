"""C-01, the match's contract, delivery 1 (AD-J02, IA-066): what each projection carries, built from what was read.

The generic tests of every contract (``test_intelligence_contract_*.py``) already hold the examples, the projection and the
leak check; these hold what is particular to C-01:

* the case Arsenal W - London City: 59 % ``calibrada`` in the public projection, 78.5 % ``sin_calibrar`` only in the private;
* the one figure per outcome is the same object in ``probabilities`` and in a published selection (G-COH, AD-B09);
* nothing private travels: a selection that is not published, the decision layer's shadow, the brief, the evidence;
* every switch that keeps something from readers today keeps it from this contract too;
* every block not computed yet is absent with its reason and its piece;
* the examples in ``tests/fixtures/contracts/intelligence/C-01`` are exactly what the builder makes of three fictitious
  matches (before kick-off, with the official line-up, over).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fbi.api.contracts.intelligence.base import Missing, Probability
from fbi.api.contracts.intelligence.match import MatchIntelligence, MatchIntelligencePrivate
from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.reading import (
    NarrativeSection,
    NarrativeSentence,
    NarrativeSource,
    ReadingNarrative,
)
from fbi.api.services import match_intelligence as mi
from fbi.api.services import news as news_service
from fbi.api.switches import MATCH_INTELLIGENCE

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence" / "C-01"
KO = datetime(2026, 11, 21, 23, 0, tzinfo=UTC)
AT = datetime(2026, 11, 21, 16, 45, tzinfo=UTC)
HOME, AWAY = 990001, 990002


# ── three fictitious matches ─────────────────────────────────────────────────────────────────────────────────────────

def fixture(status_short: str = "NS", status_group: str = "scheduled") -> dict[str, Any]:
    return {"id": 990100, "kickoff_at": KO, "status_short": status_short, "status_group": status_group,
            "round": "Fase final - Grupo A - 6", "venue_name": "Estadio Ejemplo", "home_team_id": HOME,
            "home_name": "Club Ejemplo Norte", "away_team_id": AWAY, "away_name": "Club Ejemplo Sur",
            "competition_id": 990200, "competition": "Liga Ejemplo", "country": "Ejemplolandia"}


def forecast_row(market: str, line: str, selection: str, p: str, p_model: str, *, calibrated: bool,
                 lo: str | None = None, hi: str | None = None, at: datetime = AT - timedelta(hours=6)) -> dict[str, Any]:
    return {"market_key": market, "line": Decimal(line), "family": "x", "selection": selection,
            "model_name": "elo_ologit" if market == "1X2" else "dixon_coles",
            "calibration": "CALIBRATED" if calibrated else "UNCALIBRATED",
            "basis": "champion" if calibrated else "needs_price", "known_at": at, "data_cutoff_ts": at,
            "p": Decimal(p), "p_lo": None if lo is None else Decimal(lo), "p_hi": None if hi is None else Decimal(hi),
            "p_model": Decimal(p_model)}


FORECAST = [
    # the case Arsenal W - London City (production, 15-nov-2026 10:35 UTC): 0.5878 calibrated, the model's own 0.7847
    forecast_row("1X2", "0", "Home", "0.5878", "0.7847", calibrated=True, lo="0.5200", hi="0.6600"),
    forecast_row("1X2", "0", "Draw", "0.2167", "0.1387", calibrated=True, lo="0.1700", hi="0.2700"),
    forecast_row("1X2", "0", "Away", "0.1955", "0.0767", calibrated=True, lo="0.1500", hi="0.2400"),
    forecast_row("OU", "2.5", "Over", "0.6100", "0.6400", calibrated=True, lo="0.5500", hi="0.6700"),
    forecast_row("OU", "2.5", "Under", "0.3900", "0.3600", calibrated=True, lo="0.3300", hi="0.4500"),
    forecast_row("BTTS", "0", "Yes", "0.5600", "0.5600", calibrated=False),
    forecast_row("BTTS", "0", "No", "0.4400", "0.4400", calibrated=False),
]

CONTENT = {
    "stakes": {
        "home": {"rank": 1, "rule": "stakes-v5", "zone": "title", "gap_up": None, "gap_down": 3, "zone_above": None,
                 "zone_below": "europe", "pressure": "title", "remaining": 1, "settled": False, "max_gain": 3},
        "away": {"rank": 3, "rule": "stakes-v5", "zone": None, "gap_up": 2, "gap_down": 6, "zone_above": "europe",
                 "zone_below": "relegation", "pressure": "europe", "remaining": 1, "settled": False, "max_gain": 3},
    },
    "form": {"home": {"n": 6, "sequence": "WWDWWL", "ppg": 2.33, "gf_pg": 2.1, "ga_pg": 0.8},
             "away": {"n": 6, "sequence": "DWLWDW", "ppg": 1.83, "gf_pg": 1.5, "ga_pg": 1.1}},
}

PACKET = {"id": 7001, "version": "packet-v9", "as_of": AT - timedelta(minutes=20), "missing": ["lineups"]}


def decision(selection: str, line: str, market: str, state: str, p: str, p_model: str, odds: str,
             *, calibrated: bool = True) -> dict[str, Any]:
    return {"market_key": market, "selection": selection, "line": Decimal(line), "known_at": AT - timedelta(minutes=30),
            "state": state, "odds": Decimal(odds), "p_model": Decimal(p_model), "p_cal": Decimal(p),
            "calibrator_id": 11 if calibrated else None, "ev_cal": Decimal("-0.04"), "reasons": ["ev_below_min"]}


DECISIONS = [
    decision("Home", "0", "1X2", "RECHAZADO", "0.5879", "0.7847", "1.62"),
    decision("Home", "-0.5", "AH", "CAUTELA", "0.5478", "0.6086", "1.95", calibrated=False),
]


def set_item(source: str, selection: str = "Home", market: str = "1X2", line: str = "0",
             settled: datetime | None = None) -> dict[str, Any]:
    return {"source": source, "market_key": market, "selection": selection, "line": Decimal(line),
            "selected_at": AT - timedelta(hours=2), "settled_at": settled}


def news_row(i: int, story: str, status: str, claim: str, tier: str, source: str, *, kind: str = "injury",
             published: datetime | None = None) -> news_service.Row:
    return news_service.Row(
        id=i, fixture_id=990100, team_id=HOME, kind=kind, claim=claim, source_name=source,
        source_url=f"https://{source}/nota-{i}", tier=tier, published_at=published,
        retrieved_at=AT - timedelta(hours=3, minutes=i), last_seen_at=AT - timedelta(minutes=10), story_key=story,
        status=status, assertion="out", player="J. Ejemplo", title=None)


NEWS = [
    news_row(1, "s1", "CONFIRMED", "El club confirmó la baja del portero para el partido del sábado.", "club",
             "club-ejemplo-norte.invalid", published=datetime(2026, 11, 21, tzinfo=UTC)),
    news_row(2, "s2", "PROBABLE", "Según la prensa local, el delantero estará en duda para el partido.", "media",
             "diario-ejemplo.invalid", kind="doubtful", published=AT - timedelta(hours=5)),
]

NARRATIVE = ReadingNarrative(
    version="user-narrative-v3", written_at=AT - timedelta(hours=1), data_at=AT - timedelta(hours=1, minutes=10),
    es=[NarrativeSection(key="summary", sentences=[NarrativeSentence(
        text="El líder del grupo recibe al tercero con la final en juego.", refs=["P:stakes.home"])])],
    en=[NarrativeSection(key="summary", sentences=[NarrativeSentence(
        text="The group leader hosts the third side with the final at stake.", refs=["P:stakes.home"])])],
    sources=[NarrativeSource(name="club-ejemplo-norte.invalid")])

BRIEF = {"created_at": AT - timedelta(hours=1), "pass": "day", "version": "brief-v4", "engine": "llm",
         "model": "modelo-ejemplo", "status": "ok", "escalate": False, "reasons": ["lineup_pending"],
         "uncertainty": "medium", "data_quality": "good",
         "summary": "Texto propio del modelo, sin verificar: solo lo ve el dueño."}

LINEUPS = [{"team_side": "home", "formation": "4-3-3", "coach_name": "A. Ejemplo", "fetched_at": KO - timedelta(minutes=22)},
           {"team_side": "away", "formation": "4-2-3-1", "coach_name": "B. Ejemplo", "fetched_at": KO - timedelta(minutes=21)}]


def inputs(case: str) -> mi.Inputs:
    before = mi.Inputs(at=AT, fixture=fixture(), forecast_rows=FORECAST, packet=PACKET, content=CONTENT,
                       narrative=NARRATIVE, decisions=DECISIONS, set_items=[set_item("evaluation")], news_rows=NEWS,
                       brief=BRIEF, narrative_shown=True)
    if case == "antes_del_partido":
        return before
    lineup_at = KO - timedelta(minutes=15)
    if case == "con_alineacion_oficial":
        return replace(before, at=lineup_at, lineups=LINEUPS, packet=PACKET | {"as_of": lineup_at - timedelta(minutes=8)},
                       set_items=[set_item("evaluation"), set_item("qualified")])
    if case == "terminado":
        over = KO + timedelta(hours=3)
        return replace(before, at=over, fixture=fixture("FT", "finished"), lineups=LINEUPS, narrative_shown=False,
                       set_items=[set_item("evaluation", settled=over - timedelta(minutes=30)),
                                  set_item("qualified", settled=over - timedelta(minutes=30))])
    raise ValueError(case)


CASES = ("antes_del_partido", "con_alineacion_oficial", "terminado")


def answers(case: str) -> tuple[MatchIntelligencePrivate, MatchIntelligence]:
    private = mi.assemble(inputs(case))
    return private, to_public(private, MatchIntelligence)


def dumped(model: MatchIntelligence) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


def write_examples() -> None:
    """Rewrites the examples from the cases above (run by hand after a deliberate change; the test below holds them)."""
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        private, public = answers(case)
        for name, model in (("private", private), ("public", public)):
            (EXAMPLES / f"{case}.{name}.json").write_text(
                json.dumps(dumped(model), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── the examples are the builder's ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case", CASES)
def test_each_example_is_what_the_builder_makes_of_its_case(case: str) -> None:
    private, public = answers(case)
    for name, model in (("private", private), ("public", public)):
        stored = json.loads((EXAMPLES / f"{case}.{name}.json").read_text(encoding="utf-8"))
        assert dumped(model) == stored, f"{case}.{name}.json is stale: rewrite it with write_examples()"


@pytest.mark.parametrize("case", CASES)
def test_the_public_projection_of_each_case_leaks_nothing(case: str) -> None:
    _, public = answers(case)
    found = leaks(dumped(public), public_schema=MatchIntelligence.model_json_schema(mode="serialization"),
                  private_schema=MatchIntelligencePrivate.model_json_schema(mode="serialization"))
    assert found == []
    text = json.dumps(dumped(public))
    for private_word in ("raw_probability", "decision_state", "RECHAZADO", "CAUTELA", "brief", "Texto propio",
                         "evidence", "ev_below_min", "story_key", "elo_ologit", "fair_odds", "in_evaluation_set", "decision-v1"):
        assert private_word not in text, private_word


# ── the case Arsenal W - London City ─────────────────────────────────────────────────────────────────────────────────

def home_figure(answer: MatchIntelligence) -> Any:
    return next(f for f in answer.probabilities.items if f.market == "1X2" and f.outcome == "home")


def test_59_calibrated_for_the_reader_and_78_5_uncalibrated_only_for_the_owner() -> None:
    private, public = answers("antes_del_partido")
    pub, priv = home_figure(public), home_figure(private)
    assert (pub.probability.pct, pub.probability.calibration, pub.probability.origin) == (59, "calibrada", "forecast-v1")
    assert not hasattr(pub, "raw_probability")
    assert priv.probability == pub.probability, "the owner sees the same figure the reader does"
    assert (priv.raw_probability.pct, priv.raw_probability.calibration) == (78.5, "sin_calibrar")
    assert priv.basis == "champion" and priv.fair_odds == pytest.approx(1.70)
    btts = next(f for f in public.probabilities.items if f.market == "BTTS" and f.outcome == "yes")
    assert btts.probability.calibration == "sin_calibrar", "the model's own number is said as such"
    assert isinstance(btts.probability.interval_pct, Missing), "no interval given, none invented"


def test_a_figure_is_not_yet_part_of_an_evaluation_nor_priced() -> None:
    _, public = answers("antes_del_partido")
    for f in public.probabilities.items:
        assert f.probability.evaluation == Missing(missing_reason="no_entregado", expected_piece="AD-D06")
        assert f.price == Missing(missing_reason="no_entregado", expected_piece="AD-B06")


# ── selections: published only, with the one figure ──────────────────────────────────────────────────────────────────

def test_nothing_published_means_an_empty_public_list_and_every_selection_in_the_private() -> None:
    private, public = answers("antes_del_partido")
    assert public.selections.items == [] and public.selections.missing_reason == "sin_publicados"
    states = {(s.market, s.selection, s.line): s for s in private.selections.items}
    assert set(states) == {("1X2", "Home", 0.0), ("AH", "Home", -0.5)}
    home = states[("1X2", "Home", 0.0)]
    assert home.decision_state == "RECHAZADO" and home.in_evaluation_set and not home.published
    assert home.public_state is None
    assert home.lifecycle_state == Missing(missing_reason="no_entregado", expected_piece="AD-D02")
    assert isinstance(home.decision_probability, Probability) and home.decision_probability.pct == 59
    assert home.decision_probability.origin == "decision-v1"
    handicap = states[("AH", "Home", -0.5)]
    assert handicap.probability == Missing(missing_reason="no_entregado", expected_piece="AD-B05"), (
        "the one figure covers 1X2, total goals and both teams to score until AD-B05")
    assert isinstance(handicap.decision_probability, Probability)
    assert handicap.decision_probability.calibration == "sin_calibrar", "no calibrator: said"


@pytest.mark.parametrize(("case", "state"), [("con_alineacion_oficial", "publicada"), ("terminado", "liquidada")])
def test_a_published_pick_carries_its_public_state_and_the_outcomes_one_figure(case: str, state: str) -> None:
    _, public = answers(case)
    [selection] = public.selections.items
    assert selection.public_state == state
    assert selection.probability == home_figure(public).probability, "G-COH: one figure per outcome, everywhere"


def test_the_public_state_follows_the_match() -> None:
    item = set_item("qualified")
    assert mi.public_state(None, "previo") is None
    assert mi.public_state(item, "previo") == "publicada"
    assert mi.public_state(item, "en_juego") == "en_juego"
    assert mi.public_state(item, "terminado") == "en_juego", "over but not settled yet"
    assert mi.public_state(set_item("qualified", settled=AT), "terminado") == "liquidada"


# ── the switches that keep something from readers ───────────────────────────────────────────────────────────────────

def test_a_forecast_kept_from_readers_is_kept_from_this_contract() -> None:
    private = mi.assemble(replace(inputs("con_alineacion_oficial"), forecast_shown=False))
    public = to_public(private, MatchIntelligence)
    assert len(private.probabilities.items) == 7
    assert public.probabilities.items == [] and public.probabilities.missing_reason == "sin_publicados"
    [selection] = public.selections.items
    assert selection.probability == Missing(missing_reason="pendiente_derechos")


def test_the_reading_the_chronicle_and_the_news_follow_their_switches() -> None:
    x = replace(inputs("antes_del_partido"), reading_shown=False, narrative_shown=False, news_shown=False, news_rows=())
    private = mi.assemble(x)
    public = to_public(private, MatchIntelligence)
    for block in (public.context, public.form, public.citations):
        assert block.items == [] and block.missing_reason == "pendiente_derechos"
    assert public.reader_chronicle == Missing(missing_reason="pendiente_derechos")
    # the reason does not tell a reader whether something exists in the shadow
    bare = to_public(mi.assemble(replace(x, narrative=None, packet=None, content={}, forecast_rows=(),
                                         forecast_shown=False)), MatchIntelligence)
    assert bare.reader_chronicle == public.reader_chronicle
    assert bare.context.missing_reason == bare.form.missing_reason == "pendiente_derechos"
    assert bare.probabilities.missing_reason == "pendiente_derechos"
    assert isinstance(private.chronicle_preview, type(mi.chronicle_of(NARRATIVE))), "the owner still reads it"


def test_without_a_packet_or_a_forecast_the_blocks_say_why() -> None:
    x = replace(inputs("antes_del_partido"), packet=None, content={}, forecast_rows=(),
                forecast_fixture={"data_class": "PRODUCT_ONLY"})
    public = to_public(mi.assemble(x), MatchIntelligence)
    assert public.probabilities.missing_reason == "sin_cobertura"
    assert public.context.missing_reason == "sin_datos" and public.form.missing_reason == "sin_datos"
    assert mi.assemble(replace(x, forecast_fixture=None)).probabilities.missing_reason == "sin_datos"


# ── what is absent says why ──────────────────────────────────────────────────────────────────────────────────────────

def test_every_block_not_computed_yet_is_absent_with_its_piece() -> None:
    _, public = answers("antes_del_partido")
    for name, piece in mi.NOT_YET.items():
        assert getattr(public, name) == Missing(missing_reason="no_entregado", expected_piece=piece), name
    assert set(mi.NOT_YET) == {"scenarios", "chronicle", "evaluations", "new_since_yesterday", "pending_unknowns", "keys",
                               "risks", "players_to_watch"}


def no_mute_null(value: Any, path: str = "$") -> list[str]:
    allowed = {"$.freshness.stale_reason"}
    if value is None:
        return [] if path in allowed else [path]
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in no_mute_null(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for v in value for p in no_mute_null(v, f"{path}[]")]
    return []


@pytest.mark.parametrize("case", CASES)
def test_the_public_answer_carries_no_mute_null(case: str) -> None:
    _, public = answers(case)
    assert no_mute_null(dumped(public)) == []


# ── the pieces ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_line_up_is_expected_before_kick_off_and_said_missing_after() -> None:
    assert mi.lineup([], fixture()) == Missing(missing_reason="aun_no_disponible", expected_at=KO - timedelta(minutes=20))
    assert mi.lineup(LINEUPS[:1], fixture("FT", "finished")) == Missing(missing_reason="sin_datos")
    official = mi.lineup(LINEUPS, fixture())
    assert not isinstance(official, Missing)
    assert official.home.formation == "4-3-3" and official.known_at == KO - timedelta(minutes=21)


def test_the_stakes_and_the_form_never_trust_a_shape() -> None:
    fx = fixture()
    odd = {"stakes": {"home": {"rank": "x", "rule": "stakes-v5"}, "away": {"rank": 2, "rule": None}},
           "form": {"home": {"n": 5, "sequence": "WWXWL"}, "away": {"n": 0, "sequence": "W"}}}
    assert mi.stakes(odd, fx, AT) == [] and mi.form(odd, fx, AT) == []
    [home, away] = mi.stakes(CONTENT, fx, AT)
    assert (home.zone, home.pressure, home.above) == ("title", "title", Missing(missing_reason="sin_datos"))
    assert away.zone == "none" and away.above.zone == "europe" and away.above.points == 2  # type: ignore[union-attr]
    weird = {"stakes": {"home": {"rank": 4, "rule": "stakes-v5", "zone": "galaxy", "pressure": "cosmic"}}}
    [w] = mi.stakes(weird, fx, AT)
    assert (w.zone, w.pressure) == ("other", "unknown")


def test_the_level_of_a_story_is_todays_status_in_the_closed_list() -> None:
    assert mi.confirmation("CONFIRMED", ["club"], 1) == ("oficial", [])
    assert mi.confirmation("CONFIRMED", ["media", "journalist"], 2) == ("dos_origenes", [])
    assert mi.confirmation("CONFIRMED", ["media"], 1) == ("un_medio", []), "one outlet does not confirm"
    assert mi.confirmation("PROBABLE", ["media"], 1) == ("un_medio", [])
    assert mi.confirmation("RUMOR", ["social"], 1) == ("rumor", [])
    assert mi.confirmation("CONTRADICTORY", ["media"], 2) == (
        Missing(missing_reason="no_entregado", expected_piece="AD-C07"), ["contradiccion"])
    assert mi.confirmation("OUTDATED", ["media"], 1)[1] == ["desactualizada"]


def test_a_citation_carries_its_four_dates_and_its_source() -> None:
    [first, second] = mi.citations(NEWS)
    assert (first.n, first.confirmation, first.source.name) == (1, "oficial", "club-ejemplo-norte.invalid")
    assert first.published_day_only, "the club gave only the day"
    assert first.known_at == AT - timedelta(hours=3, minutes=1)
    assert first.relation == Missing(missing_reason="no_entregado", expected_piece="AD-G08")
    assert first.fact_at == Missing(missing_reason="sin_datos")
    assert second.confirmation == "un_medio" and not second.published_day_only
    not_spanish = news_row(9, "s9", "PROBABLE", "The keeper will miss the match.", "media", "x.invalid")
    assert mi.citations([not_spanish]) == [], "a citation needs PrediGol's own words"


def test_a_match_about_to_be_played_with_an_old_packet_is_stale() -> None:
    soon = KO - timedelta(hours=2)
    assert mi.freshness(fixture(), soon - timedelta(hours=7), soon).stale_reason == "paquete_antiguo"
    assert not mi.freshness(fixture(), soon - timedelta(hours=1), soon).stale
    assert not mi.freshness(fixture(), KO - timedelta(days=3), KO - timedelta(days=2)).stale, "far from kick-off"
    assert not mi.freshness(fixture("FT", "finished"), AT - timedelta(days=1), KO + timedelta(hours=2)).stale
    assert mi.phase_of("abandoned") == "otro"


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────────────────────

def reader_app(monkeypatch: pytest.MonkeyPatch, *, role: str = "USER") -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import ROLE_PERMISSIONS, Role
    from fbi.auth.service import Principal

    principal = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role[role],
                          language="es", timezone="America/Bogota", session_id="s", session_expires_at=KO,
                          permissions=frozenset(ROLE_PERMISSIONS[Role[role]]))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setattr(mi, "read", lambda conn, fixture_id, at=None: inputs("con_alineacion_oficial"))
    return TestClient(app, raise_server_exceptions=False, headers={"sec-fetch-site": "same-origin"})


def test_the_public_route_does_not_exist_while_the_owners_switch_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    client = reader_app(monkeypatch)
    for value in (None, "0", "off", "si"):
        if value is None:
            monkeypatch.delenv(MATCH_INTELLIGENCE, raising=False)
        else:
            monkeypatch.setenv(MATCH_INTELLIGENCE, value)
        answer = client.get("/api/v1/matches/990100/intelligence")
        assert answer.status_code == 404 and answer.json()["error"]["code"] == "not_found", value


def test_with_the_switch_on_a_reader_gets_the_public_projection_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MATCH_INTELLIGENCE, "1")
    client = reader_app(monkeypatch)
    answer = client.get("/api/v1/matches/990100/intelligence")
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data == json.loads((EXAMPLES / "con_alineacion_oficial.public.json").read_text(encoding="utf-8"))
    assert client.get("/api/v1/admin/intelligence/matches/990100/intelligence").status_code == 403


def test_the_owner_gets_the_private_projection_without_any_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(MATCH_INTELLIGENCE, raising=False)
    client = reader_app(monkeypatch, role="SUPER_ADMIN")
    answer = client.get("/api/v1/admin/intelligence/matches/990100/intelligence")
    assert answer.status_code == 200, answer.text
    data = answer.json()["data"]
    assert data["projection"] == "private"
    assert data == json.loads((EXAMPLES / "con_alineacion_oficial.private.json").read_text(encoding="utf-8"))
