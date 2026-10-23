"""The command a person types to read the registry of context factors, to validate one or to take a validation back
(``python -m scripts.context_factors``): it asks before it writes, says what it would change and what it leaves alone, refuses
what the registry would refuse, and leaves no trace when it does. The transaction is rolled back after every test."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from scripts import context_factors as cli

from fbi.intel import factors, h2h

pytestmark = pytest.mark.integration

T0 = datetime(2034, 4, 1, 12, tzinfo=UTC)
REASON = "the weighted record beat the form on the test matches"
RESULT = {"matches": 2100, "logloss_delta": -0.004, "ci95": [-0.007, -0.001]}


class Session:
    """The test's connection as a command sees it: ``commit()`` keeps what was written inside the test's own transaction and
    ``rollback()`` discards what the command wrote since the last commit (the world of a test is never committed)."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn
        self.rollbacks = 0
        conn.execute("SAVEPOINT command")

    def commit(self) -> None:
        self._conn.execute("RELEASE SAVEPOINT command")
        self._conn.execute("SAVEPOINT command")

    def rollback(self) -> None:
        self.rollbacks += 1
        self._conn.execute("ROLLBACK TO SAVEPOINT command")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def result_file(tmp_path: Path, doc: Any = None) -> Path:
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(RESULT if doc is None else doc))
    return path


def count(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM intel.context_factors").fetchone()
    assert row is not None
    return int(row[0])


def promote(db: psycopg.Connection[Any], tmp_path: Path, *, factor: str = factors.H2H, experiment: str = "F12-h2h-01",
            reason: str = REASON, by: str | None = None, confirm: bool = False, doc: Any = None) -> tuple[int, str]:
    code, lines = cli.promote_command(db, factor=factor, experiment=experiment, result_file=result_file(tmp_path, doc), reason=reason,
                                      by=by, confirm=confirm, at=T0)
    return code, "\n".join(lines)


# ── reading ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_list_says_every_factor_is_descriptive_and_what_an_experiment_would_have_to_show(db: psycopg.Connection[Any]) -> None:
    text = "\n".join(cli.show(db, at=T0))
    for f in factors.CATALOGUE:
        assert f.key in text and f.version in text and f.label in text and f.claim in text
    assert text.count("never decided: born DESCRIPTIVE") == len(factors.CATALOGUE)
    assert "VALIDATED" not in text


def test_the_list_tells_who_validated_what_and_when(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    assert promote(db, tmp_path, by="Simon", confirm=True)[0] == 0
    text = "\n".join(cli.show(db, at=T0 + timedelta(days=1)))
    assert "VALIDATED" in text and "experiment F12-h2h-01" in text and "by Simon" in text and REASON in text and "2034-04-01 12:00 UTC" in text
    assert "never decided" in text, "the other factors are as they were"
    before = "\n".join(cli.show(db, at=T0 - timedelta(days=1)))
    assert "F12-h2h-01" not in before and before.count("never decided") == len(factors.CATALOGUE), \
        "and as of an earlier moment, nothing had been decided"


def test_a_decision_about_an_older_version_of_the_code_is_listed_apart(db: psycopg.Connection[Any]) -> None:
    db.execute("INSERT INTO intel.context_factors (factor, version, status, decided_at, decided_by, who, reason, evidence) "
               "VALUES (%s, 'h2h-v1', 'VALIDATED', %s, 'owner', 'Simon', %s, %s)",
               (factors.H2H, T0, REASON, json.dumps({"factor": factors.H2H, "version": "h2h-v1", "experiment": "old", "result": RESULT})))
    text = "\n".join(cli.show(db, at=T0 + timedelta(days=1)))
    assert "OTHER VERSIONS OF THE CODE" in text and "h2h_weighted h2h-v1" in text and "say nothing about the version in force" in text
    assert text.count("never decided") == len(factors.CATALOGUE), "the version in force is still undecided"


def test_the_history_is_every_decision_oldest_first_and_refuses_a_factor_that_does_not_exist(db: psycopg.Connection[Any],
                                                                                          tmp_path: Path) -> None:
    assert cli.history_lines(db, None) == ["No decision has been taken. Every factor is DESCRIPTIVE."]
    promote(db, tmp_path, by="Simon", confirm=True)
    back = cli.retire_command(db, factor=factors.H2H, reason="the experiment did not replicate", by="Simon", confirm=True,
                              at=T0 + timedelta(days=3))
    assert back[0] == 0
    lines = cli.history_lines(db, factors.H2H)
    assert len(lines) == 2 and "VALIDATED" in lines[0] and "DESCRIPTIVE" in lines[1] and "taken back (decision #" in lines[1]
    assert cli.history_lines(db, factors.TACTICS) == ["No decision has been taken about tactics_profile. Every factor is DESCRIPTIVE."]
    with pytest.raises(LookupError, match="not a context factor"):
        cli.history_lines(db, "moon_phase")


# ── promoting ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_promoting_asks_before_it_writes_and_says_what_it_changes_and_what_it_does_not(db: psycopg.Connection[Any],
                                                                                    tmp_path: Path) -> None:
    code, text = promote(db, tmp_path)
    assert code == 0 and text.startswith("DRY RUN - validating h2h_weighted (h2h-v2")
    assert "experiment 'F12-h2h-01'" in text and "matches" in text and "logloss_delta" in text, "what the result holds"
    assert factors.BY_KEY[factors.H2H].claim in text
    assert "What it changes" in text and "What it does not change: any model, probability, forecast, pick or price" in text
    assert "Nothing was written" in text and count(db) == 0


def test_confirming_needs_a_person(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    code, text = promote(db, tmp_path, confirm=True)
    assert code == 2 and "--confirm needs --by NAME" in text and count(db) == 0


def test_a_person_who_confirms_validates_the_factor_at_the_version_in_force(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    code, text = promote(db, tmp_path, by="Simon", confirm=True)
    assert code == 0 and "h2h_weighted (h2h-v2) is VALIDATED (decision #" in text and "by Simon" in text
    stand = factors.standings(db, at=T0)[factors.H2H]
    assert stand.status == factors.VALIDATED and stand.decision is not None
    assert stand.decision.version == h2h.VERSION and stand.decision.evidence["result"] == RESULT
    again = promote(db, tmp_path, by="Simon", confirm=True)
    assert again[0] == 0 and "already validated by that experiment: nothing written" in again[1] and count(db) == 1
    dry = promote(db, tmp_path)
    assert dry[0] == 0 and "already validated by that experiment: nothing would change" in dry[1]


@pytest.mark.parametrize(("change", "message"), [
    ({"factor": "moon_phase"}, "not a context factor"),
    ({"reason": "short"}, "at least 10 characters"),
    ({"experiment": "   "}, "names the experiment"),
    ({"doc": {}}, "must hold one JSON object"),
    ({"doc": [1, 2]}, "must hold one JSON object"),
    ({"doc": {"when": float("inf")}}, "not plain JSON"),
], ids=["unknown_factor", "short_reason", "no_experiment", "empty_result", "result_not_an_object", "result_not_plain_json"])
def test_a_validation_the_registry_would_refuse_is_refused_before_it_asks(db: psycopg.Connection[Any], tmp_path: Path,
                                                                       change: dict[str, Any], message: str) -> None:
    for confirm in (False, True):
        code, text = promote(db, tmp_path, by="Simon", confirm=confirm, **change)
        assert code == 3 and text.startswith("refused:") and message in text
    assert count(db) == 0


def test_a_result_file_that_is_missing_or_not_json_is_refused(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    code, lines = cli.promote_command(db, factor=factors.H2H, experiment="F12-h2h-01", result_file=tmp_path / "nothing.json",
                                      reason=REASON, by="Simon", confirm=True, at=T0)
    assert code == 3 and "no such file" in lines[0]
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    code, lines = cli.promote_command(db, factor=factors.H2H, experiment="F12-h2h-01", result_file=broken, reason=REASON,
                                      by="Simon", confirm=True, at=T0)
    assert code == 3 and "is not readable JSON" in lines[0] and count(db) == 0


# ── taking a validation back ───────────────────────────────────────────────────────────────────────────────────────────


def test_retiring_asks_before_it_writes_and_leaves_the_past_as_it_was(db: psycopg.Connection[Any], tmp_path: Path) -> None:
    promote(db, tmp_path, by="Simon", confirm=True)
    code, lines = cli.retire_command(db, factor=factors.H2H, reason="the experiment did not replicate", by=None, confirm=False,
                                     at=T0 + timedelta(days=3))
    text = "\n".join(lines)
    assert code == 0 and "DRY RUN" in text and "DESCRIPTIVE again" in text and "Nothing was written" in text and count(db) == 1
    assert cli.retire_command(db, factor=factors.H2H, reason="the experiment did not replicate", by=None, confirm=True)[0] == 2
    code, lines = cli.retire_command(db, factor=factors.H2H, reason="the experiment did not replicate", by="Simon", confirm=True,
                                     at=T0 + timedelta(days=3))
    assert code == 0 and "is DESCRIPTIVE again" in lines[0]
    assert factors.standings(db, at=T0 + timedelta(days=3))[factors.H2H].status == factors.DESCRIPTIVE
    assert factors.standings(db, at=T0 + timedelta(days=1))[factors.H2H].status == factors.VALIDATED, "as of the 2nd it was validated"


def test_retiring_what_is_not_validated_is_refused(db: psycopg.Connection[Any]) -> None:
    for confirm in (False, True):
        code, lines = cli.retire_command(db, factor=factors.H2H, reason="there is nothing to take back", by="Simon", confirm=confirm,
                                         at=T0)
        assert code == 3 and "nothing to take back" in lines[0]
    code, lines = cli.retire_command(db, factor="moon_phase", reason="there is no such factor", by="Simon", confirm=True)
    assert code == 3 and "not a context factor" in lines[0]
    assert count(db) == 0


# ── the command line ───────────────────────────────────────────────────────────────────────────────────────────────────


def run_main(session: Session, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: session)
    return cli.main(list(argv))


def test_the_command_line_is_wired_to_those_commands(db: psycopg.Connection[Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    session = Session(db)
    assert run_main(session, monkeypatch, "list") == 0
    assert "CONTEXT FACTORS" in capsys.readouterr().out
    assert run_main(session, monkeypatch, "history") == 0
    assert "Every factor is DESCRIPTIVE" in capsys.readouterr().out
    assert run_main(session, monkeypatch, "history", "moon_phase") == 3
    assert "not a context factor" in capsys.readouterr().err

    path = str(result_file(tmp_path))
    args = ("promote", factors.H2H, "--experiment", "F12-h2h-01", "--result", path, "--reason", REASON)
    assert run_main(session, monkeypatch, *args) == 0
    assert "DRY RUN" in capsys.readouterr().out and count(db) == 0
    before = session.rollbacks
    assert run_main(session, monkeypatch, *args[:-1], "short", "--by", "Simon", "--confirm") == 3
    refused = capsys.readouterr()
    assert "refused:" in refused.err and refused.out == "", "a refusal goes to stderr and leaves no trace"
    assert session.rollbacks == before + 1 and count(db) == 0
    assert run_main(session, monkeypatch, *args, "--by", "Simon", "--confirm") == 0
    assert "is VALIDATED" in capsys.readouterr().out and count(db) == 1

    assert run_main(session, monkeypatch, "promote", factors.H2H, "--reason", REASON) == 2
    assert "promote needs --experiment NAME and --result FILE.json" in capsys.readouterr().err
    assert run_main(session, monkeypatch, "retire", factors.H2H) == 2
    assert "need the FACTOR and --reason TEXT" in capsys.readouterr().err
    assert run_main(session, monkeypatch, "retire", factors.H2H, "--reason", "the experiment did not replicate", "--by", "Simon",
                    "--confirm") == 0
    assert "is DESCRIPTIVE again" in capsys.readouterr().out and count(db) == 2
