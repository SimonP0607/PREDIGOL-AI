"""The e-mail of a material change of a legal text (plan UX, section 41: «A4 en la app; por correo desde A5»).

When the current version of a document is published (not a draft), material, and replaces an earlier published
version, every active reader who accepted that document before and has not accepted the new version yet receives
one ``legal_change`` message - once per reader and version (the deduplication key). Only while the consent gate is
on (FBI_CONSENT_GATE): the e-mail promises that the next sign-in asks for the new text, and only the gate does.

The first published version is not a change: the gate asks for it at the next sign-in, and no e-mail goes out. The
owner (SUPER_ADMIN) and the synthetic journey's account are not readers (fbi.customer.consents.exempt).
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
import structlog
from psycopg.types.json import Json

from fbi.customer import consents, legal
from fbi.messaging.templates import check_params

log = structlog.get_logger(__name__)


def changes_to_announce() -> list[tuple[legal.DocumentName, legal.Version]]:
    out: list[tuple[legal.DocumentName, legal.Version]] = []
    for document in legal.DOCUMENTS:
        versions = legal.register()[document]
        current = versions[-1]
        if current.draft or not current.material:
            continue
        if not any(not v.draft for v in versions[:-1]):
            continue
        out.append((document, current))
    return out


def enqueue_legal_changes(conn: psycopg.Connection[Any]) -> int:
    """Queue the messages a published material change owes. Idempotent; in the caller's transaction."""
    if not consents.gate_enabled():
        return 0
    synthetic = os.environ.get("FBI_SYNTHETIC_EMAIL", "").strip().lower()
    queued = 0
    for document, version in changes_to_announce():
        params = {"document": document, "version": version.version}
        template = check_params("legal_change", params)
        cur = conn.execute("""
            INSERT INTO customer.messages_outbox (user_id, category, template, locale, params, dedup_key)
            SELECT u.id, %s, %s, u.language, %s, 'legal_change:' || %s || ':' || %s || ':' || u.id
              FROM auth.users u
             WHERE u.status = 'active' AND u.role <> 'SUPER_ADMIN' AND u.email <> %s
               AND EXISTS (SELECT 1 FROM customer.consents c
                            WHERE c.user_id = u.id AND c.document = %s AND c.granted)
               AND NOT EXISTS (SELECT 1 FROM customer.consents c
                                WHERE c.user_id = u.id AND c.document = %s AND c.granted AND c.version = ANY(%s))
            ON CONFLICT (dedup_key) DO NOTHING
        """, (template.category, template.name, Json(params), document, version.version, synthetic, document,
              document, sorted(legal.valid_versions(document))))
        if cur.rowcount > 0:
            queued += cur.rowcount
            log.info("legal_change.queued", document=document, version=version.version, messages=cur.rowcount)
    return queued
