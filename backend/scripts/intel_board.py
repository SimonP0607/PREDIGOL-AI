"""RP-13.1 - the board BEFORE and AFTER: the frozen baseline against a new measurement made with the same saved query.

    python -m scripts.intel_board ../docs/intelligence/baseline/baseline-v1.json after.json [--json] [--out board.json]
    python -m scripts.intel_board baseline-v1.json baseline-v1.json --reproduce    # the baseline against itself: every difference zero

``after.json`` is what ``intel_baseline_report.py`` writes from a new run of ``intel_baseline.sh`` (same query, same ``base_before``, a later cut).
It reads two files and writes text or one file; it never touches a database. Exit 0, 2 when it cannot read."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from fbi.ops import before_after

OK = 0
CANNOT = 2


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--reproduce", action="store_true", help="compare the baseline with itself (the cut need not be later)")
    args = ap.parse_args(argv)
    try:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"cannot read: {exc}\n")
        return CANNOT
    board = before_after.compare(before, after, allow_identical=args.reproduce)
    if args.out is not None:
        args.out.write_text(json.dumps(board, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.stdout.write((json.dumps(board, indent=1, ensure_ascii=False) if args.as_json else before_after.render(board)) + "\n")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
