"""Measure how fast /odds/live actually moves, so the cadence is chosen, not guessed.

    python scripts/measure_live_cadence.py              # replay the stored run, 0 requests
    python scripts/measure_live_cadence.py --fetch      # 12 calls, 10s apart

The default replays data/measurements/live_cadence.json, so the finding can be
re-derived at any time without spending a request. See odds/live_cadence.py for
what the measurement settled.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import pathlib
import sys
from collections import Counter
from datetime import datetime
from itertools import pairwise
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

STORE = pathlib.Path("data/measurements/live_cadence.json.gz")
CALLS = 12
GAP = 10.0

Snap = tuple[datetime, dict[str, Any], str]
PriceKey = tuple[int, Any, Any, str]


async def fetch(calls: int, gap: float) -> list[Snap]:
    from scripts.capture_odds import _client

    client = _client()
    snaps: list[Snap] = []
    try:
        for i in range(calls):
            r = await client.get("/odds/live", {})
            snaps.append((r.fetched_at, r.body, r.stored.hash))
            print(f"[{i:02d}] {r.fetched_at.isoformat()} "
                  f"fixtures={len(r.body.get('response') or [])} hash={r.stored.hash[:12]}")
            if i < calls - 1:
                await asyncio.sleep(gap)
    finally:
        await client.aclose()
    STORE.parent.mkdir(parents=True, exist_ok=True)
    # Gzipped: 1.8 MB of payloads compresses to about a tenth of that, and the
    # measurement has to survive in the repository for the finding to be
    # reproducible - data/raw is not committed.
    with gzip.open(STORE, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(
            [{"fetched_at": t.isoformat(), "hash": h, "body": b} for t, b, h in snaps],
            fh,
            separators=(",", ":"),
        )
    print(f"stored {len(snaps)} payloads in {STORE}")
    return snaps


def load() -> list[Snap]:
    if not STORE.exists():
        print(f"{STORE} not found; run with --fetch to measure")
        raise SystemExit(1)
    if STORE.suffix == ".gz":
        with gzip.open(STORE, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
    else:
        raw = json.loads(STORE.read_text())
    return [(datetime.fromisoformat(r["fetched_at"]), r["body"], r["hash"]) for r in raw]


def prices(body: dict[str, Any]) -> dict[PriceKey, tuple[str, bool]]:
    out: dict[PriceKey, tuple[str, bool]] = {}
    for e in body.get("response") or []:
        fid = int(e["fixture"]["id"])
        for bet in e.get("odds") or []:
            for v in bet.get("values") or []:
                out[(fid, bet.get("id"), v.get("value"), str(v.get("handicap")))] = (
                    str(v.get("odd")), bool(v.get("suspended"))
                )
    return out


def updates(body: dict[str, Any]) -> dict[int, Any]:
    return {int(e["fixture"]["id"]): e.get("update") for e in body.get("response") or []}


def analyse(snaps: list[Snap]) -> None:
    print("\n=== payload identity")
    hashes = [h for _, _, h in snaps]
    print(f"distinct payload hashes: {len(set(hashes))} of {len(hashes)}")

    print("\n=== gap | fixtures | update changed | prices moved | appeared | vanished")
    moved_counts: list[int] = []
    moved_fracs: list[float] = []
    for (t0, b0, _), (t1, b1, _) in pairwise(snaps):
        gap = (t1 - t0).total_seconds()
        u0, u1 = updates(b0), updates(b1)
        upd = sum(1 for f in u1 if f in u0 and u0[f] != u1[f])
        p0, p1 = prices(b0), prices(b1)
        common = p0.keys() & p1.keys()
        moved = sum(1 for k in common if p0[k] != p1[k])
        moved_counts.append(moved)
        if common:
            moved_fracs.append(moved / len(common))
        print(f"  {gap:5.1f}s | {len(u1):2d} | {upd:2d}/{len(u1)} | "
              f"{moved:4d}/{len(common):4d} | {len(p1.keys() - p0.keys()):3d} | "
              f"{len(p0.keys() - p1.keys()):3d}")

    still = sum(1 for c in moved_counts if c == 0)
    print(f"\nticks where NOTHING moved: {still}/{len(moved_counts)}")
    if moved_fracs:
        print(f"average share of prices that moved per tick: "
              f"{sum(moved_fracs) / len(moved_fracs):.3%}")
    if moved_counts:
        cycles = sum(1 for c in moved_counts if c > 0)
        if cycles:
            span = (snaps[-1][0] - snaps[0][0]).total_seconds()
            print(f"refreshes seen: {cycles} over {span:.0f}s "
                  f"-> one every {span / cycles:.1f}s")

    print("\n=== how long one price stays put (consecutive ticks unchanged)")
    series: dict[PriceKey, list[tuple[str, bool]]] = {}
    for _, b, _ in snaps:
        for k, v in prices(b).items():
            series.setdefault(k, []).append(v)
    runs: Counter[int] = Counter()
    for vals in series.values():
        if len(vals) < len(snaps):
            continue
        n = 1
        for a, b2 in pairwise(vals):
            if a == b2:
                n += 1
            else:
                runs[n] += 1
                n = 1
        runs[n] += 1
    total = sum(runs.values())
    for length in sorted(runs):
        share = f" ({runs[length] / total:.1%})" if total else ""
        print(f"  {length:2d} tick(s): {runs[length]:5d}{share}")

    print("\n=== suspension churn")
    for (_, b0, _), (t1, b1, _) in pairwise(snaps):
        p0, p1 = prices(b0), prices(b1)
        common = p0.keys() & p1.keys()
        froze = sum(1 for k in common if not p0[k][1] and p1[k][1])
        thawed = sum(1 for k in common if p0[k][1] and not p1[k][1])
        if froze or thawed:
            print(f"  {t1.isoformat()} froze={froze} thawed={thawed}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fetch", action="store_true",
                    help=f"spend {CALLS} requests on a fresh measurement")
    ap.add_argument("--calls", type=int, default=CALLS)
    ap.add_argument("--gap", type=float, default=GAP)
    args = ap.parse_args()
    snaps = asyncio.run(fetch(args.calls, args.gap)) if args.fetch else load()
    analyse(snaps)


if __name__ == "__main__":
    main()
