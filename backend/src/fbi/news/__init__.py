"""The news store (IA-080, plan piece AD-G01): feeds, articles (``news.items``), stories, the story of each article and who it names
(``news.item_entities``) - migration 0146, every table append-only.

* ``fbi.news.canonical`` - the canonical URL and the fingerprint the store deduplicates on (``canon-v1``, ``fp-v1``).
* ``fbi.news.store``     - the writes: idempotent, deduplicated, with the source policy of IA-063 applied and copied into each item.
* ``fbi.news.readers``   - the reads C-06 (AD-G07) will be served from, with the public side filtered.
* ``fbi.news.vocab``     - the words, the same as the CHECKs of the migration.

In shadow (IA-099 to IA-102, ``fbi.news.pipeline``, behind ``FBI_NEWS_STORIES`` and ``FBI_NEWS_TEXT``, both off): ``entities`` (who a title
names), ``grouping`` (duplicates and stories, ``stories-v1``), ``classify`` (category, language, country, level), ``writer`` with
``anticopy`` and ``health`` (PrediGol's own text and its verifiers), ``evidence_reads`` (its only reads of ``ai.evidence``); the moderation
is ``fbi.newsroom``. The owner's guide: ``backend/docs/owner/IA_099_NOTICIAS_EN_SOMBRA.md``.

The claims of an article stay in ``ai.evidence`` (``item_id``, written when the claim is inserted). Nothing fills the store in
production yet: the ingestion of AD-G02 will, in shadow. The owner's guide: ``backend/docs/owner/IA_080_ESQUEMA_NOTICIAS.md``."""
