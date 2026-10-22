"""The data truth audit V2: provider vs PrediGol vs official sources, with an evidence ledger.

Modules: ``ledger`` (E-XXX entries), ``runner`` (provider requests stored as NEW raw payloads,
one ``audit.truth_v2_runs`` row per command), ``standings``,
``leagues``, ``identity``, ``fields``. (``players`` and ``team_stats`` live in ``fbi.api.audits``: they read the
product's own code.) Nothing here writes ``core``, ``market`` or ``features``.
"""
