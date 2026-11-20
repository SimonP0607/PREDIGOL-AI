"""The owner's signature of a preregistered protocol (IA-143, plan piece AD-K07 «cada promoción con firma»): ``protocol-signatures-v1``.

A protocol is fixed BEFORE its data is looked at, and its fingerprint (the SHA-256 of its canonical JSON) says which text it is. Until now
nothing recorded that the owner approved one: the readers wrote ``signed_by_owner: False`` by hand. This package is the catalog of the
protocols that can be signed and the rules of a signature; ``fbi.protosign.store`` reads and appends the rows of ``ai.protocol_signatures``
(revision 0166, append-only).

    the catalog      every LAB protocol of ``fbi.research.protocol`` (its fingerprint, pinned by ``tests/unit/test_research_protocols.py``)
                     and the own records of ``fbi.protosign.records`` (the chronicle's AD-F04, AD-F05, AD-F06 and the retirement of
                     ``review-v2``, AD-D11), each with the fingerprint of its canonical record
    a signature      ONE protocol in ONE fingerprint: key, version, the fingerprint signed, the owner's reason, ``decided_by = 'owner'``,
                     the hour, the code version
    in force         a signature counts only for the fingerprint the code has NOW: a protocol that changed (a new fingerprint) needs a new
                     signature, and the old row stays as it was (nothing is deleted)

A SIGNATURE TURNS NOTHING ON. No verdict switches on, promotes or changes a threshold because a protocol is signed (AD-K07): it only records
that the protocol is the one the owner approved before the data was looked at. Pure: no database, no clock; it imports nothing of the
import cycle (the console, C-03 and C-08 read it through ``fbi.protosign.store``)."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from fbi.protosign import records
from fbi.research import protocol as lab

VERSION: Final = "protocol-signatures-v1"
LAB: Final = lab.VERSION
"""``lab-protocol-v1``: a protocol of ``fbi.research.protocol``."""
OWN: Final = records.FRAMEWORK
"""``own-record-v1``: a protocol that is the record of its own module (the chronicle's, and the retirement of ``review-v2``)."""
FRAMEWORKS: Final = (LAB, OWN)
DECIDED_BY: Final = "owner"
REASON_MIN: Final = 10
REASON_MAX: Final = 600
SHA256: Final = re.compile(r"^[0-9a-f]{64}$")
KEY: Final = re.compile(r"^(INT|AD)-[A-Z][0-9]{2}$")
NOTICE: Final = ("Una firma no activa nada: deja constancia de que el protocolo es el que el dueño aprobó antes de mirar los datos. "
                 "Ningún veredicto enciende, promociona ni cambia un umbral por estar firmado (AD-K07).")


@dataclass(frozen=True, slots=True)
class Signable:
    """A protocol as the code has it NOW: what a signature is checked against."""

    key: str
    version: str
    fingerprint: str
    framework: str
    title: str
    registered_on: str
    where: str
    body: Mapping[str, Any]
    """What the owner reads before signing: the whole protocol (a LAB one) or its whole record (an own one)."""

    def head(self) -> dict[str, Any]:
        return {"key": self.key, "version": self.version, "fingerprint": self.fingerprint, "framework": self.framework,
                "title": self.title, "registered_on": self.registered_on, "where": self.where}


def _lab(p: lab.Protocol) -> Signable:
    return Signable(p.key, p.version, lab.fingerprint(p), LAB, p.title, p.registered_on, "fbi/research/protocol.py", dataclasses.asdict(p))


def _own(r: Mapping[str, Any]) -> Signable:
    return Signable(str(r["key"]), str(r["version"]), records.fingerprint(r), OWN, str(r["title"]), str(r["registered_on"]), str(r["where"]),
                    dict(r))


def catalog() -> dict[str, Signable]:
    """Every protocol that can be signed, by key: the LAB ones in their order of registration, then the own records."""
    out = {k: _lab(p) for k, p in lab.PROTOCOLS.items()}
    for r in records.RECORDS:
        if str(r["key"]) in out:
            raise ValueError(f"{r['key']} is registered twice")
        out[str(r["key"])] = _own(r)
    return out


def current(key: str) -> Signable:
    found = catalog().get(key)
    if found is None:
        raise LookupError(f"no hay protocolo registrado con la clave {key}")
    return found


def in_force(signable: Signable, row: Mapping[str, Any]) -> bool:
    """A stored signature counts only for the protocol as it is now: the same key, version and fingerprint, signed by the owner."""
    return (row.get("protocol_key") == signable.key and row.get("protocol_version") == signable.version
            and row.get("fingerprint") == signable.fingerprint and row.get("decided_by") == DECIDED_BY)


def sign_problems(key: str, fingerprint: str, reason: str) -> list[str]:
    """Why a signature would be refused (empty: it would be written). The fingerprint must be the one the code has now - a signature of
    another text is not a signature of this one."""
    out: list[str] = []
    found = catalog().get(key)
    if found is None:
        out.append(f"no hay protocolo registrado con la clave {key!r} (python -m scripts.ia_protocols list)")
    if not SHA256.match(fingerprint or ""):
        out.append("la huella es un sha256 en minúsculas (64 caracteres hexadecimales), la que da `show`")
    elif found is not None and fingerprint != found.fingerprint:
        out.append(f"la huella {fingerprint[:12]}… no es la vigente de {key} ({found.fingerprint[:12]}…): el protocolo cambió o la huella "
                   "se copió mal; mírelo de nuevo con `show` (una firma sobre otra huella no vale)")
    text = (reason or "").strip()
    if not REASON_MIN <= len(text) <= REASON_MAX:
        out.append(f"el motivo es del dueño, con sus palabras: de {REASON_MIN} a {REASON_MAX} caracteres")
    return out


__all__ = ["DECIDED_BY", "FRAMEWORKS", "KEY", "LAB", "NOTICE", "OWN", "REASON_MAX", "REASON_MIN", "SHA256", "VERSION", "Signable", "catalog",
           "current", "in_force", "sign_problems"]
