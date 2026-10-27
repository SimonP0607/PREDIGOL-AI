"""The legal texts a reader accepts, each version fixed by its sha256 (plan UX, A4; plan de seguridad, section 23).

Three documents - the terms of service, the personal-data processing policy (with its cookies section) and the
responsible-gaming page (with the risk notice) - live in this package as structured JSON, in Spanish and English
(``texts/<locale>/<document>.json``), so the page, the consent and the proof come from one source and no markdown
renderer stands between what was written and what was read. The data controller's details (``texts/controller.json``,
the owner's P4) fill the ``{{controller.*}}`` placeholders.

``texts/versions.json`` is the register: every version of each document with its date, whether it is a draft (until
the lawyer's written OK, P5), whether its change was material (a material change asks every reader to accept again)
and the sha256 of its canonical form in each language. A test recomputes the hashes: a text cannot change without a
new version, and a consent stores the hash of exactly what the reader was shown.

The four purposes a reader must accept are separate, unticked boxes: the terms, the processing of the data, the +18
declaration (the terms' statements) and the reading of the risk notice (the responsible-gaming page's). The optional
ones add a purpose here and a statement to their document: the commercial e-mail (B8, ``marketing_email``, on the
processing policy).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

import structlog

log = structlog.get_logger(__name__)

TEXTS = Path(__file__).resolve().parent / "texts"

DocumentName = Literal["terms", "privacy", "responsible_gaming"]
Locale = Literal["es", "en"]
DOCUMENTS: tuple[DocumentName, ...] = ("terms", "privacy", "responsible_gaming")
LOCALES: tuple[Locale, ...] = ("es", "en")
VERSION_FORMAT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[a-z0-9.-]{0,24}$")
"""As the database checks it (customer.consents.version): the date first, so versions sort by when they were made."""
PLACEHOLDER = re.compile(r"\{\{controller\.([a-z_]+)\}\}")


@dataclass(frozen=True, slots=True)
class Purpose:
    kind: str
    document: DocumentName
    required: bool
    withdrawable: bool
    """True when the reader can withdraw it from the profile: the processing authorisation (Ley 1581, art. 8.e; using
    PrediGol needs it, so the gate asks for it again) and every optional purpose. Accepting the terms, the +18
    declaration and the reading of the risk notice are statements of fact: they end with the account (a deletion
    request), not with a withdrawal."""


PURPOSES: tuple[Purpose, ...] = (
    Purpose("terms", "terms", required=True, withdrawable=False),
    Purpose("privacy", "privacy", required=True, withdrawable=True),
    Purpose("age_18", "terms", required=True, withdrawable=False),
    Purpose("risk_notice", "responsible_gaming", required=True, withdrawable=False),
    # Optional, never ticked beforehand: the weekly summary by e-mail (plan UX, B8). Offered only while the summary can
    # really reach the reader (fbi.messaging.digest.offered); withdrawn at any moment, from the profile or in one click
    # from any summary - and the gate never asks for it.
    Purpose("marketing_email", "privacy", required=False, withdrawable=True),
)
REQUIRED: tuple[str, ...] = tuple(p.kind for p in PURPOSES if p.required)
BY_KIND: dict[str, Purpose] = {p.kind: p for p in PURPOSES}


@dataclass(frozen=True, slots=True)
class Version:
    version: str
    date: str
    draft: bool
    material: bool
    changes: dict[str, str]
    sha256: dict[str, str]


@dataclass(frozen=True, slots=True)
class Document:
    document: DocumentName
    locale: Locale
    version: str
    date: str
    draft: bool
    title: str
    summary: str
    sections: list[dict[str, Any]]
    statements: dict[str, str]
    sha256: str
    """Of the canonical form of exactly this text in this language (``canonical``)."""


class LegalTextError(ValueError):
    """The register or a text is not what the code expects: a deploy-time bug, never a reader's input."""


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@cache
def controller() -> dict[str, str]:
    data = _read(TEXTS / "controller.json")
    return {k: str(v) for k, v in data.items() if not k.startswith("_")}


@cache
def register() -> dict[DocumentName, tuple[Version, ...]]:
    raw = _read(TEXTS / "versions.json")
    out: dict[DocumentName, tuple[Version, ...]] = {}
    for name in DOCUMENTS:
        entries = raw.get(name, {}).get("versions") or []
        if not entries:
            raise LegalTextError(f"versions.json: {name} has no version")
        versions = tuple(
            Version(version=e["version"], date=e["date"], draft=bool(e["draft"]), material=bool(e["material"]),
                    changes=dict(e["changes"]), sha256=dict(e["sha256"]))
            for e in entries)
        for v in versions:
            if not VERSION_FORMAT.match(v.version) or not v.version.startswith(v.date):
                raise LegalTextError(f"versions.json: {name} {v.version!r} is not a dated version")
            if set(v.changes) != set(LOCALES) or set(v.sha256) != set(LOCALES):
                raise LegalTextError(f"versions.json: {name} {v.version} needs both languages")
        if [v.version for v in versions] != sorted(v.version for v in versions) or len(
                {v.version for v in versions}) != len(versions):
            raise LegalTextError(f"versions.json: {name}'s versions must be unique and in order")
        if not versions[0].material:
            raise LegalTextError(f"versions.json: {name}'s first version is material by definition")
        out[name] = versions
    return out


def current(document: DocumentName) -> Version:
    return register()[document][-1]


def valid_versions(document: DocumentName) -> frozenset[str]:
    """The versions whose acceptance still holds: the latest material one and every one after it. A non-material
    change (a typo, a clearer sentence) does not ask anyone to accept again."""
    versions = register()[document]
    last_material = max(i for i, v in enumerate(versions) if v.material)
    return frozenset(v.version for v in versions[last_material:])


def any_draft() -> bool:
    """True while a document a reader must accept is still a draft: the gate stays off (plan UX, A4: P5 first)."""
    return any(current(BY_KIND[kind].document).draft for kind in REQUIRED)


def _fill(value: Any) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            field = m.group(1)
            if field not in controller():
                raise LegalTextError(f"unknown placeholder {{{{controller.{field}}}}}")
            return controller()[field]
        return PLACEHOLDER.sub(sub, value)
    if isinstance(value, list):
        return [_fill(v) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v) for k, v in value.items()}
    return value


def canonical(payload: Mapping[str, Any]) -> bytes:
    """One byte string per text: sorted keys, no spaces, UTF-8 as written (the sha256 is over this)."""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _payload(document: DocumentName, locale: Locale, version: str, text: Mapping[str, Any]) -> dict[str, Any]:
    return {"document": document, "locale": locale, "version": version, "title": text["title"],
            "summary": text["summary"], "sections": text["sections"], "statements": text["statements"]}


@cache
def load(document: DocumentName, locale: Locale) -> Document:
    """The current version of a document in a language, filled in, with the sha256 of what it says."""
    if document not in DOCUMENTS or locale not in LOCALES:
        raise LegalTextError(f"no such text: {document}/{locale}")
    version = current(document)
    text = _fill(_read(TEXTS / locale / f"{document}.json"))
    payload = _payload(document, locale, version.version, text)
    digest = hashlib.sha256(canonical(payload)).hexdigest()
    if digest != version.sha256[locale]:
        # The test suite refuses this; should it ever reach a server, the reader is still shown the text and a
        # consent still stores the hash of what was shown - the register is what is wrong.
        log.error("legal.text_changed_without_a_version", document=document, locale=locale,
                  version=version.version)
    return Document(document=document, locale=locale, version=version.version, date=version.date,
                    draft=version.draft, title=text["title"], summary=text["summary"], sections=text["sections"],
                    statements=dict(text["statements"]), sha256=digest)


def statement(kind: str, locale: Locale) -> tuple[Document, str]:
    """The document a purpose is accepted on and the exact sentence of its box."""
    purpose = BY_KIND.get(kind)
    if purpose is None:
        raise LegalTextError(f"unknown purpose {kind!r}")
    doc = load(purpose.document, locale)
    text = doc.statements.get(kind)
    if not text:
        raise LegalTextError(f"{purpose.document}/{locale} has no statement for {kind}")
    return doc, text


def due(latest: Mapping[str, tuple[bool, str]]) -> list[str]:
    """The purposes a reader must (re)accept, in the order of the boxes: never answered, withdrawn, or answered on a
    version a material change has replaced. ``latest`` maps a purpose to its latest decision (granted, version)."""
    out: list[str] = []
    for kind in REQUIRED:
        decision = latest.get(kind)
        if decision is None or not decision[0] or decision[1] not in valid_versions(BY_KIND[kind].document):
            out.append(kind)
    return out
