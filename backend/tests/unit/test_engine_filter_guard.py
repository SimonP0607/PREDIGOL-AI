"""Nobody counts the shadow of phase 3 by accident (plan IA, phase 3, A4). Migration 0119 lets ``ai.pick_reviews`` carry the engines ``ma-v1``,
``ma-v1-h`` and ``cs-v1`` beside the ``rules``, ``llm`` and ``combined`` of production. Every figure, every cost, every gate and every study that read
the table before the shadow existed must read the same after it: a row of the shadow is a row of an experiment, not a review a user, a gate or a
memory can learn from. This test reads the code, not the data (``tests/integration/test_shadow_engines_readers.py`` is the behaviour):

* every statement that reads ``ai.pick_reviews`` - every ``FROM`` and every ``JOIN`` of it, subqueries included - either names its engines and they
  are the engines of production (``fbi.ai.config.PRODUCTION_ENGINES``), or names only engines of the shadow (a reader of the shadow's own), or is a
  lookup BY ID of a review something else already pointed at, or is one of the few readers whose engine is the caller's word, listed below with its
  reason;
* the readers changed in this phase keep the filter on the whole list, and the decision layer (filter 6) reads ``combined`` and ``rules`` and no
  other engine - there is no shadow engine named in its module at all;
* the lists of engines of the code (the ``Literal`` of a review, the engines a report is made for, the ones the owner can name, the migration) are
  one list.

A new reader of the table that forgets the filter fails here, with the file and the statement."""

from __future__ import annotations

import ast
import functools
import re
import typing
from dataclasses import dataclass
from pathlib import Path

import pytest

from fbi.ai import review, shadow
from fbi.ai.config import BASELINE_ENGINES, KNOWN_ENGINES, PRODUCTION_ENGINES, SHADOW_ENGINES

BACKEND = Path(__file__).resolve().parents[2]
SOURCES = sorted([*(BACKEND / "src" / "fbi").rglob("*.py"), *(BACKEND / "scripts").glob("*.py")])

PRODUCTION = frozenset(PRODUCTION_ENGINES)
SHADOW = frozenset(SHADOW_ENGINES)

READS = re.compile(
    r"\b(?:FROM|JOIN)\s+ai\.pick_reviews\b(?:\s+(?:AS\s+)?(?P<alias>(?!(?:WHERE|JOIN|ON|GROUP|ORDER|LEFT|RIGHT|INNER|CROSS|FULL|LIMIT|UNION|USING"
    r"|AS|SET|HAVING|WINDOW)\b)[a-z_]\w*))?", re.IGNORECASE)
"""A statement reads the table when it names it after FROM or JOIN (a write says INSERT INTO / UPDATE), and the alias it gives the table, if any."""
FILTER = re.compile(
    r"(?:\b(?P<q>[a-z_]\w*)\.)?\bengine\b\s*(?:(?P<op>=|<>|!=)\s*(?P<one>'[^']*'|%s|%\(\w+\)s)|(?P<neg>NOT\s+)?IN\s*\((?P<many>[^)]*)\))",
    re.IGNORECASE)
"""A condition on the ``engine`` column: ``engine = 'x'``, ``engine IN ('x', 'y')``, their negations, and ``engine = %s`` / ``%(name)s`` (the caller's word)."""
BY_ID = re.compile(r"\bid\s*=\s*(?:ANY\s*\(|%\()|\.id\s*=\s*\w+\.review_id\b|\breview_id\s*=\s*\w+\.id\b", re.IGNORECASE)
"""A lookup of a review something else already named: ``id = ANY(%(ids)s)``, ``id = %(id)s``, ``JOIN ai.pick_reviews r ON r.id = d.review_id``."""

CALLERS_WORD = (
    ("src/fbi/ai/review.py", "AND line = %s AND engine = %s AND engine_version = %s",
     "the cache of ONE engine's review of ONE input (``_stored``): the engine is the one that is reviewing - a shadow engine finds its own answer, "
     "production never asks for it"),
    ("src/fbi/ai/review.py", "AND line = %s AND engine = %s ORDER BY reviewed_at DESC",
     "the newest review of ONE engine of ONE selection (``NEWEST_REVIEW_SQL``): the engine is the caller's own, as it is when the review is stored"),
    ("src/fbi/ai/shadow.py", "WHERE r.engine = %(engine)s AND r.reviewed_at < f.kickoff_at",
     "the settled selections of the engine being evaluated: ``shadow.ENGINES`` is the list of the engines a report is made for, the shadow's three included"),
    ("src/fbi/api/services/ai_layer.py", "AND r.engine = %(engine)s",
     "the console's listing of ONE engine, chosen by the router's ``Engine`` literal: a listing of reviews for the owner, which counts nothing"),
)
"""The readers whose engine is a parameter. Each says whose word it is: none of them counts a figure of production over the table."""

COUNTED_BY_ENGINE = (
    ("src/fbi/ai/cycle.py", "FROM ai.pick_reviews r WHERE r.reviewed_at >= %(day)s",
     "the day's allowance of model reviews (``USED_TODAY_SQL``): every figure of the statement is a count FILTERed to ``engine = 'llm'``, so a row of "
     "another engine is in none of them"),
)
"""The readers that put the engine in each of their counts (``count(*) FILTER (WHERE engine = 'llm' ...)``) and not in the ``WHERE``: the figures do not
move for a row of another engine. Each count of the statement must carry the condition (``counts_by_engine``)."""

CHANGED = (
    ("src/fbi/ai/gate_a.py", "bool_or(engine = 'llm') AS llm", PRODUCTION),
    ("src/fbi/ai/costs.py", "count(DISTINCT fixture_id) AS fixtures_reviewed", PRODUCTION),
    ("src/fbi/ai/gate_research.py", "SELECT (SELECT count(*) FROM ai.pick_reviews r", PRODUCTION),
    ("src/fbi/ai/postmortem.py", "SELECT DISTINCT f.id, f.kickoff_at", PRODUCTION),
    ("src/fbi/intel/match_review.py", "EXISTS (SELECT 1 FROM ai.pick_reviews pr", PRODUCTION),
    ("src/fbi/intel/decision.py", "SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line, r.engine)", frozenset({"combined", "rules"})),
)
"""The readers this phase changed (or pinned): a fragment of the statement and the engines it names. ``intel.decision`` is filter 6's."""


@dataclass(frozen=True)
class Read:
    alias: str | None
    text: str


class Strings(ast.NodeVisitor):
    """Every string of a module that could be SQL, once each: a constant, an f-string as one text (its constant parts together), a sum of strings as one
    text. A string that is a statement by itself is a docstring: not SQL."""

    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []

    @staticmethod
    def text_of(node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else "{}" for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = Strings.text_of(node.left), Strings.text_of(node.right)
            return None if left is None or right is None else left + right
        return None

    def visit_Expr(self, node: ast.Expr) -> None:
        if self.text_of(node.value) is None:
            self.generic_visit(node)

    def _take(self, node: ast.AST) -> bool:
        text = self.text_of(node)
        if text is not None:
            self.found.append((node.lineno, text))  # type: ignore[attr-defined]
        return text is not None

    def visit_Constant(self, node: ast.Constant) -> None:
        self._take(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if not self._take(node):
            self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self._take(node)
        for part in node.values:  # the expressions inside the braces can hold strings of their own
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)


def strings(path: Path) -> list[tuple[int, str]]:
    visitor = Strings()
    visitor.visit(ast.parse(path.read_text()))
    return visitor.found


SUBQUERY = re.compile(r"\(\s*(?:SELECT|WITH)\b", re.IGNORECASE)
UNION = re.compile(r"\bUNION\b", re.IGNORECASE)


def reads(text: str) -> list[Read]:
    """The part of a statement that belongs to each read of the table: from its ``FROM``/``JOIN`` to the end of the SELECT it is in - the parenthesis
    that closes it, a ``UNION``, or the end of the text - with the subqueries inside that SELECT left out. A condition of the same SELECT (its ``WHERE``
    comes after every table it joins) is the read's; the ``engine`` of another table further on, in a sibling subquery, is not."""
    blind = re.sub(r"'[^']*'", lambda m: " " * len(m.group(0)), text)  # a parenthesis inside a quoted string is not one
    unions = {m.start() for m in UNION.finditer(blind)}
    out: list[Read] = []
    for m in READS.finditer(text):
        kept: list[str] = []
        depth, i = 0, m.start()
        while i < len(text):
            c = blind[i]
            if c == "(" and SUBQUERY.match(blind, i):
                close, level = i, 0
                for j in range(i, len(blind)):
                    level += (blind[j] == "(") - (blind[j] == ")")
                    if level == 0:
                        close = j
                        break
                else:
                    close = len(blind) - 1
                kept.append(" " * (close + 1 - i))
                i = close + 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                if depth == 0:
                    break
                depth -= 1
            elif i in unions and depth == 0:
                break
            kept.append(text[i])
            i += 1
        alias = m.group("alias")
        out.append(Read(None if alias is None else alias.lower(), "".join(kept)))
    return out


def named(read: Read) -> tuple[set[str], str | None]:
    """The engines a read names in its conditions, and what is wrong with them if something is: ``negated`` (``NOT IN``, ``<>``: the next shadow engine
    would pass), or ``parametrised`` (the caller's word)."""
    names: set[str] = set()
    flaw: str | None = None
    for m in FILTER.finditer(read.text):
        if m.group("q") is not None and m.group("q").lower() != read.alias:
            continue  # the condition is on another table
        if m.group("neg") or m.group("op") in ("<>", "!="):
            flaw = "negated"
        elif m.group("many") is not None:
            names.update(re.findall(r"'([^']*)'", m.group("many")))
        elif m.group("one").startswith("'"):
            names.add(m.group("one").strip("'"))
        elif flaw is None:
            flaw = "parametrised"
    return names, flaw


def kind_of(read: Read) -> str:
    """production | shadow | by id | parametrised | negated | mixed | bare."""
    names, flaw = named(read)
    if flaw is not None:
        return flaw
    if not names:
        return "by id" if BY_ID.search(read.text) else "bare"
    if names <= PRODUCTION:
        return "production"
    if names <= SHADOW:
        return "shadow"
    return "mixed"


def squashed(text: str) -> str:
    return " ".join(text.split())


def counts_by_engine(text: str) -> bool:
    """Every aggregate of the statement is ``FILTER (WHERE <engine> = '<an engine of production>' ...)``: no figure of it counts another engine."""
    flat = squashed(text)
    aggregates = re.findall(r"\b(?:count|sum|avg|min|max|bool_or|bool_and|array_agg)\(", flat, re.IGNORECASE)
    one_of_production = "|".join(PRODUCTION_ENGINES)
    filtered = re.findall(rf"\b(?:count|sum|avg|min|max)\([^()]*\)\s+FILTER\s*\(\s*WHERE\s+(?:\w+\.)?engine\s*=\s*'(?:{one_of_production})'",
                          flat, re.IGNORECASE)
    return bool(aggregates) and len(aggregates) == len(filtered)


@functools.cache
def statements() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in SOURCES:
        for line, text in strings(path):
            if READS.search(text):
                found.append((str(path.relative_to(BACKEND)), line, text))
    return found


# ── the guard itself: it must see what it is meant to see ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("sql", "kind"), [
    ("SELECT count(*) FROM ai.pick_reviews WHERE reviewed_at >= %(since)s", "bare"),
    ("SELECT count(*) FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id WHERE r.reviewed_at >= %(since)s", "bare"),
    ("SELECT count(*) FILTER (WHERE engine = 'combined') FROM ai.pick_reviews WHERE reviewed_at >= %(since)s", "bare"),
    ("SELECT bool_or(engine = 'llm') FROM ai.pick_reviews WHERE reviewed_at >= %(since)s GROUP BY 1", "bare"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine = 'combined'", "production"),
    ("SELECT 1 FROM ai.pick_reviews r WHERE r.engine = 'combined' AND r.fixture_id = 1", "production"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine IN ('rules', 'llm', 'combined')", "production"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine in ('combined','rules')", "production"),
    ("SELECT 1 FROM ai.pick_reviews pr WHERE pr.fixture_id = 1 AND pr.engine IN ('rules', 'llm', 'combined'))", "production"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine = 'ma-v1'", "shadow"),
    ("SELECT 1 FROM ai.pick_reviews r WHERE r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')", "shadow"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine IN ('combined', 'ma-v1')", "mixed"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine = 'somebody-else'", "mixed"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine <> 'ma-v1'", "negated"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine != 'cs-v1'", "negated"),
    ("SELECT 1 FROM ai.pick_reviews r WHERE r.engine NOT IN ('ma-v1', 'ma-v1-h', 'cs-v1')", "negated"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine = %s", "parametrised"),
    ("SELECT 1 FROM ai.pick_reviews r WHERE r.engine = %(engine)s", "parametrised"),
    ("SELECT output FROM ai.pick_reviews WHERE id = %(id)s", "by id"),
    ("SELECT id, output FROM ai.pick_reviews WHERE id = ANY(%(ids)s)", "by id"),
    ("SELECT 1 FROM d JOIN ai.pick_reviews r ON r.id = d.review_id", "by id"),
    ("SELECT x FROM ai.pick_reviews r WHERE r.id = ANY(%(ids)s)", "by id"),
    ("SELECT 1 FROM ai.pick_reviews WHERE engine_version = 'x' AND fixture_id = 1", "bare"),
    ("SELECT 1 FROM ai.pick_reviews WHERE fixture_id = 1 AND output->>'engine' = 'combined'", "bare"),
])
def test_the_guard_tells_a_filtered_read_from_a_bare_one(sql: str, kind: str) -> None:
    [read] = reads(sql)
    assert kind_of(read) == kind, sql


def test_one_filter_does_not_cover_two_reads_and_the_filter_of_another_table_covers_none() -> None:
    two = ("SELECT (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s) AS a, "
           "(SELECT count(*) FROM ai.pick_reviews WHERE reviewed_at >= %(since)s) AS b")
    assert [kind_of(r) for r in reads(two)] == ["production", "bare"], "the filter of the first read does not cover the second"
    other = ("SELECT (SELECT count(*) FROM ai.pick_reviews WHERE reviewed_at >= %(since)s) AS reviews, "
             "(SELECT count(*) FROM ai.match_briefs WHERE engine = 'llm' AND status = 'ok') AS briefs")
    assert [kind_of(r) for r in reads(other)] == ["bare"], "the engine of match_briefs, further on, is not the engine of the reviews"
    joined = ("SELECT 1 FROM ai.pick_reviews a JOIN ai.pick_reviews b ON b.fixture_id = a.fixture_id "
              "WHERE a.engine = 'combined' AND b.reviewed_at < a.reviewed_at")
    assert [kind_of(r) for r in reads(joined)] == ["production", "bare"], "a condition on the alias a says nothing of b"
    cte = ("WITH last AS (SELECT DISTINCT ON (r.fixture_id) r.fixture_id FROM ai.pick_reviews r WHERE r.reviewed_at < %(at)s) "
           "SELECT 1 FROM last JOIN ai.match_briefs m ON m.fixture_id = last.fixture_id WHERE m.engine = 'llm'")
    assert [kind_of(r) for r in reads(cte)] == ["bare"], "the subquery ends where its parenthesis does"
    exists = ("SELECT 1 FROM core.fixtures f WHERE EXISTS (SELECT 1 FROM ai.pick_reviews pr WHERE pr.fixture_id = f.id) "
              "AND NOT EXISTS (SELECT 1 FROM ai.postmortems pm WHERE pm.engine = 'llm')")
    assert [kind_of(r) for r in reads(exists)] == ["bare"]


def test_a_write_is_not_a_read_and_a_docstring_is_not_sql() -> None:
    assert reads("INSERT INTO ai.pick_reviews (engine) VALUES (%s)") == []
    assert reads("UPDATE ai.pick_reviews SET status = 'x'") == []
    found = Strings()
    found.visit(ast.parse('"""A module that says SELECT 1 FROM ai.pick_reviews in prose."""\nSQL = "SELECT 1 FROM ai.pick_reviews"\n'
                          'JOINED = f"SELECT {1} FROM ai.pick_reviews WHERE engine = \'llm\'"\nSUM = "SELECT 1 " + "FROM ai.pick_reviews"\n'))
    assert [t for _, t in found.found] == ["SELECT 1 FROM ai.pick_reviews", "SELECT {} FROM ai.pick_reviews WHERE engine = 'llm'",
                                           "SELECT 1 FROM ai.pick_reviews"]


def test_the_guard_reads_a_good_part_of_the_code() -> None:
    found = statements()
    files = {f for f, _, _ in found}
    n = sum(len(reads(t)) for _, _, t in found)
    assert n >= 38 and len(files) >= 16, "the scan finds the readers of the table (a regex that matches nothing guards nothing)"
    assert {"src/fbi/ai/gate_a.py", "src/fbi/ai/costs.py", "src/fbi/ai/gate_research.py", "src/fbi/ai/postmortem.py", "src/fbi/intel/match_review.py",
            "src/fbi/intel/decision.py", "src/fbi/ai/shadow.py", "src/fbi/api/services/ai_layer.py", "src/fbi/api/services/ai_v2.py"} <= files
    kinds = {kind_of(r) for _, _, t in found for r in reads(t)}
    assert {"production", "by id", "parametrised"} <= kinds, "and it tells the kinds apart"


# ── the code ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_read_of_the_reviews_table_names_production_engines_or_a_review_already_named_or_says_whose_word_it_is() -> None:
    exempt = [(f, s) for f, s, _ in CALLERS_WORD]
    counted = [(f, s) for f, s, _ in COUNTED_BY_ENGINE]
    bad: list[str] = []
    for file, line, text in statements():
        for read in reads(text):
            kind = kind_of(read)
            if kind in ("production", "shadow", "by id"):
                continue
            if kind == "parametrised" and any(f == file and s in squashed(read.text) for f, s in exempt):
                continue
            if kind == "bare" and counts_by_engine(text) and any(f == file and s in squashed(read.text) for f, s in counted):
                continue
            bad.append(f"{file}:{line} [{kind}]: {squashed(read.text)[:170]}")
    assert bad == [], ("these statements read ai.pick_reviews without saying which engines they count - a row of the shadow of phase 3 would move their "
                       "figure (``engine IN ('rules', 'llm', 'combined')``, fbi.ai.config.PRODUCTION_ENGINES):\n" + "\n".join(bad))


def test_each_reader_whose_engine_is_the_callers_is_still_there_still_a_parameter_and_says_why() -> None:
    for file, snippet, reason in CALLERS_WORD:
        parts = [r for f, _, text in statements() if f == file for r in reads(text) if snippet in squashed(r.text)]
        assert len(parts) == 1, f"{file}: «{snippet}» is not (or not only once) in the code: take it out of CALLERS_WORD"
        assert kind_of(parts[0]) == "parametrised", f"{file}: «{snippet}» no longer takes its engine from the caller"
        assert len(reason) > 60, f"{file}: say why it is safe"


def test_each_reader_that_counts_by_engine_is_still_there_and_still_filters_every_count() -> None:
    for file, snippet, reason in COUNTED_BY_ENGINE:
        parts = [(r, text) for f, _, text in statements() if f == file for r in reads(text) if snippet in squashed(r.text)]
        assert len(parts) == 1, f"{file}: «{snippet}» is not (or not only once) in the code: take it out of COUNTED_BY_ENGINE"
        assert kind_of(parts[0][0]) == "bare" and counts_by_engine(parts[0][1]), f"{file}: a count of «{snippet}» is not filtered by its engine"
        assert len(reason) > 60, f"{file}: say why it is safe"
    assert counts_by_engine("SELECT count(*) FILTER (WHERE r.engine = 'llm' AND r.status = 'ok') AS a, count(*) FILTER (WHERE engine = 'combined') AS b FROM x")
    assert not counts_by_engine("SELECT count(*) FILTER (WHERE r.engine = 'llm') AS a, count(*) AS b FROM x"), "a count with no engine counts them all"
    assert not counts_by_engine("SELECT count(*) FILTER (WHERE r.engine = 'ma-v1') AS a FROM x"), "and one that counts the shadow is not production's"
    assert not counts_by_engine("SELECT count(DISTINCT fixture_id) AS a, count(*) FILTER (WHERE engine = 'llm') AS b FROM x")


def test_no_reader_of_production_names_an_engine_of_the_shadow_beside_the_engines_of_production() -> None:
    mixed = [f"{file}:{line}" for file, line, text in statements() for r in reads(text) if kind_of(r) == "mixed"]
    assert mixed == [], "a statement that counts the shadow's engines with production's mixes the experiment into the figure"


@pytest.mark.parametrize(("file", "fragment", "engines"), CHANGED, ids=[c[0].rsplit("/", 1)[-1] for c in CHANGED])
def test_the_readers_this_phase_changed_filter_on_the_whole_list_of_production(file: str, fragment: str, engines: frozenset[str]) -> None:
    mine = [r for f, _, text in statements() if f == file for r in reads(text) if fragment in squashed(text)]
    assert mine, f"{file}: «{fragment}» is not in the code"
    for read in mine:
        assert kind_of(read) == "production", f"{file}: {squashed(read.text)[:170]}"
        assert named(read)[0] == set(engines), f"{file}: it names {sorted(named(read)[0])}, it should name {sorted(engines)}"


def test_taking_the_filter_out_of_a_reader_this_phase_changed_would_make_the_guard_fail() -> None:
    """The mutation: the same statements without their ``engine IN (...)`` are bare reads."""
    from fbi.ai import costs, gate_a, gate_research, postmortem
    from fbi.intel import decision, match_review

    statements_ = {"gate_a": gate_a.CANDIDATES_SQL, "costs": costs.REVIEWS_SQL, "gate_research": gate_research.CITED_SQL,
                   "postmortem": postmortem.DUE_SQL, "match_review": match_review.DUE_SQL, "decision": decision.REVIEWS_SQL}
    for name, sql in statements_.items():
        assert [kind_of(r) for r in reads(sql)] == ["production"], name
        without = re.sub(r"(?:\w+\.)?engine\s+IN\s*\([^)]*\)", "TRUE", sql)
        assert without != sql, name
        assert [kind_of(r) for r in reads(without)] == ["bare"], f"{name}: without its filter the guard must see a bare read"


def test_the_decision_layer_reads_combined_and_rules_and_never_an_engine_of_the_shadow() -> None:
    """Filter 6 (context) judges a selection by the newest ``combined`` review and the ``rules`` findings, both as of the moment of the decision. The
    shadow of phase 3 is invisible to it: ``REVIEWS_SQL`` names the two engines and ``read_world`` files the rest under ``rules``, so a third engine in
    that list would be read as rules."""
    from fbi.intel import decision

    sql = squashed(decision.REVIEWS_SQL)
    assert "r.engine IN ('combined', 'rules')" in sql and len(reads(decision.REVIEWS_SQL)) == 1
    assert "AND r.reviewed_at <= %(at)s" in sql and "interval '12 hours'" in sql, "as of the decision, and not older than twelve hours"
    source = Path(decision.__file__).read_text()
    for engine in SHADOW_ENGINES:
        assert engine not in source, f"fbi.intel.decision names {engine}: filter 6 must not know the shadow exists"
    assert "fbi.ai.arms" not in source and "from fbi.ai import arms" not in source, "nor the assignment of the matches to its arms"


# ── one list of engines ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_engines_of_the_code_are_one_list() -> None:
    assert PRODUCTION_ENGINES == ("rules", "llm", "combined") == (*BASELINE_ENGINES, "combined")
    assert SHADOW_ENGINES == ("ma-v1", "ma-v1-h", "cs-v1")
    assert not PRODUCTION & SHADOW
    assert typing.get_args(review.Engine) == (*PRODUCTION_ENGINES, *SHADOW_ENGINES), "the engine of a review result: the six the table can hold"
    assert (*PRODUCTION_ENGINES, *SHADOW_ENGINES) == shadow.ENGINES, "the engines a report is made for"
    assert set(KNOWN_ENGINES) | {"combined"} == PRODUCTION | SHADOW, "the owner can name every engine but ``combined``, which is what they add up to"
    annotation = typing.get_type_hints(review.EngineResult)["engine"]
    assert typing.get_args(annotation) == typing.get_args(review.Engine)


def test_a_report_is_written_for_the_engines_that_always_had_one_and_for_the_others_only_with_data() -> None:
    assert shadow.REPORTED_EMPTY == ("rules", "combined"), "``llm`` never wrote an empty report: nor does an engine of the shadow"
    assert set(shadow.REPORTED_EMPTY) <= set(shadow.ENGINES)
