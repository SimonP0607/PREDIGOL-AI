"""Who an entity is outside PrediGol, and every name it goes by (plan 2026, AD-H01 / AD-H02, ``IA-071``).

* ``names``    the one normalisation of a name (``alias_key``) and the name checks the rules are built from.
* ``reep``     the pinned Reep v1 release (CC0): its sha256 per file, the download, the readers.
* ``rules``    pure decisions: which external id goes to which of our entities, what waits for a person, the homonyms.
* ``store``    the writes: loads as versions, diffs, retirements, decisions; the official names and the old alias tables.

Nothing here is read by the reader yet (it reaches it only through the profiles of AD-H07, under ``FBI_PROFILES``), nothing
changes a model, a probability or a pick, and nothing external ever overwrites the provider's data.
"""
