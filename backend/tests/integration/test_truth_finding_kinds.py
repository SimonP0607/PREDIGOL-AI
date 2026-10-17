"""Every kind and severity the truth audit produces is one its table accepts.

4 Oct 2026: the audit's result comparison started reporting ``provider_contradiction`` and the table's CHECK (0048)
refused the whole batch - the audit never completed again and the Data Truth page showed a 21-hour-old run."""

from __future__ import annotations

import psycopg

from fbi.truth.findings import Kind, Severity


def test_the_findings_table_accepts_every_kind_and_severity(db: psycopg.Connection) -> None:
    run = db.execute("INSERT INTO audit.truth_runs (started_at, status) VALUES (now(), 'running') RETURNING id"
                     ).fetchone()
    assert run is not None
    for kind in Kind:
        for severity in Severity:
            db.execute("INSERT INTO audit.truth_findings (run_id, dataset, entity, field, kind, severity) "
                       "VALUES (%s, 'results', 'fixture 1', 'result', %s, %s)", (run[0], kind.value, severity.value))
    n = db.execute("SELECT count(*) FROM audit.truth_findings WHERE run_id = %s", (run[0],)).fetchone()
    assert n == (len(Kind) * len(Severity),)
