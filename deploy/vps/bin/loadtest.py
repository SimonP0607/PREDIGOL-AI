#!/usr/bin/env python3
"""Load test: N signed-in people browsing PrediGol at once, through the server's own front door (Caddy, HTTPS).

Run it ON the server through `predigolctl loadtest` (accounts, raised per-IP limits and the clean-up are done
there), or directly:

    python3 loadtest.py --base https://predigol.example --resolve 127.0.0.1 --accounts FILE \\
        --users 100,200 --minutes 5 [--ramp 60] [--think 3:10] [--cacert CA] [--sample-docker] [--out FILE.json]

Each virtual user signs in once (its own session cookie, as a browser keeps it), then visits pages the way the
web app loads them - Home, Picks, Matches and a match, Live, Competitions and a table, Odds, My picks, Search -
with a pause of --think seconds between pages. Phases: the first --users value, held for --minutes, then more
users join up to the next value, and so on. Per phase: requests, errors, status codes, latency p50/p95/p99/max
(overall and per page), throughput, bytes; with --sample-docker also the server's CPU, memory, PostgreSQL
connections and disk IOPS (peak and mean). Standard library only (Python 3.10+).

The accounts file has one "email<TAB>password" per line (scripts/loadtest_accounts.py).
Exit 0 when every phase stayed under --max-error-rate (default 1 %), 1 otherwise.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import random
import re
import socket
import ssl
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit

API = "/api/v1"

# The pages, as the web app fetches them (src/lib/api/v1/client.ts), and how often people open each.
PAGES: list[tuple[str, int]] = [
    ("home", 28), ("picks", 14), ("matches", 16), ("match", 12), ("live", 8),
    ("competition", 8), ("odds", 5), ("my_picks", 5), ("search", 4),
]


@dataclass
class Sample:
    page: str
    path: str
    status: int
    seconds: float
    nbytes: int


@dataclass
class Catalog:
    fixtures: list[int] = field(default_factory=list)
    competitions: list[int] = field(default_factory=list)
    teams: list[int] = field(default_factory=list)
    words: list[str] = field(default_factory=lambda: ["madrid", "united", "nacional", "milan", "boca"])


class Client:
    """One person's browser: a keep-alive HTTPS connection and a session cookie."""

    def __init__(self, base: str, resolve: str | None, ctx: ssl.SSLContext, timeout: float) -> None:
        u = urlsplit(base)
        self.host = u.hostname or ""
        self.port = u.port or 443
        self.origin = f"https://{self.host}" + ("" if self.port == 443 else f":{self.port}")
        self.resolve = resolve
        self.ctx = ctx
        self.timeout = timeout
        self.cookie = ""
        self.conn: http.client.HTTPSConnection | None = None

    def _connect(self) -> http.client.HTTPSConnection:
        conn = http.client.HTTPSConnection(self.host, self.port, context=self.ctx, timeout=self.timeout)
        if self.resolve:  # connect to this address, but speak TLS (SNI, certificate) for the real name
            sock = socket.create_connection((self.resolve, self.port), timeout=self.timeout)
            conn.sock = self.ctx.wrap_socket(sock, server_hostname=self.host)
        return conn

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, bytes, float]:
        headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "predigol-loadtest",
                   "X-Requested-With": "predigol", "Origin": self.origin, "Referer": self.origin + "/"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        for attempt in (1, 2):  # a keep-alive connection the server closed: reconnect once
            if self.conn is None:
                self.conn = self._connect()
            started = time.perf_counter()
            try:
                self.conn.request(method, path, body=data, headers=headers)
                res = self.conn.getresponse()
                payload = res.read()
                elapsed = time.perf_counter() - started
            except (http.client.HTTPException, OSError):
                self.close()
                if attempt == 2:
                    raise
                continue
            for k, v in res.getheaders():
                if k.lower() == "set-cookie" and "session" in v.split("=", 1)[0]:
                    self.cookie = v.split(";", 1)[0]
            if res.getheader("Connection", "").lower() == "close":
                self.close()
            return res.status, payload, elapsed
        raise RuntimeError("unreachable")

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None


def page_paths(page: str, cat: Catalog, rnd: random.Random) -> list[str]:
    fid = rnd.choice(cat.fixtures) if cat.fixtures else None
    cid = rnd.choice(cat.competitions) if cat.competitions else None
    if page == "home":
        return [f"{API}/auth/me", f"{API}/home"]
    if page == "picks":
        return [f"{API}/picks", f"{API}/daily", f"{API}/parlays/safe"]
    if page == "matches":
        return [f"{API}/matches"]
    if page == "match" and fid:
        return [f"{API}/matches/{fid}", f"{API}/matches/{fid}/center", f"{API}/odds/fixtures/{fid}"]
    if page == "live":
        return [f"{API}/live"]
    if page == "competition" and cid:
        paths = [f"{API}/competitions", f"{API}/competitions/{cid}/standings"]
        if cat.teams:
            paths.append(f"{API}/teams/{rnd.choice(cat.teams)}")
        return paths
    if page == "odds":
        return [f"{API}/odds/best"]
    if page == "my_picks":
        return [f"{API}/me/picks?" + urlencode({"limit": 500}), f"{API}/me/history?period=30d"]
    if page == "search":
        return [f"{API}/search?" + urlencode({"q": rnd.choice(cat.words), "limit": 8})]
    return [f"{API}/home"]


def ints_under(obj: Any, keys: set[str], out: set[int]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, int) and v > 0:
                out.add(v)
            ints_under(v, keys, out)
    elif isinstance(obj, list):
        for v in obj:
            ints_under(v, keys, out)


def discover(client: Client) -> Catalog:
    cat = Catalog()
    status, body, _ = client.request("GET", f"{API}/matches")
    if status == 200:
        found: set[int] = set()
        data = json.loads(body).get("data")
        if isinstance(data, list):
            for m in data:
                if isinstance(m, dict):
                    for k in ("fixture_id", "id"):
                        if isinstance(m.get(k), int):
                            found.add(m[k])
                            break
        cat.fixtures = sorted(found)[:300]
        teams: set[int] = set()
        ints_under(data, {"home_team_id", "away_team_id", "team_id"}, teams)
        cat.teams = sorted(teams)[:300]
    status, body, _ = client.request("GET", f"{API}/competitions")
    if status == 200:
        found = set()
        for c in json.loads(body).get("data") or []:
            if isinstance(c, dict):
                for k in ("competition_id", "id"):
                    if isinstance(c.get(k), int):
                        found.add(c[k])
                        break
        cat.competitions = sorted(found)[:100]
    return cat


class Run:
    def __init__(self, args: argparse.Namespace, accounts: list[tuple[str, str]], cat: Catalog,
                 ctx: ssl.SSLContext) -> None:
        self.args = args
        self.accounts = accounts
        self.cat = cat
        self.ctx = ctx
        self.lock = threading.Lock()
        self.samples: list[Sample] = []
        self.logins: list[tuple[int, float]] = []
        self.failures: Counter[str] = Counter()
        self.stop = threading.Event()
        self.think = tuple(float(x) for x in args.think.split(":"))

    def record(self, s: Sample) -> None:
        with self.lock:
            self.samples.append(s)

    def user(self, n: int) -> None:
        rnd = random.Random(n)
        email, password = self.accounts[n % len(self.accounts)]
        client = Client(self.args.base, self.args.resolve, self.ctx, self.args.timeout)
        try:
            status, _, secs = client.request("POST", f"{API}/auth/login", {"email": email, "password": password})
        except Exception as exc:  # a load test counts failures; it never stops on one
            with self.lock:
                self.failures[f"login: {type(exc).__name__}"] += 1
            return
        with self.lock:
            self.logins.append((status, secs))
        if status != 200:
            return
        names = [p for p, _ in PAGES]
        weights = [w for _, w in PAGES]
        while not self.stop.is_set():
            page = rnd.choices(names, weights)[0]
            for path in page_paths(page, self.cat, rnd):
                if self.stop.is_set():
                    break
                try:
                    status, body, secs = client.request("GET", path)
                    self.record(Sample(page, re.sub(r"/\d+", "/{id}", path.split("?")[0]), status, secs, len(body)))
                except Exception as exc:
                    with self.lock:
                        self.failures[f"{page}: {type(exc).__name__}"] += 1
            self.stop.wait(rnd.uniform(*self.think))
        client.close()


class Sampler(threading.Thread):
    """The server while it is loaded: host CPU, memory, disk IOPS; containers' CPU and memory; database
    connections. Every 5 s."""

    def __init__(self, disk: str | None) -> None:
        super().__init__(daemon=True)
        self.rows: list[dict[str, Any]] = []
        self.stop = threading.Event()
        self.disk = disk or self._main_disk()

    @staticmethod
    def _main_disk() -> str | None:
        try:
            src = subprocess.run(["findmnt", "-no", "SOURCE", "/"], capture_output=True, text=True, timeout=5).stdout
            name = src.strip().rsplit("/", 1)[-1]
            return re.sub(r"(?<=\D)\d+$", "", name) if not name.startswith("nvme") else re.sub(r"p\d+$", "", name)
        except Exception:
            return None

    @staticmethod
    def _cpu() -> tuple[int, int]:
        with open("/proc/stat") as fh:
            parts = [int(x) for x in fh.readline().split()[1:9]]
        return sum(parts), parts[3] + parts[4]

    def _ios(self) -> int:
        if not self.disk:
            return 0
        with open("/proc/diskstats") as fh:
            for line in fh:
                f = line.split()
                if f[2] == self.disk:
                    return int(f[3]) + int(f[7])
        return 0

    def run(self) -> None:
        t0, i0 = self._cpu()
        io0, at0 = self._ios(), time.monotonic()
        while not self.stop.wait(5):
            t1, i1 = self._cpu()
            io1, at1 = self._ios(), time.monotonic()
            row: dict[str, Any] = {"at": time.time(), "host_cpu_pct": round(100 * (1 - (i1 - i0) / max(1, t1 - t0)), 1),
                                   "iops": round((io1 - io0) / max(0.001, at1 - at0), 1)}
            t0, i0, io0, at0 = t1, i1, io1, at1
            with open("/proc/meminfo") as fh:
                mem = {ln.split(":")[0]: int(ln.split()[1]) for ln in fh}
            row["host_mem_used_gb"] = round((mem["MemTotal"] - mem["MemAvailable"]) / 1048576, 2)
            try:
                out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}"],
                                     capture_output=True, text=True, timeout=20).stdout
                for line in out.splitlines():
                    d = json.loads(line)
                    name = d.get("Name", "")
                    if not name.startswith("predigol-"):
                        continue
                    svc = name.removeprefix("predigol-")
                    row[f"{svc}_cpu_pct"] = float(d["CPUPerc"].rstrip("%") or 0)
                    used = d["MemUsage"].split("/")[0].strip()
                    num = float(re.sub(r"[A-Za-z]+", "", used) or 0)
                    unit = re.sub(r"[0-9.]+", "", used)
                    row[f"{svc}_mem_mb"] = round(num * {"GiB": 1024, "MiB": 1, "KiB": 1 / 1024, "B": 1 / 1048576}.get(unit, 1), 1)
                conns = subprocess.run(["docker", "exec", "predigol-postgres", "psql", "-U", "fbi", "-d", "fbi", "-qAtX",
                                        "-c", "SELECT count(*) FROM pg_stat_activity WHERE datname = 'fbi'"],
                                       capture_output=True, text=True, timeout=20).stdout.strip()
                row["pg_connections"] = int(conns or 0)
            except Exception:
                pass
            self.rows.append(row)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)  # nearest rank
    return ordered[max(1, math.ceil(q / 100 * len(ordered))) - 1]


def summarize(samples: list[Sample], seconds: float) -> dict[str, Any]:
    lat = [s.seconds * 1000 for s in samples]
    codes = Counter(s.status for s in samples)
    errors = sum(n for c, n in codes.items() if c >= 500 or c in (0, 429))
    by_page: dict[str, list[float]] = defaultdict(list)
    by_path: dict[str, list[float]] = defaultdict(list)
    for s in samples:
        by_page[s.page].append(s.seconds * 1000)
        by_path[s.path].append(s.seconds * 1000)

    def stats(v: list[float]) -> dict[str, Any]:
        return {"n": len(v), "p50": round(pct(v, 50), 1), "p95": round(pct(v, 95), 1), "p99": round(pct(v, 99), 1),
                "max": round(max(v), 1) if v else 0}

    return {
        "requests": len(samples), "rps": round(len(samples) / max(1, seconds), 1),
        "errors": errors, "error_rate_pct": round(100 * errors / max(1, len(samples)), 3),
        "status": {str(k): v for k, v in sorted(codes.items())},
        "latency_ms": stats(lat) | {"mean": round(statistics.fmean(lat), 1) if lat else 0},
        "mb_transferred": round(sum(s.nbytes for s in samples) / 1e6, 1),
        "pages": {p: stats(v) for p, v in sorted(by_page.items())},
        "slowest_paths": sorted(({"path": p} | stats(v) for p, v in by_path.items()), key=lambda r: -r["p95"])[:6],
    }


def server_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    keys = sorted({k for r in rows for k in r if k != "at"})
    out: dict[str, Any] = {}
    for k in keys:
        v = [r[k] for r in rows if k in r]
        if v:
            out[k] = {"peak": max(v), "mean": round(statistics.fmean(v), 1)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="https://<domain>")
    ap.add_argument("--resolve", help="connect to this address instead of resolving the domain (127.0.0.1)")
    ap.add_argument("--cacert", help="trust this CA (Caddy's local authority for a *.localhost rehearsal)")
    ap.add_argument("--accounts", required=True)
    ap.add_argument("--users", default="100,200")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--ramp", type=float, default=60, help="seconds over which each phase's new users join")
    ap.add_argument("--think", default="3:10", help="pause between pages, seconds MIN:MAX")
    ap.add_argument("--timeout", type=float, default=30)
    ap.add_argument("--sample-docker", action="store_true")
    ap.add_argument("--disk", help="block device for IOPS (default: the one holding /)")
    ap.add_argument("--max-error-rate", type=float, default=1.0, help="percent")
    ap.add_argument("--out")
    args = ap.parse_args()

    accounts: list[tuple[str, str]] = []
    with open(args.accounts) as fh:
        for line in fh:
            email, sep, password = line.rstrip("\n").partition("\t")
            if sep:
                accounts.append((email, password))
    levels = [int(x) for x in args.users.split(",")]
    if len(accounts) < max(levels):
        print(f"{len(accounts)} accounts for {max(levels)} users: each account must be one person", file=sys.stderr)
        return 2
    ctx = ssl.create_default_context(cafile=args.cacert) if args.cacert else ssl.create_default_context()

    probe = Client(args.base, args.resolve, ctx, args.timeout)
    status, _, _ = probe.request("POST", f"{API}/auth/login", {"email": accounts[0][0], "password": accounts[0][1]})
    if status != 200:
        print(f"the first account cannot sign in (HTTP {status})", file=sys.stderr)
        return 2
    cat = discover(probe)
    probe.close()
    print(f"catalogue: {len(cat.fixtures)} matches, {len(cat.competitions)} competitions, {len(cat.teams)} teams",
          flush=True)

    run = Run(args, accounts, cat, ctx)
    sampler = Sampler(args.disk) if args.sample_docker else None
    if sampler:
        sampler.start()
    threads: list[threading.Thread] = []
    phases: list[dict[str, Any]] = []
    for level in levels:
        new = level - len(threads)
        print(f"phase {level} users: {new} join over {args.ramp:.0f}s, then {args.minutes:g} min", flush=True)
        for _ in range(new):
            t = threading.Thread(target=run.user, args=(len(threads),), daemon=True)
            threads.append(t)
            t.start()
            time.sleep(args.ramp / max(1, new))
        with run.lock:
            start_n = len(run.samples)
        rows_from = len(sampler.rows) if sampler else 0
        started = time.monotonic()
        time.sleep(args.minutes * 60)
        seconds = time.monotonic() - started
        with run.lock:
            window = run.samples[start_n:]
            logins = list(run.logins)
            failures = dict(run.failures)
        phase = {"users": level, "seconds": round(seconds), **summarize(window, seconds),
                 "logins": {"n": len(logins), "ok": sum(1 for s, _ in logins if s == 200),
                            "p95_ms": round(pct([t * 1000 for _, t in logins], 95), 1)},
                 "client_failures": failures}
        if sampler:
            phase["server"] = server_summary(sampler.rows[rows_from:])
        phases.append(phase)
        lat = phase["latency_ms"]
        print(f"  {phase['requests']} requests ({phase['rps']}/s), errors {phase['error_rate_pct']}%, "
              f"p50 {lat['p50']} ms, p95 {lat['p95']} ms, p99 {lat['p99']} ms, max {lat['max']} ms", flush=True)
        if sampler and phase.get("server"):
            s = phase["server"]
            print("  server: " + ", ".join(f"{k} peak {v['peak']}" for k, v in s.items()
                                          if k in ("host_cpu_pct", "host_mem_used_gb", "pg_connections", "iops",
                                                   "postgres_cpu_pct", "api_cpu_pct")), flush=True)
    run.stop.set()
    for t in threads:
        t.join(timeout=args.timeout + 5)
    if sampler:
        sampler.stop.set()
    result = {"base": args.base, "think_s": args.think, "minutes_per_phase": args.minutes, "phases": phases,
              "catalogue": {"matches": len(cat.fixtures), "competitions": len(cat.competitions),
                            "teams": len(cat.teams)}}
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=1)
        print(f"written {args.out}")
    bad = [p["users"] for p in phases if p["error_rate_pct"] > args.max_error_rate]
    if bad:
        print(f"FAILED: error rate above {args.max_error_rate}% at {bad} users")
        return 1
    print("PASSED: every phase under the error budget")
    return 0


if __name__ == "__main__":
    sys.exit(main())
