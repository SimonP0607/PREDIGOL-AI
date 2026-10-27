"""bin/secrets-export.sh: the server's secrets packed for the owner, encrypted with his PUBLIC age key. A value must never be
printed (not even in the manifest inside), a private key must be refused wherever it shows up, and a failure leaves nothing."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from tests.unit._vps_sandbox import Sandbox, tools_present

pytestmark = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)

# Values that must never appear in what the script prints, nor in the manifest. (Marked "fake-": the project's secret scanner
# lets a value that says it is a stand-in through; it does not let a real-looking one into a test file.)
CIPHER = "fake-pitr-cipher-pass-0123456789abcdef"
AUTH = "fake-auth-secret-key-fedcba9876543210"
DBPASS = "fake-db-password-aaaa1111bbbb2222"
R2KEY = "fake-r2-copias-secret-key-5555666677778888"
RECIPIENT = "age1" + "q" * 58


@pytest.fixture
def sb(tmp_path: Path) -> Sandbox:
    box = Sandbox(tmp_path)
    box.set_env(
        PITR_CIPHER_PASS=CIPHER,
        POSTGRES_PASSWORD=DBPASS,
        PITR_S3_KEY="",
        BACKUP_AGE_RECIPIENT=RECIPIENT,
    )
    (tmp_path / "app.env").write_text(
        f"FBI_AUTH_SECRET_KEY={AUTH}\nFBI_SENTRY_DSN=\nFBI_ENV=production\n"
    )
    (tmp_path / "rclone.conf").write_text(
        f"[r2]\ntype = s3\nprovider = Cloudflare\naccess_key_id = fake-id\nsecret_access_key = {R2KEY}\n"
    )
    (tmp_path / "out").mkdir()
    return box


def _bundle(path: Path) -> tarfile.TarFile:
    """The 'ciphertext' of the stand-in age is its first line plus the plain tar; the real age is tested separately."""
    data = path.read_bytes()
    assert data.startswith(b"age-encryption.org/v1\n")
    return tarfile.open(fileobj=io.BytesIO(data.split(b"\n", 1)[1]))


def _out(sb: Sandbox) -> list[Path]:
    return sorted((sb.root / "out").glob("secrets-*.tar.age"))


def _run(sb: Sandbox, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    result = sb.run("secrets-export.sh", "--out", str(sb.root / "out"), *args, **env)
    for secret in (CIPHER, AUTH, DBPASS, R2KEY):
        assert secret not in result.stdout + result.stderr, "a value was printed"
    return result


def test_writes_one_encrypted_file_with_the_three_files_and_the_manifest(sb: Sandbox) -> None:
    result = _run(sb)
    assert result.returncode == 0, result.stdout + result.stderr
    (out,) = _out(sb)
    assert out.stat().st_mode & 0o777 == 0o600
    names = _bundle(out).getnames()
    here = str(sb.root).lstrip("/")
    assert sorted(names) == sorted(
        [
            f"bundle/{here}/predigol.env",
            f"bundle/{here}/app.env",
            f"bundle/{here}/rclone.conf",
            "bundle/MANIFEST.txt",
        ]
    )
    assert f"{out}" in result.stdout and "delete it from the server" in result.stdout
    assert not list((sb.root / "out").glob("*.partial")), "no half-written file is left"


def test_the_files_inside_are_the_servers_own_and_the_manifest_has_names_but_no_values(
    sb: Sandbox,
) -> None:
    assert _run(sb).returncode == 0
    (out,) = _out(sb)
    tar = _bundle(out)
    here = str(sb.root).lstrip("/")
    app = tar.extractfile(f"bundle/{here}/app.env")
    assert app is not None and AUTH in app.read().decode()
    manifest_file = tar.extractfile("bundle/MANIFEST.txt")
    assert manifest_file is not None
    manifest = manifest_file.read().decode()
    for secret in (CIPHER, AUTH, DBPASS, R2KEY, "fake-id"):
        assert secret not in manifest
    assert "PITR_CIPHER_PASS" in manifest and "FBI_AUTH_SECRET_KEY" in manifest
    assert "empty: FBI_SENTRY_DSN" in manifest, "the empty ones are told apart"
    assert "rclone remotes: r2" in manifest
    assert "encrypted for: age1qqqqqqqqqqqq..." in manifest, "the PUBLIC key, cut short"


def test_a_recipient_given_on_the_command_line_wins(sb: Sandbox) -> None:
    other = "age1" + "z" * 58
    assert _run(sb, "--recipient", other).returncode == 0
    (out,) = _out(sb)
    manifest_file = _bundle(out).extractfile("bundle/MANIFEST.txt")
    assert manifest_file is not None and "age1zzzzzzzzzzzz..." in manifest_file.read().decode()


@pytest.mark.parametrize(
    ("recipient", "message"),
    [
        ("", "no recipient"),
        ("AGE-SECRET-KEY-1" + "Q" * 50, "PRIVATE key"),
        ("ssh-ed25519", "must be an age PUBLIC key"),
    ],
)
def test_a_missing_private_or_malformed_recipient_is_refused(
    sb: Sandbox, recipient: str, message: str
) -> None:
    sb.set_env(BACKUP_AGE_RECIPIENT=recipient or None)
    result = _run(sb)
    assert result.returncode == 1 and message in result.stdout
    assert not _out(sb)


def test_a_recipient_that_age_itself_rejects_is_refused(sb: Sandbox) -> None:
    """The real age refuses a malformed key; a typo would encrypt every secret to nobody."""
    (sb.stubs / "age").write_text(
        '#!/usr/bin/env bash\necho "age: error: malformed recipient" >&2\nexit 1\n'
    )
    result = _run(sb)
    assert result.returncode == 1 and "age does not accept that recipient" in result.stdout
    assert not _out(sb)


def test_a_private_key_in_any_packed_file_stops_everything(sb: Sandbox) -> None:
    app = sb.root / "app.env"
    app.write_text(app.read_text() + "SOMETHING=AGE-SECRET-KEY-1" + "Q" * 50 + "\n")
    result = _run(sb)
    assert result.returncode == 1 and "PRIVATE key" in result.stdout
    assert "AGE-SECRET-KEY-1QQQ" not in result.stdout + result.stderr, (
        "the key itself is not echoed"
    )
    assert not _out(sb)


def test_it_never_overwrites_a_file_and_needs_the_folder(sb: Sandbox) -> None:
    first = _run(sb, FAKE_NOW="2026-10-25 14:00:00")
    assert first.returncode == 0, first.stdout + first.stderr
    again = _run(sb, FAKE_NOW="2026-10-25 14:00:00")
    assert again.returncode == 1 and "already exists" in again.stdout
    assert len(_out(sb)) == 1
    missing = sb.run("secrets-export.sh", "--out", str(sb.root / "nope"))
    assert missing.returncode == 1 and "is not a folder" in missing.stdout


def test_usage(sb: Sandbox) -> None:
    for args in (["--out"], ["--recipient"], ["--what"], ["extra"]):
        result = sb.run("secrets-export.sh", *args)
        assert result.returncode == 2 and "usage:" in result.stderr, args


def test_an_age_that_fails_half_way_leaves_nothing_behind(sb: Sandbox) -> None:
    """age is fine with the one-byte recipient check, then dies while writing the real file - after creating it, as the real one does."""
    (sb.stubs / "age").write_text(
        "#!/usr/bin/env bash\n"
        'out=""; while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && out="$2"; shift; done\n'
        'if [[ -n "$out" ]]; then cat > /dev/null; echo "half a file" > "$out"; echo "age: disk full" >&2; exit 1; fi\n'
        "exit 0\n"
    )
    result = _run(sb)
    assert result.returncode != 0
    assert not _out(sb) and not list((sb.root / "out").iterdir()), "not even a .partial"


def test_the_file_age_makes_opens_with_the_private_key_and_only_with_it(
    sb: Sandbox, tmp_path: Path
) -> None:
    """With the REAL age: encrypt to a fresh public key, open with the private one; a different key must not open it."""
    real_age, real_keygen = (
        shutil.which("age", path="/usr/bin:/usr/local/bin"),
        shutil.which("age-keygen", path="/usr/bin:/usr/local/bin"),
    )
    if not (real_age and real_keygen):
        pytest.skip("age and age-keygen are not installed")
    key = tmp_path / "owner.key"
    pub = subprocess.run([real_keygen, "-o", str(key)], capture_output=True, text=True, check=True)
    recipient = next(w for w in (pub.stderr + pub.stdout).split() if w.startswith("age1"))
    sb.set_env(BACKUP_AGE_RECIPIENT=recipient)
    (sb.stubs / "age").unlink()  # the real one comes next on the PATH
    result = _run(sb)
    assert result.returncode == 0, result.stdout + result.stderr
    (out,) = _out(sb)
    opened = subprocess.run(
        [real_age, "-d", "-i", str(key), str(out)], capture_output=True, check=True
    )
    with tarfile.open(fileobj=io.BytesIO(opened.stdout)) as tar:
        assert "bundle/MANIFEST.txt" in tar.getnames()
    other = tmp_path / "other.key"
    subprocess.run([real_keygen, "-o", str(other)], capture_output=True, check=True)
    wrong = subprocess.run(
        [real_age, "-d", "-i", str(other), str(out)], capture_output=True, check=False
    )
    assert wrong.returncode != 0, "a different key opened it"
    assert CIPHER.encode() not in out.read_bytes(), "the file is not readable as it is"
