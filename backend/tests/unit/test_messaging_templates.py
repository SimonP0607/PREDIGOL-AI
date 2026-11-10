"""The e-mails' templates (plan UX, A5): the same placeholders in Spanish and English, only the template's own short
parameters in the queue (never a secret, a token, the reader's name or address), every value escaped, and a page a
phone's mail app reads well - one column, a 44 px button, no image, no tracking pixel, no external resource."""

from __future__ import annotations

import importlib.util
import re
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from fbi.messaging import templates
from fbi.messaging.templates import (
    ACCOUNT_FIELDS,
    CATEGORIES,
    MANDATORY,
    OPTIONAL,
    OUTBOX_CATEGORIES,
    TEMPLATES,
    TemplateError,
    check_params,
    long_date,
    placeholders,
    render,
)

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0123_service_email_category.py"


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0123", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample(name: str) -> dict[str, str]:
    return dict(TEMPLATES[name].sample)


def test_every_template_says_the_same_in_both_languages() -> None:
    for t in TEMPLATES.values():
        assert placeholders(t, "es") == placeholders(t, "en"), t.name
        assert bool(t.es.button) == bool(t.en.button), t.name
        assert len(t.es.paragraphs) == len(t.en.paragraphs), t.name
        assert t.category in OUTBOX_CATEGORIES
        assert t.sample or not t.params, f"{t.name} needs parameters that render (tests and the console's preview use them)"


def test_the_categories_are_the_databases() -> None:
    m = migration()
    assert set(OUTBOX_CATEGORIES) == set(m.CATEGORIES)  # what the queue holds: the readers' and commercial mail
    assert set(CATEGORIES) == set(m.CATEGORIES) - {"marketing"}
    assert set(OPTIONAL) == set(m.OPTIONAL)
    assert MANDATORY | set(OPTIONAL) == set(CATEGORIES) and not MANDATORY & set(OPTIONAL)
    assert {"account", "security", "privacy", "legal"} == MANDATORY
    assert {"membership", "support", "service"} == set(OPTIONAL)


@pytest.mark.parametrize("name", sorted(TEMPLATES))
@pytest.mark.parametrize("locale", ["es", "en"])
def test_every_template_renders_with_its_sample(name: str, locale: str) -> None:
    # an e-mail with a one-use link (plan UX, A7) is rendered with the moment its link expires
    until = datetime(2026, 11, 1, 18, 5, tzinfo=UTC) if TEMPLATES[name].grant else None
    out = render(name, locale, sample(name), {"name": "Ana"}, until=until)  # type: ignore[arg-type]
    assert "{" not in out.subject + out.text, "a placeholder was left unfilled"
    assert "Ana" in out.text
    assert out.html.startswith("<!doctype html>") and f'lang="{locale}"' in out.html
    # the account's footer, or - commercial e-mail, plan UX B8 - why the reader gets it and the one-click way out
    footer = (templates.COMMERCIAL_FOOTER[locale][0] if TEMPLATES[name].category in templates.COMMERCIAL  # type: ignore[index]
              else templates.FOOTER[locale])  # type: ignore[index]
    assert out.text.endswith("\n") and footer in out.text


PAYMENT_NOTICE_MAILS = ("payment_request_received", "payment_request_rejected", "payment_request_annulled")


@pytest.mark.parametrize("name", PAYMENT_NOTICE_MAILS)
@pytest.mark.parametrize("locale", ["es", "en"])
def test_every_mail_about_a_payment_notice_says_the_house_never_asks_for_nequi_keys(name: str, locale: str) -> None:
    """Plan del flujo, «Antifraude» (UX-098): the e-mails say that PrediGol never asks for the Nequi password, a code or the
    bank account - a message that does is not ours - and they carry no amount, no reference and no address."""
    out = render(name, locale, sample(name), {"name": "Ana"})  # type: ignore[arg-type]
    line = templates.NEVER_ASKS[locale]  # type: ignore[index]
    assert line in out.text and line in out.html
    assert "Nequi" in line and ("clave" in line or "password" in line) and ("código" in line or "code" in line)
    raw = out.subject + "\n" + out.text
    for word in ("COP", "USD", "$", "@"):
        assert word not in raw, f"{name}/{locale} carries {word!r}"
    assert len(TEMPLATES[name].es.paragraphs) == len(TEMPLATES[name].en.paragraphs)


def test_the_page_is_one_column_with_a_44px_button_and_nothing_external() -> None:
    out = render("privacy_request_received", "es", sample("privacy_request_received"), {"name": "Ana"})
    assert "max-width:560px" in out.html and "min-height:44px" in out.html and "font-size:16px" in out.html
    assert not re.search(r"<img|<script|<link|<iframe|url\(|@import", out.html, re.IGNORECASE)
    links = re.findall(r'href="([^"]+)"', out.html)
    assert links == [out.link], "one link: the button; no tracking pixel, no other address"
    assert out.link is not None and out.link.endswith("/profile#privacy")


def test_the_words_of_the_parameters_are_the_readers_language() -> None:
    es = render("privacy_request_received", "es", sample("privacy_request_received"), {"name": "Ana"})
    en = render("privacy_request_received", "en", sample("privacy_request_received"), {"name": "Ann"})
    assert "consulta sobre tus datos (n.º 12)" in es.text and "9 de noviembre de 2026" in es.text
    assert "query about your data (no. 12)" in en.text and "9 November 2026" in en.text
    assert long_date("2026-01-01", "es") == "1 de enero de 2026" and long_date("2026-12-31", "en") == "31 December 2026"


def test_every_value_is_escaped_in_the_html_and_plain_in_the_text() -> None:
    name = '<script>alert("x")</script> & Co'
    out = render("privacy_request_answered", "es", sample("privacy_request_answered"), {"name": name})
    assert name in out.text
    assert "<script>" not in out.html and "&lt;script&gt;" in out.html and "&amp; Co" in out.html


def test_the_button_leads_to_the_web_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_WEB_BASE_URL", "https://predigol.example/")
    out = render("legal_change", "en", sample("legal_change"), {"name": "Ann"})
    assert out.link == "https://predigol.example/legal/terms"


@pytest.mark.parametrize(("params", "why"), [
    ({"request": "privacy_query", "ticket": "12"}, "expected"),                                        # missing
    ({"request": "privacy_query", "ticket": "12", "deadline": "2026-11-09", "x": "y"}, "expected"),    # extra
    ({"request": "privacy_query", "ticket": "12", "deadline": "2026-11-09", "token": "a"}, "never keeps"),
    ({"request": "privacy_query", "ticket": "12", "deadline": "2026-11-09", "password": "a"}, "never keeps"),
    ({"request": "privacy_query", "ticket": "12", "deadline": "2026-11-09", "email": "a@b.c"}, "never keeps"),
    ({"request": "privacy_query", "ticket": "12", "deadline": "2026-11-09", "name": "Ana"}, "never keeps"),
    ({"request": "privacy_query", "ticket": "12", "deadline": 20261109}, "string"),
    ({"request": "privacy_query", "ticket": "12", "deadline": "x" * 201}, "string"),
    ({"request": "privacy_cookie", "ticket": "12", "deadline": "2026-11-09"}, "unknown request"),
    ({"request": "privacy_query", "ticket": "12a", "deadline": "2026-11-09"}, "a ticket is a number"),
    ({"request": "privacy_query", "ticket": "12", "deadline": "next week"}, "not a date"),
])
def test_the_queue_keeps_only_the_templates_own_short_parameters(params: dict[str, object], why: str) -> None:
    with pytest.raises(TemplateError, match=why):
        check_params("privacy_request_received", params)


def test_unknown_templates_languages_and_account_fields_are_refused() -> None:
    with pytest.raises(TemplateError, match="no template"):
        check_params("password_reset_with_the_link_inside", {})
    with pytest.raises(TemplateError, match="no language"):
        render("privacy_request_answered", "fr", sample("privacy_request_answered"), {"name": "A"})  # type: ignore[arg-type]
    with pytest.raises(TemplateError, match="account fields"):
        render("privacy_request_answered", "es", sample("privacy_request_answered"), {"name": "A", "email": "a@b.c"})
    with pytest.raises(TemplateError, match="unknown legal text"):
        check_params("legal_change", {"document": "cookies", "version": "2026-10-25-draft1"})
    with pytest.raises(TemplateError, match="has no version"):
        check_params("legal_change", {"document": "terms", "version": "2020-01-01"})
    assert {"name"} == ACCOUNT_FIELDS


def test_a_secret_never_hides_in_a_templates_parameters() -> None:
    for t in TEMPLATES.values():
        for param in t.params:
            assert not templates.FORBIDDEN_PARAMS.search(param), (t.name, param)
            assert param not in ACCOUNT_FIELDS, (t.name, param)
