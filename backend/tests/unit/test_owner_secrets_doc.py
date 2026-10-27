"""Plan S3: the owner's inventory of secrets says what the code has.

``docs/owner/SECRETS_AND_ROTATION.md`` is what the owner opens the day a key leaks or a rotation falls due. Whether its advice is wise no test can hold. What a
test can hold is that the document and the code do not drift apart: every secret the two example files define is in the inventory, the file the inventory
names for a secret is the file that defines it, every setting the text names exists, every "how to change it" points at a paragraph that is there (and every
paragraph is pointed at), the incident guide cites only paragraphs that exist, the commands shown are commands the dispatcher has, the properties it claims
("no container receives the alert bot or the ping URLs", "the example files hold no value") are the ones the code has, and no value of any secret is in the text.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
DOC = BACKEND / "docs" / "owner" / "SECRETS_AND_ROTATION.md"
GUIDE = BACKEND / "docs" / "owner" / "GUIAS_RESPUESTA_INCIDENTES.md"
KIT = BACKEND / "deploy" / "vps"
BIN = KIT / "bin"
ACCOUNTS = BACKEND / "scripts" / "accounts.py"
EXAMPLES = {"predigol.env": KIT / "predigol.env.example", "app.env": KIT / "app.env.example"}

# bin/pitr-enable.sh belongs to step W2 of S2 (point-in-time recovery), which comes AFTER the package of the alerts (S3): a tree that does not have it yet
# still has the document that describes it (the PITR is part of the final state, and the text only says what happens once it is on), so the checks that
# read the script run as soon as the script is in the tree, and the day W2 arrives they hold the document to it.
W2_SCRIPTS = frozenset({"pitr-enable.sh"})
W2_IN_TREE = all((BIN / name).is_file() for name in W2_SCRIPTS)

if not DOC.is_file():
    pytest.skip(f"no {DOC.name} next to the code", allow_module_level=True)

TEXT = DOC.read_text(encoding="utf-8")


def section(heading: str) -> str:
    found = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", TEXT, flags=re.M | re.S)
    assert found, f"the document has no section {heading!r}"
    return found.group(1)


INVENTORY = section("Inventario")
ROTATION = section("Cómo se rota cada uno")
NAME = re.compile(r"[A-Z][A-Z0-9_]*\*?")


def settings(path: Path) -> dict[str, str]:
    """Every ``NAME=value`` of an example file, active or commented out, with its value (the text after the first ``=`` up to the first blank)."""
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=(\S*)", line)
        if m:
            found.setdefault(m[1], m[2])
    return found


def is_secret_like(name: str) -> bool:
    return bool(re.search(r"PASSWORD|PASS$|SECRET|TOKEN|DSN|_KEY(_|$)", name)) or name.startswith(
        "HC_PING_"
    )


def inventory_rows() -> list[list[str]]:
    rows = []
    for line in INVENTORY.splitlines():
        if line.startswith("|") and not re.match(r"^\|[-| ]+\|$", line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows[1:]  # without the header


def names_in(cell: str) -> list[str]:
    """The settings a cell names: its `BACKTICKED` words that look like a setting (``HC_PING_*`` is a family)."""
    return [t for t in re.findall(r"`([^`]+)`", cell) if NAME.fullmatch(t)]


def rotation_titles() -> list[str]:
    return re.findall(r"^\*\*(.+?)\.\*\*", ROTATION, flags=re.M)


def paragraph(title: str) -> str:
    """A paragraph of the rotation section: from its bold title (``**Title.** ``) up to the next one (its steps and bullets included; a bold phrase
    that happens to start a wrapped line is not a title)."""
    found = re.search(
        rf"^\*\*{re.escape(title)}.*?(?=^\*\*[^\n]*?\.\*\* |\Z)", ROTATION, flags=re.M | re.S
    )
    assert found, f"the rotation section has no paragraph that starts with {title!r}"
    return found.group(0)


def code_spans(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", s).strip() for s in re.findall(r"`([^`]+)`", text)]


# --- the shape -----------------------------------------------------------------------------------------------------------------------------------------


def test_the_inventory_has_five_filled_columns_in_every_row() -> None:
    rows = inventory_rows()
    assert len(rows) >= 15, "the inventory lost rows"
    for row in rows:
        assert len(row) == 5, f"a row without five columns: {row}"
        assert all(row), f"an empty cell in: {row[0]}"


def test_the_document_never_shows_a_value() -> None:
    """Names, never values: nothing in the text has the shape of a key, a token, an ping URL, a DSN or a private key."""
    patterns = {
        "a long hexadecimal run": r"\b[0-9a-fA-F]{32,}\b",
        "an age private key": r"AGE-SECRET-KEY-",
        "an age public key": r"\bage1[0-9a-z]{50,}\b",
        "a Telegram token": r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",
        "a Healthchecks ping URL": r"hc-ping\.com/[0-9a-fA-F-]{8,}",
        "an Anthropic key": r"\bsk-ant-",
        "a Sentry DSN": r"https://[0-9a-f]{16,}@",
        "a base64 string of key length": r"\b[A-Za-z0-9+/]{43}=(?![A-Za-z0-9+/])",
    }
    for what, pattern in patterns.items():
        assert not re.search(pattern, TEXT), f"the document holds {what}"


def test_the_example_files_hold_no_secret_value() -> None:
    for path in EXAMPLES.values():
        full = [n for n, v in settings(path).items() if is_secret_like(n) and v]
        assert not full, f"{path.name} has a value for {full}: an example holds names only"


# --- the document and the example files ----------------------------------------------------------------------------------------------------------------


def test_every_secret_of_the_two_example_files_is_in_the_inventory() -> None:
    named = {n for row in inventory_rows() for n in names_in(row[0])}
    families = [n for n in named if n.endswith("*")]
    missing = []
    for file, path in EXAMPLES.items():
        for name in settings(path):
            covered = name in named or any(fnmatch.fnmatch(name, f) for f in families)
            if is_secret_like(name) and not covered:
                missing.append(f"{name} ({file})")
    assert not missing, f"secrets of the example files that the inventory does not list: {missing}"


def test_the_file_the_inventory_names_is_the_file_that_defines_the_setting() -> None:
    """A secret listed under ``app.env`` that the example puts in ``predigol.env`` (or the reverse) sends the owner to edit the wrong file."""
    wrong = []
    for row in inventory_rows():
        where = next((f for f in EXAMPLES if row[1].startswith(f"`{f}`")), None)
        if where is None:
            continue
        defined = settings(EXAMPLES[where])
        for name in names_in(row[0]):
            hits = (
                fnmatch.filter(defined, name)
                if name.endswith("*")
                else [n for n in defined if n == name]
            )
            if not hits:
                wrong.append(f"{name}: the inventory says {where}, which does not define it")
    assert not wrong, "\n".join(wrong)
    # and the check above was not vacuous
    assert any(row[1].startswith("`app.env`") for row in inventory_rows())
    assert any(row[1].startswith("`predigol.env`") for row in inventory_rows())


def _kit_text() -> str:
    parts = []
    for base in (KIT, BACKEND / "src", BACKEND / "scripts"):
        for path in base.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and (path.suffix in {".py", ".sh", ".yml", ".example", ".caddy", ".md", ""})
            ):
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def test_every_setting_the_text_names_exists_in_the_code() -> None:
    """The reverse of the above: a setting the text tells the owner to edit that no script, compose file or module reads is a setting that does nothing."""
    corpus = _kit_text()
    unknown = []
    for token in sorted(set(code_spans(TEXT))):
        looks_like_a_setting = NAME.fullmatch(token) and len(token) > 3 and not token.endswith("*")
        if looks_like_a_setting and token not in corpus:
            unknown.append(token)
    assert not unknown, f"settings the text names and the code does not know: {unknown}"
    # the extraction found the settings it is meant to find
    assert {"PREDIGOL_ALERT_BOT_TOKEN", "FBI_AUTH_SECRET_KEY", "HC_PING_MAINT"} <= set(
        code_spans(TEXT)
    )


# --- the pointers ----------------------------------------------------------------------------------------------------------------------------------


def test_every_how_to_change_it_points_at_a_paragraph_that_exists() -> None:
    titles = rotation_titles()
    assert len(titles) >= 14, "the extraction of the paragraph titles stopped working"
    bad = []
    for row in inventory_rows():
        refs = re.findall(r"«([^»]+)»", row[4])
        guides = re.findall(r"Guía (\d)", row[4])
        if not refs and not guides:
            bad.append(f"{row[0]}: it does not say where to find how")
        for ref in refs:
            if not any(t.startswith(ref) for t in titles):
                bad.append(f"{row[0]}: no paragraph starts with «{ref}»")
        for number in guides:
            if f"## Guía {number} · " not in GUIDE.read_text(encoding="utf-8"):
                bad.append(f"{row[0]}: no Guía {number}")
    assert not bad, "\n".join(bad)


def test_every_paragraph_is_pointed_at_by_a_row_of_the_inventory() -> None:
    """A paragraph no row sends the owner to is a paragraph nobody finds, and a secret that has none is missing from the inventory."""
    refs = [r for row in inventory_rows() for r in re.findall(r"«([^»]+)»", row[4])]
    orphans = [t for t in rotation_titles() if not any(t.startswith(r) for r in refs)]
    assert not orphans, f"paragraphs no row of the inventory points at: {orphans}"


@pytest.mark.skipif(not GUIDE.is_file(), reason="the incident guide is not here")
def test_the_incident_guide_cites_only_paragraphs_that_exist() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    cited = re.findall(r"SECRETS_AND_ROTATION\.md, «([^»]+)»", guide)
    assert len(cited) >= 6, "the guide no longer cites this document the way the test reads"
    titles = rotation_titles()
    bad = [c for c in cited if not any(t.startswith(c) for t in titles)]
    assert not bad, f"the incident guide cites paragraphs this document does not have: {bad}"


@pytest.mark.skipif(not GUIDE.is_file(), reason="the incident guide is not here")
def test_every_secret_the_guide_revokes_has_its_how_to_replace_it_here() -> None:
    """Guide 6 lists what to revoke; for each secret whose replacement it leaves to this document, the paragraph is there (the cited ones are checked above)
    and the Healthchecks row says what is true: a check's address cannot be regenerated, the check is copied and the old one deleted."""
    guide = GUIDE.read_text(encoding="utf-8")
    row = next(ln for ln in guide.splitlines() if ln.startswith("| URLs de Healthchecks.io"))
    assert "Create a Copy" in row and "Regenerar" not in row
    assert "Create a Copy" in paragraph("URLs de Healthchecks.io")
    assert "no deja cambiar" in paragraph("URLs de Healthchecks.io")
    for token in ("Telegram", "Anthropic", "Sentry", "R2", "age"):
        assert token in guide


# --- the commands ----------------------------------------------------------------------------------------------------------------------------------


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


def predigolctl_calls() -> list[list[str]]:
    calls = []
    for span in code_spans(TEXT):
        for found in re.finditer(r"predigolctl\b([^|;&`)]*)", span):
            try:
                tokens = shlex.split(found[1])
            except ValueError:
                tokens = found[1].split()
            tokens = [t for t in tokens if t not in {"&&"} and ">" not in t]
            if tokens:
                calls.append(tokens)
    return calls


def test_every_predigolctl_command_the_text_shows_exists() -> None:
    top, accounts, pitr = _dispatcher(), _accounts_subcommands(), _pitr_subcommands()
    sources = {
        "accounts": ACCOUNTS,
        "pitr": BIN / "pitr.sh",
        "backup": BIN / "backup.sh",
        "health": BIN / "healthcheck.sh",
        "secrets-export": BIN / "secrets-export.sh",
    }
    calls = predigolctl_calls()
    assert {c[0] for c in calls} >= {
        "backup",
        "up",
        "accounts",
        "pitr",
        "secrets-export",
        "alert-test",
        "health",
        "logs",
    }
    problems = []
    for tokens in calls:
        command = tokens[0]
        if command not in top:
            problems.append(f"predigolctl {command}: the dispatcher has no such command")
            continue
        if command == "accounts" and len(tokens) > 1 and tokens[1] not in accounts:
            problems.append(f"predigolctl accounts {tokens[1]}: no such subcommand")
        if command == "pitr" and len(tokens) > 1 and tokens[1] not in pitr:
            problems.append(f"predigolctl pitr {tokens[1]}: no such subcommand")
        for flag in (t for t in tokens if t.startswith("--")):
            source = sources.get(command, BIN / "predigolctl").read_text(encoding="utf-8")
            if flag not in source:
                problems.append(f"predigolctl {command} {flag}: not a flag of that command")
    assert not problems, "\n".join(sorted(set(problems)))


def test_the_commands_that_change_accounts_say_which_accounts() -> None:
    for tokens in predigolctl_calls():
        if (
            tokens[0] == "accounts"
            and len(tokens) > 1
            and tokens[1] in {"mfa-reset", "revoke-sessions"}
        ):
            assert any(t in {"--email", "--all", "--domain"} for t in tokens), tokens


def test_the_scripts_the_text_names_are_in_the_kit() -> None:
    """``bin/x.sh`` and bare ``x.sh`` the owner is told to run exist. The ``step_*`` scripts belong to the rotation packages (S1.d, S1.e), which are built
    for the night they run and are not in the repository."""
    missing = []
    for span in code_spans(TEXT):
        for found in re.finditer(r"(?:bin/)?([a-z][a-z0-9_-]*\.sh)\b", span):
            name = found[1]
            if name.startswith("step_") or (name in W2_SCRIPTS and not W2_IN_TREE):
                continue
            if not (BIN / name).is_file():
                missing.append(name)
    assert not missing, f"scripts the text names and the kit does not have: {sorted(set(missing))}"
    assert {"r2-setup.sh", "r2-restore-drill.sh", "backup.sh", "pitr-enable.sh"} <= set(
        re.findall(r"([a-z0-9-]+\.sh)", TEXT)
    )


# --- what the text claims about the code ---------------------------------------------------------------------------------------------------------


def test_no_container_receives_the_alert_bot_or_the_ping_urls() -> None:
    """The inventory says the alert bot is read by the scripts and "ningún contenedor", and the ping URLs by the timers. Compose passes variables to a
    container by naming them: if the compose file named one of these, a container would have it."""
    compose = (KIT / "docker-compose.yml").read_text(encoding="utf-8")
    for prefix in ("PREDIGOL_ALERT_", "HC_PING_"):
        assert prefix not in compose, (
            f"docker-compose.yml names {prefix}*: a container would receive it"
        )


def test_the_alert_scripts_read_predigol_env_on_every_run() -> None:
    """«No hay que reiniciar nada» when the bot token or a ping URL changes: lib.sh sources both files each time a script starts."""
    lib = (BIN / "lib.sh").read_text(encoding="utf-8")
    assert '. "$PREDIGOL_ENV_FILE"' in lib and '. "$PREDIGOL_APP_ENV_FILE"' in lib
    notify = lib.split("notify_ok() {", 1)[1].split("\n}\n", 1)[0]
    assert notify.index("PREDIGOL_ALERT_BOT_TOKEN") < notify.index("FBI_TELEGRAM_BOT_TOKEN"), (
        "the host's bot is tried first"
    )


def test_the_url_of_a_ping_has_the_shape_the_text_says() -> None:
    """The text says the URL has no trailing slash, no /start and no /fail: ping_hc adds those."""
    lib = (BIN / "lib.sh").read_text(encoding="utf-8")
    assert '"${url}${kind:+/$kind}"' in lib
    assert "hc-ping.com/<uuid>" in EXAMPLES["predigol.env"].read_text(encoding="utf-8")
    assert {
        "HC_PING_HEALTH",
        "HC_PING_BACKUP",
        "HC_PING_RESTORE_TEST",
        "HC_PING_RAW_SYNC",
        "HC_PING_PITR",
        "HC_PING_PITR_TEST",
        "HC_PING_MAINT",
    } == {n for n in settings(EXAMPLES["predigol.env"]) if n.startswith("HC_PING_")}
    healthchecks = paragraph("URLs de Healthchecks.io")
    assert "Son siete" in healthchecks
    for name in settings(EXAMPLES["predigol.env"]):
        if name.startswith("HC_PING_"):
            assert f"`{name}`" in healthchecks, f"the paragraph does not list {name}"


def test_secrets_export_packs_the_files_the_text_says() -> None:
    script = (BIN / "secrets-export.sh").read_text(encoding="utf-8")
    packed = re.search(r"for f in ([^;]+); do", script)
    assert packed
    for var in ("$PREDIGOL_ENV_FILE", "$PREDIGOL_APP_ENV_FILE", "$RCLONE_FILE"):
        assert var in packed[1]
    text = paragraph("Copia de los secretos")
    for word in ("predigol.env", "app.env", "rclone", "MANIFEST.txt", "clave **pública**"):
        assert word in text
    assert "/root/secrets-<fecha>.tar.age" in text


def test_the_three_r2_tokens_are_the_ones_the_scripts_and_the_example_know() -> None:
    text = paragraph("Tokens de R2")
    names = ("predigol-copias", "predigol-pitr", "predigol-lectura")
    assert all(n in text for n in names)
    setup = (BIN / "r2-setup.sh").read_text(encoding="utf-8")
    for var in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "AGE_RECIPIENT",
    ):
        assert var in text and var in setup
    assert "no_head" in setup and "no_head" in text
    assert "pitr-enable.sh" in text  # "se niega si el PITR ya está activo"
    if W2_IN_TREE:
        enable = (BIN / "pitr-enable.sh").read_text(encoding="utf-8")
        assert "PITR_S3_KEY" in enable and "PITR_S3_KEY_SECRET" in enable
        assert "already" in enable
    inventory = INVENTORY
    for n in names:
        assert n in inventory, f"the inventory does not name the token {n}"


def test_the_age_key_retention_matches_the_bucket_rules() -> None:
    """The text keeps the old private key 13 months, "lo más que viven las copias: 396 días": the README's table of the bucket rules says day 396."""
    text = paragraph("Clave `age`")
    assert "396 días" in text and "13 meses" in text
    readme = (KIT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"dumps/monthly/.*día 396", readme)
