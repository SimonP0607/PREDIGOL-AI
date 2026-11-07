"""The Evidence Engine of PrediGol Intelligence (``evidence-engine-v1``, IA-012), in SHADOW.

No important decision may rest only on what a model wrote: it rests on structured evidence, where every assertion has a source, a date, an
entity, a match, a status, a confidence COMPUTED by the server (never declared by a model), its contradictions and a window of validity.
This package reads what ``ai.evidence`` already holds (v1's items and research v2's typed claims), the provider's line-ups and its injury
reports, and says, as of a moment, what is known about a match and how far to trust it:

* ``fbi.evidence.rules``  pure: the tiers of a source (A-D), the status ladder, the learned credibility of a source, the confidence, the
                          validity per topic and the contradiction rules - every number a versioned constant;
* ``fbi.evidence.engine`` the read: ``evidence_for(conn, fixture_id, at=...)`` and ``day_summary``. It never writes.

In shadow: computed and reported (``scripts/ia_evidence.py``), never imported by anything that decides, publishes or serves a user
(``tests/unit/test_evidence_engine_isolation.py``).
"""

from __future__ import annotations

VERSION = "evidence-engine-v1"
