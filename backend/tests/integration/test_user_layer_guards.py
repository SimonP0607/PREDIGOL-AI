"""Two guards of the separation between the user layer and PrediGol Intelligence (plan UX, A0 and section 4), over the real
application and a migrated database.

1. A user's visit never calls the outside world. "Analizar una vez y leer muchas": what a client reads was computed and stored
   before; no page view may reach a language model, Exa or the football provider. Every GET route a signed-in USER can open
   (the public and app tiers of ``create_app()``, read from its own OpenAPI document so a new route is covered the day it is
   added) is called with every real network door shut: httpx's two transports (the only HTTP client in ``src/fbi``: the AI
   providers, the search, the provider client), ``urllib.request.urlopen`` and any Python socket that dials an internet
   address. One attempt fails the test with the route that made it. (The database is reached through libpq, not a Python
   socket, and the test client through its own in-process transport, so neither trips the doors.)

2. The shadow view stays the Admin Console's. Every client route that takes ``preview`` refuses it to a USER - 403 for
   ``shadow``, and no other value gets through - and a route whose answer names its ``source`` says ``qualified`` to a USER.
   (``test_auth_rbac.py`` signs in for real on four of these routes; this one walks all of them, so a route added with a
   ``preview`` parameter cannot forget the check.)
"""

from __future__ import annotations

import re
import socket
import urllib.request
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    from fbi.api.app import create_app

    document: dict[str, Any] = create_app().openapi()
    return document


def user_get_routes(spec: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    """(path template, parameters) of every GET route outside the Admin Console."""
    return sorted(
        (path, ops["get"].get("parameters", []))
        for path, ops in spec["paths"].items()
        if "get" in ops and path.startswith("/api/v1/") and not path.startswith("/api/v1/admin")
    )


def concrete(template: str, params: list[dict[str, Any]], seed: Seed) -> str:
    """The template with real ids from the seed graph, plus the query parameters a route requires: the first value a closed
    list allows, the seed's match for a number (``GET /explain?entity=match&id=...``), a word for free text - so the route
    really runs instead of stopping at its own validation."""
    ids = {"fixture_id": seed.fixture_id, "competition_id": seed.competition_id, "team_id": seed.home_team_id,
           "kind": "daily"}
    path = re.sub(r"\{([^}]+)\}", lambda m: str(ids.get(m.group(1), 1)), template)

    def value(p: dict[str, Any]) -> str:
        schema = p.get("schema", {})
        if schema.get("enum"):
            return str(schema["enum"][0])
        return str(seed.fixture_id) if schema.get("type") == "integer" else "a"

    required = [p for p in params if p["in"] == "query" and p.get("required")]
    return path + ("?" + "&".join(f"{p['name']}={value(p)}" for p in required) if required else "")


@pytest.fixture()
def as_user(migrated_database: str, seed: Seed) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    from fbi.api.app import create_app

    with TestClient(signed_in(create_app(), "USER"), headers=SAME_SITE) as client:
        yield client
    mp.undo()
    reset_cache()


class DialedError(AssertionError):
    """A route tried to reach the outside world."""


@pytest.fixture()
def doors_shut(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    def refuse(what: str) -> None:
        attempts.append(what)
        raise DialedError(f"outbound call from a user route: {what}")

    def sync_send(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        refuse(f"httpx {request.method} {request.url}")
        raise AssertionError("unreachable")

    async def async_send(self: httpx.AsyncHTTPTransport, request: httpx.Request) -> httpx.Response:
        refuse(f"httpx {request.method} {request.url}")
        raise AssertionError("unreachable")

    def urlopen(url: Any, *args: Any, **kwargs: Any) -> Any:
        refuse(f"urllib {getattr(url, 'full_url', url)}")

    real_connect = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            refuse(f"socket {address}")
        real_connect(self, address)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_send)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_send)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return attempts


def test_the_doors_are_really_shut(doors_shut: list[str]) -> None:
    """The trap catches what it must: an httpx call to a model's address and a raw socket to the internet."""
    with pytest.raises(DialedError), httpx.Client() as client:
        client.post("https://api.anthropic.com/v1/messages", json={})
    with pytest.raises(DialedError), socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
        raw.connect(("93.184.215.14", 443))
    assert len(doors_shut) == 2


def test_no_route_a_user_can_open_reaches_the_outside_world(spec: dict[str, Any], seed: Seed, as_user: TestClient,
                                                            doors_shut: list[str]) -> None:
    routes = user_get_routes(spec)
    assert len(routes) >= 30, "the user routes were not found in the OpenAPI document"
    failures: list[str] = []
    for template, params in routes:
        path = concrete(template, params, seed)
        try:
            r = as_user.get(path)
        except DialedError as exc:
            failures.append(f"{path}: {exc}")
            continue
        if r.status_code >= 500:
            failures.append(f"{path}: {r.status_code} {r.text[:200]}")
    assert not doors_shut, f"user routes tried to reach the outside world: {doors_shut}"
    assert not failures, "\n".join(failures)


def test_every_route_with_a_preview_refuses_it_to_a_user(spec: dict[str, Any], seed: Seed,
                                                         as_user: TestClient) -> None:
    with_preview = [(t, p) for t, p in user_get_routes(spec) if any(x["name"] == "preview" for x in p)]
    assert len(with_preview) >= 12, [t for t, _ in with_preview]
    for template, params in with_preview:
        base = concrete(template, params, seed)
        joiner = "&" if "?" in base else "?"
        shadow = as_user.get(f"{base}{joiner}preview=shadow")
        assert shadow.status_code == 403 and shadow.json()["error"]["code"] == "forbidden", (template, shadow.text)
        other = as_user.get(f"{base}{joiner}preview=evaluation")
        assert other.status_code in (403, 422), (template, other.status_code)


def test_what_a_user_reads_without_a_preview_is_the_qualified_record(spec: dict[str, Any], seed: Seed,
                                                                     as_user: TestClient) -> None:
    sourced: list[str] = []
    for template, params in user_get_routes(spec):
        if not any(x["name"] == "preview" for x in params):
            continue
        r = as_user.get(concrete(template, params, seed))
        if r.status_code != 200:
            continue
        data = r.json().get("data")
        if isinstance(data, dict) and "source" in data:
            sourced.append(template)
            assert data["source"] == "qualified", (template, data["source"])
    assert {"/api/v1/picks", "/api/v1/parlays/{kind}"} <= set(sourced), sourced
