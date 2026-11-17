"""The anti-copy verifier of PrediGol's own news texts (IA-101, plan piece AD-G04): ``anticopy-v1``. Pure.

Decision 8 of the plan: PrediGol writes its OWN headline and summary and links the source; it never reproduces an article. This module
measures how much of an own text is the words of a source - the outlets' titles of the story's articles, the quotes of the facts it rests
on, and the body of an article when one was read in memory (it is never stored) - and refuses a text above the thresholds.

THE THRESHOLDS, PREREGISTERED on 17-nov-2026 before any text was generated or measured (``THRESHOLDS``; a change is ``anticopy-v2``):

* ``max_run_words`` = 15: no run of more than 15 consecutive words of a source in the text (the owner's rule: «ninguna frase literal > 15
  palabras»);
* ``max_shared_4grams`` = 0.25: at most a quarter of the text's word 4-grams may be found in the sources (a 4-gram made only of names of
  the story - a team, a player, a competition - and common words does not count: a name is not a copy);
* ``max_headline_3grams`` = 0.5 and ``headline_not_title``: the own headline shares at most half of its word 3-grams with any outlet's
  title, and is never one of them (nor contains one) once folded.

Everything is compared on the folded text (``fp-v1``'s folding: no accents, lower case, letters and digits), so a copy with other accents
or punctuation is still a copy."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from fbi.core.fingerprint import folded
from fbi.news.grouping import STOPWORDS

VERSION: Final = "anticopy-v1"
THRESHOLDS: Final = {"max_run_words": 15, "max_shared_4grams": 0.25, "max_headline_3grams": 0.5, "headline_not_title": True}
"""Preregistered 17-nov-2026 (see the module)."""
N: Final = 4


def words(text: str | None) -> list[str]:
    return folded(text or "").split()


def ngrams(toks: Sequence[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]


def longest_run(text: Sequence[str], source: Sequence[str]) -> int:
    """The longest run of consecutive words the text shares with the source (longest common substring, in words)."""
    if not text or not source:
        return 0
    best = 0
    prev = [0] * (len(source) + 1)
    for a in text:
        cur = [0] * (len(source) + 1)
        for j, b in enumerate(source, start=1):
            if a == b:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


@dataclass(frozen=True, slots=True)
class Measured:
    longest_run: int
    shared_4grams: float
    headline_3grams: float
    headline_is_title: bool
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_json(self) -> dict[str, object]:
        return {"version": VERSION, "longest_run": self.longest_run, "shared_4grams": round(self.shared_4grams, 4),
                "headline_3grams": round(self.headline_3grams, 4), "headline_is_title": self.headline_is_title,
                "problems": list(self.problems)}


def _name_words(names: Iterable[str]) -> set[str]:
    return {w for n in names for w in words(n)}


def _only_names(gram: tuple[str, ...], named: set[str]) -> bool:
    """A 4-gram whose every word but the common ones is a word of a name of the story: a name, not a copy."""
    content = [w for w in gram if w not in STOPWORDS]
    return not content or set(content) <= named


def measure(*, headline: str, body: str, titles: Sequence[str], sources: Sequence[str], names: Iterable[str] = ()) -> Measured:
    """The text against its sources. ``titles``: the outlets' titles of the story; ``sources``: every other text of a third party it rests
    on (quotes, a body read in memory); ``names``: the story's teams, players and competition (a 4-gram of names only is not a copy)."""
    named = _name_words(names)
    src_words = [words(s) for s in (*titles, *sources) if s]
    own = words(f"{headline} . {body}")
    run = max((longest_run(own, s) for s in src_words), default=0)
    pool = {g for s in src_words for g in ngrams(s, N)}
    grams = [g for g in ngrams(own, N) if not _only_names(g, named)]
    shared = sum(1 for g in grams if g in pool) / len(grams) if grams else 0.0
    head = words(headline)
    head3 = ngrams(head, 3)
    best3 = 0.0
    is_title = False
    folded_head = " ".join(head)
    for t in titles:
        tw = words(t)
        t3 = set(ngrams(tw, 3))
        if head3:
            best3 = max(best3, sum(1 for g in head3 if g in t3) / len(head3))
        joined = " ".join(tw)
        if joined and (joined == folded_head or (len(tw) >= 4 and joined in folded_head) or (len(head) >= 4 and folded_head in joined)):
            is_title = True
    problems = []
    if run > int(THRESHOLDS["max_run_words"]):
        problems.append("copy_long_run")
    if shared > float(THRESHOLDS["max_shared_4grams"]):
        problems.append("copy_shared_ngrams")
    if best3 > float(THRESHOLDS["max_headline_3grams"]):
        problems.append("copy_headline")
    if is_title and THRESHOLDS["headline_not_title"]:
        problems.append("headline_is_a_title")
    return Measured(run, shared, best3, is_title, tuple(dict.fromkeys(problems)))


__all__ = ["THRESHOLDS", "VERSION", "Measured", "N", "longest_run", "measure", "ngrams", "words"]
