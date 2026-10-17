"""Plain settings variables, seen the way the typed settings see them: the ``.env`` file, then the process.

The platform's typed settings (pydantic-settings) read ``.env`` in the working directory as well as the process
environment. A few modules read plain variables instead: the AI layer's models, keys and limits
(``fbi.ai.config``), the web search key (``fbi.analyst.search``) and the analyst's settings. In host mode
(``scripts/dev-up`` on the owner's machine) nothing exports ``.env`` into the process, so a key the owner put in
that file reached pydantic but not those modules. ``environment()`` gives them pydantic's view: the file's values,
with a variable set in the process winning over the file - as it does for pydantic. A missing file is no file.

Values are never logged or returned to a client by this module; callers keep that rule (``AiSettings.public``).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values

ENV_FILE = ".env"


def environment(path: str | os.PathLike[str] = ENV_FILE) -> Mapping[str, str]:
    """The ``.env`` file's variables overlaid by the process environment (process wins)."""
    file = Path(path)
    values: dict[str, str] = {}
    if file.is_file():
        values = {k: v for k, v in dotenv_values(file).items() if v is not None}
    return {**values, **os.environ}
