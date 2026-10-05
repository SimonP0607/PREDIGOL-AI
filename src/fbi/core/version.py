"""Which code produced this row.

Model versions, backtests, picks and the worker heartbeat all record a
``code_version``. It is read from the checked-out repository without calling
``git`` - the container image has no git binary, but the working tree is
mounted - and falls back to an explicit "unknown" rather than a guess.
"""

from __future__ import annotations

import hashlib
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


MODEL_PACKAGES = ("models", "features", "predictions", "backtesting", "domain")
"""The packages whose code decides what a model predicts. A change anywhere in them is a new model version; a change
elsewhere (a page, an audit, a doc) is not."""


def model_code_fingerprint(root: Path | None = None) -> str:
    """sha256 of the model packages' Python sources, path and bytes, in path order: 12 hex characters."""
    base = root or Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for package in MODEL_PACKAGES:
        for path in sorted((base / package).rglob("*.py")):
            digest.update(str(path.relative_to(base)).replace(os.sep, "/").encode())
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()[:12]


@lru_cache(maxsize=1)
def model_code_version() -> str:
    """What a model version is keyed by (5 Oct 2026): the fingerprint of the model code, not the repository commit.
    Keyed by the commit, every deploy - a page, a doc, an audit - made a new version of every model (the Models page
    showed the running Poisson, Dixon-Coles and Elo with no backtest at all, the backtested versions being older
    commits), so no version could ever gather the backtest and the prospective record that qualifying it needs."""
    explicit = os.environ.get("FBI_MODEL_CODE_VERSION")
    return explicit or f"mc{model_code_fingerprint()[:10]}"
