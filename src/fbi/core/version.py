"""Which code produced this row.

Model versions, backtests, picks and the worker heartbeat all record a
``code_version``. It is read from the checked-out repository without calling
``git`` - the container image has no git binary, but the working tree is
mounted - and falls back to an explicit "unknown" rather than a guess.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

UNKNOWN = "unknown"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def code_version() -> str:
    """Short commit SHA of the running tree, ``FBI_CODE_VERSION`` if set, else "unknown"."""
    explicit = os.environ.get("FBI_CODE_VERSION")
    if explicit:
        return explicit
    git = _repo_root() / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = head[5:]
            ref_file = git / ref
            if ref_file.exists():
                return ref_file.read_text().strip()[:12]
            packed = git / "packed-refs"
            if packed.exists():
                for line in packed.read_text().splitlines():
                    if line.endswith(" " + ref):
                        return line.split(" ", 1)[0][:12]
            return UNKNOWN
        return head[:12]
    except OSError:
        return UNKNOWN
