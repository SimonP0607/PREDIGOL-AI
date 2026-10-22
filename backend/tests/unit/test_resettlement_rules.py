"""Plan F0, defect 5: the pure parts of the re-settlement - when a settled record changes, when it is held, and what
the reasons and the report say. (The database parts are in tests/integration/test_resettlement.py.)"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from fbi.picks import settlement
from fbi.picks.resettlement import (
    MAX_FIXTURES,
    RECHECK_WINDOW,
    Change,
    Held,
    ResettlementReport,
    Revision,
    explain,
    judge,
)

D = Decimal
WIN = settlement.Settlement(settlement.Status.WIN, D("1.3000"), basis=settlement.BASIS)
LOSS = settlement.Settlement(settlement.Status.LOSS, D("-1.0000"), basis=settlement.BASIS)
PUSH = settlement.Settlement(settlement.Status.PUSH, D("0.0000"), basis=settlement.BASIS)
VOID_CANCELLED = settlement.Settlement(settlement.Status.VOID, D(0), basis="not_played")
VOID_NO_RESULT = settlement.Settlement(settlement.Status.VOID, D(0), basis=settlement.NO_RESULT_BASIS)
WAITING = settlement.Settlement(settlement.Status.PENDING, None, "postponed: void 72 h after kick-off unless played")
NOT_FINISHED = settlement.Settlement(settlement.Status.PENDING, None, None)


def verdict(stored: str, profit: str | None, outcome: settlement.Settlement, *, score_based: bool = True,
            priced: bool = True, upper: bool = False, status_short: str = "FT") -> tuple[str, str | None, Decimal | None, str]:
    v = judge(stored_status=stored, stored_profit=None if profit is None else D(profit), score_based=score_based,
              outcome=outcome, priced=priced, upper=upper, status_short=status_short)
    return v.action, v.status, v.profit, v.code


def test_a_record_that_the_current_result_settles_the_same_is_left_alone() -> None:
    assert verdict("win", "1.3000", WIN)[0] == "same"
    assert verdict("WIN", "1.3000", WIN, upper=True)[0] == "same", "the product keeps its statuses in capitals"
    assert verdict("push", "0.0000", PUSH)[0] == "same"
    assert verdict("void", "0.0000", VOID_CANCELLED, score_based=False)[0] == "same", "a void that is still a void"


def test_a_score_that_now_settles_it_differently_changes_it() -> None:
    assert verdict("win", "1.3000", LOSS) == ("change", "loss", D("-1.0000"), "")
    assert verdict("LOSS", "-1.0000", WIN, upper=True) == ("change", "WIN", D("1.3000"), "")
    assert verdict("loss", "-1.0000", PUSH) == ("change", "push", D("0.0000"), "")


def test_the_same_status_with_another_profit_is_a_change_too() -> None:
    """The profit is part of the result: a pick settled at a profit the rules do not give is corrected."""
    assert verdict("win", "1.2000", WIN) == ("change", "win", D("1.3000"), "")
    assert verdict("win", None, WIN)[0] == "change"


def test_a_record_without_a_known_profit_is_compared_on_its_status_alone() -> None:
    """A leg keeps no profit, and a user's bet may lack a price: the profit is then not part of the comparison."""
    assert verdict("WIN", None, WIN, priced=False, upper=True)[0] == "same"
    assert verdict("LOSS", None, WIN, priced=False, upper=True) == ("change", "WIN", None, "")


@pytest.mark.parametrize(("outcome", "status_short", "needle"), [
    (WAITING, "PST", "postponed"),
    (NOT_FINISHED, "NS", "reads NS, not finished"),
    (NOT_FINISHED, " 2h ", "reads 2H, not finished"),
])
def test_a_match_that_no_longer_settles_a_record_holds_it(outcome: settlement.Settlement, status_short: str,
                                                          needle: str) -> None:
    v = judge(stored_status="win", stored_profit=D("1.3"), score_based=True, outcome=outcome, priced=True,
              upper=False, status_short=status_short)
    assert (v.action, v.code, v.status, v.profit) == ("held", "no_longer_settles", None, None)
    assert needle in v.detail


def test_a_match_that_now_settles_by_rule_is_not_a_correction_of_a_score() -> None:
    for outcome in (VOID_CANCELLED, VOID_NO_RESULT):
        v = judge(stored_status="win", stored_profit=D("1.3"), score_based=True, outcome=outcome, priced=True,
                  upper=False, status_short="CANC")
        assert (v.action, v.code) == ("held", "settles_by_rule_now")
        assert outcome.basis is not None and outcome.basis in v.detail


def test_a_void_by_rule_stands_when_a_result_appears() -> None:
    v = judge(stored_status="void", stored_profit=D(0), score_based=False, outcome=WIN, priced=True, upper=False,
              status_short="FT")
    assert (v.action, v.code) == ("held", "void_by_rule_stands") and "a person decides" in v.detail
    other = judge(stored_status="void", stored_profit=D(0), score_based=False, outcome=LOSS, priced=True,
                  upper=False, status_short="FT")
    assert other.action == "held"


def test_the_reason_quotes_the_latest_recorded_correction() -> None:
    at = datetime(2026, 10, 22, 15, 3, tzinfo=UTC)
    score = Revision(41, "score", {"reg_goals_home": 2, "reg_goals_away": 0}, {"reg_goals_home": 1, "reg_goals_away": 0},
                     ["goals_home", "reg_goals_home"], at)
    reason, revision = explain(score)
    assert revision == 41 and "2-0 -> 1-0" in reason and "goals_home, reg_goals_home" in reason
    assert "revision 41, 2026-10-22 15:03 UTC" in reason and reason.startswith("the provider corrected the result")
    status = Revision(42, "status", {"status_short": "FT"}, {"status_short": "AWD"}, ["status_short"], at)
    assert explain(status) == ("the status of the match moved from FT to AWD (revision 42, 2026-10-22 15:03 UTC)", 42)
    unknown = Revision(43, "score", {}, {"reg_goals_home": 1, "reg_goals_away": None}, ["goals_home"], at)
    assert ": ?-? -> ?-? (" in explain(unknown)[0], "a score only half known is not printed as if it were a score"
    audit, none = explain(None)
    assert none is None and audit.startswith("audit: ") and "revision 0080" in audit


def _change(kind: str, key: str, fixture: int | None) -> Change:
    return Change(kind, key, fixture, "win", D("1.3"), "loss", D("-1"), "the provider corrected the result", 7,
                  "settle-v4")


def test_the_report_counts_what_changed_and_says_so() -> None:
    r = ResettlementReport(applied=True, fixtures=[1, 2, 3])
    assert r.summary() == "re-settled 0 record(s) on 0 match(es)"
    r.changes = [_change("pick", "10", 5), _change("daily_item", "3/1", 5), _change("parlay", "8", 2),
                 _change("parlay", "9", None)]
    r.held = [Held("pick", "11", 6, "win", "no_longer_settles", "the match reads PST")]
    r.conflicts = 1
    assert r.changed_fixtures == [2, 5] and r.by_kind() == {"pick": 1, "daily_item": 1, "parlay": 2}
    assert r.summary() == "re-settled 4 record(s) on 2 match(es), 1 held for a person, 1 conflict(s)"
    lines = r.render()
    assert lines[0].startswith("APPLIED - 3 corrected match(es) examined; records read: none")
    assert any(line.startswith("  pick 10 (match 5): win (+1.3000u) -> loss (-1.0000u)") for line in lines)
    assert any(line.startswith("  HELD pick 11 (match 6, win): no_longer_settles - ") for line in lines)
    assert not any("Nothing was written" in line for line in lines)


def test_a_dry_run_and_a_refusal_read_differently() -> None:
    dry = ResettlementReport(applied=False, changes=[_change("pick", "10", 5)], examined={"pick": 4, "daily_item": 2})
    assert dry.summary().startswith("would re-settle 1 record(s) on 1 match(es)")
    lines = dry.render()
    assert lines[0] == "DRY RUN - 0 corrected match(es) examined; records read: daily_item 2, pick 4"
    assert lines[-1] == "Nothing was written. Run with --apply --by NAME to write it."
    refused = ResettlementReport(applied=False, changes=[_change("pick", "10", 5)],
                                 refused="30 matches would change result (more than 25)")
    assert refused.summary().endswith("REFUSED: 30 matches would change result (more than 25)")
    assert not any("Run with --apply" in line for line in refused.render()), "a refusal is not something to apply"
    audit = ResettlementReport(audit=True)
    assert audit.render()[0].startswith("DRY RUN - AUDIT of every settled record")
    busy = ResettlementReport(busy=True)
    assert "Another re-settlement was running" in "\n".join(busy.render())
    stale = ResettlementReport(applied=True, stale={"intel.decision_outcomes": 3})
    assert any("intel.decision_outcomes 3" in line and "F8" in line for line in stale.render())


def test_the_documented_limits() -> None:
    """The command line's help and the runbook say 7 days and 25 matches: a change of either is a decision."""
    assert timedelta(days=7) == RECHECK_WINDOW and MAX_FIXTURES == 25
