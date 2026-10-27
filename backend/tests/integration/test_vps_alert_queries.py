"""The SQL that the server's alert scripts run (deploy/vps/bin) answers what its comment says, on the REAL schema (security plan S3).

``alerts_checks.sh`` asks the database which picks of finished matches are still not settled; ``security_alerts_sql.sh`` asks ``auth.audit_events`` for failed
sign-ins, accounts put on hold, administrators from a new browser and privileged changes. A shell script is invisible to ruff, to mypy and to every model of the
tables: a column renamed by a later migration would turn these alerts silent the night it ships, and nobody would notice until the day they were needed. So
the queries are taken from the scripts themselves (never copied here) and run over synthetic rows inside the transaction of the ``db`` fixture, which is rolled
back; and once with the real ``psql`` in a read-only session, the way ``psql_q`` of ``lib.sh`` runs them, to see that what comes out is what the scripts parse.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

import psycopg
import pytest

from fbi.picks.engine import settle_open_picks
from tests.unit._vps_sandbox import BIN, tools_present

from .conftest import Seed
from .test_daily_records import World

pytestmark = pytest.mark.skipif(
    not tools_present(), reason="bash, jq, flock and sha256sum are needed"
)

STATEMENT_TIMEOUT = "SET statement_timeout = '20s'; "
UA_WIN118 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
UA_WIN119 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.123 Safari/537.36"
UA_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"
SECURITY_QUERIES = ("SQL_FAILED", "SQL_LOCKED", "SQL_NEWDEVICE", "SQL_PRIVILEGED", "SQL_OWNER")


def _shell(script: str, call: str, **env: str) -> list[str]:
    """What ``call`` prints (NUL-separated words) after SOURCING a script of the server: nothing in it runs, only its definitions are read."""
    result = subprocess.run(
        ["bash", "-c", f'set -u; . "{BIN / script}"; {call}'],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return result.stdout.split("\0")[:-1]


def _security_sql() -> dict[str, str]:
    values = _shell(
        "security_alerts_sql.sh",
        "printf '%s\\0' " + " ".join(f'"${name}"' for name in SECURITY_QUERIES),
    )
    return dict(zip(SECURITY_QUERIES, values, strict=True))


def _picks_sql(after: int | None = None, window: int | None = None) -> str:
    env = {}
    if after is not None:
        env["UNSETTLED_AFTER_H"] = str(after)
    if window is not None:
        env["UNSETTLED_WINDOW_D"] = str(window)
    (sql,) = _shell("alerts_checks.sh", "sql_picks_unsettled; printf '\\0'", **env)
    assert sql.startswith(STATEMENT_TIMEOUT), "the query starts with its own statement_timeout"
    return sql.removeprefix(STATEMENT_TIMEOUT).strip()


def _scalar(db: psycopg.Connection[Any], sql: str) -> str:
    """The one value a query of the scripts answers, as the shell sees it (text)."""
    row = db.execute(f"SELECT ({sql})::text").fetchone()
    assert row is not None and row[0] is not None
    return str(row[0])


def _picks(db: psycopg.Connection[Any], after: int | None = None, window: int | None = None) -> str:
    return _scalar(db, _picks_sql(after, window))


# --- picks that were not settled -----------------------------------------------------------------------------------------------------------------

# name: (status of the match, kick-off, result stored, pick taken), all of them "ago": seven matches in seven situations (A with two picks)
SITUATIONS = {
    "F1": ("FT", "8 hours", "5 hours", "12 hours"),  # A: stuck
    "F2": ("FT", "5 hours", "2 hours", "12 hours"),  # B: finished 2 h ago: not yet (threshold 3 h)
    "F3": (
        "FT",
        "10 days",
        "10 days",
        "12 hours",
    ),  # C: kicked off 10 days ago: out of the 7-day window
    "F4": ("FT", "9 hours", "6 hours", "12 hours"),  # D: waits, with a reason recorded
    "F5": ("PST", "9 hours", "6 hours", "12 hours"),  # E: postponed: waits on purpose
    "F6": ("FT", "9 hours", "6 hours", "30 minutes"),  # F: the pick was taken after the result
    "F7": ("AET", "7 hours", "4 hours", "12 hours"),  # G: stuck, after extra time
}
WAITS = "finished, but no regulation score is recorded"


@pytest.fixture()
def matches(db: psycopg.Connection[Any], seed: Seed) -> World:
    """The world of test_daily_records (a match with one pick each), moved around in time: the rows of seven matches in the seven situations above."""
    assert _picks(db) == "0 0 0 0 0", "the test database holds no open pick of its own"
    world = World(db, seed)
    # a pick is a pre-match record, frozen by a trigger; inside this transaction, which is rolled back, it is switched off so that the test can age them
    db.execute("ALTER TABLE picks.picks DISABLE TRIGGER picks_picks_frozen")
    for name, (status, kickoff, stored, taken) in SITUATIONS.items():
        fixture, pick = world.fixtures[name], world.picks[name]
        world.result(name, 1, 0)
        db.execute(
            "UPDATE core.fixtures SET status_short = %s, kickoff_at = now() - %s::interval WHERE id = %s",
            (status, kickoff, fixture),
        )
        db.execute(
            "UPDATE core.fixture_results SET settled_at = now() - %s::interval WHERE fixture_id = %s",
            (stored, fixture),
        )
        db.execute(
            "UPDATE picks.picks SET status = 'shadow', created_at = now() - %s::interval WHERE id = %s",
            (taken, pick),
        )
    # a second pick on A's match (the Draw), taken at the same time: the alert counts picks and matches apart
    db.execute(
        "CREATE TEMP TABLE _second ON COMMIT DROP AS SELECT * FROM picks.picks WHERE id = %s",
        (world.picks["F1"],),
    )
    candidate = db.execute(
        "INSERT INTO picks.pick_candidates (run_id, fixture_id, prediction_id, market_key, selection, bookmaker_id, market_odds, p_calibrated, "
        "p_market_fair, edge, price_edge, ev, ev_adjusted, decision) "
        "SELECT c.run_id, c.fixture_id, c.prediction_id, c.market_key, 'Draw', c.bookmaker_id, c.market_odds, c.p_calibrated, c.p_market_fair, c.edge, "
        "c.price_edge, c.ev, c.ev_adjusted, c.decision FROM picks.pick_candidates c JOIN picks.picks p ON p.candidate_id = c.id WHERE p.id = %s RETURNING id",
        (world.picks["F1"],),
    ).fetchone()
    assert candidate is not None
    db.execute(
        "UPDATE _second SET id = nextval('picks.picks_id_seq'), candidate_id = %s, selection = 'Draw'",
        (candidate[0],),
    )
    db.execute("INSERT INTO picks.picks SELECT * FROM _second")
    second = db.execute(
        "SELECT id FROM picks.picks WHERE candidate_id = %s", (candidate[0],)
    ).fetchone()
    assert second is not None
    world.picks["F1 (Draw)"] = int(second[0])
    # the pipeline gives every pick its 'pending' result when it creates it (fbi/picks/engine.py); D's carries a reason
    for name, pick in world.picks.items():
        db.execute(
            "INSERT INTO picks.pick_results (pick_id, result_status, review_reason) VALUES (%s, 'pending', %s)",
            (pick, WAITS if name == "F4" else None),
        )
    return world


def test_only_the_matches_that_finished_hours_ago_and_never_settled_are_stuck(
    db: psycopg.Connection[Any], matches: World
) -> None:
    # "stuck_picks stuck_matches review_picks review_matches oldest_stuck_hours": A (two picks) and G are stuck, D waits with a reason; B (2 h), C (10 days),
    # E (postponed) and F (the pick came after the result) do not count; the oldest of A and G has waited 5 h (its result was stored 5 h ago)
    assert _picks(db) == "3 2 1 1 5"


def test_a_narrower_threshold_and_a_wider_window_see_more_but_never_what_waits_on_purpose(
    db: psycopg.Connection[Any], matches: World
) -> None:
    # 1 h and 30 days: B and C count too (E is postponed, F is 30 minutes old). The age of a pick starts at the LATER of its result and its own creation:
    # C's pick (taken 12 h ago, its result 10 days ago) has waited 12 h, which is also the oldest of all
    assert _picks(db, after=1, window=30) == "5 4 1 1 12"


def test_a_pick_already_settled_is_not_stuck(db: psycopg.Connection[Any], matches: World) -> None:
    db.execute("UPDATE picks.picks SET status = 'settled'")
    assert _picks(db) == "0 0 0 0 0"
    assert _picks(db, after=0, window=30) == "0 0 0 0 0"


def test_what_the_alert_calls_stuck_the_settlement_job_settles_or_tells_why_it_cannot(
    db: psycopg.Connection[Any], matches: World
) -> None:
    """The query repeats the test of OPEN_PICKS_SQL (fbi/picks/engine.py): the picks it counts are those the job takes. After the job the stuck ones are
    settled, except G: an AET match with neither the 90-minute nor the extra-time score cannot be settled, and the job records why, which moves it from
    "stuck" (SEV2: nobody tried) to "waiting with a reason" (SEV3). The postponed match is not counted at all."""
    report = settle_open_picks(db, run_id=None)
    assert report.open_picks == len(SITUATIONS) + 1, "seven matches, and A has two picks"
    assert _picks(db, after=0, window=30) == "0 0 1 1 0"
    left = db.execute(
        "SELECT f.status_short FROM picks.picks p JOIN core.fixtures f ON f.id = p.fixture_id WHERE p.status <> 'settled' ORDER BY 1"
    ).fetchall()
    assert left == [("AET",), ("PST",)]


def test_the_query_runs_in_a_read_only_session_the_way_the_script_runs_it(
    migrated_database: str,
) -> None:
    """psql_q: a read-only session (-c SET ...), then the query with its own SET prefix, the last line of the output; the check parses five numbers."""
    psql = shutil.which("psql")
    if psql is None:
        pytest.skip("psql is not installed")
    (full,) = _shell("alerts_checks.sh", "sql_picks_unsettled; printf '\\0'")
    out = subprocess.run(
        [
            psql,
            migrated_database,
            "-v",
            "ON_ERROR_STOP=1",
            "-qAtX",
            "-c",
            "SET default_transaction_read_only = on",
            "-c",
            full,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.splitlines()[-1]
    assert len(out.split()) == 5 and all(w.isdigit() for w in out.split()), out


# --- the security alerts ------------------------------------------------------------------------------------------------------------------------


def _user(db: psycopg.Connection[Any], email: str, role: str) -> int:
    row = db.execute(
        "INSERT INTO auth.users (email, display_name, password_hash, role, status) VALUES (%s, %s, '$argon2id$fake', %s, 'active') RETURNING id",
        (email, email.split("@")[0], role),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _pair(value: str) -> tuple[int, set[str]]:
    """'count|ids' (accounts on hold, new devices) as the script parses it."""
    count, _, ids = value.partition("|")
    return int(count), {i for i in ids.split(",") if i}


def _triple(value: str) -> tuple[int, int, set[str]]:
    """'total|by_someone_else|ids' (privileged changes)."""
    total, by_other, ids = value.split("|")
    return int(total), int(by_other), {i for i in ids.split(",") if i}


def test_the_security_queries_come_from_the_script_and_are_all_there() -> None:
    sql = _security_sql()
    assert set(sql) == set(SECURITY_QUERIES)
    assert all(q.strip() for q in sql.values())
    assert ":owner" in sql["SQL_PRIVILEGED"], "the owner's id is the only thing the caller fills in"
    assert not any(re.search(r"\bemail\b", q) for q in sql.values()), (
        "the e-mail column of the audit trail is never read: it holds whatever was typed in a failed sign-in, even a password"
    )


def test_failed_sign_ins_are_counted_over_the_last_five_minutes_only(
    db: psycopg.Connection[Any],
) -> None:
    sql = _security_sql()["SQL_FAILED"]
    before = int(_scalar(db, sql))
    db.execute(
        "INSERT INTO auth.audit_events (action, email, detail) SELECT 'login.failed', 'typed-password-in-the-email-field', '{}' FROM generate_series(1, 25)"
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, email, detail) SELECT 'login.refused', 'x', '{}' FROM generate_series(1, 3)"
    )
    db.execute(
        "INSERT INTO auth.audit_events (at, action, email, detail) SELECT now() - interval '10 minutes', 'login.failed', 'x', '{}' FROM generate_series(1, 4)"
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, email, detail) VALUES ('login.succeeded', 'x', '{}')"
    )
    assert int(_scalar(db, sql)) - before == 28, (
        "25 failed + 3 refused now; the 4 of ten minutes ago and a success do not count"
    )


def test_two_accounts_on_hold_in_the_hour_are_told_with_their_ids(
    db: psycopg.Connection[Any],
) -> None:
    sql = _security_sql()["SQL_LOCKED"]
    count_before, ids_before = _pair(_scalar(db, sql))
    user, other, owner = (_user(db, f"{n}@alerts.test", "USER") for n in ("user", "other", "owner"))
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, detail) SELECT 'login.locked', %s, '{}' FROM generate_series(1, 3)",
        (user,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, detail) VALUES ('login.locked', %s, '{}')",
        (other,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (at, action, target_user_id, detail) VALUES (now() - interval '2 hours', 'login.locked', %s, '{}')",
        (owner,),
    )
    count, ids = _pair(_scalar(db, sql))
    assert count - count_before == 2, (
        "three events on one account are one account; the one of two hours ago is out"
    )
    assert ids - ids_before == {str(user), str(other)}
    assert _scalar(db, sql).endswith(",".join(sorted(ids))), (
        "the ids are listed in the order the script prints them (as text)"
    )


def test_a_browser_update_is_not_a_new_device_but_a_new_browser_of_an_administrator_is(
    db: psycopg.Connection[Any],
) -> None:
    sql = _security_sql()["SQL_NEWDEVICE"]
    count_before, ids_before = _pair(_scalar(db, sql))
    owner = _user(db, "owner@alerts.test", "SUPER_ADMIN")
    user = _user(db, "user@alerts.test", "USER")
    db.execute(
        "INSERT INTO auth.audit_events (at, action, target_user_id, ip, detail) VALUES (now() - interval '30 days', 'login.succeeded', %s, '203.0.113.5', jsonb_build_object('user_agent', %s::text))",
        (owner, UA_WIN118),
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, ip, detail) VALUES ('login.succeeded', %s, '203.0.113.5', jsonb_build_object('user_agent', %s::text))",
        (owner, UA_WIN119),
    )
    count, ids = _pair(_scalar(db, sql))
    assert (count - count_before, ids - ids_before) == (0, set()), (
        "Chrome 118 -> 119 on the same system: an update"
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, ip, detail) VALUES ('login.succeeded', %s, '198.51.100.9', jsonb_build_object('user_agent', %s::text))",
        (owner, UA_MAC),
    )
    # an ordinary account from anywhere is not what this alert watches
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, ip, detail) VALUES ('login.succeeded', %s, '198.51.100.10', jsonb_build_object('user_agent', %s::text))",
        (user, UA_MAC),
    )
    count, ids = _pair(_scalar(db, sql))
    assert (count - count_before, ids - ids_before) == (1, {str(owner)})


def test_the_owner_is_the_oldest_administrator_and_nobody_created_later_takes_the_place(
    db: psycopg.Connection[Any],
) -> None:
    sql = _security_sql()["SQL_OWNER"]
    before = int(_scalar(db, sql))  # 0 when there is no administrator at all
    first = _user(db, "first@alerts.test", "SUPER_ADMIN")
    expected = before or first
    assert int(_scalar(db, sql)) == expected
    _user(db, "second@alerts.test", "SUPER_ADMIN")
    _user(db, "plain@alerts.test", "USER")
    assert int(_scalar(db, sql)) == expected, "an account created later never becomes the owner"


def test_privileged_changes_are_told_with_how_many_were_done_by_someone_who_is_not_the_owner(
    db: psycopg.Connection[Any],
) -> None:
    template = _security_sql()["SQL_PRIVILEGED"]
    owner = _user(db, "owner@alerts.test", "SUPER_ADMIN")
    admin2 = _user(db, "admin2@alerts.test", "SUPER_ADMIN")
    user = _user(db, "user@alerts.test", "USER")
    sql = template.replace(":owner", str(owner))
    base_total, base_other, base_ids = _triple(_scalar(db, sql))
    db.execute(
        'INSERT INTO auth.audit_events (action, actor_user_id, target_user_id, detail) VALUES (\'user.role_changed\', %s, %s, \'{"from":"USER","to":"SUPER_ADMIN"}\')',
        (owner, user),
    )
    total, by_other, ids = _triple(_scalar(db, sql))
    assert (total - base_total, by_other - base_other, ids - base_ids) == (1, 0, {str(user)}), (
        "the owner's own change: told, but not as someone else's"
    )
    # admin2 resets the user's password; a reset of MFA from the command line (no actor); a SUPER_ADMIN created; a USER created (ignored); an old reset
    db.execute(
        "INSERT INTO auth.audit_events (action, actor_user_id, target_user_id, detail) VALUES ('password.reset', %s, %s, '{\"by\":\"admin\"}')",
        (admin2, user),
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, detail) VALUES ('mfa.reset', %s, '{\"by\":\"command_line\"}')",
        (user,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, detail) VALUES ('user.created', %s, '{\"role\":\"SUPER_ADMIN\"}')",
        (admin2,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (action, target_user_id, detail) VALUES ('user.created', %s, '{\"role\":\"USER\"}')",
        (user,),
    )
    db.execute(
        "INSERT INTO auth.audit_events (at, action, actor_user_id, target_user_id, detail) VALUES (now() - interval '20 minutes', 'password.reset', %s, %s, '{}')",
        (admin2, owner),
    )
    total, by_other, ids = _triple(_scalar(db, sql))
    assert (total - base_total, by_other - base_other) == (4, 1), (
        "four in the window, one by another account; the old one and the USER creation are out"
    )
    assert ids - base_ids == {str(user), str(admin2)}


def test_what_comes_out_of_a_read_only_psql_is_what_security_alerts_sh_parses(
    migrated_database: str,
) -> None:
    """Each query through the real psql, read-only, last line: the shapes the script's regular expressions accept (numbers, 'n|ids', 'n|n|ids')."""
    psql = shutil.which("psql")
    if psql is None:
        pytest.skip("psql is not installed")
    queries = _security_sql()
    shapes = {
        "SQL_FAILED": r"\d+",
        "SQL_LOCKED": r"\d+\|[\d,]*",
        "SQL_NEWDEVICE": r"\d+\|[\d,]*",
        "SQL_OWNER": r"\d+",
        "SQL_PRIVILEGED": r"\d+\|\d+\|[\d,]*",
    }
    for name, shape in shapes.items():
        sql = queries[name].replace(":owner", "1")
        out = subprocess.run(
            [
                psql,
                migrated_database,
                "-v",
                "ON_ERROR_STOP=1",
                "-qAtX",
                "-c",
                "SET default_transaction_read_only = on",
                "-c",
                sql,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.splitlines()[-1]
        assert re.fullmatch(shape, out), f"{name}: {out!r}"
