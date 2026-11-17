"""The private queue of moderation over HTTP (IA-102): SUPER_ADMIN only; a withdrawal from the console is a new version and a line of the
register; the outlet's title never comes back; an act the state does not allow is a 409."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.news import store
from tests.integration.signed_in import SAME_SITE, signed_in
from tests.unit import news_world

pytestmark = pytest.mark.integration
TITLE = "TITULAR-DEL-MEDIO-QUE-NUNCA-SALE"
AT = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)


def committed_story(dsn: str) -> str:
    key = store.story_key_for(uuid.uuid4().hex)
    with psycopg.connect(dsn) as c:
        w = store.write_item(c, store.Article(url=f"https://radio.ejemplo.invalid/n/{uuid.uuid4().hex}", source_name="Radio",
                                              fingerprint_text=TITLE + key, seen_at=AT, found_via="rss", written_by="signals-v1",
                                              source_title=TITLE), news_world.policy())
        store.write_story(c, store.Story(story_key=key, at=AT, first_seen_at=AT, written_by="news-pipeline-v1", category="colombia",
                                         level="un_medio", lang="es", country="Colombia", claim_type="contexto"))
        assert w.id is not None
        store.link_item_story(c, w.id, key, at=AT, method="url", grouper_version="stories-v1")
        c.commit()
    return key


def client(role: str = "SUPER_ADMIN") -> TestClient:
    return TestClient(signed_in(create_app(), role), headers=SAME_SITE)


def test_only_the_owner_reaches_the_queue(migrated_database: str) -> None:
    assert client("USER").get("/api/v1/admin/news/moderation").status_code == 403
    assert client().get("/api/v1/admin/news/moderation").status_code == 200


def test_a_withdrawal_from_the_console_hides_records_and_comes_back(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import source_policy

    key = committed_story(migrated_database)
    monkeypatch.setattr(source_policy, "load", lambda conn: news_world.policy())
    api = client()
    seen = api.get(f"/api/v1/admin/news/stories/{key}")
    assert seen.status_code == 200 and TITLE not in seen.text
    body: dict[str, Any] = seen.json()
    assert [i["publish_level"] for i in body["items"]] == ["link"] and body["story"]["status"] == "activa", "a pending source: link only"
    r = api.post(f"/api/v1/admin/news/stories/{key}/withdraw", json={"reason": "Lo pide el titular de los derechos",
                                                                    "requested_by": "titular_derechos", "reference": "caso 41"})
    assert r.status_code == 200 and r.json()["status"] == "retirada"
    assert api.post(f"/api/v1/admin/news/stories/{key}/withdraw", json={"reason": "otra vez"}).status_code == 409
    withdrawn = api.get("/api/v1/admin/news/moderation", params={"status": "retirada"}).json()["stories"]
    mine = next(s for s in withdrawn if s["story_key"] == key)
    assert mine["log"][0]["action"] == "withdraw" and mine["log"][0]["requested_by"] == "titular_derechos"
    assert api.post(f"/api/v1/admin/news/stories/{key}/restore", json={"reason": "Acuerdo con el medio"}).json()["status"] == "activa"
    assert api.post("/api/v1/admin/news/stories/st-no-existe-nunca/approve", json={"reason": "nada"}).status_code == 404
    assert api.post(f"/api/v1/admin/news/stories/{key}/withdraw", json={"reason": "x"}).status_code == 422, "a reason is required"
    with psycopg.connect(migrated_database) as c:
        rows = c.execute("SELECT status FROM news.stories WHERE story_key = %s ORDER BY version", (key,)).fetchall()
        assert [r[0] for r in rows] == ["activa", "retirada", "activa"]
