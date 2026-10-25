"""The legal texts' versions and hashes (plan UX, A4; fbi.customer.legal).

    python -m scripts.legal_texts check              # every text has the hash the register gives it (exit 1 if not)
    python -m scripts.legal_texts hashes [--version V]

``hashes`` prints, for the texts as they are on disk, the sha256 each document would have under version V (by default
its current one) - what a new entry of ``texts/versions.json`` needs after a text or the controller's details change.
Nothing is written: the register is edited by hand, with the date, draft, material and what changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from fbi.customer import legal


def hashes(version: str | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for name in legal.DOCUMENTS:
        label = version or legal.current(name).version
        if not legal.VERSION_FORMAT.match(label):
            raise SystemExit(f"{label!r} is not a dated version (YYYY-MM-DD, then up to 24 of a-z 0-9 . -)")
        out[name] = {}
        for locale in legal.LOCALES:
            text = legal._fill(json.loads((legal.TEXTS / locale / f"{name}.json").read_text(encoding="utf-8")))
            payload = legal._payload(name, locale, label, text)
            out[name][locale] = hashlib.sha256(legal.canonical(payload)).hexdigest()
    return out


def check() -> int:
    bad = []
    digests = hashes(None)
    for name in legal.DOCUMENTS:
        current = legal.current(name)
        for locale, digest in digests[name].items():
            if digest != current.sha256[locale]:
                bad.append(f"{locale}/{name}.json changed without a new version (register {current.version})")
    for line in bad or ["every text has the hash the register gives it"]:
        print(line)
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    h = sub.add_parser("hashes")
    h.add_argument("--version")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check()
    print(json.dumps(hashes(args.version), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
