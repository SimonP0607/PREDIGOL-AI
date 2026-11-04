"""The rules of what readers tell PrediGol (plan UX, B6 and section 40) that need no database: the comment keeps no address
and no long number, the context keeps only where it was asked, an entry of Novedades has an id of its own, and the
switch is on until the owner says otherwise."""

from __future__ import annotations

import pytest

from fbi.customer import feedback


@pytest.mark.parametrize(("raw", "kept"), [
    ("Me faltó la Liga BetPlay", "Me faltó la Liga BetPlay"),
    ("  muy   útil\n\nlas lecturas  ", "muy útil las lecturas"),
    ("escríbanme a lector.uno@example.com por favor", f"escríbanme a {feedback.REMOVED} por favor"),
    ("mi celular es +57 300 123 4567", f"mi celular es {feedback.REMOVED}"),
    ("cédula 1.020.304.050 y listo", f"cédula {feedback.REMOVED} y listo"),
    ("miren https://example.com/x?y=1 o www.example.org", f"miren {feedback.REMOVED} o {feedback.REMOVED}"),
    ("el 2-1 del sábado y 3 goles en 15 minutos", "el 2-1 del sábado y 3 goles en 15 minutos"),
    ("cuota 2.30 y 1,85", "cuota 2.30 y 1,85"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_a_comment_keeps_no_address_and_no_long_number(raw: str | None, kept: str | None) -> None:
    assert feedback.scrub(raw) == kept


def test_a_comment_is_cut_at_its_limit() -> None:
    out = feedback.scrub("a" * 1500)
    assert out is not None and len(out) == feedback.COMMENT_MAX


@pytest.mark.parametrize(("raw", "kept"), [
    ({"trigger": "analysis_opened", "route": "/matches/123"}, {"trigger": "analysis_opened", "route": "/matches/123"}),
    ({"trigger": "result_seen", "route": "/my-picks?tab=1#x"}, {"trigger": "result_seen", "route": "/my-picks"}),
    ({"trigger": "login", "route": "https://evil.example/x"}, {}),
    ({"route": "/matches/1/" + "x" * 200}, {"route": ("/matches/1/" + "x" * 200)[:feedback.ROUTE_MAX]}),
    ({"route": "/matches/<script>"}, {}),
    ({"email": "a@b.co", "score": 5, "trigger": None}, {}),
    (None, {}),
])
def test_the_context_keeps_only_where_it_was_asked(raw: dict[str, object] | None, kept: dict[str, str]) -> None:
    assert feedback.clean_context(raw) == kept


@pytest.mark.parametrize(("update_id", "valid"), [
    ("2026-10-27-mis-picks", True),
    ("2026-11-02-feedback-y-novedades", True),
    ("2026-10-27", False),
    ("mis-picks", False),
    ("2026-10-27-Mis Picks", False),
    ("2026-10-27-" + "a" * 41, False),
    ("updates:2026-10-27-mis-picks", False),
])
def test_an_entry_of_novedades_has_an_id_of_its_own(update_id: str, valid: bool) -> None:
    assert bool(feedback.UPDATE_ID.fullmatch(update_id)) is valid


@pytest.mark.parametrize(("value", "on"), [(None, True), ("", True), ("1", True), ("on", True), ("0", False),
                                           ("off", False), ("maybe", False)])
def test_the_switch_is_on_until_the_owner_says_otherwise(monkeypatch: pytest.MonkeyPatch, value: str | None,
                                                         on: bool) -> None:
    if value is None:
        monkeypatch.delenv(feedback.SWITCH, raising=False)
    else:
        monkeypatch.setenv(feedback.SWITCH, value)
    assert feedback.enabled() is on


def test_the_survey_comes_at_most_once_every_30_days_and_a_low_score_is_the_risk_signal() -> None:
    assert feedback.SURVEY_EVERY.days == 30
    assert feedback.FIRST_AFTER.days == 7, "never in the account's first week"
    assert feedback.AT_RISK_SCORE == 2 and feedback.AT_RISK_WINDOW.days == 30
    assert feedback.RETENTION.days == 730
    assert feedback.SUBJECTS == ("reading", "narrative", "explanation", "explain")
    assert feedback.TRIGGERS == ("analysis_opened", "result_seen")
