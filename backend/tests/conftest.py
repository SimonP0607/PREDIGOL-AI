"""Settings every test run needs.

FBI_AUTH_SECRET_KEY: the second factor cannot be enrolled or checked without it. This one exists only for tests -
32 bytes that spell what they are - and is never valid anywhere else (production refuses to start without its own).
"""

from __future__ import annotations

import os

TEST_AUTH_KEY = "dGVzdC1vbmx5LWtleS1mb3ItcHJlZGlnb2wtdGVzdHM="

os.environ.setdefault("FBI_AUTH_SECRET_KEY", TEST_AUTH_KEY)
