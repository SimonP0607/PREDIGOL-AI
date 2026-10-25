"""R02 of the security plan (S1; GHSA-qx66-fv34-fjm8): the front door and the TanStack Start server functions.

The web framework answers a request to ``/_serverFn/<id>`` as a call of a server function. The versions that were audited reflected what came
in the URL back as HTML (an unauthenticated reflected XSS). Production runs the patched versions since UX A0 (25 Oct 2026), the app defines no
server function of its own and its CSRF middleware (``web/src/start.ts``) refuses anything that is not same-origin. The Caddyfile adds a second
lock: a call of a server function carries the header ``x-tsr-serverFn: true`` and is neither a document navigation nor a request for HTML;
anything else on that path gets an empty 403 and a Content-Security-Policy that allows nothing. The header is the client's, so the rule is a
filter and not authentication.

What is held here, without a running Caddy: the three tests are the ones the framework itself makes, the site-wide headers skip that path (Caddy
runs a site-wide ``header`` block last - and one with ``-Server`` is deferred - so a path cannot override one of its fields from a handler: the
path that needs another Content-Security-Policy gets its own block) and both blocks come from the one snippet, so they cannot drift apart. When
``caddy`` is installed (``CADDY_BIN`` or the PATH) the same is read from the configuration Caddy builds from the file, which is what it runs:
the rule is before the catch-all and says what the file says. ``bin/serverfn-matrix.sh`` and ``bin/serverfn-probe.sh`` probe a running server;
their own logic is tried here against a small server that behaves as the rule does, and against one that does not."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest

KIT = Path(__file__).resolve().parents[2] / "deploy" / "vps"
BACKEND = KIT.parents[1]
CADDYFILE = KIT / "Caddyfile"
SECURITY_HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Referrer-Policy",
    "Permissions-Policy",
    "Cross-Origin-Opener-Policy",
)
# the three tests that refuse a request on /_serverFn/*, in the words of the Caddyfile
CONDITIONS = (
    '{http.request.header.X-Tsr-Serverfn} != "true"',
    '{http.request.header.Sec-Fetch-Mode} == "navigate"',
    '{http.request.header.Accept}.contains("text/html")',
)
SITE_ENV = {
    "PREDIGOL_DOMAIN": "predigol.example.com",
    "PREDIGOL_SITE": "predigol.example.com",
    "PREDIGOL_TLS_MODE": "internal",
    "PREDIGOL_TRUSTED_PROXIES": "127.0.0.1/32",
}


def _code() -> str:
    """The Caddyfile without its comment lines."""
    text = CADDYFILE.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _block(code: str, opener: str) -> str:
    """The text between the braces of the first block whose opening line matches ``opener`` (a regular expression over the whole line)."""
    found = re.search(rf"^[ \t]*{opener}[ \t]*\{{[ \t]*$", code, flags=re.M)
    assert found, f"no block opens with {opener!r}"
    depth, position = 1, found.end()
    while depth:
        if code[position] == "{":
            depth += 1
        elif code[position] == "}":
            depth -= 1
        position += 1
    return code[found.end() : position - 1]


# --- what the file says ----------------------------------------------------------------------------------------------------------------------


def test_a_server_function_call_needs_the_framework_header_and_is_not_a_page_request() -> None:
    """The framework's client sends ``x-tsr-serverFn: true`` and its server tells a call by that header (``=== "true"``). A navigation of a
    document or a request that asks for HTML is never a call. Refused when ANY of the three holds, and only those."""
    rule = _block(_code(), r"handle /_serverFn/\*")
    expression = re.search(r"@not_a_call expression `([^`]+)`", rule)
    assert expression, "the matcher of what is refused"
    assert [part.strip() for part in expression.group(1).split("||")] == list(CONDITIONS)
    assert re.search(r"^\s*respond @not_a_call 403\s*$", rule, flags=re.M), "an empty 403"
    assert re.search(r"^\s*reverse_proxy web:3000\s*$", rule, flags=re.M), "what is not refused goes to the web, as it did before the rule"


def test_the_refusal_and_the_pass_carry_a_policy_that_allows_nothing() -> None:
    rule = _block(_code(), r"handle /_serverFn/\*")
    headers = _block(rule, r"header")
    assert "Content-Security-Policy \"default-src 'none'\"" in headers
    assert "import security_headers" in headers


def test_the_site_wide_headers_skip_the_server_function_path() -> None:
    """Regression found while building the rule (25 Oct 2026): a ``header`` inside the path's handler lost against the site-wide block, which
    Caddy runs last, so the path kept the page policy. The site-wide block now has a matcher that leaves the path out, and the path has its
    own."""
    code = _code()
    assert re.search(r"^\s*@not_serverfn not path /_serverFn/\*\s*$", code, flags=re.M)
    wide = _block(code, r"header @not_serverfn")
    assert "import security_headers" in wide
    assert wide.count("Content-Security-Policy") == 1 and "default-src 'self'" in wide
    assert code.count("Content-Security-Policy") == 2, "the page policy and the one of the server-function path, no other"
    site_level = re.findall(r"^\theader([^\n{]*)\{", code, flags=re.M)
    assert site_level and all(item.strip().startswith("@") for item in site_level), "no header block at the site's level without a matcher"


def test_both_header_blocks_come_from_the_one_snippet() -> None:
    code = _code()
    snippet = _block(code, r"\(security_headers\)")
    for name in SECURITY_HEADERS:
        assert re.search(rf"^\s*{name} \"", snippet, flags=re.M), f"{name} is in the snippet"
    assert re.search(r"^\s*-Server\s*$", snippet, flags=re.M), "the server's name is not told"
    assert code.count("import security_headers") == 2, "the page block and the server-function block"
    outside = code.replace(snippet, "")
    for name in SECURITY_HEADERS:
        assert name not in outside, f"{name} is set in one place only"


def test_the_notes_name_what_the_rule_does() -> None:
    """The document of the rule says what the file does: the three tests, the answer, the scripts that probe it and the step that makes Caddy
    read a changed file."""
    note = (BACKEND / "docs" / "security" / "R02_SERVER_FUNCTIONS.md").read_text(encoding="utf-8")
    for needle in ("x-tsr-serverFn", "Sec-Fetch-Mode", "text/html", "403", "default-src 'none'", "serverfn-matrix.sh", "serverfn-probe.sh",
                   "--force-recreate caddy", "GHSA-qx66-fv34-fjm8"):
        assert needle in note, needle
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    assert "--force-recreate caddy" in readme and "/_serverFn/" in readme


# --- what Caddy builds from it (only when caddy is installed) -------------------------------------------------------------------------------


def _caddy() -> str | None:
    return os.environ.get("CADDY_BIN") or shutil.which("caddy")


needs_caddy = pytest.mark.skipif(_caddy() is None, reason="caddy is not installed (set CADDY_BIN to run the tests that read the configuration it builds)")


def _site_routes(tmp_path: Path) -> list[dict[str, Any]]:
    caddy = _caddy()
    assert caddy
    # the Caddyfile imports its TLS snippet from the container's path; point it at the kit's copy
    adapted = tmp_path / "Caddyfile"
    adapted.write_text(CADDYFILE.read_text(encoding="utf-8").replace("/etc/caddy/snippets", str(KIT / "caddy")), encoding="utf-8")
    done = subprocess.run([caddy, "adapt", "--config", str(adapted), "--adapter", "caddyfile"], capture_output=True, text=True,
                          env={**os.environ, "HOME": str(tmp_path), **SITE_ENV}, check=False)
    assert done.returncode == 0, done.stderr
    config = json.loads(done.stdout)
    for server in config["apps"]["http"]["servers"].values():
        for route in server["routes"]:
            if route.get("match") == [{"host": [SITE_ENV["PREDIGOL_SITE"]]}]:
                routes: list[dict[str, Any]] = route["handle"][0]["routes"]
                return routes
    raise AssertionError("the routes of the site")


def _paths(route: dict[str, Any]) -> list[str] | None:
    for matcher in route.get("match") or []:
        if "path" in matcher:
            paths: list[str] = matcher["path"]
            return paths
    return None


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


@needs_caddy
def test_caddy_puts_the_rule_before_the_catch_all_and_builds_what_the_file_says(tmp_path: Path) -> None:
    routes = _site_routes(tmp_path)
    at = next(i for i, route in enumerate(routes) if _paths(route) == ["/_serverFn/*"])
    catch_all = next(i for i, route in enumerate(routes) if not route.get("match") and route["handle"][0].get("handler") == "subroute"
                     and route["handle"][0]["routes"][0]["handle"][0].get("handler") == "reverse_proxy")
    assert at < catch_all, "Caddy sorts the handle blocks by the specificity of their path; the one without a matcher goes last"
    headers, refusal, upstream = routes[at]["handle"][0]["routes"]
    set_by_rule = headers["handle"][0]["response"]
    assert set_by_rule["set"]["Content-Security-Policy"] == ["default-src 'none'"]
    assert all(name in set_by_rule["set"] for name in SECURITY_HEADERS) and set_by_rule["delete"] == ["Server"]
    assert refusal["handle"] == [{"handler": "static_response", "status_code": 403}]
    expression = refusal["match"][0]["expression"]["expr"]
    assert [part.strip() for part in expression.split("||")] == list(CONDITIONS)
    assert upstream["handle"][0]["upstreams"] == [{"dial": "web:3000"}]


@needs_caddy
def test_caddy_gives_every_path_the_same_headers_except_the_policy_of_the_server_function_path(tmp_path: Path) -> None:
    routes = _site_routes(tmp_path)
    carrying = [node for node in _walk(routes) if node.get("handler") == "headers" and "Strict-Transport-Security" in node["response"].get("set", {})]
    assert len(carrying) == 2, "the page block and the server-function block"
    for node in carrying:
        assert all(name in node["response"]["set"] for name in SECURITY_HEADERS) and node["response"]["delete"] == ["Server"]
        assert node["response"]["deferred"] is True
    wide = next(route for route in routes if route.get("match") == [{"not": [{"path": ["/_serverFn/*"]}]}])
    assert wide["handle"][0]["response"]["set"]["Content-Security-Policy"][0].startswith("default-src 'self'")


# --- the scripts that probe a running server (tried against a server that behaves as the rule does, and against one that does not) ---------------


def _norm(path: str) -> str:
    """The path as Caddy matches it: decoded, dot segments resolved, trailing slash kept."""
    decoded = unquote(urlsplit(path).path)
    cleaned = posixpath.normpath(decoded)
    return cleaned + "/" if decoded.endswith("/") and not cleaned.endswith("/") else cleaned


class _Door(BaseHTTPRequestHandler):
    """A server that answers as the front door does when ``obey`` is true: /_serverFn/* is refused by the three tests; everything else goes on."""

    obey = True

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        path = _norm(self.path)
        in_rule = path.lower().startswith("/_serverfn/")
        refused = in_rule and (
            self.headers.get("X-Tsr-Serverfn") != "true"
            or self.headers.get("Sec-Fetch-Mode") == "navigate"
            or "text/html" in (self.headers.get("Accept") or "")
        )
        if refused and self.obey:
            self.send_response(403)
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = f"<html>{self.path}</html>".encode() if not self.obey else b"web"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._answer()

    def do_POST(self) -> None:
        self._answer()

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _serve(obey: bool) -> tuple[ThreadingHTTPServer, str]:
    handler = type("Door", (_Door,), {"obey": obey})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _run(script: str, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(KIT / "bin" / script), base], capture_output=True, text=True, timeout=120, check=False)


needs_curl = pytest.mark.skipif(shutil.which("curl") is None or shutil.which("bash") is None, reason="the probe scripts need bash and curl")


@needs_curl
@pytest.mark.parametrize("script", ["serverfn-matrix.sh", "serverfn-probe.sh"])
def test_the_probe_scripts_pass_against_a_server_that_behaves_as_the_rule_does(script: str) -> None:
    server, base = _serve(obey=True)
    try:
        done = _run(script, base)
    finally:
        server.shutdown()
    assert done.returncode == 0, done.stdout[-1500:]
    assert " 0 mismatches" in done.stdout or " 0 reflected-as-html" in done.stdout


@needs_curl
def test_the_matrix_fails_against_a_server_that_lets_everything_through() -> None:
    server, base = _serve(obey=False)
    try:
        done = _run("serverfn-matrix.sh", base)
    finally:
        server.shutdown()
    assert done.returncode != 0 and "MISMATCH" in done.stdout


@needs_curl
def test_the_marker_probe_fails_against_a_server_that_reflects_the_marker_as_html() -> None:
    server, base = _serve(obey=False)
    try:
        done = _run("serverfn-probe.sh", base)
    finally:
        server.shutdown()
    assert done.returncode != 0 and "FAIL" in done.stdout
