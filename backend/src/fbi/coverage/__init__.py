"""Coverage matrix of the plan PM (block 2): how complete each datum and each market is, per competition season, phase and datum.

``levels`` holds the rules ``coverage-levels-v1`` (PM-02-01, decision DM-04) as pure functions; ``job`` measures and grades the matrix
every night into ``analytics.coverage_*`` (PM-02-03, ``FBI_AVAILABILITY_REFRESH``), in a process of its own
(``scripts.availability_refresh``). The resolver of a match and the routes of C-16 come with the tasks after it, behind
``FBI_AVAILABILITY``.
"""
