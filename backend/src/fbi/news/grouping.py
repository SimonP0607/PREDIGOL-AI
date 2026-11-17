"""Duplicates and stories (IA-099, plan piece AD-G02): which articles of ``news.items`` tell the same fact. ``stories-v1``. Pure: nothing
is read or written here - ``fbi.news.pipeline`` reads the items, hands them over and writes what this module decides.

WHAT AN ITEM IS HERE (``ItemSignal``): what the store already has of an article - its identity (the sha256 of its canonical URL), the
fingerprint of what was read (``content_sha256``), its domain, its dates, its language, the title the outlet gave it (PRIVATE metadata: read
here to compare, never shown and never sent to a model), the type of claim, and the teams and players it names (``news.item_entities``).
There is no text of the article: the grouping works without one.

THE LADDER OF DUPLICATES, from the surest (``GROUP_METHODS`` of migration 0146), for each new item in the order it was seen:

1. ``url`` - the same canonical URL already in a story (a new version of the same article: AMP, mobile, tracking parameters and a final
   slash are already the same URL, ``canon-v1``). Exact.
2. ``huella`` - the same fingerprint (``fp-v1``) as an item of an open story: the same title reprinted by another outlet (a wire copy).
   Exact.
3. ``similitud`` - a near duplicate: the words of the two titles (folded in any script, without the words every title has and without
   numbers alone) overlap by ``NEAR_TITLE`` or more (Jaccard), or by ``NEAR_BITS_WITH`` and their simhashes differ by ``NEAR_BITS`` bits or
   fewer, within ``WINDOW``. Two titles of the SAME outlet need ``SAME_OUTLET`` (its templates share most of their words).
4. ``entidades`` - the same fact told another way: the same specific type of claim (an injury, a transfer, a suspension ...; never
   ``contexto``/``analisis``), within ``WINDOW``, and the same player, or the same team and titles that still share ``ENTITY_OVERLAP`` of
   their other words.
5. ``idiomas`` - the same fact in another language: different languages, the same specific type of claim, the same player or the same
   pair of teams, and dates no further apart than ``ACROSS_LANGUAGES``.
6. otherwise a NEW story, whose key is derived from the first item (``store.story_key_for``): the same item always seeds the same key.

Never in one story (``conflict``): two items that both name teams and none in common, or whose titles both read «A vs B» with pairs that
do not match - different matches or clubs, however alike their titles (a site's templates). And a fingerprint of a title with fewer than ``MIN_TOKENS`` words says nothing (a title in Chinese folds,
under ``fp-v1``, to its digits).

A story is OPEN while its newest item is younger than ``WINDOW`` (72 h, the upper end of the 48-72 h of the plan's file). Matching is to any
member of an open story (single link); an item is never moved by this module once it is in a story (moving one is a person's decision,
``manual``) - so a pass is INCREMENTAL: it groups only what is new, against the stories still open.

The thresholds were written before any measurement (17-nov-2026). The first replay over production's 14 days of web evidence (2.095
articles) and a hand review of 15 of its stories found 4 false merges (a site's templates, titles in Chinese): the folding of any script,
the numbers left out, ``conflict``, ``NEAR_BITS_WITH`` and the guard of the fingerprint come from that review; a second replay and review
of 20 stories found the templates of one outlet with other teams (``SAME_OUTLET`` and the pairs of ``versus`` come from it); a third,
of 20 more, two outlets' subdomains, a women's match and titles «AvsB» without spaces (``outlet``, ``MARKERS``, ``_TIGHT_VS``) - in this same version, before
anything is deployed. A change after deployment is a new version (``stories-v2``)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from fbi.core.fingerprint import folded

VERSION: Final = "stories-v1"
WINDOW: Final = timedelta(hours=72)
ACROSS_LANGUAGES: Final = timedelta(hours=36)
NEAR_TITLE: Final = 0.6
"""Jaccard of the words of two titles from which they are the same article reworded (a near duplicate)."""
NEAR_BITS: Final = 3
"""Hamming distance of two title simhashes under which two titles are the same (titles are short: stricter than the 6 bits of pages) -
and only when their words already overlap by ``NEAR_BITS_WITH`` (a simhash of eight words is noisy on its own)."""
NEAR_BITS_WITH: Final = 0.4
SAME_OUTLET: Final = 0.85
"""Two titles of the SAME outlet are a near duplicate only when they share this much: below it they are its templates («X v Y preview»)."""
ENTITY_OVERLAP: Final = 0.5
"""With only a team in common, the share of their OTHER words two titles must still share to be the same fact."""
MIN_TOKENS: Final = 3
"""A title with fewer distinctive words is not compared by its words (too little to tell two facts apart)."""

GENERIC_TYPES: Final = frozenset({"contexto", "analisis", "estadisticas", "rumores"})
"""Types of claim too broad to say that two items are the same fact by their entities alone."""

STOPWORDS: Final = frozenset(["a", "al", "ante", "bajo", "con", "contra", "de", "del", "desde", "durante", "e", "el", "en", "entre", "esta", "este", "esto", "hacia", "hasta", "la", "las", "lo", "los", "mas", "para", "pero", "por", "que", "se", "sin", "sobre", "su", "sus", "un", "una", "unos", "unas", "y", "o", "u", "ya", "le", "les", "fue", "ser", "es", "son", "era", "han", "ha", "hay", "como", "cuando", "donde", "muy", "tras", "tambien", "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "from", "by", "with", "as", "is", "are", "was", "were", "be", "been", "has", "have", "had", "it", "its", "this", "that", "these", "those", "into", "after", "before", "over", "under", "vs", "v", "his", "her", "their", "they", "he", "she", "we", "you", "not", "no", "new", "o", "os", "as", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "um", "uma", "para", "com", "por", "que", "e", "sem", "le", "la", "les", "des", "du", "de", "un", "une", "et", "en", "au", "aux", "pour", "par", "sur", "avec", "dans", "est", "il", "lo", "gli", "i", "di", "da", "del", "della", "dei", "per", "con", "su", "non", "che", "e", "der", "die", "das", "den", "dem", "des", "ein", "eine", "und", "mit", "von", "zu", "im", "am", "ist", "fur", "auf"])
"""Words every title has, in the six languages of the directory: they say nothing of which fact it is."""

_TOKEN: Final = re.compile(r"[0-9a-z]+")
_WORDS: Final = re.compile(r"[^\W_]+")
_IDEOGRAPH: Final = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _fold_any(text: str) -> str:
    """Lower case without accents, KEEPING the letters of every script (``fp-v1``'s folding keeps only a-z and digits: a title in Chinese
    or Arabic would fold to its digits alone)."""
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text or "").casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokens(title: str | None) -> frozenset[str]:
    """The distinctive words of a title: folded (no accents, lower case, any script), without the common words, without numbers alone (a
    date, a year, a round: every template has them), at least two characters - and each Chinese, Japanese or Korean character on its own
    (those scripts write no spaces)."""
    out: set[str] = set()
    for w in _WORDS.findall(_fold_any(title or "")):
        if _IDEOGRAPH.search(w):
            out.update(ch for ch in w if _IDEOGRAPH.match(ch))
            rest = _IDEOGRAPH.sub(" ", w).split()
        else:
            rest = [w]
        out.update(x for x in rest if len(x) >= 2 and not x.isdigit() and x not in STOPWORDS)
    return frozenset(out)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def simhash(title: str | None) -> int | None:
    """A 64-bit simhash of the distinctive words of a title, as a SIGNED integer (the column ``news.items.simhash`` is a BIGINT), or None
    for a title with fewer than ``MIN_TOKENS`` words."""
    words = sorted(tokens(title))
    if len(words) < MIN_TOKENS:
        return None
    acc = [0] * 64
    for w in words:
        h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            acc[bit] += 1 if h >> bit & 1 else -1
    value = sum(1 << bit for bit in range(64) if acc[bit] > 0)
    return value - (1 << 64) if value >= 1 << 63 else value


def bits_apart(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << 64) - 1)).bit_count()


# ── the type of claim of a title (when no claim of the item says it) ────────────────────────────────────────────────────

_TYPE_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple((t, re.compile(p)) for t, p in (
    ("sanciones", r"\b(?:sancion\w*|suspendid\w*|suspension\w*|suspended|banned|ban|expulsad\w*|expulsion|tarjeta roja|red card|"
                  r"sancao|suspenso|squalific\w*|gesperrt|sperre)\b"),
    ("lesiones", r"\b(?:lesion\w*|lesionad\w*|injur\w*|baja\w*|ruled out|out for|se pierde|molestia\w*|duda para|doubtful|"
                 r"lesao|lesionado|blessure|blesse|infortun\w*|verletz\w*|fitness|recupera\w*|knock|parte medico)\b"),
    ("convocatorias", r"\b(?:convoca\w*|called up|call up|squad list|nomina|lista de|selecionad\w*|convocati|aufgebot)\b"),
    ("alineaciones", r"\b(?:alineacion\w*|once titular|line ?up|lineups|starting xi|titulares|escalacao|formazione|aufstellung)\b"),
    ("fichajes", r"\b(?:fichaj\w*|ficha\w*|refuerzo\w*|traspaso\w*|transfer\w*|sign\w*|contrat\w*|renuev\w*|renova\w*|cedid\w*|"
                 r"prestamo|loan\w*|mercato|calciomercato|wechsel|neuzugang)\b"),
    ("arbitraje", r"\b(?:arbitr\w*|referee\w*|var|juez|designacion)\b"),
    ("reglamento", r"\b(?:reglamento|regulation\w*|formato|format|norma\w*)\b"),
    ("declaraciones", r"\b(?:dijo|declar\w*|rueda de prensa|entrevista|said|says|press conference|interview|afirmo|aseguro|"
                      r"habla|hablo|disse|afirmou|ha detto|a declare|sagte)\b"),
    ("resultados", r"\b(?:vence\w*|venci\w*|gana\w*|gano|empat\w*|derrot\w*|gole\w*|beat\w*|win\w*|won|draw\w*|defeat\w*|victoria|"
                   r"resultado\w*|result\w*|\d+ \d+)\b"),
    ("calendario", r"\b(?:horario\w*|programacion|schedule\w*|kick off|calendario|fecha \d+|jornada|matchday|fixture\w*)\b"),
    ("rumores", r"\b(?:rumor\w*|rumour\w*|se especula|interesa|suena|podria|could|linked|target\w*|reportedly)\b"),
))
"""The first rule whose words a folded title has decides; none, ``contexto``. A title written as a rumour about a transfer is a transfer
(its level, AD-G03, says it is a rumour)."""


def claim_type_of_title(title: str | None) -> str:
    text = " ".join(_TOKEN.findall(folded(title or "")))
    for kind, pattern in _TYPE_RULES:
        if pattern.search(text):
            return kind
    return "contexto"


# ── items and stories ───────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class ItemSignal:
    item_id: int
    url_sha256: str
    content_sha256: str
    domain: str
    seen_at: datetime
    published_at: datetime | None = None
    title: str | None = None
    lang: str | None = None
    claim_type: str | None = None
    teams: frozenset[int] = frozenset()
    players: frozenset[int] = frozenset()
    simhash: int | None = None

    @property
    def at(self) -> datetime:
        """When the fact was told: the publication date when the item has one (never after it was seen), else when it was seen."""
        return self.published_at if self.published_at is not None and self.published_at <= self.seen_at else self.seen_at

    @property
    def words(self) -> frozenset[str]:
        return tokens(self.title)

    @property
    def kind(self) -> str:
        return self.claim_type or claim_type_of_title(self.title)

    @property
    def hash(self) -> int | None:
        return self.simhash if self.simhash is not None else simhash(self.title)


@dataclass
class OpenStory:
    key: str
    items: list[ItemSignal] = field(default_factory=list)

    @property
    def newest(self) -> datetime:
        return max(i.at for i in self.items)

    @property
    def kind(self) -> str:
        return story_kind(self.items)


def story_kind(items: Iterable[ItemSignal]) -> str:
    """The type of claim of a story: the most frequent specific one of its items (ties: the order of ``_TYPE_RULES``), else ``contexto``."""
    counts = Counter(i.kind for i in items)
    order = [t for t, _ in _TYPE_RULES] + ["contexto"]
    specific = [(n, -order.index(t) if t in order else -99, t) for t, n in counts.items() if t not in GENERIC_TYPES]
    if specific:
        return max(specific)[2]
    return max(((n, -order.index(t) if t in order else -99, t) for t, n in counts.items()), default=(0, 0, "contexto"))[2]


@dataclass(frozen=True, slots=True)
class Assignment:
    item_id: int
    story_key: str
    method: str
    score: float
    new_story: bool
    seed: str
    """The url_sha256 of the item that opened the story (the key is derived from it)."""


@dataclass(frozen=True, slots=True)
class _Feat:
    """What the comparisons read of an item, computed once per pass."""

    words: frozenset[str]
    hash: int | None
    kind: str


def _feat(i: ItemSignal) -> _Feat:
    return _Feat(i.words, i.hash, i.kind)


def _near(a: ItemSignal, fa: _Feat, b: ItemSignal, fb: _Feat) -> float | None:
    if len(fa.words) >= MIN_TOKENS and len(fb.words) >= MIN_TOKENS:
        j = jaccard(fa.words, fb.words)
        if outlet(a.domain) == outlet(b.domain):
            return j if j >= SAME_OUTLET else None  # one outlet's titles that share most words are its templates
        if j >= NEAR_TITLE:
            return j
        if j >= NEAR_BITS_WITH and fa.hash is not None and fb.hash is not None and bits_apart(fa.hash, fb.hash) <= NEAR_BITS:
            return max(j, 1 - bits_apart(fa.hash, fb.hash) / 64)
    return None


def _same_fact(a: ItemSignal, fa: _Feat, b: ItemSignal, fb: _Feat) -> float | None:
    if fa.kind in GENERIC_TYPES or fa.kind != fb.kind:
        return None
    if not (a.lang is None or b.lang is None or a.lang == b.lang):
        return None
    if a.players & b.players:
        return 0.9
    if a.teams & b.teams:
        j = jaccard(fa.words, fb.words)
        if j >= (SAME_OUTLET if outlet(a.domain) == outlet(b.domain) else ENTITY_OVERLAP):
            return round(0.5 + j / 2, 3)
    return None


def _across(a: ItemSignal, fa: _Feat, b: ItemSignal, fb: _Feat) -> float | None:
    if a.lang is None or b.lang is None or a.lang == b.lang:
        return None
    if fa.kind in GENERIC_TYPES or fa.kind != fb.kind or abs(a.at - b.at) > ACROSS_LANGUAGES:
        return None
    if a.players & b.players:
        return 0.8
    if len(a.teams) >= 2 and a.teams == b.teams:
        return 0.7
    return None


TESTS: Final = (("similitud", _near), ("entidades", _same_fact), ("idiomas", _across))


SECOND_LEVEL: Final = frozenset({"co", "com", "net", "org", "gov", "gob", "ac", "edu"})
MARKERS: Final = frozenset({"frauen", "women", "womens", "woman", "femenino", "femenil", "feminino", "femminile", "feminine", "feminin",
                            "ladies", "wsl", "nwsl", "u15", "u16", "u17", "u18", "u19", "u20", "u21", "u23", "sub15", "sub17", "sub20",
                            "sub23", "juvenil", "youth", "reserves", "reserva", "ii"})
"""Words that make a team another team: its women's side, an age group, its reserves. Two titles that differ in them are two matches."""
_VERSUS_WORDS: Final = frozenset({"vs", "v", "versus", "contra"})
_TIGHT_VS: Final = re.compile(r"(?<=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af0-9])vs(?=[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af])")


def outlet(domain: str) -> str:
    """The outlet of a domain: its registered part (``zht.qiumiwu.com`` and ``m.qiumiwu.com`` are one outlet; ``bbc.co.uk`` keeps three)."""
    labels = (domain or "").lower().split(".")
    if len(labels) >= 3 and labels[-2] in SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def markers(title: str | None) -> frozenset[str]:
    return frozenset(w for w in _WORDS.findall(_fold_any(title or "")) if w in MARKERS)
_SEGMENT: Final = re.compile(r"[|:\u2013\u2014()\[\]]| - ")


def _side(words: Sequence[str]) -> frozenset[str]:
    return frozenset(x for x in words if not x.isdigit() and x not in STOPWORDS)


def versus(title: str | None) -> tuple[frozenset[str], frozenset[str]] | None:
    """The two sides of a title written «A vs B» (``vs``, ``v``, ``versus``, ``contra``): the word next to it on each side (the last word
    of the first team, the first of the second - the words further away are the template's: «preview», «prediction»), or None."""
    for segment in _SEGMENT.split(_TIGHT_VS.sub(" vs ", _fold_any(title or ""))):
        words = _WORDS.findall(segment)
        for i, w in enumerate(words):
            if w in _VERSUS_WORDS and 0 < i < len(words) - 1:
                left, right = _side(words[max(0, i - 1):i]), _side(words[i + 1:i + 2])
                if left and right:
                    return left, right
    return None


def conflict(a: ItemSignal, b: ItemSignal) -> bool:
    """Two items about different matches or clubs: never the same story, however alike their titles (a site's templates «X vs Y Preview &
    Prediction»). They both name teams and none in common; or one title names a women's side, an age group or reserves the other does not;
    or both titles read «A vs B» and the two pairs do not match."""
    if a.teams and b.teams and not (a.teams & b.teams):
        return True
    if markers(a.title) != markers(b.title):
        return True
    va, vb = versus(a.title), versus(b.title)
    if va is None or vb is None:
        return False
    straight = bool(va[0] & vb[0]) and bool(va[1] & vb[1])
    crossed = bool(va[0] & vb[1]) and bool(va[1] & vb[0])
    return not (straight or crossed)


def _fingerprint_usable(f: _Feat, item: ItemSignal) -> bool:
    """A fingerprint of a title says «the same text» only when the title has words enough (a title of digits and symbols folds to almost
    nothing - ``fp-v1`` keeps a-z and digits only, so a title in Chinese folds to its date: two different ones then share a fingerprint)."""
    if item.title is None:
        return True
    kept = [w for w in folded(item.title).split() if not w.isdigit() and w not in STOPWORDS and len(w) >= 2]
    return len(kept) >= MIN_TOKENS


def group(new: Sequence[ItemSignal], stories: Sequence[OpenStory], *, story_key: object = None) -> list[Assignment]:
    """Where each new item goes (see the module): a list of assignments in the order the items were seen. ``stories`` are the open
    stories with their members (they are extended in place as items join them); ``story_key`` makes the key of a new story from the url_sha256
    of its first item (``fbi.news.store.story_key_for`` by default).

    Only the stories that share a word of the title, a team or a player with an item are compared with it (an index per pass), so a pass
    is about linear in the number of items, not quadratic."""
    if story_key is None:
        from fbi.news.store import story_key_for as make_key
    else:
        make_key = story_key  # type: ignore[assignment]
    live = list(stories)
    feats: dict[int, _Feat] = {}

    def feat(i: ItemSignal) -> _Feat:
        f = feats.get(id(i))
        if f is None:
            f = feats[id(i)] = _feat(i)
        return f

    newest: dict[int, datetime] = {}
    by_url: dict[str, OpenStory] = {}
    by_content: dict[str, OpenStory] = {}
    index: dict[tuple[str, object], set[int]] = {}

    def enter(n: int, i: ItemSignal) -> None:
        s = live[n]
        newest[n] = max(newest.get(n, i.at), i.at)
        by_url.setdefault(i.url_sha256, s)
        by_content.setdefault(i.content_sha256, s)
        for w in feat(i).words:
            index.setdefault(("w", w), set()).add(n)
        for t in i.teams:
            index.setdefault(("t", t), set()).add(n)
        for p in i.players:
            index.setdefault(("p", p), set()).add(n)

    position = {id(s): n for n, s in enumerate(live)}
    for n, s in enumerate(live):
        for i in s.items:
            enter(n, i)
    out: list[Assignment] = []
    for item in sorted(new, key=lambda i: (i.at, i.seen_at, i.item_id)):
        fi = feat(item)
        chosen: tuple[OpenStory, str, float] | None = None
        if item.url_sha256 in by_url:
            chosen = (by_url[item.url_sha256], "url", 1.0)
        elif (item.content_sha256 in by_content and _fingerprint_usable(fi, item)
              and item.at - newest[position[id(by_content[item.content_sha256])]] <= WINDOW
              and not any(conflict(item, m) for m in by_content[item.content_sha256].items)):
            chosen = (by_content[item.content_sha256], "huella", 1.0)
        else:
            keys = [("w", w) for w in fi.words] + [("t", t) for t in item.teams] + [("p", p) for p in item.players]
            candidates = sorted({n for k in keys for n in index.get(k, ())})
            for method, test in TESTS:
                best: tuple[float, int] | None = None
                for n in candidates:
                    if item.at - newest[n] > WINDOW:
                        continue
                    if any(conflict(item, m) for m in live[n].items):
                        continue
                    for m in live[n].items:
                        if abs(item.at - m.at) > WINDOW:
                            continue
                        score = test(item, fi, m, feat(m))
                        if score is not None and (best is None or score > best[0]):
                            best = (score, n)
                if best is not None:
                    chosen = (live[best[1]], method, best[0])
                    break
        if chosen is None:
            story = OpenStory(str(make_key(item.url_sha256)))
            position[id(story)] = len(live)
            live.append(story)
            story.items.append(item)
            out.append(Assignment(item.item_id, story.key, "url", 1.0, True, item.url_sha256))
        else:
            story, method, score = chosen
            story.items.append(item)
            seed = min(story.items, key=lambda i: (i.at, i.item_id)).url_sha256
            out.append(Assignment(item.item_id, story.key, method, round(min(max(score, 0.0), 1.0), 3), False, seed))
        enter(position[id(story)], item)
    return out


@dataclass
class Measure:
    """What a replay says of a set of items: how many were exact duplicates, near ones, how many stories and of what size."""

    items: int = 0
    by_method: Counter[str] = field(default_factory=Counter)
    stories: int = 0
    multi_item: int = 0
    multi_domain: int = 0
    largest: int = 0
    sizes: Counter[int] = field(default_factory=Counter)

    def as_json(self) -> dict[str, object]:
        dup_exact = self.by_method["url_dup"] + self.by_method["huella"]
        return {"version": VERSION, "items": self.items, "stories": self.stories, "by_method": dict(sorted(self.by_method.items())),
                "exact_duplicates": dup_exact, "exact_duplicate_rate": round(dup_exact / self.items, 4) if self.items else None,
                "near_duplicates": self.by_method["similitud"],
                "grouped_rate": round(1 - self.stories / self.items, 4) if self.items else None,
                "stories_with_2plus_items": self.multi_item, "stories_with_2plus_domains": self.multi_domain, "largest": self.largest,
                "sizes": {str(k): v for k, v in sorted(self.sizes.items())}}


def measure(items: Sequence[ItemSignal]) -> Measure:
    """Group a whole set from scratch (a replay) and count: an item whose canonical URL was already seen is ``url_dup``."""
    m = Measure(items=len(items))
    keys = {i.url_sha256: f"st-{i.url_sha256[:24]}" for i in items}
    found = group(items, [], story_key=lambda seed: keys[str(seed)])
    members: dict[str, list[ItemSignal]] = {}
    index = {i.item_id: i for i in items}
    for a in found:
        members.setdefault(a.story_key, []).append(index[a.item_id])
        m.by_method["new_story" if a.new_story else ("url_dup" if a.method == "url" else a.method)] += 1
    m.stories = len(members)
    for group_items in members.values():
        m.sizes[min(len(group_items), 10)] += 1
        m.largest = max(m.largest, len(group_items))
        m.multi_item += int(len(group_items) >= 2)
        m.multi_domain += int(len({i.domain for i in group_items}) >= 2)
    return m


__all__ = ["ACROSS_LANGUAGES", "ENTITY_OVERLAP", "MIN_TOKENS", "NEAR_BITS", "NEAR_TITLE", "VERSION", "WINDOW", "Assignment", "ItemSignal",
           "Measure", "OpenStory", "bits_apart", "claim_type_of_title", "group", "jaccard", "measure", "simhash", "story_kind", "tokens"]
