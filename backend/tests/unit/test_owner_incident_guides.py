"""Plan S3: the owner's incident-response guides send him to commands, queries and annexes that exist, and what they call "only look" cannot change anything.

``docs/owner/GUIAS_RESPUESTA_INCIDENTES.md`` is what the owner reads with a SEV1 on his phone. Whether its advice is wise no test can hold. What a test can
hold is that every ``predigolctl`` command the guides name is one the dispatcher has (and takes the flags used), that every "Guía N", "Anexo X" and query id
they point at is there, that the shell blocks parse, that the Caddy-log and incident-register commands give the answers the guide says on sample files, that
the blocks that "only look" cannot write, and that no command prints a secret. The SQL of Annex A runs against the real schema in
``tests/integration/test_owner_incident_guides_sql.py``."""

from __future__ import annotations

import gzip
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
GUIDE = BACKEND / "docs" / "owner" / "GUIAS_RESPUESTA_INCIDENTES.md"
BIN = BACKEND / "deploy" / "vps" / "bin"
ACCOUNTS = BACKEND / "scripts" / "accounts.py"

if not GUIDE.is_file():
    pytest.skip(f"no {GUIDE.name} next to the code", allow_module_level=True)

TEXT = GUIDE.read_text(encoding="utf-8")
FENCE = re.compile(r"^```([a-z]*)\n(.*?)^```", re.M | re.S)
PROSE = FENCE.sub("", TEXT)  # everything outside the fenced blocks
needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash is needed")
needs_jq = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None, reason="bash and jq are needed"
)


def blocks(lang: str) -> list[str]:
    return [body for tag, body in FENCE.findall(TEXT) if tag == lang]


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def section(heading: str) -> str:
    """The body of ``## heading ...`` up to the next ``## `` or ``# `` heading."""
    found = re.search(rf"^## {re.escape(heading)}.*?(?=^#{{1,2}} |\Z)", TEXT, flags=re.M | re.S)
    assert found, f"the guide has no section {heading!r}"
    return found.group(0)


def code_lines() -> list[str]:
    """Every command the guide shows: the lines of its shell blocks and its inline `code` spans (a span may wrap)."""
    lines = [line for body in blocks("bash") for line in body.splitlines()]
    return lines + [flat(span) for span in re.findall(r"`([^`]+)`", PROSE)]


# --- the shape: eight guides, nine annexes, in order ---------------------------------------------------------------------------------------------------


def test_the_guide_has_eight_guides_and_nine_annexes_in_order() -> None:
    assert re.findall(r"^## Guía (\d) · ", TEXT, flags=re.M) == list("12345678")
    assert re.findall(r"^## Anexo ([A-Z]) · ", TEXT, flags=re.M) == list("ABCDEFGHI")


def test_each_guide_stays_short_enough_to_read_under_stress() -> None:
    """About one page each: a guide that keeps growing stops being read. Guide 2 holds four cases (A to D) and is the longest."""
    limits = {2: 85}
    for number in range(1, 9):
        lines = section(f"Guía {number} · ").count("\n")
        assert lines <= limits.get(number, 65), (
            f"Guía {number} has {lines} lines: split it, or move the detail into an annex"
        )


def test_every_guide_ends_with_when_it_is_over_what_not_to_do_and_who_to_tell() -> None:
    for number in range(1, 9):
        body = section(f"Guía {number} · ")
        assert (
            re.search(r"\*\*(Terminó cuando|Cómo sé que terminó)", body)
            or "Cómo sé que terminó" in body
        ), f"Guía {number}: when it is over"
        assert "**No hagas**" in body, f"Guía {number}: what not to do"
        assert "**Avisar a:**" in body, f"Guía {number}: who to tell"


# --- the cross-references -----------------------------------------------------------------------------------------------------------------------------


def _query_ids() -> dict[str, set[str]]:
    """Which numbered items each annex defines: the SQL queries of A, the log commands of B, the register commands of E."""
    return {
        "A": {m[1] for body in blocks("sql") for m in re.finditer(r"^-- A(\d+)", body, flags=re.M)},
        "B": {
            m[1] for body in blocks("bash") for m in re.finditer(r"^# B(\d+)\.", body, flags=re.M)
        },
        "E": {
            m[1] for body in blocks("bash") for m in re.finditer(r"^# E(\d+)\.", body, flags=re.M)
        },
    }


def test_the_numbered_items_of_the_annexes_are_all_there() -> None:
    ids = _query_ids()
    assert ids["A"] == {str(n) for n in range(1, 13)}
    assert ids["B"] == {str(n) for n in range(1, 9)}
    assert ids["E"] == {"1", "2", "3"}


def test_every_guide_the_text_points_at_exists() -> None:
    mentioned: set[str] = set()
    for found in re.finditer(r"Gu[ií]as? ((?:\d(?:,| y| e)? ?)+)", TEXT):
        mentioned |= set(re.findall(r"\d", found[1]))
    assert mentioned and mentioned <= set("12345678"), (
        f"guides that do not exist: {sorted(mentioned - set('12345678'))}"
    )


def test_every_annex_and_numbered_item_the_text_points_at_exists() -> None:
    ids = _query_ids()
    annexes = set(re.findall(r"^## Anexo ([A-Z]) · ", TEXT, flags=re.M))
    wrong: list[str] = []
    for found in re.finditer(
        r"Anexos? ([A-Z])(\d{1,2})?\b(?:,| y| e) ([A-Z])(\d{1,2})?\b|Anexo ([A-Z])(\d{1,2})?\b",
        TEXT,
    ):
        pairs = [(found[1], found[2]), (found[3], found[4])] if found[1] else [(found[5], found[6])]
        for letter, number in pairs:
            if not letter:
                continue
            if letter not in annexes:
                wrong.append(f"Anexo {letter}")
            elif number and number not in ids.get(letter, set()):
                wrong.append(f"{letter}{number}")
    assert not wrong, f"references to something the annexes do not hold: {sorted(set(wrong))}"
    # a bare query id in the prose ("la consulta A9", "A1 y A6", "B4") must exist too
    bare = {(m[1], m[2]) for m in re.finditer(r"(?<![\w.-])([ABE])(\d{1,2})(?![\w.-])", PROSE)}
    missing = sorted(f"{letter}{number}" for letter, number in bare if number not in ids[letter])
    assert not missing, f"query ids the prose names and no annex defines: {missing}"


def test_the_sub_steps_the_guide_cites_are_in_the_guide_2_cases() -> None:
    body = section("Guía 2 · ")
    cases = set(re.findall(r"^\*\*([A-D])\. ", body, flags=re.M))
    assert cases == set("ABCD")
    for letter, number in re.findall(r"(?<![\w.])([A-D])\.(\d)\b", TEXT):
        if letter in "AD":  # B and C are paragraphs; A and D have numbered steps
            steps = re.search(
                rf"^\*\*{letter}\. .*?(?=^\*\*[A-D]\. |^\*\*Después|\Z)", body, flags=re.M | re.S
            )
            assert steps and re.search(rf"^{number}\. ", steps[0], flags=re.M), (
                f"{letter}.{number} is cited and the case has no such step"
            )


# --- the commands -------------------------------------------------------------------------------------------------------------------------------------------


def _dispatcher() -> set[str]:
    body = (
        (BIN / "predigolctl")
        .read_text(encoding="utf-8")
        .split('case "${1:-}" in', 1)[1]
        .split("\nesac", 1)[0]
    )
    return set(re.findall(r"^  ([a-z][a-z0-9-]*)\)", body, flags=re.M))


def _accounts_subcommands() -> set[str]:
    source = ACCOUNTS.read_text(encoding="utf-8")
    names = set(re.findall(r'sub\.add_parser\("([a-z-]+)"\)', source))
    for group in re.findall(r"for name in \(([^)]*)\)", source):
        names |= set(re.findall(r'"([a-z-]+)"', group))
    return names


def _pitr_subcommands() -> set[str]:
    source = (BIN / "pitr.sh").read_text(encoding="utf-8")
    return set(
        re.findall(r"^  ([a-z][a-z-]*)\) ", source.rsplit('case "${1:-}" in', 1)[1], flags=re.M)
    )


FLAG_SOURCES = {
    "accounts": ACCOUNTS,
    "pitr": BIN / "pitr.sh",
    "backup": BIN / "backup.sh",
    "prune": BIN / "prune.sh",
    "health": BIN / "healthcheck.sh",
    "restore-test": BIN / "restore-test.sh",
    "incident": BIN / "incident.sh",
    "create-user": BACKEND / "scripts" / "create_user.py",
}
SERVICES = {"postgres", "api", "worker", "web", "caddy"}


def predigolctl_calls() -> list[list[str]]:
    calls: list[list[str]] = []
    for line in code_lines():
        for found in re.finditer(r"predigolctl\b([^|;&`)]*)", line):
            rest = found[1].split(" #")[0]
            try:
                tokens = shlex.split(rest)
            except ValueError:
                tokens = rest.split()
            tokens = [t for t in tokens if ">" not in t]
            if tokens:
                calls.append(tokens)
    return calls


def test_the_guide_names_a_fair_number_of_commands() -> None:
    """A guard on the extraction itself: if the regular expressions stop finding commands, the checks below would pass on nothing."""
    calls = predigolctl_calls()
    assert len(calls) >= 30
    assert {
        "accounts",
        "pitr",
        "logs",
        "status",
        "health",
        "stop",
        "up",
        "backup",
        "psql",
        "rollback",
    } <= {c[0] for c in calls}


def test_every_predigolctl_command_exists_and_takes_the_flags_the_guide_uses() -> None:
    top, accounts, pitr = _dispatcher(), _accounts_subcommands(), _pitr_subcommands()
    assert {"accounts", "pitr", "psql", "logs", "rollback", "prune"} <= top, (
        "predigolctl's dispatcher no longer has the shape this test reads"
    )
    assert {
        "list",
        "disable",
        "unlock",
        "revoke-sessions",
        "mfa-reset",
        "require-password-change",
    } <= accounts
    assert {"status", "recover", "restore"} <= pitr
    problems: list[str] = []
    for tokens in predigolctl_calls():
        command = tokens[0]
        if command not in top:
            problems.append(f"predigolctl {command}: the dispatcher has no such command")
            continue
        if command == "accounts" and len(tokens) > 1 and tokens[1] not in accounts:
            problems.append(f"predigolctl accounts {tokens[1]}: no such subcommand")
        if command == "pitr" and len(tokens) > 1 and tokens[1] not in pitr:
            problems.append(f"predigolctl pitr {tokens[1]}: no such subcommand")
        if (
            command == "logs"
            and len(tokens) > 1
            and re.fullmatch(r"[a-z]+", tokens[1])
            and tokens[1] not in SERVICES
        ):
            problems.append(f"predigolctl logs {tokens[1]}: not one of the five services")
        source = FLAG_SOURCES.get(command, BIN / "predigolctl").read_text(encoding="utf-8")
        for flag in (t for t in tokens if t.startswith("--")):
            if flag not in source:
                problems.append(
                    f"predigolctl {' '.join(tokens[:2])}: {flag} is not a flag of {FLAG_SOURCES.get(command, BIN / 'predigolctl').name}"
                )
    assert not problems, "\n".join(sorted(set(problems)))


def test_the_incident_commands_the_guide_shows_are_the_ones_incident_sh_has() -> None:
    """Annex E sends the owner to ``predigolctl incident list|show|note|severity|open|close``. Each is a branch of incident.sh's dispatcher, the fields of
    ``note`` are the ones the script accepts AND the ones the table's CHECK allows (three lists that must stay one), and an ``open`` names a service the script knows."""
    source = (BIN / "incident.sh").read_text(encoding="utf-8")
    branches = set(
        re.findall(
            r"^  ([a-z]+)\) shift; cmd_", source.rsplit('case "${1:-}" in', 1)[1], flags=re.M
        )
    )
    assert branches == {"list", "show", "note", "severity", "open", "close"}
    fields = re.search(r'^FIELDS="([^"]+)"', source, flags=re.M)
    services = re.search(r'^SERVICES="([^"]+)"', source, flags=re.M)
    assert fields and services, (
        "incident.sh no longer declares FIELDS and SERVICES the way this test reads"
    )
    calls = [c[1:] for c in predigolctl_calls() if c[0] == "incident" and len(c) > 1]
    assert {c[0] for c in calls} == branches, (
        "Annex E must show every incident command at least once"
    )
    for call in calls:
        if call[0] == "note":
            assert call[2] in fields[1].split(), (
                f"predigolctl incident note ... {call[2]}: not a field of incident.sh"
            )
        if call[0] == "open":
            assert call[1] in services[1].split(), (
                f"predigolctl incident open {call[1]}: not a service of incident.sh"
            )
            assert call[2] in {"SEV1", "SEV2", "SEV3"}, f"open with severity {call[2]}"
        for token in call:
            if token.startswith("INC-"):
                assert re.fullmatch(r"INC-\d{4}-\d{3}", token), f"not an incident id: {token}"
    named = re.search(r"Los campos de `note` son (.*?):", flat(PROSE))
    assert named, "Annex E no longer lists the fields of note"
    assert set(re.findall(r"`([a-z_]+)`", named[1])) == set(fields[1].split())
    migration = next((BACKEND / "migrations" / "versions").glob("*_incident_register.py"), None)
    assert migration, "the incident register's migration is not in migrations/versions"
    in_table = re.search(
        r"CHECK \(field IS NULL OR field IN \(([^)]*)\)", migration.read_text(encoding="utf-8")
    )
    assert in_table, "the migration no longer has the CHECK this test reads"
    assert set(re.findall(r"'([a-z_]+)'", in_table[1])) == set(fields[1].split())


def test_the_account_commands_that_change_things_say_which_accounts() -> None:
    """``accounts disable`` and ``revoke-sessions`` refuse to run without a target, but a guide that shows the bare command invites the wrong reading."""
    for tokens in predigolctl_calls():
        if (
            tokens[0] == "accounts"
            and len(tokens) > 1
            and tokens[1] in {"disable", "revoke-sessions", "unlock", "mfa-reset"}
        ):
            assert any(t in {"--email", "--all", "--domain"} for t in tokens), (
                f"no target in: predigolctl {' '.join(tokens)}"
            )


def test_the_wipes_and_the_resets_the_guide_warns_against_appear_only_after_a_no_hagas() -> None:
    """Dangerous words may be named, but only inside a "No hagas" list: a step that tells the owner to run them would be a bug."""
    forbidden = (
        "pg_resetwal",
        "down -v",
        "prune --volumes",
        "rm -rf /srv/predigol",
        "DROP DATABASE",
        "TRUNCATE",
    )
    for needle in forbidden:
        for found in re.finditer(re.escape(needle), TEXT):
            before = TEXT[: found.start()]
            last_no_hagas = before.rfind("**No hagas**")
            last_heading = max(
                before.rfind("\n## "),
                before.rfind("\n**A. "),
                before.rfind("\n**B. "),
                before.rfind("\n**C. "),
                before.rfind("\n**D. "),
            )
            sentence = TEXT[max(0, found.start() - 160) : found.end() + 40]
            warns = re.search(r"\b(Nada de|nada de|No |no |Jamás|jamás|nunca|Nunca|NO)", sentence)
            assert (last_no_hagas > last_heading) or warns, (
                f"{needle!r} appears as a step, not as a warning: …{flat(sentence)}…"
            )


# --- the shell blocks ---------------------------------------------------------------------------------------------------------------------------------------


@needs_bash
@pytest.mark.parametrize("body", blocks("bash"), ids=lambda b: flat(b)[:40])
def test_every_shell_block_parses(body: str) -> None:
    done = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_the_sql_blocks_are_single_selects_and_write_nothing() -> None:
    statements = 0
    for body in blocks("sql"):
        code = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("--"))
        assert not re.search(
            r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|vacuum|call|do)\b",
            code,
            flags=re.I,
        ), body
        for statement in (s.strip() for s in code.split(";")):
            if statement:
                statements += 1
                assert statement.upper().startswith("SELECT"), f"not a SELECT: {statement[:60]}"
    assert statements >= 12


def test_the_looking_block_of_annex_f_changes_nothing() -> None:
    """F.1 is sold as "only look": no command that stops, kills, deletes, restarts, writes a file or opens a shell in a container."""
    looking = next(body for body in blocks("bash") if "last -a -n 20" in body)
    forbidden = (
        r"\brm\b",
        r"\bmv\b",
        r"\bkill",
        r"\bsystemctl (stop|start|restart|disable|enable|mask|daemon)",
        r"\bdocker (stop|start|rm|kill|restart|exec|run|compose)",
        r"\biptables\b",
        r"\bchmod\b",
        r"\bchown\b",
        r"\bsed -i",
        r"\btee\b",
        r"\bdd\b",
        r"(?<![0-9&>-])>(?![&=>])(?! ?/dev/null)",  # a redirect to a file (not 2>/dev/null, 2>&1 or awk's >=)
    )
    for pattern in forbidden:
        assert not re.search(pattern, looking), f"F.1 must only look, but matches {pattern!r}"


def test_the_only_iptables_changes_are_in_annex_c() -> None:
    for number in range(1, 9):
        body = section(f"Guía {number} · ")
        assert not re.search(r"iptables -[IAD]\b", body), (
            f"Guía {number} carries an iptables change: it belongs in Annex C"
        )
    assert re.search(r"iptables -I DOCKER-USER", section("Anexo C · "))


def test_no_command_prints_a_secret() -> None:
    """Nothing in the guide sends the owner to show a key, a password or a token: no cat of an env file or of the credentials file, no printenv, no grep for a secret's name."""
    forbidden = (
        r"\bcat\b[^|]*(\.env\b|/etc/predigol|predigol-credentials|authorized_keys\b.*\bsecret)",
        r"\bprintenv\b",
        r"(?<![\w.-])env\s*(\||$)",
        r"\bdocker (inspect|exec)\b[^|]*\benv\b",
        r"\bgrep\b[^|]*\b\w*(SECRET|TOKEN|PASSWORD|API_KEY)\w*\b[^|]*(\.env|/etc/predigol)",
        r"\becho\s+\"?\$\{?\w*(SECRET|TOKEN|PASSWORD|KEY)",
    )
    for line in code_lines():
        for pattern in forbidden:
            assert not re.search(pattern, line), f"a command that can print a secret: {line}"
    mentions = [line for line in code_lines() if "/etc/predigol/" in line]
    assert all("PREDIGOL_DOMAIN" in line for line in mentions), (
        "the only env file the guide reads is for the domain name, which is public"
    )


# --- the Caddy-log and the incident-register commands, on sample files ---------------------------------------------------------------------------


def _line(ts: float, status: int, method: str, uri: str, ip: str, agent: str = "curl/8.5.0") -> str:
    """One line of Caddy's JSON access log, with the fields the real one has (checked on a real log)."""
    request = {
        "remote_ip": ip,
        "client_ip": ip,
        "proto": "HTTP/2.0",
        "method": method,
        "host": "predigolai.com",
        "uri": uri,
        "headers": {"User-Agent": [agent]},
    }
    return json.dumps(
        {
            "level": "info",
            "ts": ts,
            "logger": "http.log.access.log0",
            "msg": "handled request",
            "request": request,
            "status": status,
            "duration": 0.01,
        }
    )


SWEEPER, VICTIM, OTHER = "203.0.113.7", "198.51.100.1", "198.51.100.2"


@pytest.fixture()
def caddy_dir(tmp_path: Path) -> Path:
    now = time.time()
    rows = (
        [
            (now - 60 - i, 200, "GET", "/api/v1/matches?token=SECRET", VICTIM, "Mozilla/5.0")
            for i in range(6)
        ]
        + [
            (now - 50 - i, 500, "GET", "/api/v1/picks?x=SECRET", OTHER, "Mozilla/5.0")
            for i in range(2)
        ]
        + [(now - 40, 502, "POST", "/api/v1/other", OTHER, "Mozilla/5.0")]
        + [
            (now - 30 - i, 401, "POST", "/api/v1/auth/login?x=1", SWEEPER, "sqlmap/1.7")
            for i in range(5)
        ]
        + [
            (now - 25 - i, 429, "POST", "/api/v1/auth/mfa/verify", SWEEPER, "sqlmap/1.7")
            for i in range(2)
        ]
        + [(now - 20, 200, "POST", "/api/v1/auth/login", VICTIM, "Mozilla/5.0")]
        + [
            (now - 18, 401, "GET", "/api/v1/auth/login", SWEEPER, "curl/8.5.0")
        ]  # a GET: not an attempt to sign in
        + [
            (now - 15 - i, 403, "GET", "/api/v1/admin/users?q=SECRET", SWEEPER, "sqlmap/1.7")
            for i in range(3)
        ]
        + [(now - 10, 401, "POST", "/api/v1/admin/x", "203.0.113.8", "curl/8.5.0")]
        + [
            (now - 5, 200, "GET", "/api/v1/admin/users", VICTIM, "Mozilla/5.0")
        ]  # allowed: not counted by admin.denied
        + [
            (now - 3600, 500, "GET", "/api/v1/old", "198.51.100.9", "Mozilla/5.0")
        ]  # an hour old: outside the 15 minutes
    )
    (tmp_path / "access.log").write_text(
        "\n".join(_line(*row) for row in sorted(rows, key=lambda r: r[0])) + "\n", encoding="utf-8"
    )
    old = [
        _line(1_761_473_000.0, 503, "GET", "/api/v1/rotated?x=SECRET", "198.51.100.9"),
        _line(1_761_473_001.0, 200, "GET", "/ok", "198.51.100.9"),
    ]
    with gzip.open(
        tmp_path / "access-2026-10-26T10-00-00.000-size.log.gz", "wt", encoding="utf-8"
    ) as handle:
        handle.write("\n".join(old) + "\n")
    return tmp_path


def run_block(marker: str, caddy_dir: Path, *, extra: str = "") -> str:
    """Run the guide's variables block plus the annex block that begins ``# <marker>.``, with the log folder moved to ``caddy_dir``."""
    preamble = next(body for body in blocks("bash") if body.startswith("LOG="))
    block = next(body for body in blocks("bash") if body.startswith(f"# {marker}."))
    script = (preamble + extra + block).replace("/srv/predigol/caddy/data", str(caddy_dir))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def counted(output: str) -> dict[str, int]:
    """``uniq -c`` output as {key: count}."""
    return {
        line.strip().split(" ", 1)[1].strip(): int(line.strip().split(" ", 1)[0])
        for line in output.splitlines()
        if line.strip()
    }


@needs_jq
def test_b1_counts_the_answers_of_the_last_quarter_of_an_hour(caddy_dir: Path) -> None:
    got = counted(run_block("B1", caddy_dir))
    assert got == {
        "200": 8,
        "500": 2,
        "502": 1,
        "401": 7,
        "429": 2,
        "403": 3,
    }  # the hour-old 500 is left out


@needs_jq
def test_b2_names_the_routes_that_fail_without_the_query_string(caddy_dir: Path) -> None:
    out = run_block("B2", caddy_dir)
    assert counted(out) == {"500 GET /api/v1/picks": 2, "502 POST /api/v1/other": 1}
    assert "SECRET" not in out and "?" not in out


@needs_jq
def test_b3_and_b4_and_b5_say_who_asks_and_who_is_refused(caddy_dir: Path) -> None:
    assert counted(run_block("B3", caddy_dir)) == {
        VICTIM: 8,
        OTHER: 3,
        SWEEPER: 11,
        "203.0.113.8": 1,
    }
    assert counted(run_block("B4", caddy_dir)) == {
        f"401 {SWEEPER}": 5,
        f"429 {SWEEPER}": 2,
        f"200 {VICTIM}": 1,
    }
    assert counted(run_block("B5", caddy_dir)) == {SWEEPER: 3, "203.0.113.8": 1}


@needs_jq
def test_b6_and_b7_follow_one_address_without_the_query_string(caddy_dir: Path) -> None:
    out = run_block("B6", caddy_dir)
    lines = out.splitlines()
    assert len(lines) == 11
    assert all(re.fullmatch(r"\d\d:\d\d:\d\d \d{3} [A-Z]+ /\S*", line) for line in lines), lines
    assert "SECRET" not in out and "?" not in out
    agents = counted(run_block("B7", caddy_dir, extra=f"IP={SWEEPER}\n"))
    assert agents == {"sqlmap/1.7": 10, "curl/8.5.0": 1}


@needs_jq
def test_b8_reads_the_rotated_files_and_prints_their_dates_in_utc(caddy_dir: Path) -> None:
    out = run_block("B8", caddy_dir)
    assert "2025-10-26T10:03:20Z 503 /api/v1/rotated" in out
    assert "SECRET" not in out and "/ok" not in out


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    """The incident register as the S3 alerts write it: events appended to incidents.jsonl, open alerts in alerts.json."""
    events = [
        {
            "at": "2026-10-26T10:00:00Z",
            "event": "open",
            "incident": "INC-2026-014",
            "key": "svc.api",
            "service": "api",
            "severity": "SEV1",
            "text": "api is down",
        },
        {
            "at": "2026-10-26T10:05:00Z",
            "event": "open",
            "incident": "INC-2026-015",
            "key": "disk.root",
            "service": "host",
            "severity": "SEV2",
            "text": "disk at 82%",
        },
        {
            "at": "2026-10-26T10:12:00Z",
            "event": "close",
            "incident": "INC-2026-014",
            "key": "svc.api",
            "service": "api",
            "severity": "SEV1",
            "text": "recovered",
            "minutes": 12,
        },
    ]
    (tmp_path / "incidents.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    alerts = {
        "disk.root": {
            "sev": "SEV2",
            "text": "disk at 82%",
            "since": "2026-10-26T10:05:00Z",
            "incident": "INC-2026-015",
            "last_sent": "2026-10-26T10:05:00Z",
            "owner": "",
        }
    }
    (tmp_path / "alerts.json").write_text(json.dumps(alerts), encoding="utf-8")
    return tmp_path


def run_register(marker: str, state_dir: Path) -> str:
    block = next(body for body in blocks("bash") if "# E1." in body)
    lines = block.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"# {marker}."))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("# E")), len(lines))
    script = "\n".join(lines[start:end]).replace("/srv/predigol/state", str(state_dir))
    done = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False, timeout=60
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


@needs_jq
def test_e1_e2_e3_read_the_register_the_way_the_guide_says(state_dir: Path) -> None:
    last = run_register("E1", state_dir).splitlines()
    assert last[0] == "2026-10-26T10:00:00Z open INC-2026-014 SEV1 svc.api: api is down"
    assert last[-1] == "2026-10-26T10:12:00Z close INC-2026-014 SEV1 svc.api: recovered"
    assert run_register("E2", state_dir).splitlines() == [
        "INC-2026-015 SEV2 disk.root desde 2026-10-26T10:05:00Z: disk at 82%"
    ]
    history = run_register("E3", state_dir).splitlines()
    assert history == [
        "2026-10-26T10:00:00Z open api is down",
        "2026-10-26T10:12:00Z close recovered",
    ]


# --- the numbers the guide quotes from the code ------------------------------------------------------------------------------------------------------


WORDS = {5: "cinco", 30: "treinta"}


def test_the_protections_guide_7_lists_are_the_ones_in_the_code() -> None:
    """Guide 7 tells the owner what already protects him: how many failures lock an account, how many reach a 429, how fast the API lets one address go.
    If the code changes, the guide must."""
    guide = flat(section("Guía 7 · ")).lower()
    source = BACKEND / "src" / "fbi"
    settings = (source / "auth" / "settings.py").read_text(encoding="utf-8")
    throttle = (source / "auth" / "throttle.py").read_text(encoding="utf-8")
    app = (source / "api" / "app.py").read_text(encoding="utf-8")

    def field(name: str) -> int:
        found = re.search(rf"{name}: int = Field\(default=(\d+)", settings)
        assert found, f"auth/settings.py no longer declares {name} the way this test reads"
        return int(found[1])

    by_client = re.search(
        r"BY_CLIENT = FailureWindow\(max_failures=(\d+), window_s=(\d+) \* 60\)", throttle
    )
    general = re.search(r'"FBI_API_RATE_LIMIT", "(\d+)"', app)
    login = re.search(r'"FBI_API_LOGIN_RATE_LIMIT", "(\d+)"', app)
    assert by_client and general and login, (
        "the throttles or the rate limits no longer have the shape this test reads"
    )
    threshold, minutes, longest = (
        field("lock_threshold"),
        field("lock_minutes"),
        field("lock_max_minutes"),
    )
    assert (
        f"{WORDS[threshold]} contraseñas o códigos malos seguidos bloquean esa cuenta {minutes} minutos"
        in guide
    )
    assert f"el bloqueo se duplica, hasta {longest // 60} horas" in guide
    # since UX A1 the lock of an address is the account's rule, applied to EVERY address (the streak lives in the database): there is no window per
    # e-mail any more, and the guide must not quote one
    assert "BY_EMAIL" not in throttle and "def lock_minutes(streak: int" in throttle
    assert "la misma regla vale para cualquier correo que se escriba, tenga cuenta o no" in guide
    assert (
        f"{WORDS[threshold]} fallos seguidos con un mismo correo lo hacen esperar {minutes} minutos, y el bloqueo se duplica igual"
        in guide
    )
    assert (
        f"{WORDS[int(by_client[1])]} fallos en {by_client[2]} minutos desde una misma dirección"
        in guide
    )
    assert f"unas {login[1]} peticiones por minuto" in guide
    assert f"el resto de la api, unas {general[1]}" in guide
    assert (
        'mfa_roles: str = "SUPER_ADMIN"' in settings
        and "una cuenta super_admin, además de la contraseña, necesita el código" in guide
    )


# --- the alerts: the table "El mensaje dice… → guía" and the scripts that raise them ---------------------------------------------------------------


ALERT_SCRIPTS = ("healthcheck.sh", "alerts_checks.sh", "security-alerts.sh", "incident-dump.sh")
ALERT_CALL = re.compile(
    r'\b(?:alert_set|alert_unless_deploy)\s+("[^"]+"|[A-Za-z][\w.]*)\s+(SEV[123])\b'
)


def alerts_in_the_code() -> dict[str, set[str]]:
    """Every alert key the server's scripts can raise, with the severities they raise it at ("svc.$svc" is the guide's "svc.<nombre>")."""
    found: dict[str, set[str]] = {}
    for name in ALERT_SCRIPTS:
        for key, severity in ALERT_CALL.findall((BIN / name).read_text(encoding="utf-8")):
            found.setdefault(key.strip('"').replace("$svc", "<nombre>"), set()).add(severity)
    return found


def alerts_in_the_table() -> dict[str, set[str]]:
    """The keys in the first column of the table, with the severities written next to them: "(SEV2)" after a key, or after the group of keys before it."""
    found: dict[str, set[str]] = {}
    pending: list[str] = []
    for row in section("El mensaje dice").splitlines():
        if not row.startswith("| ") or row.startswith(("| ---", "| Clave")):
            continue
        pending = []
        for token in re.finditer(
            r"`(?P<key>[a-z][a-z0-9_<>]*(?:\.[a-z0-9_<>]+)+)`|\((?P<note>[^)]*SEV[^)]*)\)",
            row.split("|")[1],
        ):
            if token["key"]:
                pending.append(token["key"])
                found.setdefault(token["key"], set())
            else:
                for key in pending:
                    found[key] |= set(re.findall(r"SEV[123]", token["note"]))
                pending = []
    return found


def test_the_table_of_alerts_names_every_alert_the_server_can_raise_and_only_those() -> None:
    """The owner reads the message at the worst moment and looks its key up here. An alert the table does not list sends him to nothing (`incidents.dump`
    was added to the scripts one day before the table knew it); a key that no script raises is a promise nobody keeps."""
    code, table = alerts_in_the_code(), alerts_in_the_table()
    assert len(code) >= 30, "the scripts no longer have the shape this test reads"
    assert set(code) - set(table) == set(), "raised by the scripts and missing from the table"
    assert set(table) - set(code) == set(), "in the table and raised by no script"


def test_the_severity_the_table_writes_is_the_most_severe_one_the_code_raises() -> None:
    """Where the table writes a severity it may name fewer levels than the code uses (a probe that cannot find its route is a SEV3 of api.login), but never
    one the code does not raise, and never a milder top level than the one the owner will be woken by."""
    code, table = alerts_in_the_code(), alerts_in_the_table()
    wrong = {
        key: (sorted(written), sorted(code[key]))
        for key, written in table.items()
        if written and (not written <= code[key] or min(written) != min(code[key]))
    }
    assert not wrong, f"table vs code (severities): {wrong}"
    assert sum(1 for written in table.values() if written) >= 20, (
        "the table no longer writes the severities this test reads"
    )
