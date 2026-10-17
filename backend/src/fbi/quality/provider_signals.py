"""Turning what a provider boundary refused into recorded quality issues.

``OddsParseLog`` is filled at the boundary, where the provider's words are turned
into domain objects. Everything it holds is a fact about the provider's answer:

  * a bet id we do not map - which markets exist is the provider's business, and
    an unmapped bet is information, not a fault;
  * a bet whose name no longer matches the catalogue - the strongest early signal
    that the provider renumbered something under us;
  * a value the boundary could not read - a line that is not a multiple of 0.25,
    an impossible price, a selection that does not belong to its market.

None of it is repaired here. It is written down, with the payload it came from,
and the unmapped bets are added to the provider catalogue so that "we do not
model this" stops looking like "we lost this".
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
import structlog

from fbi.catalog.provider_markets import record_observed_bets
from fbi.providers.base import OddsParseLog, OddsSource
from fbi.quality.issues import (
    EntityType,
    IssueCode,
    IssueRegistry,
    QualityIssue,
    Severity,
    issues_from,
    rejected,
    unknown_entity,
)

log = structlog.get_logger(__name__)

SCOPE_OF_SOURCE: dict[str, str] = {"prematch": "prematch", "live": "inplay"}


@dataclass
class SignalReport:
    issues_opened: int = 0
    issues_seen_again: int = 0
    bets_newly_observed: int = 0

    @property
    def anything(self) -> bool:
        return bool(self.issues_opened or self.issues_seen_again or self.bets_newly_observed)


def issues_from_parse_log(
    parse_log: OddsParseLog,
    *,
    source: OddsSource,
    payload_hash: str | None = None,
    run_id: int | None = None,
) -> list[QualityIssue]:
    """One issue per distinct thing the boundary refused."""
    found: list[QualityIssue] = []
    scope = SCOPE_OF_SOURCE[source]
    for (bet_id, name), _count in sorted(parse_log.unmapped_bets.items()):
        found.append(unknown_entity(
            entity_type=EntityType.PROVIDER_MARKET, name=name or f"bet {bet_id}",
            provider_entity_id=bet_id, payload_hash=payload_hash, run_id=run_id,
            detail=f"{scope} bet {bet_id} is offered by the provider and not mapped to a market "
                   f"of ours; the prices are in the raw payload and are not stored",
        ))
    for bet_id, expected, got in parse_log.renamed_bets:
        found.append(QualityIssue(
            code=IssueCode.PROVIDER_INCONSISTENCY,
            entity_type=EntityType.PROVIDER_MARKET,
            severity=Severity.ERROR,
            provider_entity_id=bet_id,
            payload_hash=payload_hash,
            run_id=run_id,
            field="name",
            observed=got,
            expected=expected,
            detail=f"{scope} bet {bet_id} arrived under a different name; its prices were NOT stored, "
                   f"because a renumbering would relabel them silently",
        ))
    for market_key, raw_value, reason in parse_log.rejected:
        found.append(rejected(
            entity_type=EntityType.ODDS_SNAPSHOT, field_name=market_key, observed=raw_value,
            reason=reason, payload_hash=payload_hash, run_id=run_id,
        ))
    return issues_from(found)


def record_parse_log(
    conn: psycopg.Connection,
    parse_log: OddsParseLog,
    *,
    source: OddsSource,
    payload_hash: str | None = None,
    run_id: int | None = None,
) -> SignalReport:
    """Write the issues AND register the unmapped bets in the provider catalogue.

    Does not commit: it belongs to the same unit of work as the capture that
    produced it.
    """
    report = SignalReport()
    issues = issues_from_parse_log(parse_log, source=source, payload_hash=payload_hash, run_id=run_id)
    if issues:
        result = IssueRegistry(conn).record_many(issues)
        report.issues_opened, report.issues_seen_again = result.opened, result.seen_again
    if parse_log.unmapped_bets:
        new = record_observed_bets(conn, parse_log.unmapped_bets, scope=SCOPE_OF_SOURCE[source])
        report.bets_newly_observed = len(new)
    if parse_log.rejected_total > len(parse_log.rejected):
        log.warning("odds.rejections_truncated", kept=len(parse_log.rejected),
                    total=parse_log.rejected_total,
                    detail="the count is exact; the examples are the first ones seen")
    return report
