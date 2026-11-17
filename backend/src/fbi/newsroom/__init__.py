"""The owner's desk of the news (IA-102, plan piece AD-G05): the private queue of moderation and the register of withdrawals.

A package of its own, with nothing of ``fbi.ai``: the API's admin router reads and writes it (``fbi.api.routers.news_moderation``) without
importing the news pipeline - which reads the source policy of ``fbi.ai`` - so the import graph does not grow a loop
(``tests/unit/test_architecture.py``). The pipeline (``fbi.news.pipeline``) sends stories to the queue through it."""
