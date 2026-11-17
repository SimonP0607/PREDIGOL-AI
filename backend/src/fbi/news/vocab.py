"""The words of the news store (IA-080, AD-G01), one place: migration 0146 writes the same lists as CHECKs, and
``tests/unit/test_news_vocab.py`` holds the two together."""

from __future__ import annotations

from typing import Final, Literal

from fbi.ai import source_registry as registry

FeedKind = Literal["rss", "atom", "sitemap", "news_sitemap"]
FoundVia = Literal["rss", "sitemap", "search", "official", "manual"]
StoreLevel = Literal["facts", "link"]
PublishLevel = Literal["summary", "link", "none"]
Category = Literal["fichajes", "bajas_y_sanciones", "declaraciones", "resultados_y_proximos", "selecciones", "colombia",
                   "internacional", "competiciones"]
Level = Literal["oficial", "dos_origenes", "declaracion", "un_medio", "rumor"]
Status = Literal["activa", "en_moderacion", "retirada"]
GroupMethod = Literal["url", "huella", "similitud", "entidades", "idiomas", "manual"]
EntityType = Literal["team", "player", "coach", "referee", "competition", "fixture", "venue"]
Role = Literal["protagonista", "mencionado"]
LinkMethod = Literal["plantilla", "alias", "proveedor", "manual"]
Decider = Literal["system", "owner"]

FEED_KINDS: Final = ("rss", "atom", "sitemap", "news_sitemap")
FOUND_VIA: Final = ("rss", "sitemap", "search", "official", "manual")
SOURCE_STATES: Final = (*registry.STATES, "desconocida", "excluida")
"""The five states of the directory v2 and the two the policy gives a host it does not list (``fbi.ai.source_policy``)."""
STORE_LEVELS: Final = ("facts", "link")
"""What of a source may be kept (``source_policy.can_store``) - without ``none``: a source that may keep nothing is never stored."""
PUBLISH_LEVELS: Final = ("summary", "link", "none")
CATEGORIES: Final = ("fichajes", "bajas_y_sanciones", "declaraciones", "resultados_y_proximos", "selecciones", "colombia",
                     "internacional", "competiciones")
"""The front page's categories (AD-G03)."""
LEVELS: Final = ("oficial", "dos_origenes", "declaracion", "un_medio", "rumor")
"""The confirmation ladder (AD-C07), from the highest."""
CLAIM_TYPES: Final = registry.CLAIM_TYPES
"""A story's type of claim, in the directory's words (``autoridad_por_afirmacion``)."""
STATUSES: Final = ("activa", "en_moderacion", "retirada")
GROUP_METHODS: Final = ("url", "huella", "similitud", "entidades", "idiomas", "manual")
ENTITY_TYPES: Final = ("team", "player", "coach", "referee", "competition", "fixture", "venue")
ROLES: Final = ("protagonista", "mencionado")
LINK_METHODS: Final = ("plantilla", "alias", "proveedor", "manual")
DECIDERS: Final = ("system", "owner")

PUBLISH_ORDER: Final = {"none": 0, "link": 1, "summary": 2}
STORE_ORDER: Final = {"none": 0, "link": 1, "facts": 2}
