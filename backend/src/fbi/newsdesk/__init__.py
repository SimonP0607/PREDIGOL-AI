"""The news as contract C-06 serves it (IA-120 / IA-121, plan pieces AD-G06 and AD-G07): reads of the news store and the front page's order.

* ``reads`` - the stories of ``news.stories`` (their newest version), their articles (``news.items`` through ``news.item_story``) and who
  they name (``news.item_entities``, with PrediGol's names), with filters and PostgreSQL's full-text search. What of an article may be
  shown is decided by the caller's ``publish`` (the stricter of the copy written when it was seen and the source policy in force: the API
  hands it in from ``fbi.ai.source_policy``).
* ``front`` - the order of the front page (``front-v1``, pure): the lead, «Última hora» (only stories with a structured publication date),
  «Tus equipos» (the reader's favourite teams and players) and the featured ones by level and the nearness of a match.

Read only: nothing here writes, searches the web or calls a model. It imports nothing of ``fbi.ai`` or ``fbi.news`` (the API reads it,
and the import cycle of ``tests/unit/test_architecture.py`` must not grow); its SQL is its own and reads the same tables
``fbi.news.readers`` does, with the same rule of the newest row."""
