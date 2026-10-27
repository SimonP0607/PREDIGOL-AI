"""Plan S3.5: the owner's guide to the drills of the alerts says what the code does.

``docs/owner/SIMULACROS_AVISOS.md`` is what the owner reads before the session in which Claude makes every alert reach his phone once, and the
sheet that closes R03 (the "acta") is filled in from it. Whether the plan of the session is wise no test can hold. What a test can hold is that the document and the code
do not drift apart: Table A is the table of ``bin/alert-drill.sh`` row by row, its dots are the record ``--all`` sends, and that table is the alerts the scripts raise
(every key and every severity, and for each row a text the scripts would send); Table B is the Healthchecks checks the scripts ping, with the variables the example file
defines; the acta is the catalogue's 34 alerts, blank, each one tied to the rows that provoke it; the numbers in the text (36 messages, 3 seconds, 20 seconds, three
refusals in a row, a safety timer longer than the check's margin) are the code's; the commands shown exist, and the shell blocks run - in a dry run, through a stub of
``predigolctl`` - without sending anything and without printing a secret.
"""

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

import pytest

from tests.unit._vps_sandbox import tools_present

BACKEND = Path(__file__).resolve().parents[2]
DOC = BACKEND / "docs" / "owner" / "SIMULACROS_AVISOS.md"
KIT = BACKEND / "deploy" / "vps"
BIN = KIT / "bin"
DRILL = BIN / "alert-drill.sh"
SENTRY_DRILL = BACKEND / "scripts" / "sentry_drill.py"
GITLEAKS_CI = BACKEND.parent / ".github" / "workflows" / "gitleaks.yml"

if not DOC.is_file():
    pytest.skip(f"no {DOC.name} next to the code", allow_module_level=True)

TEXT = DOC.read_text(encoding="utf-8")
SCRIPT = DRILL.read_text(encoding="utf-8")
# a fenced block may sit in a list item: its closing fence has the indentation of its opening one
FENCE = re.compile(r"^([ \t]*)```([a-z]*)\n(.*?)^\1```[ \t]*$", re.M | re.S)
PROSE = FENCE.sub("", TEXT)  # everything outside the fenced blocks
needs_tools = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)

# The plan's catalogue of alerts (section 20, 34 of them): which phase brings each one. The 26 of S3 are the rest.
LATER_PHASES = {20: "IA", 21: "IA", 22: "IA", 27: "S9", 29: "S10", 30: "S4", 31: "S4", 34: "S11"}
CATALOGUE = range(1, 35)


def section(prefix: str) -> str:
    """The body of the ``## prefix...`` section, up to the next ``## `` heading."""
    found = re.search(rf"^## {re.escape(prefix)}[^\n]*\n(.*?)(?=^## |\Z)", TEXT, flags=re.M | re.S)
    assert found, f"the document has no section that starts with {prefix!r}"
    return found.group(1)


def table(text: str) -> list[list[str]]:
    """The rows of the markdown table in ``text``, header first (the separator line is dropped). A cell is stripped; an empty cell is kept."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("|") and line.endswith("|") and not re.fullmatch(r"\|[-| :]+\|", line):
            rows.append([cell.strip() for cell in line[1:-1].split("|")])
    return rows


def blocks(lang: str) -> list[str]:
    """The fenced blocks of ``lang``, without the indentation of the list item they may sit in."""
    found = []
    for indent, tag, body in FENCE.findall(TEXT):
        if tag == lang:
            lines = [ln.removeprefix(indent) for ln in body.splitlines()]
            found.append("\n".join(lines) + "\n")
    return found


def spans(text: str) -> list[str]:
    """The `inline code` of ``text``, with a wrapped span put on one line."""
    return [re.sub(r"\s+", " ", s).strip() for s in re.findall(r"`([^`\n]+)`", text)]


# --- what the code has ---------------------------------------------------------------------------------------------------------------------------------


def drill_rows() -> list[tuple[str, str, str]]:
    """The table of alert-drill.sh, in its order: (key, severity, text), the text with ``{nombre}`` as the script has it."""
    body = re.search(r"cat << 'TABLE'\n(.*?)\nTABLE\n", SCRIPT, flags=re.S)
    assert body, "alert-drill.sh no longer has its table in a TABLE here-document"
    rows = []
    for line in body[1].splitlines():
        key, sev, text = line.split("|", 2)
        rows.append((key, sev, text))
    return rows


def script_words(name: str) -> list[str]:
    found = re.search(rf"^{name}=\(([^)]*)\)", SCRIPT, flags=re.M)
    assert found, f"alert-drill.sh no longer defines {name}"
    return found[1].split()


SERVICES = script_words("SERVICES")
HC_NAMES = script_words("HC_NAMES")


def record() -> list[tuple[str, str]]:
    """What ``--all`` sends, in order: (key, severity), a service read as ``svc.<nombre>`` (the five are the same alert)."""
    body = re.search(r"^RECORD=\(\n(.*?)\n\)", SCRIPT, flags=re.M | re.S)
    assert body, "alert-drill.sh no longer defines RECORD"
    out = []
    for entry in body[1].split():
        key, sev = entry.rsplit(":", 1)
        service = re.fullmatch(rf"svc\.(?:{'|'.join(SERVICES)})(\.loop)?", key)
        out.append((f"svc.<nombre>{service[1] or ''}" if service else key, sev))
    return out


def default_seconds(name: str) -> int:
    found = re.search(rf"{name}=\$\(\(10#\$\{{{name}:-(\d+)\}}\)\)", SCRIPT)
    assert found, f"alert-drill.sh no longer gives {name} a default in the way this test reads"
    return int(found[1])


# --- the alerts the scripts raise: key, severity, and what the text can say ------------------------------------------------------------------------------

ALERT_CALL = re.compile(
    r'\b(?:alert_set|alert_unless_deploy)\s+("?)([A-Za-z][A-Za-z0-9_.$]*)\1\s+(SEV[123])\s+"'
)
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def skip_nested(s: str, i: int, close: str) -> int:
    """``s[i]`` follows the opening ``(`` or ``{`` of a ``$(...)`` or ``${...}``: the index after its matching ``close``, quotes and backslashes respected."""
    opener = "(" if close == ")" else "{"
    depth = 1
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            i = s.index("'", i + 1) + 1
            continue
        if c == '"':
            i = double_quoted(s, i + 1)[0]
            continue
        if c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError(f"a ${opener}...{close} that never closes")


def double_quoted(s: str, i: int) -> tuple[int, str]:
    """``s[i]`` follows the opening ``"`` of a bash string: the index after its closing ``"`` and a regular expression of what the string can say (each expansion is ``.+?``)."""
    regex: list[str] = []
    literal: list[str] = []

    def flush() -> None:
        if literal:
            regex.append(re.escape("".join(literal)))
            literal.clear()

    while i < len(s):
        c, following = s[i], s[i + 1 : i + 2]
        if c == '"':
            flush()
            return i + 1, "".join(regex)
        if c == "\\" and following and following in '"$`\\':
            literal.append(following)
            i += 2
        elif c == "$" and following == "(":
            flush()
            regex.append(".+?")
            i = skip_nested(s, i + 2, ")")
        elif c == "$" and following == "{":
            flush()
            regex.append(".+?")
            i = skip_nested(s, i + 2, "}")
        elif c == "$" and (name := IDENT.match(s, i + 1)):
            flush()
            regex.append(".+?")
            i = name.end()
        else:
            literal.append(c)
            i += 1
    raise ValueError("a string that never closes")


def alert_calls() -> list[tuple[str, str, str, str]]:
    """(script, key, severity, regex of the text) of every ``alert_set`` / ``alert_unless_deploy`` call of the server's scripts; ``svc.$svc`` is ``svc.<nombre>``."""
    found = []
    for path in sorted(BIN.glob("*.sh")):
        if path.name in {"alerts_lib.sh", "alert-drill.sh"}:
            continue  # the function itself, and the drill
        lines = path.read_text(encoding="utf-8").splitlines()
        code = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
        for call in ALERT_CALL.finditer(code):
            key = call[2].replace("$svc", "<nombre>")
            assert "$" not in key, f"{path.name}: the key {call[2]!r} is built at run time"
            found.append((path.name, key, call[3], double_quoted(code, call.end())[1]))
    return found


def sample(text: str) -> str:
    """The text of a row of the table as one service would send it."""
    return text.replace("{nombre}", SERVICES[0])


# --- the shape -----------------------------------------------------------------------------------------------------------------------------------------


def test_the_document_has_its_sections_in_order() -> None:
    headings = re.findall(r"^## (.+)$", TEXT, flags=re.M)
    expected = [
        "Lo que te toca",
        "Qué prueba un simulacro y qué no",
        "Antes de la sesión",
        "Tabla A",
        "Tabla B",
        "Tabla C",
        "El orden de la sesión",
        "El silencio del latido",
        "Si un aviso no llega en 10 minutos",
        "Al terminar",
        "Acta de simulacros",
    ]
    assert len(headings) == len(expected), headings
    for found, wanted in zip(headings, expected, strict=True):
        assert found.startswith(wanted), f"{found!r} where {wanted!r} should be"


def test_the_document_never_shows_a_value() -> None:
    """Names, never values: nothing in the text has the shape of a key, a token, a ping URL, a DSN or a private key, and no template marker is left."""
    patterns = {
        "a long hexadecimal run": r"\b[0-9a-fA-F]{32,}\b",
        "an age private key": r"AGE-SECRET-KEY-",
        "an age public key": r"\bage1[0-9a-z]{50,}\b",
        "a Telegram token": r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",
        "a Healthchecks ping URL": r"hc-ping\.com/[0-9a-fA-F-]{8,}",
        "an Anthropic key": r"\bsk-ant-",
        "a Sentry DSN": r"https://[0-9a-f]{16,}@",
        "a base64 string of key length": r"\b[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/])",
        "a template marker": r"@@|\bTODO\b|\bXXX\b",
    }
    for what, pattern in patterns.items():
        assert not re.search(pattern, TEXT), f"the document holds {what}"


# --- Table A: the drill table, the record, the scripts ---------------------------------------------------------------------------------------------------


def table_a() -> list[list[str]]:
    rows = table(section("Tabla A"))
    assert [c.replace("`", "") for c in rows[0]] == ["#", "Clave", "Gravedad", "Mensaje", "--all"]
    return rows[1:]


def test_table_a_is_the_drill_table_row_by_row() -> None:
    """The owner reads each message in this table and then sees it on his phone: a row that said something else than alert-drill.sh sends would make him doubt a
    message that is right."""
    shown = [
        (key.replace("`", ""), sev, message.replace("`", ""))
        for _, key, sev, message, _ in table_a()
    ]
    sent = [(key, sev, text.replace("{nombre}", "<nombre>")) for key, sev, text in drill_rows()]
    assert len(sent) >= 40, "the drill table lost rows"
    assert shown == sent


def test_the_number_of_each_row_is_the_alerts_number_in_the_catalogue() -> None:
    """``#`` is the number in the plan's catalogue (1 to 34), the same for every severity of a key, or a dash for what the server sends and the catalogue does not
    number (they have no row in the acta)."""
    numbers: dict[str, set[str]] = {}
    for number, key, *_ in table_a():
        numbers.setdefault(key.replace("`", ""), set()).add(number)
    assert all(len(n) == 1 for n in numbers.values()), f"a key with two numbers: {numbers}"
    for key, (number,) in numbers.items():
        assert number == "—" or int(number) in CATALOGUE, f"{key}: {number} is not in the catalogue"
    assert {k for k, (n,) in numbers.items() if n == "—"} == {
        "backup.local",
        "backup.locks",
        "incidents.dump",
        "pitr.backup",
        "web.degraded",
    }


def test_the_dots_are_the_record_that_all_sends() -> None:
    marked = [(key.replace("`", ""), sev) for _, key, sev, _, mark in table_a() if mark == "●"]
    assert all(mark in {"●", ""} for *_, mark in table_a())
    assert sorted(marked) == sorted(record())
    assert len(marked) == len(set(marked)) == 36


def test_the_rows_without_a_dot_are_other_severities_of_an_alert_that_has_one() -> None:
    """The text says so: «Las filas sin marca son otras gravedades de un aviso que ya está en el registro»."""
    rows = [(key.replace("`", ""), sev, mark) for _, key, sev, _, mark in table_a()]
    marked = {(key, sev) for key, sev, mark in rows if mark}
    unmarked = [(key, sev) for key, sev, mark in rows if not mark]
    assert unmarked, "every row is marked: the sentence about the others is false"
    for key, sev in unmarked:
        others = [k for k, s in marked if k == key and s != sev]
        assert others, f"{key} {sev} is not in the record, and no other severity of {key} is"
    # every alert of the table has at least one row in the record
    assert {key for key, _, _ in rows} == {key for key, _ in marked}


def test_the_scripts_raise_exactly_the_alerts_of_the_table() -> None:
    """A key or a severity that a script raises and the table lacks cannot be drilled; one that the table has and no script raises is a drill of nothing."""
    calls = alert_calls()
    assert len(calls) >= 50, "the extraction of the alert_set calls stopped working"
    assert {"healthcheck.sh", "alerts_checks.sh", "security-alerts.sh", "incident-dump.sh"} <= {
        c[0] for c in calls
    }
    raised = {(key, sev) for _, key, sev, _ in calls}
    in_the_table = {(key, sev) for key, sev, _ in drill_rows()}
    assert raised - in_the_table == set(), "raised by the scripts and missing from the drill table"
    assert in_the_table - raised == set(), "in the drill table and raised by no script"


def test_each_text_of_the_table_is_one_the_scripts_would_send() -> None:
    """Sample numbers stand where the scripts count something, but the words are the scripts': a text that no call of that key and severity could produce is a message
    the owner will never see in production."""
    shapes: dict[tuple[str, str], list[str]] = {}
    for _, key, sev, regex in alert_calls():
        shapes.setdefault((key, sev), []).append(regex)
    wrong = []
    for key, sev, text in drill_rows():
        if not any(re.fullmatch(shape, sample(text)) for shape in shapes[(key, sev)]):
            wrong.append(f"{key} {sev}: {sample(text)!r}")
    assert not wrong, (
        "texts that no alert_set call of that key and severity could send:\n" + "\n".join(wrong)
    )
    assert len(drill_rows()) >= 40


def test_the_scanner_reads_what_it_is_meant_to_read() -> None:
    """The two checks above are only as good as the scanner: it must see the nested quotes of a command substitution and the expansions of a text."""
    code = (
        "alert_set a.b SEV2 \"$n ejecuciones en $(( x / 60 )) min (${BASH_REMATCH[2]}) $(printf '%s, ' \"${c[@]}\" | sed 's/, $//')\" ; echo hi\n"
        'alert_unless_deploy "svc.$svc.loop" SEV1 "contenedor $svc"\n'
    )
    first = ALERT_CALL.search(code)
    assert first
    end, regex = double_quoted(code, first.end())
    assert code[end:].startswith(" ; echo hi")
    assert re.fullmatch(regex, "3 ejecuciones en 5 min (id 0) Caddyfile")
    assert not re.fullmatch(regex, "3 ejecuciones en 5 min (id 0)")
    second = ALERT_CALL.search(code, end)
    assert second and (second[2], second[3]) == ("svc.$svc.loop", "SEV1")
    assert re.fullmatch(double_quoted(code, second.end())[1], "contenedor api")


# --- Table B: the Healthchecks checks ----------------------------------------------------------------------------------------------------------------


def table_b() -> list[list[str]]:
    rows = table(section("Tabla B"))
    assert [c.replace("`", "") for c in rows[0]] == [
        "Check",
        "Variable (predigol.env)",
        "Aviso",
        "Periodo · margen",
        "Se provoca con",
    ]
    return rows[1:]


def test_table_b_is_the_seven_checks_of_the_script_with_their_variables_and_commands() -> None:
    rows = table_b()
    names = [row[0].replace("`", "") for row in rows]
    assert names == HC_NAMES and len(names) == 7
    for row, name in zip(rows, names, strict=True):
        assert row[1] == f"`HC_PING_{name.upper().replace('-', '_')}`"
        assert row[4] == f"`predigolctl alert-drill --healthchecks {name}`"


def test_the_ping_variables_are_the_ones_the_example_file_defines_and_the_scripts_ping() -> None:
    example = (KIT / "predigol.env.example").read_text(encoding="utf-8")
    defined = set(re.findall(r"^#?\s*(HC_PING_[A-Z_]+)=", example, flags=re.M))
    pinged: set[str] = set()
    for path in BIN.glob("*.sh"):
        source = path.read_text(encoding="utf-8")
        pinged |= set(re.findall(r'ping_hc "\$\{(HC_PING_[A-Z_]+):-\}"', source))
    shown = {row[1].replace("`", "") for row in table_b()}
    assert shown == defined == pinged and len(shown) == 7


# --- Table C and the acta -------------------------------------------------------------------------------------------------------------------------------


def table_c() -> list[list[str]]:
    rows = table(section("Tabla C"))
    assert [c.replace("`", "") for c in rows[0]] == [
        "#",
        "Aviso",
        "Cómo se provoca",
        "Quién",
        "Dónde llega",
        "Cómo se deshace",
    ]
    return rows[1:]


def acta() -> list[list[str]]:
    rows = table(section("Acta de simulacros"))
    assert rows[0] == [
        "#",
        "Aviso",
        "Fase",
        "Se dispara con",
        "Disparo (UTC)",
        "Recibido (UTC)",
        "Min",
        "Canal",
        "Captura",
        "OK",
    ]
    return rows[1:]


def alert_numbers() -> dict[str, int]:
    """The catalogue number of each key of Table A that has one."""
    return {key.replace("`", ""): int(number) for number, key, *_ in table_a() if number != "—"}


def test_the_acta_is_a_blank_sheet_of_the_34_alerts_of_the_catalogue() -> None:
    rows = acta()
    assert [row[0] for row in rows] == [str(n) for n in CATALOGUE]
    for row in rows:
        assert len(row) == 10, row
        assert all(row[:4]), f"alert {row[0]}: a cell of its name, phase or trigger is empty"
        assert not any(row[4:]), (
            f"alert {row[0]}: the sheet is meant to be blank, and has {row[4:]}"
        )


def test_the_phases_of_the_acta_are_the_plans_and_the_text_counts_them_right() -> None:
    phases = {int(row[0]): row[2] for row in acta()}
    assert phases == {n: LATER_PHASES.get(n, "S3") for n in CATALOGUE}
    s3 = sum(1 for phase in phases.values() if phase == "S3")
    later = {phase for phase in phases.values() if phase != "S3"}
    flat = re.sub(r"\s+", " ", section("Acta de simulacros"))
    assert (s3, len(phases) - s3) == (26, 8)
    assert "de los 34 avisos del catálogo" in flat
    assert "los 26 avisos de S3" in flat
    assert "Los ocho avisos de fases posteriores (IA, S4, S9, S10 y S11)" in flat
    assert later == {"IA", "S4", "S9", "S10", "S11"}


def test_every_alert_of_s3_is_provoked_by_rows_that_exist_and_carry_its_number() -> None:
    """The «Se dispara con» column names keys of Table A, checks of Table B or a command of Table C; each one must be the alert of that very row of the acta, and
    each key or check of the tables must be named by the row of its number: an alert nobody provokes is a hole in R03."""
    keys = alert_numbers()
    pairs = {(key.replace("`", ""), sev) for _, key, sev, *_ in table_a()}
    checks = {row[0].replace("`", ""): int(row[2]) for row in table_b()}
    outside = {int(row[0]) for row in table_c()}
    problems: list[str] = []
    named: dict[int, set[str]] = {}
    for number, _, phase, how, *_ in acta():
        n = int(number)
        if phase != "S3":
            if not how.startswith("Al cerrar"):
                problems.append(f"{n}: a later phase, and it says {how!r}")
            continue
        tokens = spans(how)
        for token in tokens:
            named.setdefault(n, set()).add(token)
            if token in keys:
                if keys[token] != n:
                    problems.append(f"{n}: `{token}` is alert {keys[token]}")
            elif token in checks:
                if checks[token] != n:
                    problems.append(f"{n}: the check `{token}` is alert {checks[token]}")
            elif token.startswith("predigolctl "):
                if n not in outside:
                    problems.append(f"{n}: a command, and Table C has no row {n}")
            else:
                problems.append(f"{n}: `{token}` is no key, no check and no command")
        for token, first, second in re.findall(r"`([^`]+)` \((SEV\d) y (SEV\d)\)", how):
            for sev in (first, second):
                if (token, sev) not in pairs:
                    problems.append(f"{n}: {token} has no {sev} row in Table A")
        if ("Tabla C" in how) != (n in outside):
            problems.append(f"{n}: «Tabla C» in the acta and the rows of Table C disagree")
        if not tokens and "Tabla C" not in how:
            problems.append(f"{n}: nothing provokes it")
    for key, n in keys.items():
        if key not in named.get(n, set()):
            problems.append(f"{n}: the acta does not name `{key}`")
    for name, n in checks.items():
        if name not in named.get(n, set()):
            problems.append(f"{n}: the acta does not name the check `{name}`")
    assert not problems, "\n".join(problems)


def test_table_c_is_the_s3_alerts_that_neither_the_drill_nor_healthchecks_can_send() -> None:
    s3 = {n for n in CATALOGUE if n not in LATER_PHASES}
    covered = set(alert_numbers().values()) | {int(row[2]) for row in table_b()}
    outside = sorted(int(row[0]) for row in table_c())
    assert outside == sorted(s3 - covered) == [1, 7, 33]
    names = {int(row[0]): row[1] for row in acta()}
    for row in table_c():
        assert row[1] == names[int(row[0])], f"Table C calls alert {row[0]} otherwise than the acta"


def test_what_table_c_says_about_the_sentry_drill_is_what_the_repository_has() -> None:
    row = {int(r[0]): r for r in table_c()}[7]
    sentry = SENTRY_DRILL.read_text(encoding="utf-8")
    assert "`predigolctl sentry-drill`" in row[2] and "`SentryDrillError`" in row[2]
    assert "class SentryDrillError" in sentry and "SIMULACRO" in sentry
    dispatcher_arm = re.search(r"^  sentry-drill\) (.*)$", (BIN / "predigolctl").read_text(), re.M)
    assert dispatcher_arm and "scripts.sentry_drill" in dispatcher_arm[1]
    assert "Sentry" in row[4] and "correo" in row[4]


def test_the_outside_monitor_watches_the_url_that_healthcheck_probes() -> None:
    row = {int(r[0]): r for r in table_c()}[1]
    assert "https://predigolai.com/health" in TEXT
    assert (
        'problem "https://$DOMAIN/health does not answer"' in (BIN / "healthcheck.sh").read_text()
    )
    assert "/simulacro-no-existe" in row[2] and "404" in row[2]


@pytest.mark.skipif(not GITLEAKS_CI.is_file(), reason="the CI of the repository is not here")
def test_the_gitleaks_drill_goes_through_a_pull_request_because_that_is_when_the_ci_runs() -> None:
    """A push to a throwaway branch triggers nothing: the workflow runs on pushes to main, on pull requests and by hand, and a finding fails the job."""
    ci = GITLEAKS_CI.read_text(encoding="utf-8")
    triggers = ci.split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert re.search(r"^  pull_request:", triggers, re.M)
    assert re.search(r"^  push:\n    branches: \[main\]", triggers, re.M)
    row = {int(r[0]): r for r in table_c()}[33]
    assert "pull request borrador hacia `main`" in row[2] and "rama de prueba" in row[2]
    assert "security/scan.sh history" in ci and "Un hallazgo hace fallar el trabajo" in ci
    assert "GitHub avisa" in row[4]


SELFTEST = BACKEND.parent / "security" / "selftest.sh"
PRE_COMMIT = BACKEND.parent / ".githooks" / "pre-commit"


@pytest.mark.skipif(
    not (SELFTEST.is_file() and PRE_COMMIT.is_file()), reason="the security folder is not here"
)
def test_the_invented_secret_has_the_shape_the_selftest_of_gitleaks_holds_as_blocked() -> None:
    """The first version of the text said `clave = "…"`, which Gitleaks' generic rule does not read (it looks for key, secret, token, api... in the name): a drill
    with that line would have passed the CI and proved nothing. The shape the text gives is the one security/selftest.sh asserts is blocked by the repository's own
    configuration."""
    flat = re.sub(r"\s+", " ", PROSE)
    assert 'una línea `api_key = "…"` con 40 caracteres al azar' in flat
    selftest = SELFTEST.read_text(encoding="utf-8")
    assert 'api_key = \\"$(rnd_alnum 40)\\"' in selftest
    assert re.search(r'expect_block_retry "api_key[^"]*" "generic-api-key" w_svc', selftest)
    assert "`security/selftest.sh`" in flat and "`SKIP_GITLEAKS=1`" in flat
    assert 'SKIP_GITLEAKS:-0}" = 1' in PRE_COMMIT.read_text(encoding="utf-8")


# --- the commands, the files and the numbers the text names ------------------------------------------------------------------------------------------


def dispatcher() -> set[str]:
    body = (
        (BIN / "predigolctl")
        .read_text(encoding="utf-8")
        .split('case "${1:-}" in', 1)[1]
        .split("\nesac", 1)[0]
    )
    return set(re.findall(r"^  ([a-z][a-z0-9-]*)\)", body, flags=re.M))


def predigolctl_calls(*, only_prose: bool = False) -> list[list[str]]:
    """Every ``predigolctl ...`` the text shows, as tokens: the lines of its shell blocks and its inline `code` spans."""
    lines = spans(PROSE)
    if not only_prose:
        lines = [line for body in blocks("bash") for line in body.splitlines()] + lines
    calls = []
    for line in lines:
        for found in re.finditer(r"predigolctl\b([^;|&#`)\n]*)", line):
            tokens = shlex.split(found[1])
            if tokens:
                calls.append(tokens)
    return calls


def test_every_predigolctl_command_the_text_shows_exists() -> None:
    top = dispatcher()
    flags = set(re.findall(r"(?:^|\s)(--[a-z][a-z-]*)\)", SCRIPT, flags=re.M))
    incident = (BIN / "incident.sh").read_text(encoding="utf-8")
    incident_commands = set(re.findall(r"^  ([a-z]+)\) shift; cmd_", incident, flags=re.M))
    calls = predigolctl_calls()
    assert {c[0] for c in calls} >= {"alert-test", "alert-drill", "sentry-drill", "incident"}
    assert flags >= {"--list", "--all", "--healthchecks", "--evidence", "--hold", "--pause"}
    problems = []
    for tokens in calls:
        command = tokens[0]
        if command not in top:
            problems.append(f"predigolctl {command}: the dispatcher has no such command")
        elif command == "incident" and tokens[1] not in incident_commands:
            problems.append(f"predigolctl incident {tokens[1]}: incident.sh has no such command")
        elif command in {"alert-test", "sentry-drill"} and len(tokens) > 1:
            problems.append(
                f"predigolctl {command} takes no arguments here, and the text gives some"
            )
        for flag in (t for t in tokens if t.startswith("--")):
            if command == "alert-drill" and flag not in flags:
                problems.append(f"predigolctl alert-drill {flag}: the script has no such option")
    assert not problems, "\n".join(sorted(set(problems)))


def test_the_scripts_and_units_the_text_names_exist() -> None:
    names = set(re.findall(r"(?<![\w./-])(?:bin/)?([a-z][a-z0-9_-]*\.sh)\b", TEXT))
    assert {"alerts_lib.sh", "healthcheck.sh"} <= names
    assert not [n for n in names if not (BIN / n).is_file()], names
    timers = set(re.findall(r"(?<![\w./-])([a-z][a-z0-9_-]*\.timer)\b", TEXT))
    assert "predigol-health.timer" in timers
    assert not [t for t in timers if not (KIT / "systemd" / t).is_file()], timers
    assert SENTRY_DRILL.is_file()


def test_the_numbers_in_the_text_are_the_codes() -> None:
    flat = re.sub(r"\s+", " ", TEXT)
    pause, hold, total = default_seconds("PAUSE"), default_seconds("HOLD"), len(record())
    # «los 36 de golpe», «sus 36 mensajes», «Los 36 mensajes de apertura»
    counts = re.findall(r"\b(\d+) (?:de golpe|mensajes)\b", flat)
    assert len(counts) >= 3 and set(counts) == {str(total)}, counts
    # «uno cada 3 segundos (unos 2 minutos)»
    cadence = re.search(r"uno cada (\d+) segundos \(unos (\d+) minutos\)", flat)
    assert cadence and int(cadence[1]) == pause and round(total * pause / 60) == int(cadence[2])
    # every number of seconds is the default hold, the default pause, or the value of an example that says so on its own line
    examples = {int(v) for v in re.findall(r"--(?:hold|pause) (\d+)", TEXT)}
    mentioned = {int(v) for v in re.findall(r"\b(\d+) segundos", flat)}
    assert hold in mentioned and pause in mentioned and mentioned <= {hold, pause, *examples}
    seen = 0
    for line in TEXT.splitlines():
        for option, phrase in (("hold", "a los"), ("pause", "cada")):
            given, said = (
                re.search(rf"--{option} (\d+)", line),
                re.search(rf"{phrase} (\d+) segundos", line),
            )
            if given and said:
                assert given[1] == said[1], line
                seen += 1
    assert seen == 2, "the examples of --hold and --pause no longer say how long they wait"
    # «Si Telegram rechaza tres seguidos, se detiene»
    assert "rechaza tres seguidos" in flat and "streak >= 3" in SCRIPT
    # «Los siete checks»
    assert len(HC_NAMES) == 7 and len(re.findall(r"\b[Ll]os siete checks\b", flat)) >= 2
    # the incident numbers: 901 for one alert, 900 + n in the record
    assert 'drill_one "$key" "$sev" "$text" 901 "$plan"' in SCRIPT and "$((900 + n))" in SCRIPT
    assert "`INC-AAAA-901` en adelante" in flat and "empieza por 9" in flat
    # «las 14:05 de tu móvil son las 19:05 UTC» (Bogotá = UTC-5)
    hours = re.search(r"las (\d\d):(\d\d) de tu móvil son las (\d\d):(\d\d) UTC", flat)
    assert hours and (int(hours[1]) + 5) % 24 == int(hours[3]) and hours[2] == hours[4]
    assert "Bogotá = UTC\u22125" in flat and "más 5 horas" in flat


def test_the_heartbeat_is_silenced_for_longer_than_healthchecks_takes_to_notice() -> None:
    """If the safety timer came back before the check's period plus its margin, Healthchecks would never see the silence and the drill would prove nothing."""
    health = {row[0].replace("`", ""): row for row in table_b()}["health"]
    period, margin = (int(v) for v in re.findall(r"(\d+) min", health[3]))
    timer = (KIT / "systemd" / "predigol-health.timer").read_text(encoding="utf-8")
    assert f"OnUnitActiveSec={period}min" in timer
    flat = re.sub(r"\s+", " ", section("El silencio del latido"))
    assert f"{period + margin} minutos después del último latido" in flat
    assert f"periodo de {period} minutos más margen de {margin}" in flat
    assert f"Durante esos {period + margin} minutos nadie vigila" in flat
    block = next(b for b in blocks("bash") if "systemd-run" in b)
    first, second = (line for line in block.splitlines() if line.strip())
    assert re.fullmatch(
        r"systemd-run --on-active=\d+m systemctl start predigol-health.timer", first
    )
    assert second == "systemctl stop predigol-health.timer", "the safety net comes before the stop"
    safety = int(re.search(r"--on-active=(\d+)m", first)[1])  # type: ignore[index]
    assert safety > period + margin
    assert f"a los {safety} minutos el temporizador vuelve a arrancar" in flat


def test_what_the_text_says_the_scripts_print_is_what_they_print() -> None:
    flat = re.sub(r"\s+", " ", TEXT)
    alert_test = (BIN / "alert-test.sh").read_text(encoding="utf-8")
    assert "the server's alert bot" in alert_test and "`the server's alert bot`" in flat
    # what Telegram's refusal looks like, and what its codes mean
    assert "was NOT taken" in SCRIPT and "«was NOT taken»" in flat
    assert "401 or 404 above = the token is wrong or was revoked" in SCRIPT
    assert "400 or 403 = the bot may not write to that chat" in SCRIPT
    assert "401 o 404 es un token malo o revocado; 400 o 403, que el bot no puede escribir" in flat
    # what --evidence prints and where the drills are written
    assert '"| Disparo (UTC) | Qué | Clave o check |' in SCRIPT and "«Disparo»" in flat
    for stage in ("apertura", "recordatorio", "recuperado"):
        assert f'"{stage}"' in SCRIPT and stage in flat
    lib = (BIN / "lib.sh").read_text(encoding="utf-8")
    assert (
        'PREDIGOL_DATA="${PREDIGOL_DATA:-/srv/predigol}"' in lib
        and 'STATE="$PREDIGOL_DATA/state"' in lib
    )
    assert '"$REAL_STATE/drills.jsonl"' in SCRIPT and "`/srv/predigol/state/drills.jsonl`" in flat
    # the shape of every message: the bot's prefix, the word SIMULACRO, and the drill's own incident number
    assert "text=PrediGol ($(hostname)): $*" in lib
    assert 'notify_ok "SIMULACRO · $*"' in SCRIPT
    assert (
        "`PrediGol (nombre-del-servidor): SIMULACRO · [SEV1] clave: texto (INC-AAAA-9NN)`" in flat
    )
    # the Healthchecks drill: /fail, a wait of --hold seconds, the plain ping
    assert "ping_one fail" in SCRIPT and re.search(
        r"sleep \"\$HOLD\".*\n\s*if ping_one; then", SCRIPT
    )


# --- the shell blocks, run: a dry run through a stub of predigolctl, with stubs for everything that would reach outside -------------------------------------

BOT_TOKEN = "DRILLDOC-BOT-TOKEN-1"
CHAT_ID = "-100777000555"
PING_MARK = "PINGMARK"
HC_VARS = [f"HC_PING_{name.upper().replace('-', '_')}" for name in HC_NAMES]
STUBS = {
    # the dispatcher's arms the text shows: alert-drill is the real script told to send nothing, the others are only written down
    "predigolctl": 'printf "predigolctl %s\\n" "$*" >> "$STUB_LOG"\n'
    '[ "${1:-}" = alert-drill ] || exit 0\nshift\nexec bash "$DRILL" "$@" --dry-run\n',
    "systemctl": 'printf "systemctl %s\\n" "$*" >> "$STUB_LOG"\n[ "${1:-}" != is-active ] || echo active\n',
    "systemd-run": 'printf "systemd-run %s\\n" "$*" >> "$STUB_LOG"\n',
    # nothing may reach the network: a call is written down and fails
    "curl": 'printf "curl %s\\n" "$*" >> "$STUB_LOG"\ncat > /dev/null\nexit 7\n',
}


class Sandbox:
    """A server that is not one: the two environment files with made-up values, a data folder, and stubs first in the PATH."""

    def __init__(self, root: Path, *, ping_urls: bool = True) -> None:
        bins = root / "bin"
        bins.mkdir()
        (root / "data").mkdir()
        settings = [
            "PREDIGOL_DOMAIN=example.invalid",
            f"PREDIGOL_ALERT_BOT_TOKEN={BOT_TOKEN}",
            f"PREDIGOL_ALERT_CHAT_ID={CHAT_ID}",
        ]
        for var, name in zip(HC_VARS, HC_NAMES, strict=True):
            settings.append(
                f"{var}=https://hc.example.invalid/ping/{PING_MARK}-{name}"
                if ping_urls
                else f"{var}="
            )
        (root / "predigol.env").write_text("\n".join(settings) + "\n", encoding="utf-8")
        (root / "app.env").write_text("", encoding="utf-8")
        for name, body in STUBS.items():
            stub = bins / name
            stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.log = root / "stub.log"
        self.root = root
        self.env = {
            "PATH": f"{bins}:{os.environ['PATH']}",
            "HOME": str(root),
            "LC_ALL": "C.UTF-8",
            "PREDIGOL_ENV_FILE": str(root / "predigol.env"),
            "PREDIGOL_APP_ENV_FILE": str(root / "app.env"),
            "PREDIGOL_DATA": str(root / "data"),
            "STUB_LOG": str(self.log),
            "DRILL": str(DRILL),
        }

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv),
            env=self.env,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=180,
            stdin=subprocess.DEVNULL,
            check=False,
        )

    def drill(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run("bash", str(DRILL), *args)

    def stubbed_calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def assert_nothing_secret_was_printed(done: subprocess.CompletedProcess[str]) -> None:
    out = done.stdout + done.stderr
    for secret in (BOT_TOKEN, CHAT_ID.lstrip("-"), PING_MARK):
        assert secret not in out, f"the output holds {secret!r}"


DRY_MESSAGE = re.compile(
    r"WOULD SEND: SIMULACRO · \[(?:SEV[123]|SEV1 sigue abierto desde las \d\d:\d\d UTC|recuperado)\] "
    r"[a-z0-9_.-]+(?:: .+| tras \d+ min) \(INC-\d{4}-9\d\d\)"
)


def would_send(done: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in done.stdout.splitlines() if line.startswith("WOULD SEND:")]


@needs_tools
@pytest.mark.parametrize("index", range(len(blocks("bash"))))
def test_every_shell_block_of_the_document_runs_in_a_dry_run(sandbox: Sandbox, index: int) -> None:
    """The blocks are what the session runs: each one must parse, every command in it must be accepted (alert-drill is the real script, told to send
    nothing), nothing may reach the network, and nothing secret may be printed."""
    assert len(blocks("bash")) >= 10, "the document lost shell blocks"
    block = blocks("bash")[index]
    done = sandbox.run("bash", "-e", "-o", "pipefail", "-c", block)
    assert done.returncode == 0, (
        f"block {index} failed:\n{block}\n{done.stdout[-800:]}\n{done.stderr[-800:]}"
    )
    calls = sandbox.stubbed_calls()
    assert calls, "the block called nothing"
    assert not [c for c in calls if c.startswith("curl")], (
        "a block of the document reached the network"
    )
    assert {c.split()[1] for c in calls if c.startswith("predigolctl")} <= dispatcher()
    assert_nothing_secret_was_printed(done)
    for line in would_send(done):
        assert DRY_MESSAGE.fullmatch(line), line


@needs_tools
def test_every_alert_drill_command_in_the_prose_is_accepted_by_the_script(sandbox: Sandbox) -> None:
    """Table B's commands and the ones in a sentence: the script, not this test, says whether the options and the names are right."""
    commands = {
        tuple(tokens[1:])
        for tokens in predigolctl_calls(only_prose=True)
        if tokens[0] == "alert-drill" and not any("$" in t for t in tokens)
    }
    assert {("--healthchecks", name) for name in HC_NAMES} <= commands
    for args in sorted(commands):
        done = sandbox.drill(*args, "--dry-run")
        assert done.returncode == 0, f"alert-drill {' '.join(args)}: {done.stderr[-400:]}"
    assert not [c for c in sandbox.stubbed_calls() if c.startswith("curl")]


@needs_tools
def test_all_in_a_dry_run_shows_the_record_and_the_incident_numbers_the_text_promises(
    sandbox: Sandbox,
) -> None:
    done = sandbox.drill("--all", "--dry-run")
    assert done.returncode == 0, done.stderr
    sends = would_send(done)
    assert len(sends) == len(record()) == 36
    assert all(DRY_MESSAGE.fullmatch(line) for line in sends)
    numbers = [int(re.search(r"INC-\d{4}-(\d+)\)$", line)[1]) for line in sends]  # type: ignore[index]
    assert numbers == list(range(901, 937))
    shown = []
    for line in sends:
        key, sev = re.search(r"\[(SEV\d)\] (\S+):", line)[2], re.search(r"\[(SEV\d)\]", line)[1]  # type: ignore[index]
        service = re.fullmatch(rf"svc\.(?:{'|'.join(SERVICES)})(\.loop)?", key)
        shown.append((f"svc.<nombre>{service[1] or ''}" if service else key, sev))
    assert sorted(shown) == sorted(record())
    assert_nothing_secret_was_printed(done)


@needs_tools
def test_a_full_drill_has_the_messages_the_text_describes(sandbox: Sandbox) -> None:
    """«un SEV1 completo: apertura, recordatorio y recuperación»; «un SEV2 con su "recuperado"», that says «tras 0 min» when the hold is short."""
    done = sandbox.drill("worker.heartbeat", "--reminder", "--dry-run")
    first, again, last = would_send(done)
    assert "[SEV1] worker.heartbeat:" in first
    assert "[SEV1 sigue abierto desde las" in again and "UTC] worker.heartbeat:" in again
    assert "[recuperado] worker.heartbeat tras 0 min (INC-" in last
    done = sandbox.drill("disk.usage", "SEV2", "--hold", "30", "--dry-run")
    opening, recovered = would_send(done)
    assert "[SEV2] disk.usage: el disco está al 83 %" in opening
    assert "[recuperado] disk.usage tras 0 min" in recovered
    assert "tras 0 min" in TEXT and "a los 20 segundos y dice «tras 0 min»" in re.sub(
        r"\s+", " ", TEXT
    )


@needs_tools
def test_a_severity_the_alert_never_has_is_refused_before_anything_is_sent(
    sandbox: Sandbox,
) -> None:
    """In a real run, with the stub of curl standing for Telegram: the call is refused by the script, so nothing reaches curl."""
    assert not [r for r in table_a() if r[1] == "`disk.usage`" and r[2] == "SEV3"]
    assert "(`disk.usage SEV3`) se rechaza antes de enviar nada" in re.sub(r"\s+", " ", TEXT)
    done = sandbox.drill("disk.usage", "SEV3")
    assert done.returncode == 2 and "never raised at SEV3" in done.stderr
    assert sandbox.stubbed_calls() == []


@needs_tools
def test_the_healthchecks_dry_run_names_the_variable_and_never_prints_the_url(
    sandbox: Sandbox, tmp_path_factory: pytest.TempPathFactory
) -> None:
    for var, name in zip(HC_VARS, HC_NAMES, strict=True):
        done = sandbox.drill("--healthchecks", name, "--dry-run")
        assert done.returncode == 0 and f"WOULD PING: {var} /fail" in done.stdout, done.stderr
        assert_nothing_secret_was_printed(done)
    unset = Sandbox(tmp_path_factory.mktemp("sin-urls"), ping_urls=False)
    for var, name in zip(HC_VARS, HC_NAMES, strict=True):
        done = unset.drill("--healthchecks", name, "--dry-run")
        assert (
            done.returncode == 2 and f"{var} is empty in predigol.env" in done.stdout + done.stderr
        )
    assert unset.stubbed_calls() == []
