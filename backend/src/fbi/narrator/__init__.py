"""The Narrator of PrediGol Intelligence (``narrator-v1``, IA-017): the reader's «por qué lo recomendamos» of ONE pick, written
after its decision and ONLY from the allowed facts of its trace (``fbi.observability.trace``, trace-v1), checked sentence by
sentence. Born OFF (``FBI_NARRATOR``). Owner's guide: ``docs/owner/IA_017_NARRATOR.md``.

    facts    the trace -> the closed list of facts a reader may be told, each with its id (pure, deterministic)
    prompt   the prompt ``pick-why-v1`` and its closed output contract (sentences that cite fact ids)
    verify   every sentence checked against the facts it cites; an unsupported one is dropped
    job      the switch, the budget, the call and the report (nothing is stored: see the module)
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "narrator-v1"
"""The Narrator as a whole: the facts it reads, its prompt and its checks. A change to any of them is a new version."""
